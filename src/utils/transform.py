from functools import lru_cache
from typing import Sequence
import networkx as nx
import pandas as pd
from sqlalchemy import RowMapping
from utils.definitions import (
    SpendingTypeLiteral,
    MilitarySpending,
)
from utils.helper import add_breaks

# Classified spending dimension IDs
CLASSIFIED_DIMENSION_ID_OFFSET = 1_000_000  # Offset to avoid ID conflicts with real dimensions
CLASSIFIED_PARENT_ID = -999_999  # Synthetic ID for aggregated classified parent node

# Multiplier for TOTAL budget values (stored in thousands)
TOTAL_VALUE_MULTIPLIER = 1000


class TreemapTransformer:
    def __init__(
        self,
        dimensions: Sequence[RowMapping],
        programs: Sequence[RowMapping],
        spending_type: SpendingTypeLiteral = "ALL",
        max_line_lenght: int | None = 30,
    ) -> None:
        # Ensure an intuitive ordering: MINISTRY -> CHAPTER -> SUBCHAPTER -> PROGRAM_*
        # CLASSIFIED_PARENT is at top level (sibling to MINISTRY), CLASSIFIED is under it
        self.level_order_index = {
            "MINISTRY": 0,
            "CHAPTER": 1,
            "SUBCHAPTER": 2,
            "PROGRAM": 3,
        }
        self.spending_type = spending_type
        self.dimensions = dimensions
        self.programs = programs
        self.max_line_length = max_line_lenght

    def _calculate_program_hierarchy(self, programs: Sequence[RowMapping]) -> dict[int, list[int]]:
        """Calculate all paths from root to leaves in the hierarchy graph.

        Returns a mapping of leaf program id -> full path from root to leaf.
        """
        # Build edges more efficiently with set comprehension
        deduped_edges = {
            (row["dimension_id"], row["dimension_parent_id"])
            for row in programs
            if row["dimension_parent_id"] is not None
        }

        # Early return for empty graphs
        if not deduped_edges:
            return {}

        # Create a directed graph
        g = nx.DiGraph()
        g.add_edges_from(deduped_edges)  # pyright: ignore[reportArgumentType]

        # Get roots and leaves more efficiently
        roots = [v for v, d in g.in_degree() if d == 0]
        leaves = {v for v, d in g.out_degree() if d == 0}

        # Early return if no valid structure
        if not roots or not leaves:
            return {}

        # Calculate paths from all roots to all leaves
        program_paths: list[list[int]] = []
        for root in roots:
            # Filter leaves reachable from this root for efficiency
            reachable = nx.descendants(g, root) | {root}
            reachable_leaves = leaves & reachable
            if reachable_leaves:
                paths_raw = nx.all_simple_paths(g, root, list(reachable_leaves))
                paths = [[int(elem) for elem in path] for path in paths_raw]
                program_paths.extend(paths)

        # Create a mapping for leaves to their full paths (reversed for root-to-leaf)
        leave_mapping = {path[0]: path[::-1] for path in program_paths}

        return leave_mapping

    def _calculate_difference_for_classified(
        self,
        expense_dimensions: Sequence[RowMapping],
    ) -> tuple[list[dict[str, str | float | int]], float]:
        """Calculate the difference between TOTAL and LAW budgets for Classified Spending."""
        difference_rows: list[dict[str, str | float | int]] = []
        difference_value_budget = 0.0
        totals: list[RowMapping] = []
        chapter_expense_mapping: dict[str, dict[str, float | RowMapping]] = {}
        budget_sum_value: float = 0.0
        budget_type = None
        for row in expense_dimensions:
            if row.get("budget_type") == "TOTAL":
                totals.append(row)
                continue
            if budget_type is None:
                budget_type = row.get("budget_type")
            if row["dimension_type"] == "CHAPTER":
                chapter_expense_mapping.setdefault(
                    row["dimension_original_identifier"],
                    {
                        "value": 0.0,
                        "row": row,
                    },
                )
                chapter_expense_mapping[row["dimension_original_identifier"]]["value"] += row.get(
                    "value", 0.0
                )
                budget_sum_value += row.get("value", 0.0)

        # LAW Totals are split across chapters, so we can calculate the difference per chapter
        # REPORT Totals only have 1 row, so we calculate the difference between the 1 TOTAL
        # and the sum of the chapters
        for row in totals:
            multiplier: float = TOTAL_VALUE_MULTIPLIER
            if budget_type == "REPORT":
                multiplier = 1.0
            if row["dimension_type"] is None:
                total_value = row.get("value", 0.0)
                difference_value_budget = total_value * multiplier - budget_sum_value
            if row["dimension_type"] == "CHAPTER":
                chapter_id = row["dimension_original_identifier"]
                total_value = row.get("value", 0.0)
                chapter_value = chapter_expense_mapping.get(chapter_id, {}).get("value", 0.0)
                difference_value = total_value * multiplier - chapter_value
                if difference_value > 0:
                    difference_row = dict(row)
                    difference_row["value"] = difference_value
                    difference_rows.append(difference_row)

        return difference_rows, difference_value_budget

    def _check_if_military(
        self,
        dim_type: str,
        dim_original_id: str,
        hierarchy_dict_entry: dict[str, int | float | str],
        is_classified: bool = False,
    ) -> bool:
        """Filter the hierarchy dictionary based on spending type (e.g., military only)."""
        # Cache class attributes locally for faster access in hot loop
        simple_patterns = MilitarySpending.simple_patterns
        combination_patterns = MilitarySpending.combination_patterns

        # Convert dim_original_id once (avoid repeated str() calls)
        dim_original_id_str = str(dim_original_id)

        # Check single level patterns (most common case, check first)
        for level_name, pattern in simple_patterns.items():
            if dim_type.startswith(level_name) and pattern.match(dim_original_id_str):
                return True

        # Check combination patterns using all() for short-circuit evaluation
        for combination in combination_patterns:
            if all(
                pattern.match(str(hierarchy_dict_entry.get(f"{dim}_ORIG_ID", "")))
                for dim, pattern in combination.items()
            ):
                return True

        # Check custom classified patterns only when is_classified=True
        if is_classified:
            custom_patterns = MilitarySpending.custom_patterns
            for level_name, pattern in custom_patterns.items():
                if dim_type.startswith(level_name) and pattern.match(dim_original_id_str):
                    return True

        return False

    def _build_hierarchy_dict(
        self,
        expense_dimensions: Sequence[RowMapping],
        programs: Sequence[RowMapping],
        program_paths: dict[int, list[int]],
        max_program_levels: int,
    ) -> dict[str, dict[str, int | float | str]]:
        """Build a hierarchy dictionary mapping each row ID to its hierarchy levels.

        Classified Spending (from TOTAL budgets) are placed as siblings to SUBCHAPTERs
        (under CHAPTER) and are terminal nodes (no children).
        """

        hierarchy_dict: dict[str, dict[str, int | float | str]] = {}
        program_by_dim_id = {row["dimension_id"]: row for row in programs}
        expenses_by_id: dict[int, list[RowMapping]] = {}
        for row in expense_dimensions:
            expenses_by_id.setdefault(row["id"], []).append(row)

        # Extract expense_ids from expense_dimensions and map to program path keys
        leaf_expense_mapping: dict[int, set[int]] = {}
        valid_program_ids = set(program_paths.keys())
        for row in expense_dimensions:
            if row["dimension_id"] in valid_program_ids:
                leaf_expense_mapping.setdefault(row["dimension_id"], set())
                leaf_expense_mapping[row["dimension_id"]].add(row["id"])

        for program_id, expenses in leaf_expense_mapping.items():
            # Calculate ONCE per program_id, not per expense
            program_path = program_paths.get(program_id, [])
            program_rows = [
                program_by_dim_id[d] for d in reversed(program_path) if d in program_by_dim_id
            ]

            relevant_dims = []
            # Extract the id from each expense row mapping before using it as a dictionary key
            for expense_id in expenses:
                relevant_dims.extend(expenses_by_id.get(expense_id, []))
            for row in relevant_dims:
                expense_id = row["id"]
                dim_type = row.get("dimension_type", "")
                dim_original_id = row.get("dimension_original_identifier", "")
                # Initialize dict structure and expense value if not already present
                entry = hierarchy_dict.setdefault(
                    expense_id,
                    {
                        "VALUE": row.get("value", 0.0),
                        "BUDGET_TYPE": relevant_dims[0].get("budget_type", ""),
                    },
                )
                entry["IS_MILITARY"] = self._check_if_military(
                    dim_type,
                    dim_original_id,
                    hierarchy_dict_entry=entry,
                )
                if dim_type in ["MINISTRY", "CHAPTER", "SUBCHAPTER"]:
                    entry[f"{dim_type}_DIM_ID"] = row["dimension_id"]
                    entry[f"{dim_type}_ORIG_ID"] = dim_original_id
                    entry[f"{dim_type}_NAME"] = row.get("dimension_name", None)
                    entry[f"{dim_type}_NAME_TRANSLATED"] = row.get(
                        "dimension_name_translated", None
                    )

                # Sort program rows according to their position in the path
                last_row = program_rows[0]
                for idx in range(0, max_program_levels):
                    if idx < len(program_path):
                        row = program_rows[idx]
                        last_row = row
                    else:
                        row = last_row
                    entry[f"PROGRAM_{idx}_DIM_ID"] = row["dimension_id"]
                    entry[f"PROGRAM_{idx}_ORIG_ID"] = row["dimension_original_identifier"]
                    entry[f"PROGRAM_{idx}_NAME"] = row.get("dimension_name", None)
                    entry[f"PROGRAM_{idx}_NAME_TRANSLATED"] = row.get(
                        "dimension_name_translated", None
                    )

        return hierarchy_dict

    def _get_level_sort_key(self, level_name: str) -> tuple[int, int]:
        """Sort key for hierarchy levels, ensuring PROGRAM_0 < PROGRAM_1 < PROGRAM_2."""
        parts = level_name.split("_")
        base_name = parts[0]
        primary_order = self.level_order_index.get(base_name, 100)
        secondary_order = 0
        if base_name == "PROGRAM" and len(parts) > 1 and parts[1].isdigit():
            secondary_order = int(parts[1])
        return (primary_order, secondary_order)

    def _create_dataframe(
        self,
        hierarchy: dict[str, dict[str, int | float | str]],
        root_name: str = "Federal Budget",
    ) -> pd.DataFrame:
        """Build the treemap lists (names, parents, values, metadata) from hierarchy.

        Since the same dimension (e.g., CHAPTER) can appear under different parents
        (e.g., different MINISTRYs), we create path-based unique identifiers.
        This allows the treemap to correctly show the same dimension under multiple parents.
        """
        # Create a DataFrame
        df = pd.DataFrame(data=hierarchy).T
        # replace NaN with None
        df["ROOT"] = root_name

        # Reorder columns to have a consistent order
        ordered_columns = ["VALUE", "BUDGET_TYPE", "ROOT"]
        for level in sorted(df.columns, key=self._get_level_sort_key):
            if level not in ordered_columns:
                ordered_columns.append(level)
        df = df[ordered_columns]

        # Set type for value as float
        df["VALUE"] = df["VALUE"].astype(float)
        # Preserve nulls before any string conversion for Plotly path handling.
        df = df.where(pd.notnull(df), None)
        # Normalize non-null entries to strings for id/name columns.
        str_cols = [c for c in df.columns if c != "VALUE"]
        df[str_cols] = df[str_cols].astype(str).replace("nan", None).replace("None", None)

        # Add line breaks to long names if max_line_length is set.
        line_length = self.max_line_length
        if line_length is not None:
            for col in df.columns:
                if "NAME" in col:
                    df[col] = df[col].apply(
                        lambda x: add_breaks(str(x), interval=line_length) if x else x
                    )

        # Normalize empty strings to None for Plotly compatibility.
        df = df.replace(to_replace={"": None})

        return df

    def _add_classified_expenses(
        self,
        df: pd.DataFrame,
    ) -> pd.DataFrame:
        """Add Classified Spending calculated from difference between TOTAL and LAW budgets."""
        difference_rows, difference_budget_value = self._calculate_difference_for_classified(
            self.dimensions
        )
        budget_type = "REPORT" if len(difference_rows) == 0 else "LAW"

        for row in difference_rows:
            # Get only first row in df with matching original identifier at CHAPTER_ORIG_ID column
            chapter_orig_id = row["dimension_original_identifier"]

            expense_id = row["id"]
            expense_value = row.get("value", 0.0)
            classified_entry: dict[str, int | float | str] = {
                "VALUE": expense_value,
                "BUDGET_TYPE": "CLASSIFIED",
                "ROOT": "Federal Budget",
            }
            classified_entry["MINISTRY_DIM_ID"] = CLASSIFIED_PARENT_ID
            classified_entry["MINISTRY_ORIG_ID"] = "CLASSIFIED_PARENT"
            classified_entry["MINISTRY_NAME"] = "Classified Spending"
            classified_entry["MINISTRY_NAME_TRANSLATED"] = "Classified Spending"
            classified_entry["CHAPTER_DIM_ID"] = row["dimension_id"]
            classified_entry["CHAPTER_ORIG_ID"] = row["dimension_original_identifier"]
            classified_entry["CHAPTER_NAME"] = row["dimension_name"]
            classified_entry["CHAPTER_NAME_TRANSLATED"] = row["dimension_name_translated"]
            classified_entry["SUBCHAPTER_DIM_ID"] = CLASSIFIED_DIMENSION_ID_OFFSET + int(expense_id)
            classified_entry["SUBCHAPTER_ORIG_ID"] = f"CLASSIFIED_{chapter_orig_id}"
            classified_entry["SUBCHAPTER_NAME"] = "Classified Spending"
            classified_entry["SUBCHAPTER_NAME_TRANSLATED"] = "Classified Spending"
            # PROGRAM levels
            for idx in range(0, 3):
                classified_entry[f"PROGRAM_{idx}_DIM_ID"] = CLASSIFIED_DIMENSION_ID_OFFSET + int(
                    expense_id
                )
                classified_entry[f"PROGRAM_{idx}_ORIG_ID"] = f"CLASSIFIED_{chapter_orig_id}"
                classified_entry[f"PROGRAM_{idx}_NAME"] = "Classified Spending"
                classified_entry[f"PROGRAM_{idx}_NAME_TRANSLATED"] = "Classified Spending"

            # Append the new row via concat to avoid deprecated append and type issues.
            classified_entry_df = pd.DataFrame([classified_entry])
            # Add line breaks to long names if max_line_length is set.
            line_length = self.max_line_length
            if line_length is not None:
                for col in classified_entry_df.columns:
                    if "NAME" in col:
                        classified_entry_df[col] = classified_entry_df[col].apply(
                            lambda x: add_breaks(x, interval=line_length) if x else x  # type: ignore
                        )
            df = pd.concat([df, classified_entry_df], ignore_index=True)

        if budget_type == "REPORT":
            root_row = {
                "VALUE": difference_budget_value,
                "BUDGET_TYPE": "CLASSIFIED",
                "ROOT": "Federal Budget",
                "MINISTRY_DIM_ID": CLASSIFIED_PARENT_ID,
                "MINISTRY_ORIG_ID": "CLASSIFIED_PARENT",
                "MINISTRY_NAME": "Classified Spending",
                "MINISTRY_NAME_TRANSLATED": "Classified Spending",
                "CHAPTER_DIM_ID": CLASSIFIED_DIMENSION_ID_OFFSET + 1,
                "CHAPTER_ORIG_ID": "CLASSIFIED_CHAPTER",
                "CHAPTER_NAME": "Classified Spending",
                "CHAPTER_NAME_TRANSLATED": "Classified Spending",
                "SUBCHAPTER_DIM_ID": CLASSIFIED_DIMENSION_ID_OFFSET + 2,
                "SUBCHAPTER_ORIG_ID": "CLASSIFIED_SUBCHAPTER",
                "SUBCHAPTER_NAME": "Classified Spending",
                "SUBCHAPTER_NAME_TRANSLATED": "Classified Spending",
            }
            # PROGRAM levels
            for idx in range(0, 3):
                root_row[f"PROGRAM_{idx}_DIM_ID"] = CLASSIFIED_DIMENSION_ID_OFFSET + 3 + idx
                root_row[f"PROGRAM_{idx}_ORIG_ID"] = "CLASSIFIED_PROGRAM_" + str(idx)
                root_row[f"PROGRAM_{idx}_NAME"] = "Classified Spending"
                root_row[f"PROGRAM_{idx}_NAME_TRANSLATED"] = "Classified Spending"
            df = pd.concat([df, pd.DataFrame([root_row])], ignore_index=True)

        return df

    @lru_cache(maxsize=5)
    def transform_data(
        self,
    ) -> pd.DataFrame:
        """Transform DB rows into treemap lists expected by the figure creator."""
        if not self.dimensions:
            return pd.DataFrame()

        # Extend sum mapping to include all hierarchy levels
        program_paths = self._calculate_program_hierarchy(self.programs)
        # Calculate max length of program paths for consistent PROGRAM_* columns
        max_program_levels = max((len(path) for path in program_paths.values()), default=0)
        # Calculate all paths between dimensions
        hierarchy_dict = self._build_hierarchy_dict(
            self.dimensions, self.programs, program_paths, max_program_levels
        )
        # Create dataframe from paths
        df = self._create_dataframe(
            hierarchy_dict,
        )
        df = self._add_classified_expenses(df)

        return df


