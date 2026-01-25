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


class TreemapTransformer:
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
        program_paths: dict[int, list[int]],
        viewby: ViewByDimensionTypeLiteral = "MINISTRY",
    ) -> dict[int, dict[str, int]]:
        """Build a hierarchy dictionary mapping each row ID to its hierarchy levels."""

        hierarchy_dict: dict[int, dict[str, int]] = {}
        for row in expense_dimensions:
            # Initialize dict structure and expense value if not already present
            hierarchy_dict.setdefault(
                row["id"],
                {},
            )
            if row["dimension_type"] == "MINISTRY" and viewby in ["MINISTRY"]:
                hierarchy_dict[row["id"]]["MINISTRY"] = row["dimension_id"]
                hierarchy_dict[row["id"]]["MINISTRY_ORIG_ID"] = row["dimension_original_identifier"]

            if row["dimension_type"] == "CHAPTER" and viewby in ["MINISTRY", "CHAPTER"]:
                hierarchy_dict[row["id"]]["CHAPTER"] = row["dimension_id"]
                hierarchy_dict[row["id"]]["CHAPTER_ORIG_ID"] = row["dimension_original_identifier"]

            if row["dimension_type"] == "SUBCHAPTER" and viewby in ["MINISTRY", "CHAPTER"]:
                hierarchy_dict[row["id"]]["SUBCHAPTER"] = row["dimension_id"]
                hierarchy_dict[row["id"]]["SUBCHAPTER_ORIG_ID"] = row[
                    "dimension_original_identifier"
                ]

            program_path = []
            if row["dimension_type"] == "PROGRAM":
                program_path = program_paths.get(row["dimension_id"], [])
            if program_path and len(program_path) > 0:
                level = 0
                for program in program_path:
                    hierarchy_dict[row["id"]][f"PROGRAM_{level}"] = program
                    hierarchy_dict[row["id"]][f"PROGRAM_{level}_ORIG_ID"] = row[
                        "dimension_original_identifier"
                    ]
                    level += 1

        return hierarchy_dict

    def _create_lists(
        self,
        hierarchy: dict[int, dict[str, int]],
        name_mapping: dict[int, str],
        value_mapping: dict[int, float],
        root_name: str = "Federal Budget",
    ) -> tuple[list[str], list[str], list[float], list[str], list[str]]:
        """Build the treemap lists (names, parents, values, metadata) from hierarchy.

        Since the same dimension (e.g., CHAPTER) can appear under different parents
        (e.g., different MINISTRYs), we create path-based unique identifiers.
        This allows the treemap to correctly show the same dimension under multiple parents.
        """
        # Track seen paths to avoid duplicates - key is the full path from root
        seen_paths: set[str] = set()
        metadata: list[str] = ["root"]
        names = [root_name]
        parents = [""]
        children: list[str] = [root_name]
        values: list[float] = [0.0]
        highlevel_value = 0.0

        # Ensure an intuitive ordering: MINISTRY -> CHAPTER -> SUBCHAPTER -> PROGRAM_*
        LEVEL_ORDER_INDEX = {"MINISTRY": 0, "CHAPTER": 1, "SUBCHAPTER": 2, "PROGRAM": 3}

        def _get_level_sort_key(level_name: str) -> tuple[int, int]:
            """Sort key for hierarchy levels, ensuring PROGRAM_0 < PROGRAM_1 < PROGRAM_2."""
            parts = level_name.split("_")
            base_name = parts[0]
            primary_order = LEVEL_ORDER_INDEX.get(base_name, 100)
            secondary_order = 0
            if base_name == "PROGRAM" and len(parts) > 1 and parts[1].isdigit():
                secondary_order = int(parts[1])
            return (primary_order, secondary_order)

        for _, levels in hierarchy.items():
            # Build path-based identifiers for this expense's hierarchy
            # parent_path tracks the full path string for parent references
            parent_path = root_name

            # Sort levels based on predefined order
            sorted_level_names = sorted(
                (level_name for level_name in levels.keys() if not level_name.endswith("_ORIG_ID")),
                key=_get_level_sort_key,
            )

            for level_name in sorted_level_names:
                dim_id = levels[level_name]
                # Create a path-based unique identifier: "parent_path/dim_id"
                # This ensures the same dim_id under different parents creates separate nodes
                current_path = f"{parent_path}/{dim_id}"

                if current_path in seen_paths:
                    # This exact path already exists, just update parent reference for next level
                    parent_path = current_path
                    continue

                # New unique path, add to lists
                seen_paths.add(current_path)
                # Create metadata entry
                metadata.append(level_name.title() + str(dim_id))
                # Add name from mapping or default
                names.append(name_mapping.get(dim_id, f"Unknown {dim_id}"))
                # Add parent and child references
                children.append(current_path)
                parents.append(parent_path)
                # Add value from mapping or default to 0
                value = value_mapping.get(dim_id, 0)
                values.append(value)
                # Accumulate highlevel value for top-level nodes
                if level_name == sorted_level_names[0]:
                    highlevel_value += value

                # Update parent_path for the next level in this hierarchy
                parent_path = current_path

        # Set Federal Budget value
        values[0] = highlevel_value

        return children, parents, values, metadata, names

    def _create_id_name_mapping(
        self,
        dimension_rows: Sequence[RowMapping],
        program_rows: Sequence[RowMapping],
        translated: bool = False,
    ) -> dict[int, str]:
        name_mapping = {}
        for row in dimension_rows:
            d_id = row["dimension_id"]
            d_name = row["dimension_name"] if not translated else row["dimension_name_translated"]
            name_mapping[d_id] = d_name
        for row in program_rows:
            d_id = row["dimension_id"]
            d_name = row["dimension_name"] if not translated else row["dimension_name_translated"]
            name_mapping[d_id] = d_name
        return name_mapping

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

    def _filter_hierarchy_dict_by_spending_type(
        self,
        hierarchy: dict[int, dict[str, int]],
        spending_type: SpendingTypeLiteral,
    ) -> dict[int, dict[str, int]]:
        """Filter the hierarchy dictionary based on spending type (e.g., military only)."""
        if spending_type == "ALL":
            return hierarchy

        filtered_hierarchy: dict[int, dict[str, int]] = {}
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
        sum_mapping: dict[int, float],
        translated_names: bool = False,
        spending_type: SpendingTypeLiteral = "ALL",
        viewby: ViewByDimensionTypeLiteral = "MINISTRY",
    ) -> tuple[list[str], list[str], list[float], list[str], list[str]]:
        """Transform DB rows into treemap lists expected by the figure creator."""
        if not dimensions:
            return [], [], [], [], []

        # Extend sum mapping to include all hierarchy levels
        program_paths = self._calculate_program_hierarchy(programs)
        sum_mapping = self._extend_sum_mapping_with_hierarchy(sum_mapping, program_paths)

        name_mapping = self._create_id_name_mapping(dimensions, programs, translated_names)
        # Calculate all paths between dimensions
        hierarchy_dict = self._build_hierarchy_dict(dimensions, program_paths, viewby)
        # Filter hierarchy based on spending type if needed
        if spending_type != "ALL":
            hierarchy_dict = self._filter_hierarchy_dict_by_spending_type(
                hierarchy_dict, spending_type
            )
        # Create dataframe from paths
        result_tuple = self._create_lists(hierarchy_dict, name_mapping, sum_mapping)

        return result_tuple


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

                df = pd.concat(
                    [
                        df,
                        pd.DataFrame(
                            {
                                "expenses": [classified_expense],
                                "dates": [budget["published_at"]],
                                "types": ["CLASSIFIED"],
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
