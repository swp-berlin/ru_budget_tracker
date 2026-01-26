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
    ) -> dict[int, dict[str, int | str]]:
        """Build a hierarchy dictionary mapping each row ID to its hierarchy levels.

        CLASSIFIED expenses (from TOTAL budgets) are placed as siblings to SUBCHAPTERs
        (under CHAPTER) and are terminal nodes (no children).
        """

        hierarchy_dict: dict[int, dict[str, int | str]] = {}

        # Separate classified and non-classified rows
        # Classified rows are synthetic dimensions created by _create_difference_dimension in fetch.py
        # They include ministry_id and ministry_original_identifier for proper hierarchy placement
        classified_rows = [row for row in expense_dimensions if row["budget_type"] == "CLASSIFIED"]
        non_classified = [row for row in expense_dimensions if row["budget_type"] != "CLASSIFIED"]

        # Build dimension lookup to derive ministry via chapter parent_id
        dim_info: dict[int, dict[str, int | str | None]] = {}
        id_to_orig: dict[int, str] = {}
        for row in non_classified:
            dim_id = row["dimension_id"]
            # Record dimension metadata for parent traversal
            if dim_id not in dim_info:
                dim_info[dim_id] = {
                    "id": dim_id,
                    "parent_id": row["dimension_parent_id"],
                    "type": row["dimension_type"],
                    "orig_id": row["dimension_original_identifier"],
                }
            # Record original identifier for reverse lookup
            if dim_id not in id_to_orig and row.get("dimension_original_identifier") is not None:
                id_to_orig[dim_id] = row["dimension_original_identifier"]

        # Build a canonical chapter->ministry mapping based on expense associations
        # This avoids duplicate chapters under multiple ministries when parent_id is missing
        chapter_ministry_counts: dict[int, dict[int, int]] = {}
        expense_to_rows: dict[int, list[RowMapping]] = {}
        for row in non_classified:
            expense_to_rows.setdefault(row["id"], []).append(row)
        for rows in expense_to_rows.values():
            chapter_ids = {r["dimension_id"] for r in rows if r.get("dimension_type") == "CHAPTER"}
            ministry_ids = {
                r["dimension_id"] for r in rows if r.get("dimension_type") == "MINISTRY"
            }
            for chapter_id in chapter_ids:
                ministry_counts = chapter_ministry_counts.setdefault(chapter_id, {})
                for ministry_id in ministry_ids:
                    ministry_counts[ministry_id] = ministry_counts.get(ministry_id, 0) + 1
        chapter_to_ministry: dict[int, int] = {}
        for chapter_id, ministry_counts in chapter_ministry_counts.items():
            # Pick the most frequent ministry for each chapter
            ministry_id = max(ministry_counts.items(), key=lambda item: item[1])[0]
            chapter_to_ministry[chapter_id] = ministry_id

        for row in non_classified:
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

        # Fix ministry assignment using chapter->ministry mapping to avoid false ministry mappings
        if viewby in ["MINISTRY"]:
            for _, levels in hierarchy_dict.items():
                chapter_id = levels.get("CHAPTER")
                if isinstance(chapter_id, int):
                    ministry_id = chapter_to_ministry.get(chapter_id)
                    if isinstance(ministry_id, int):
                        # Always overwrite with derived ministry to keep chapter->ministry consistent
                        levels["MINISTRY"] = ministry_id
                        ministry_orig = id_to_orig.get(ministry_id)
                        if ministry_orig is not None:
                            levels["MINISTRY_ORIG_ID"] = ministry_orig

        # Add classified expenses as separate entries - siblings to subchapters under their chapter
        # These are terminal nodes (no children like SUBCHAPTER or PROGRAM)
        # Classified rows from fetch.py have dimension_type="CLASSIFIED" and include
        # ministry_id and ministry_original_identifier for proper placement

        # For MINISTRY or PROGRAM view: aggregate all classified into ONE parent tile under root
        # with individual classified items as children
        # For CHAPTER view: keep classified under each chapter as siblings to subchapters
        if viewby in ["MINISTRY", "PROGRAM"] and classified_rows:
            # Create a parent "Classified Spending" node under root
            # Use a special negative key that won't conflict with expense IDs
            parent_key = -999999
            # Use a synthetic dimension_id for the parent node (high negative number)
            parent_dim_id = -999999
            hierarchy_dict[parent_key] = {}
            hierarchy_dict[parent_key]["CLASSIFIED_PARENT"] = parent_dim_id
            hierarchy_dict[parent_key]["CLASSIFIED_PARENT_ORIG_ID"] = "CLASSIFIED"

            # Add each individual classified spending as a child under the parent
            for row in classified_rows:
                hierarchy_dict.setdefault(row["id"], {})
                # Set the parent level so this item appears under the aggregated tile
                hierarchy_dict[row["id"]]["CLASSIFIED_PARENT"] = parent_dim_id
                hierarchy_dict[row["id"]]["CLASSIFIED_PARENT_ORIG_ID"] = "CLASSIFIED"
                # Add the individual classified item
                chapter_orig_id = row.get("dimension_original_identifier", "")
                hierarchy_dict[row["id"]]["CLASSIFIED"] = row["dimension_id"]
                hierarchy_dict[row["id"]]["CLASSIFIED_ORIG_ID"] = chapter_orig_id
        else:
            # CHAPTER view: place classified under each chapter
            for row in classified_rows:
                hierarchy_dict.setdefault(
                    row["id"],
                    {},
                )

                # For CLASSIFIED dimension_type, use the ministry info included in the row
                if row["dimension_type"] == "CLASSIFIED":
                    chapter_orig_id = row.get("dimension_original_identifier")

                    # Add CHAPTER level using dimension_parent_id (which is the LAW budget's chapter ID)
                    parent_chapter_id = row.get("dimension_parent_id")
                    if parent_chapter_id and chapter_orig_id:
                        hierarchy_dict[row["id"]]["CHAPTER"] = parent_chapter_id
                        hierarchy_dict[row["id"]]["CHAPTER_ORIG_ID"] = chapter_orig_id

                    # Add the CLASSIFIED node itself as a terminal node (sibling to SUBCHAPTER)
                    hierarchy_dict[row["id"]]["CLASSIFIED"] = row["dimension_id"]
                    hierarchy_dict[row["id"]]["CLASSIFIED_ORIG_ID"] = chapter_orig_id or ""

        return hierarchy_dict

    def _create_lists(
        self,
        hierarchy: dict[int, dict[str, int | str]],
        name_mapping: dict[int, str],
        value_mapping: dict[int, float],
        type_mapping: dict[int, str],
        root_name: str = "Federal Budget",
    ) -> tuple[list[str], list[str], list[float], list[list[str]], list[str]]:
        """Build the treemap lists (names, parents, values, metadata) from hierarchy.

        Since the same dimension (e.g., CHAPTER) can appear under different parents
        (e.g., different MINISTRYs), we create path-based unique identifiers.
        This allows the treemap to correctly show the same dimension under multiple parents.
        """
        # Track seen paths to avoid duplicates - key is the full path from root
        seen_paths: set[str] = set()
        # Track program placement to prevent the same program from appearing under different parents
        # This avoids false assignments when expense-dimension associations are inconsistent
        seen_program_paths: dict[int, str] = {}
        metadata: list[list[str]] = [["root", ""]]
        names = [root_name]
        parents = [""]
        children: list[str] = [root_name]
        values: list[float] = [0.0]
        highlevel_value = 0.0

        # Ensure an intuitive ordering: MINISTRY -> CHAPTER -> SUBCHAPTER -> PROGRAM_*
        # CLASSIFIED_PARENT is at top level (sibling to MINISTRY), CLASSIFIED is under it
        LEVEL_ORDER_INDEX = {
            "MINISTRY": 0,
            "CLASSIFIED_PARENT": 0,  # Same level as MINISTRY (top-level under root)
            "CHAPTER": 1,
            "CLASSIFIED": 2,  # Under CLASSIFIED_PARENT or under CHAPTER
            "SUBCHAPTER": 3,
            "PROGRAM": 4,
        }

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
                # Cast to int since we know non-_ORIG_ID values are dimension IDs (integers)
                dim_id_int = (
                    int(dim_id)
                    if isinstance(dim_id, (int, str)) and str(dim_id).lstrip("-").isdigit()
                    else dim_id
                )
                # Create a path-based unique identifier: "parent_path/dim_id"
                # This ensures the same dim_id under different parents creates separate nodes
                current_path = f"{parent_path}/{dim_id}"

                # Prevent programs from being placed under multiple parents
                # If a program already has a recorded path, skip inconsistent placements
                if level_name.startswith("PROGRAM") and isinstance(dim_id_int, int):
                    existing_program_path = seen_program_paths.get(dim_id_int)
                    if existing_program_path and existing_program_path != current_path:
                        # Skip the remainder of this branch to avoid false duplication
                        break

                if current_path in seen_paths:
                    # This exact path already exists, just update parent reference for next level
                    parent_path = current_path
                    continue

                # New unique path, add to lists
                seen_paths.add(current_path)
                # Record program path once to enforce unique placement across the treemap
                if level_name.startswith("PROGRAM") and isinstance(dim_id_int, int):
                    seen_program_paths.setdefault(dim_id_int, current_path)
                # Create metadata entry - use dim_id_int for lookups
                budget_type = type_mapping.get(dim_id_int, "UNKNOWN")
                metadata.append([level_name.title() + str(dim_id), budget_type])  # type: ignore[arg-type]
                # Add name from mapping or default
                names.append(name_mapping.get(dim_id_int, f"Unknown {dim_id}"))  # type: ignore[arg-type]
                # Add parent and child references
                children.append(current_path)
                parents.append(parent_path)
                # Add value from mapping or default to 0
                value = value_mapping.get(dim_id_int, 0)  # type: ignore[arg-type]
                values.append(value)
                # Accumulate highlevel value for top-level nodes
                # Also include classified spending values in the root total
                if level_name == sorted_level_names[0]:
                    highlevel_value += value
                elif budget_type == "CLASSIFIED":
                    # Classified spending should be included in root total
                    # even when it's not a top-level node (e.g., in CHAPTER view)
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
        hierarchy: dict[int, dict[str, int | str]],
        spending_type: SpendingTypeLiteral,
    ) -> dict[int, dict[str, int | str]]:
        """Filter the hierarchy dictionary based on spending type (e.g., military only)."""
        if spending_type == "ALL":
            return hierarchy

        filtered_hierarchy: dict[int, dict[str, int | str]] = {}
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
    ) -> tuple[list[str], list[str], list[float], list[list[str]], list[str]]:
        """Transform DB rows into treemap lists expected by the figure creator."""
        if not dimensions:
            return [], [], [], [], []

        # Extend sum mapping to include all hierarchy levels
        program_paths = self._calculate_program_hierarchy(programs)
        sum_mapping = self._extend_sum_mapping_with_hierarchy(sum_mapping, program_paths)
        # Extend sum mapping to include classified expense values (aggregated for MINISTRY/PROGRAM views)
        sum_mapping = self._extend_sum_mapping_with_classified(sum_mapping, dimensions, viewby)

        name_mapping = self._create_id_name_mapping(dimensions, programs, translated_names)
        type_mapping = self._create_id_type_mapping(dimensions)
        # Calculate all paths between dimensions
        hierarchy_dict = self._build_hierarchy_dict(dimensions, program_paths, viewby)
        # Filter hierarchy based on spending type if needed
        if spending_type != "ALL":
            hierarchy_dict = self._filter_hierarchy_dict_by_spending_type(
                hierarchy_dict, spending_type
            )
        # Create dataframe from paths
        result_tuple = self._create_lists(hierarchy_dict, name_mapping, sum_mapping, type_mapping)

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