class BarchartTransformer:
    def _normalize_cumulative_expenses(
        self, budgets: Sequence[RowMapping]
    ) -> list[dict[str, str | float | int]]:
        """Normalize cumulative quarterly expenses by subtracting the previous quarter's value.

        Budgets are quarterly and cumulative, so Q4 includes Q1+Q2+Q3+Q4.
        This method calculates the actual quarterly value by subtracting the previous quarter.
        Q1 is the base (no subtraction), Q2 = Q2_cumulative - Q1_cumulative, etc.
        Normalization is done separately for each year and budget type (LAW, REPORT).
        """
        normalized_budgets: list[dict[str, str | float | int]] = []

        # Group budgets by year and type for independent normalization
        grouped: dict[tuple[int, str], list[RowMapping]] = {}
        for budget in budgets:
            key = (budget["published_at"].year, budget["type"])
            grouped.setdefault(key, []).append(budget)

        # Process each year-type group
        for (_, _), group_budgets in grouped.items():
            # Sort by date ascending to process in chronological order
            sorted_budgets = sorted(group_budgets, key=lambda b: b["published_at"])

            # Track previous quarter's cumulative value for subtraction
            prev_cumulative_value: float = 0.0

            for budget in sorted_budgets:
                # Convert RowMapping to mutable dict
                normalized = dict(budget)
                current_cumulative = budget.get("total_value", 0.0) or 0.0

                # Calculate quarterly value by subtracting previous quarter
                quarterly_value = current_cumulative - prev_cumulative_value
                normalized["total_value"] = quarterly_value

                normalized_budgets.append(normalized)

                # Update previous value for next iteration
                prev_cumulative_value = current_cumulative

        return normalized_budgets

    def _transform_budget_totals(
        self,
        budgets: Sequence[RowMapping],
        normalize: bool,
    ) -> pd.DataFrame:
        """Transform law budget rows into a dataframe suitable for barchart visualization."""
        if not budgets:
            return pd.DataFrame()

        # For every published_at, subtract the law value from the total value
        # and set new value as Classified Spending
        budgets_corrected: Sequence[RowMapping] | list[dict[str, str | float | int]] = budgets
        if normalize:
            budgets_corrected = self._normalize_cumulative_expenses(budgets)

        expenses = [
            budget["total_value"] for budget in budgets_corrected if budget["type"] != "TOTAL"
        ]
        dates = [
            budget["published_at"] for budget in budgets_corrected if budget["type"] != "TOTAL"
        ]
        types = [budget["type"] for budget in budgets_corrected if budget["type"] != "TOTAL"]
        ids = [budget["id"] for budget in budgets_corrected if budget["type"] != "TOTAL"]

        df = pd.DataFrame({"expenses": expenses, "dates": dates, "types": types, "budget_id": ids})

        # For every TOTAL budget, find the corresponding non-TOTAL budget and subtract its value
        for budget in [budget for budget in budgets_corrected if budget["type"] == "TOTAL"]:
            corresponding_budget = next(
                (
                    b
                    for b in budgets_corrected
                    if b["published_at"] == budget["published_at"] and b["type"] != "TOTAL"
                ),
                None,
            )
            if corresponding_budget is None:
                continue

            multiplicator: float = 1.0
            if corresponding_budget["type"] == "LAW":
                multiplicator = TOTAL_VALUE_MULTIPLIER

            total_value: float = budget["total_value"] * multiplicator  # type: ignore

            value: float = corresponding_budget["total_value"] if corresponding_budget else 0.0  # type: ignore
            classified_expense = total_value - value
            budget_id = budget["id"]
            df = pd.concat(
                [
                    df,
                    pd.DataFrame(
                        {
                            "expenses": [classified_expense],
                            "dates": [budget["published_at"]],
                            "types": ["CLASSIFIED"],
                            "budget_id": [budget_id],
                        }
                    ),
                ],
                ignore_index=True,
            )

        return df

    def transform_data(self, budgets: Sequence[RowMapping], normalize: bool = True) -> pd.DataFrame:
        """Transform raw rows into a dataframe suitable for barchart visualization."""
        if not budgets:
            return pd.DataFrame()
        df = self._transform_budget_totals(budgets, normalize)

        return df
