from functools import lru_cache
from textwrap import wrap
from typing import Sequence
import pandas as pd
from sqlalchemy import RowMapping
from utils.definitions import SpendingTypeLiteral
from utils.fetch_treemap import ClassifiedSpendingData

# Classified spending dimension IDs
CLASSIFIED_DIMENSION_ID_OFFSET = 1_000_000  # Offset to avoid ID conflicts with real dimensions


def _wrap_label(label: str | None, limit: int = 50) -> str | None:
    if not label or len(label) <= limit:
        return label
    return "<br>".join(wrap(label, width=limit))


CLASSIFIED_PARENT_ID = -999_999  # Synthetic ID for aggregated classified parent node


class TreemapTransformer:
    def __init__(
        self,
        dimensions: Sequence[RowMapping],
        programs: Sequence[RowMapping],
        classified_spending: ClassifiedSpendingData,
        spending_type: SpendingTypeLiteral = "ALL",
        char_limit: int = 50,
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
        self.classified_spending = classified_spending
        self.limit = char_limit

    def _calculate_program_hierarchy(self, programs: Sequence[RowMapping]) -> dict[int, list[int]]:
        """Calculate all paths from root to leaves in the program tree.

        Returns a mapping of leaf program id -> full path from root to leaf.
        """
        if not programs:
            return {}

        parent: dict[int, int] = {}
        all_ids: set[int] = set()
        parent_ids: set[int] = set()

        for row in programs:
            dim_id = int(row["dimension_id"])
            par_id = row["dimension_parent_id"]
            all_ids.add(dim_id)
            if par_id is not None:
                parent[dim_id] = int(par_id)
                parent_ids.add(int(par_id))

        if not parent:
            return {}

        # Leaves are nodes that are not a parent of any other node.
        leaves = all_ids - parent_ids

        result: dict[int, list[int]] = {}
        for leaf in leaves:
            path: list[int] = []
            node: int | None = leaf
            seen: set[int] = set()
            while node is not None and node not in seen:
                path.append(node)
                seen.add(node)
                node = parent.get(node)
            # path is [leaf, …, root] — reverse to root-first order
            result[leaf] = path[::-1]

        return result

    def _build_hierarchy_dict(
        self,
        expense_dimensions: Sequence[RowMapping],
        programs: Sequence[RowMapping],
        program_paths: dict[int, list[int]],
        max_program_levels: int,
    ) -> dict[str, dict[str, int | float | str]]:
        """
        Build a hierarchy dictionary mapping each expense dimension to its full path in the program hierarchy.
            Each entry in the hierarchy dictionary will contain:
            - VALUE: The expense value for this dimension.
            - BUDGET_TYPE: The budget type (e.g., LAW, REPORT) for this dimension.
            - IS_MILITARY: A boolean indicating if this dimension is classified as military spending based on its type and original identifier.
            - For each hierarchy level (MINISTRY, CHAPTER, SUBCHAPTER, PROGRAM_0, PROGRAM_1, PROGRAM_2):
                - {LEVEL}_DIM_ID: The dimension_id of the corresponding hierarchy level.
                - {LEVEL}_ORIG_ID: The dimension_original_identifier of the corresponding hierarchy level.
                - {LEVEL}_NAME: The dimension_name of the corresponding hierarchy level.
                - {LEVEL}_NAME_TRANSLATED: The dimension_name_translated of the corresponding hierarchy level.

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
            program_rows = [program_by_dim_id[d] for d in program_path if d in program_by_dim_id]

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
                        # take absolute value to avoid negative values in treemap
                        "VALUE": abs(row.get("value", 0.0)),
                        "BUDGET_TYPE": relevant_dims[0].get("budget_type", ""),
                        "IS_MILITARY": bool(row.get("is_military", False)),
                    },
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
        root_name: str = "Federal budget",
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
        ordered_columns = ["VALUE", "BUDGET_TYPE", "IS_MILITARY", "ROOT"]
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

        # Insert <br> into labels longer than 50 characters.
        for col in df.columns:
            if "NAME" in col:
                df[col] = df[col].apply(_wrap_label, args=(self.limit,))

        # Normalize empty strings to None for Plotly compatibility.
        df = df.replace(to_replace={"": None})

        return df

    def _add_classified_expenses(
        self,
        df: pd.DataFrame,
    ) -> pd.DataFrame:
        """Add Classified Spending rows sourced from pre-computed classified spending views."""
        cs = self.classified_spending
        new_entries: list[dict] = []

        if cs.budget_type == "LAW":
            for chapter in cs.chapters:
                orig_id = chapter.original_identifier
                # Synthetic sub-ID derived from original_identifier (e.g. "02" → 1_000_002).
                synthetic_id = CLASSIFIED_DIMENSION_ID_OFFSET + int(orig_id.lstrip("0") or "0")
                # Prefix with original_identifier to match the format used by
                # _build_dimension_name_column (e.g. "02 Национальная оборона").
                chapter_name = _wrap_label(f"{orig_id} {chapter.chapter_name}", self.limit)
                chapter_name_translated = _wrap_label(
                    f"{orig_id} {chapter.chapter_name_translated}"
                    if chapter.chapter_name_translated
                    else chapter_name,
                    self.limit,
                )
                classified_entry: dict[str, int | float | str | None] = {
                    "VALUE": chapter.classified_spending,
                    "BUDGET_TYPE": "CLASSIFIED",
                    "ROOT": "Federal budget",
                    "IS_MILITARY": None,
                    "MINISTRY_DIM_ID": CLASSIFIED_PARENT_ID,
                    "MINISTRY_ORIG_ID": "CLASSIFIED_PARENT",
                    "MINISTRY_NAME": "Classified spending",
                    "MINISTRY_NAME_TRANSLATED": "Classified spending",
                    "CHAPTER_DIM_ID": chapter.dimension_id,
                    "CHAPTER_ORIG_ID": orig_id,
                    "CHAPTER_NAME": chapter_name,
                    "CHAPTER_NAME_TRANSLATED": chapter_name_translated,
                    "SUBCHAPTER_DIM_ID": synthetic_id,
                    "SUBCHAPTER_ORIG_ID": f"CLASSIFIED_{orig_id}",
                    "SUBCHAPTER_NAME": "Classified spending",
                    "SUBCHAPTER_NAME_TRANSLATED": "Classified spending",
                }
                for idx in range(0, 3):
                    classified_entry[f"PROGRAM_{idx}_DIM_ID"] = synthetic_id
                    classified_entry[f"PROGRAM_{idx}_ORIG_ID"] = f"CLASSIFIED_{orig_id}"
                    classified_entry[f"PROGRAM_{idx}_NAME"] = "Classified spending"
                    classified_entry[f"PROGRAM_{idx}_NAME_TRANSLATED"] = "Classified spending"

                new_entries.append(classified_entry)

            if new_entries:
                df = pd.concat([df, pd.DataFrame(new_entries)], ignore_index=True)

        elif cs.budget_type == "REPORT":
            if self.spending_type == "MILITARY" and cs.military_classified > 0:
                value = cs.military_classified
                share_pct = cs.military_classified_share * 100
                ministry_name = _wrap_label(
                    f"Classified spending (estimated as {share_pct:.1f}%"
                    f" of total classified spending)",
                    self.limit,
                )
            elif cs.total_classified > 0:
                value = cs.total_classified
                ministry_name = "Classified spending"
            else:
                return df

            root_row: dict[str, int | float | str | None] = {
                "VALUE": value,
                "BUDGET_TYPE": "CLASSIFIED",
                "ROOT": "Federal budget",
                "MINISTRY_DIM_ID": CLASSIFIED_PARENT_ID,
                "MINISTRY_ORIG_ID": "CLASSIFIED_PARENT",
                "MINISTRY_NAME": ministry_name,
                "MINISTRY_NAME_TRANSLATED": ministry_name,
                "CHAPTER_DIM_ID": CLASSIFIED_DIMENSION_ID_OFFSET + 1,
                "CHAPTER_ORIG_ID": "CLASSIFIED_CHAPTER",
                "CHAPTER_NAME": ministry_name,
                "CHAPTER_NAME_TRANSLATED": ministry_name,
                "SUBCHAPTER_DIM_ID": CLASSIFIED_DIMENSION_ID_OFFSET + 2,
                "SUBCHAPTER_ORIG_ID": "CLASSIFIED_SUBCHAPTER",
                "SUBCHAPTER_NAME": ministry_name,
                "SUBCHAPTER_NAME_TRANSLATED": ministry_name,
            }
            for idx in range(0, 3):
                root_row[f"PROGRAM_{idx}_DIM_ID"] = CLASSIFIED_DIMENSION_ID_OFFSET + 3 + idx
                root_row[f"PROGRAM_{idx}_ORIG_ID"] = "CLASSIFIED_PROGRAM_" + str(idx)
                root_row[f"PROGRAM_{idx}_NAME"] = root_row["MINISTRY_NAME"]
                root_row[f"PROGRAM_{idx}_NAME_TRANSLATED"] = root_row["MINISTRY_NAME_TRANSLATED"]
            df = pd.concat([df, pd.DataFrame([root_row])], ignore_index=True)

        return df

    def subtract_prev_quarter(self, df: pd.DataFrame, prev_df: pd.DataFrame) -> pd.DataFrame:
        """Subtract previous quarter's cumulative values to produce quarterly-only values."""
        dim_id_cols = [c for c in df.columns if c.endswith("_DIM_ID")]
        merged = df.merge(
            prev_df[dim_id_cols + ["VALUE"]].rename(columns={"VALUE": "PREV_VALUE"}),
            on=dim_id_cols,
            how="left",
        )
        result = df.copy()
        result["VALUE"] = (merged["VALUE"] - merged["PREV_VALUE"].fillna(0)).clip(lower=0).values
        return result

    def transform_from_flat(self, flat_rows: Sequence[RowMapping]) -> pd.DataFrame:
        """Fast path: build DataFrame from pre-computed table rows, skipping networkx."""
        df = pd.DataFrame(flat_rows)
        df = df.drop(columns=["id", "expense_id", "budget_id"], errors="ignore")
        df["ROOT"] = "Federal budget"
        df["VALUE"] = df["VALUE"].astype(float)
        df = self._add_classified_expenses(df)
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
