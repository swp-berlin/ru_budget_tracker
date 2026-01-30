from re import Pattern
from typing import Sequence
import networkx as nx
import pandas as pd
from sqlalchemy import RowMapping
from utils.definitions import (
    SpendingTypeLiteral,
    MilitarySpendingDictionary,
    ViewByDimensionTypeLiteral,
)
from utils.helper import add_breaks


class TreemapTransformer:
    def __init__(self, max_line_lenght: int | None = 30) -> None:
        # Ensure an intuitive ordering: MINISTRY -> CHAPTER -> SUBCHAPTER -> PROGRAM_*
        # CLASSIFIED_PARENT is at top level (sibling to MINISTRY), CLASSIFIED is under it
        self.level_order_index = {
            "MINISTRY": 0,
            "CLASSIFIED_PARENT": 0,  # Same level as MINISTRY (top-level under root)
            "CHAPTER": 1,
            "CLASSIFIED": 2,  # Under CLASSIFIED_PARENT or under CHAPTER
            "SUBCHAPTER": 3,
            "PROGRAM": 4,
        }
        self.max_line_length = max_line_lenght

    def _calculate_program_hierarchy(self, programs: Sequence[RowMapping]) -> dict[int, list[int]]:
        """Calculate all paths from root to leaves in the hierarchy graph.

        Returns a mapping of leaf program id -> full path from root to leaf.
        """
        program_edges = [(row["dimension_id"], row["dimension_parent_id"]) for row in programs]
        deduped_edges = {edge for edge in program_edges if edge[1] is not None}
        # Create a directed graph
        g = nx.DiGraph()
        # Add edges to the graph
        g.add_edges_from(deduped_edges)  # pyright: ignore[reportArgumentType]
        roots = (v for v, d in g.in_degree() if d == 0)
        leaves = [v for v, d in g.out_degree() if d == 0]
        program_paths: list[list[int]] = []
        for root in roots:
            paths_raw = nx.all_simple_paths(g, root, leaves)
            paths: list[list[int]] = [[int(elem) for elem in path] for path in paths_raw]
            program_paths.extend(paths)

        # Create a mapping for leaves to their full paths
        # Full path is used for root-to-leaf traversal, so we reverse the paths here
        leave_mapping = {path[0]: path[::-1] for path in program_paths}

        return leave_mapping

    def _build_hierarchy_dict(
        self,
        expense_dimensions: Sequence[RowMapping],
        programs: Sequence[RowMapping],
        program_paths: dict[int, list[int]],
        max_program_levels: int,
    ) -> dict[str, dict[str, int | float | str]]:
        """Build a hierarchy dictionary mapping each row ID to its hierarchy levels.

        CLASSIFIED expenses (from TOTAL budgets) are placed as siblings to SUBCHAPTERs
        (under CHAPTER) and are terminal nodes (no children).
        """

        hierarchy_dict: dict[str, dict[str, int | float | str]] = {}

        # Extract expense_ids from expense_dimensions and map to program path keys
        leaf_expense_mapping: dict[tuple[str, int], set[str]] = {}
        for row in expense_dimensions:
            if row["dimension_id"] in program_paths.keys():
                leaf_expense_mapping.setdefault(
                    (row["dimension_original_identifier"], row["dimension_id"]), set()
                )
                leaf_expense_mapping[
                    (row["dimension_original_identifier"], row["dimension_id"])
                ].add(row["id"])

        for (_, program_id), expenses in leaf_expense_mapping.items():
            # Initialize dict structure and expense value if not already present
            relevant_dims = [row for row in expense_dimensions if row["id"] in expenses]
            for row in relevant_dims:
                expense_id = row["id"]
                hierarchy_dict.setdefault(
                    expense_id,
                    {
                        "VALUE": row.get("value", 0.0),
                        "BUDGET_TYPE": relevant_dims[0].get("budget_type", ""),
                    },
                )
                # Add MINISTRY
                if row["dimension_type"] == "MINISTRY":
                    hierarchy_dict[expense_id]["MINISTRY_DIM_ID"] = row["dimension_id"]
                    hierarchy_dict[expense_id]["MINISTRY_ORIG_ID"] = row[
                        "dimension_original_identifier"
                    ]
                    hierarchy_dict[expense_id]["MINISTRY_NAME"] = row.get("dimension_name", None)
                    hierarchy_dict[expense_id]["MINISTRY_NAME_TRANSLATED"] = row.get(
                        "dimension_name_translated", None
                    )
                # Add CHAPTER
                if row["dimension_type"] == "CHAPTER":
                    hierarchy_dict[expense_id]["CHAPTER_DIM_ID"] = row["dimension_id"]
                    hierarchy_dict[expense_id]["CHAPTER_ORIG_ID"] = row[
                        "dimension_original_identifier"
                    ]
                    hierarchy_dict[expense_id]["CHAPTER_NAME"] = row.get("dimension_name", None)
                    hierarchy_dict[expense_id]["CHAPTER_NAME_TRANSLATED"] = row.get(
                        "dimension_name_translated", None
                    )
                # Add SUBCHAPTER
                if row["dimension_type"] == "SUBCHAPTER":
                    hierarchy_dict[expense_id]["SUBCHAPTER_DIM_ID"] = row["dimension_id"]
                    hierarchy_dict[expense_id]["SUBCHAPTER_ORIG_ID"] = row[
                        "dimension_original_identifier"
                    ]
                    hierarchy_dict[expense_id]["SUBCHAPTER_NAME"] = row.get("dimension_name", None)
                    hierarchy_dict[expense_id]["SUBCHAPTER_NAME_TRANSLATED"] = row.get(
                        "dimension_name_translated", None
                    )

                # Add PROGRAM levels by traversing the program path
                program_path = program_paths.get(program_id, [])
                program_rows = [row for row in programs if row["dimension_id"] in program_path][
                    ::-1
                ]
                if len(program_rows) == 0:
                    raise ValueError(
                        f"No program rows found for program_id {program_id}"
                        f" in program_path {program_path} for budget expense_id {expense_id}"
                    )
                # Sort program rows according to their position in the path
                last_row = program_rows[0]
                for idx in range(0, max_program_levels):
                    if idx < len(program_path):
                        row = program_rows[idx]
                        last_row = row
                    else:
                        row = last_row
                    hierarchy_dict[expense_id][f"PROGRAM_{idx}_DIM_ID"] = row["dimension_id"]
                    hierarchy_dict[expense_id][f"PROGRAM_{idx}_ORIG_ID"] = row[
                        "dimension_original_identifier"
                    ]
                    hierarchy_dict[expense_id][f"PROGRAM_{idx}_NAME"] = row.get(
                        "dimension_name", None
                    )
                    hierarchy_dict[expense_id][f"PROGRAM_{idx}_NAME_TRANSLATED"] = row.get(
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
        for col in df.columns:
            if col != "VALUE":
                df[col] = df[col].apply(lambda x: str(x) if x is not None else None)

        # Add line breaks to long names if max_line_length is set.
        line_length = self.max_line_length
        if line_length is not None:
            for col in df.columns:
                if "NAME" in col:
                    df[col] = df[col].apply(
                        lambda x: add_breaks(x, interval=line_length) if x else x
                    )

        # Normalize empty strings to None for Plotly compatibility.
        df = df.replace(to_replace={"": None})

        return df

    def _create_id_name_mapping(
        self,
        dimension_rows: Sequence[RowMapping],
        program_rows: Sequence[RowMapping],
        translated: bool = False,
    ) -> dict[int, str]:
        name_mapping: dict[int, str] = {}
        for row in dimension_rows:
            d_id = row["dimension_id"]
            d_name = row["dimension_name"] if not translated else row["dimension_name_translated"]
            name_mapping[d_id] = d_name

            # For classified expenses, the dimension_id is already unique (offset by 1000000 in fetch.py)
            # and the dimension_name contains "Classified Spending" so no extra mapping needed

        for row in program_rows:
            d_id = row["dimension_id"]
            d_name = row["dimension_name"] if not translated else row["dimension_name_translated"]
            name_mapping[d_id] = d_name

        # Add name for the synthetic classified parent node used in MINISTRY/PROGRAM views
        name_mapping[-999999] = "Classified Spending"

        return name_mapping

    def _create_id_type_mapping(
        self,
        dimension_rows: Sequence[RowMapping],
    ) -> dict[int, str]:
        type_mapping: dict[int, str] = {}
        for row in dimension_rows:
            d_id = row["dimension_id"]
            d_type = row["budget_type"]
            type_mapping[d_id] = d_type
            # For classified expenses, dimension_id is already unique and budget_type is "CLASSIFIED"

        # Add type for the synthetic classified parent node (for gray coloring)
        type_mapping[-999999] = "CLASSIFIED"

        return type_mapping

    def _extend_sum_mapping_with_hierarchy(
        self,
        sum_mapping: dict[int, float],
        program_paths: dict[int, list[int]],
    ) -> dict[int, float]:
        """
        Extend the sum mapping to include sums for all ancestor dimensions, specifically for
        programs. This ensures that parent dimensions have the correct aggregated sums.
        """
        extended = sum_mapping.copy()
        for leaf_id, path in program_paths.items():
            leaf_sum = sum_mapping.get(leaf_id, 0.0)
            # Propagate from leaf up to (but excluding) the leaf itself
            for ancestor_id in path[::-1][1:]:
                extended[ancestor_id] = extended.get(ancestor_id, 0.0) + leaf_sum
        return extended

    def _extend_sum_mapping_with_classified(
        self,
        sum_mapping: dict[int, float],
        dimensions: Sequence[RowMapping],
        viewby: ViewByDimensionTypeLiteral = "MINISTRY",
    ) -> dict[int, float]:
        """
        Extend the sum mapping to include values for classified expense nodes.

        For MINISTRY/PROGRAM views: adds a parent node with aggregated total,
        individual classified items keep their own values.

        For CHAPTER view: keeps individual classified dimension values as-is.
        """
        classified_rows = [dim for dim in dimensions if dim.get("budget_type") == "CLASSIFIED"]

        if not classified_rows:
            return sum_mapping

        if viewby in ["MINISTRY", "PROGRAM"]:
            # Add the aggregated total for the parent node (dimension_id = -999999)
            # Individual items keep their values from fetch.py
            parent_dim_id = -999999
            total_classified = sum(
                sum_mapping.get(row["dimension_id"], 0) for row in classified_rows
            )
            sum_mapping[parent_dim_id] = total_classified

        # For CHAPTER view, values are already in sum_mapping from fetch.py
        return sum_mapping

    def _filter_hierarchy_dict_by_spending_type(
        self,
        hierarchy: dict[str, dict[str, int | float | str]],
        spending_type: SpendingTypeLiteral,
    ) -> dict[str, dict[str, int | float | str]]:
        """Filter the hierarchy dictionary based on spending type (e.g., military only)."""
        if spending_type == "ALL":
            return hierarchy

        filtered_hierarchy: dict[str, dict[str, int | float | str]] = {}
        for expense_id, levels in hierarchy.items():
            is_military = False
            # Check single level patterns
            combos: list[dict[str, Pattern]] = []
            for level_name, pattern in MilitarySpendingDictionary.items():
                if isinstance(pattern, list):
                    combos = pattern
                    continue
                original_identifier = levels.get(f"{level_name}_ORIG_ID")
                if original_identifier is not None and pattern.match(str(original_identifier)):
                    is_military = True
                    break
            # Check combination patterns
            for combo in combos:
                match = True
                for level_name, pattern in combo.items():
                    original_identifier = levels.get(f"{level_name}_ORIG_ID")
                    if original_identifier is None or not pattern.match(str(original_identifier)):
                        match = False
                        break
                if match:
                    is_military = True
                    break
            if is_military:
                filtered_hierarchy[expense_id] = levels

        return filtered_hierarchy

    def transform_data(
        self,
        dimensions: Sequence[RowMapping],
        programs: Sequence[RowMapping],
        spending_type: SpendingTypeLiteral = "ALL",
    ) -> pd.DataFrame:
        """Transform DB rows into treemap lists expected by the figure creator."""
        if not dimensions:
            return pd.DataFrame()

        # Extend sum mapping to include all hierarchy levels
        program_paths = self._calculate_program_hierarchy(programs)
        # Calculate max length of program paths for consistent PROGRAM_* columns
        max_program_levels = max((len(path) for path in program_paths.values()), default=0)
        # Calculate all paths between dimensions
        hierarchy_dict = self._build_hierarchy_dict(
            dimensions, programs, program_paths, max_program_levels
        )
        # Filter hierarchy based on spending type if needed
        if spending_type != "ALL":
            hierarchy_dict = self._filter_hierarchy_dict_by_spending_type(
                hierarchy_dict, spending_type
            )
        # Create dataframe from paths
        df = self._create_dataframe(
            hierarchy_dict,
        )

        # Build ordered name columns aligned to id columns.

        return df


class BarchartTransformer:
    def _transform_budget_totals(self, budgets: Sequence[RowMapping]) -> pd.DataFrame:
        """Transform law budget rows into a dataframe suitable for barchart visualization."""
        if not budgets:
            return pd.DataFrame()

        # For every published_at, subtract the law value from the total value
        # and set new value as classified expenses

        expenses = [budget["total_value"] for budget in budgets if budget["type"] != "TOTAL"]
        dates = [budget["published_at"] for budget in budgets if budget["type"] != "TOTAL"]
        types = [budget["type"] for budget in budgets if budget["type"] != "TOTAL"]

        df = pd.DataFrame({"expenses": expenses, "dates": dates, "types": types})

        # For every TOTAL-LAW budget, find the corresponding LAW budget and subtract its value
        for budget in budgets:
            if budget["type"] == "TOTAL":
                corresponding_law = next(
                    (
                        b
                        for b in budgets
                        if b["published_at"] == budget["published_at"] and b["type"] != "TOTAL"
                    ),
                    None,
                )
                if corresponding_law is None:
                    continue
                law_value = corresponding_law["total_value"] if corresponding_law else 0.0
                classified_expense = budget["total_value"] - law_value
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

    def transform_data(self, budgets: Sequence[RowMapping]) -> pd.DataFrame:
        """Transform raw rows into a dataframe suitable for barchart visualization."""
        if not budgets:
            return pd.DataFrame()

        df = self._transform_budget_totals(budgets)

        return df
