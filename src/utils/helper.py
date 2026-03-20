"""
Miscellaneous utility functions
"""

import hashlib
import random
import re

import pandas as pd

from utils.definitions import (
    Colors,
    MilitarySpending,
    SpendingTypeLiteral,
    ViewByDimensionTypeLiteral,
)
from plotly import graph_objects as go


def add_breaks(string: str, interval: int = 25) -> str:
    """
    Insert <br> into a string so every part is at most `interval` characters.
    Splits at the whitespace closest to (and at or before) the interval boundary.
    Falls back to a hard break at the boundary if no whitespace is found.
    """
    if len(string) <= interval:
        return string

    parts = []
    start = 0
    while start < len(string):
        end = start + interval
        if end >= len(string):
            parts.append(string[start:])
            break
        # Last whitespace at or before the interval boundary
        matches = list(re.compile(r"\s").finditer(string, start, end + 1))
        space_index = matches[-1].start() if matches else -1
        if space_index > start:
            parts.append(string[start:space_index])
            start = space_index + 1
        else:
            # No whitespace in range — hard break at the boundary
            parts.append(string[start:end])
            start = end
    return "<br>".join(parts)


def create_treemap_colors(
    node_ids: list[str],
    budget_types: list[str],
    spending_type: SpendingTypeLiteral,
    viewby: ViewByDimensionTypeLiteral,
) -> list[str]:
    """Return marker colors for treemap nodes with ministry/root rules applied."""

    def _stable_random_filler_color(key: str) -> str:
        """Pick a filler color using a deterministic random seed derived from key."""
        seed_bytes = hashlib.sha256(key.encode("utf-8")).digest()
        rng = random.Random(int.from_bytes(seed_bytes[:8], "big"))
        # Use a seeded RNG so the same key always maps to the same palette entry.
        return rng.choice(Colors.color_mapping_filler)

    def _node_id_to_orig_ids(node_id: str) -> tuple[list[str], str]:
        """Transforms a node_id into a list of original IDs by
        first splitting the node_id at every forward slash and then extracting the original ID
        from the label of each node in the path.
        """
        path_ids = node_id.split("/")
        orig_ids = []
        label: str = path_ids[-1]  # The label is the last part of the node_id path
        for pid in path_ids:
            orig_id = pid.split(" - ")[
                0
            ]  # Extract original ID from label (e.g., "01 - General State")
            orig_ids.append(orig_id)
        return orig_ids, label

    # Assign colors based on node_id, budget_type and viewby dimension
    # The logic is as follows:
    # - If the node is classified, it should be gray.
    # - If the viewby is MINISTRY, ministry nodes should be gray
    #   and chapter nodes should be colored based on the chapter color mapping.
    # - If the viewby is CHAPTER, chapter nodes
    #   and their children should be colored based on the chapter color mapping.
    # - If the viewby is PROGRAM, program nodes
    #   and their children should be colored based on a stable random color
    #   derived from the highest level program ID
    # - The root node should be white unless the spending type is military,
    #   in which case it should be green.

    colors: list[str] = []
    for node_id, budget_type in zip(node_ids, budget_types):
        # Root node should be white unless the spending type is military.
        node_original_id_list, _ = _node_id_to_orig_ids(node_id)
        color = Colors.ROOT_WHITE  # Default color

        # Ministry nodes should be gray.
        if viewby == "MINISTRY" and len(node_original_id_list) == 2:
            color = Colors.MINISTRY_GRAY

        if viewby == "MINISTRY" and len(node_original_id_list) > 2:
            chapter_id = node_original_id_list[2]
            color = Colors.color_mapping_chapters.get(chapter_id, Colors.ROOT_WHITE)

        # Chapter nodes and children should be colored based the color mapping for the chapters
        if viewby == "CHAPTER" and len(node_original_id_list) >= 2:
            chapter_id = node_original_id_list[1]
            color = Colors.color_mapping_chapters.get(chapter_id, Colors.ROOT_WHITE)

        if viewby == "PROGRAM" and len(node_original_id_list) >= 2:
            main_program_id = node_original_id_list[1]
            color = _stable_random_filler_color(main_program_id)

        # Classified nodes should be gray.
        if "CLASSIFIED" in budget_type.upper():
            color = Colors.CLASSIFIED_GRAY

        # Root node should be white unless the spending type is military.
        if len(node_original_id_list) == 1:
            color = Colors.MILITARY_GREEN if spending_type == "MILITARY" else Colors.ROOT_WHITE

        colors.append(color)

    return colors


def shape_for_spending_type(
    df: pd.DataFrame,
    spending_type: SpendingTypeLiteral,
) -> pd.DataFrame:
    """Return the shape configuration for the given spending type."""
    # For military spending, we might want to highlight certain ministries or chapters.
    # This function can be expanded in the future if needed.
    if spending_type == "MILITARY":
        # Filter the dataframe to include only rows that match the military spending criteria
        # First, we check for single-dimension matches based on the patterns
        # defined in MilitarySpendingDictionary["SINGLE"].
        df_single = df[
            df.apply(
                lambda row: any(
                    (
                        re.match(pattern, str(row.get(f"{dim}_ORIG_ID", "")))
                        if isinstance(pattern, re.Pattern)
                        else False
                    )
                    # or row.get("BUDGET_TYPE") == "CLASSIFIED"
                    for dim, pattern in MilitarySpending.simple_patterns.items()
                    if dim.endswith("CHAPTER")
                    or dim.endswith("PROGRAM")
                    or dim.endswith("MINISTRY")
                ),
                axis=1,
            )
        ]
        # Then, we check for combination matches based on the patterns
        # defined in MilitarySpendingDictionary["COMBINATION"].
        df_combination = df[
            df.apply(
                lambda row: any(
                    all(
                        re.match(pattern, str(row.get(f"{dim}_ORIG_ID", "")))
                        if isinstance(pattern, re.Pattern)
                        else False
                        for dim, pattern in combination.items()
                    )
                    for combination in MilitarySpending.combination_patterns
                ),
                axis=1,
            )
        ]
        # Finally, we check for custom classified matches based on the patterns
        # defined in MilitarySpendingDictionary["CUSTOM_CLASSIFIED"].
        df_classified = df[
            df.apply(
                lambda row: any(
                    (
                        re.match(pattern, str(row.get(f"{dim}_ORIG_ID", "")))
                        if isinstance(pattern, re.Pattern)
                        else False
                    )
                    and row.get("BUDGET_TYPE") == "CLASSIFIED"
                    for dim, pattern in MilitarySpending.custom_patterns.items()
                    if dim.endswith("CHAPTER")
                    or dim.endswith("PROGRAM")
                    or dim.endswith("MINISTRY")
                ),
                axis=1,
            )
        ]
        # Combine both single and combination matches and remove duplicates
        df_military = (
            pd.concat([df_single, df_combination, df_classified])
            .drop_duplicates()
            .reset_index(drop=True)
        )
        df_military["ROOT"] = "Military Spending"
        return df_military
    return df


def shape_for_viewby(
    df: pd.DataFrame,
    viewby: ViewByDimensionTypeLiteral,
) -> pd.DataFrame:
    """Return the shape configuration for the given viewby dimension."""

    # create a copy to avoid modifying the original dataframe
    df_copy = df.copy()

    relevant_cols = []
    if viewby == "MINISTRY":
        # Remove Everything but Ministry, Chapter, lowest level and Value
        relevant_cols = [
            col for col in df_copy.columns if col.startswith(("MINISTRY", "CHAPTER", "PROGRAM_3"))
        ] + ["VALUE", "ROOT", "BUDGET_TYPE"]

    if viewby == "CHAPTER":
        # Remove Everything but Chapter, lowest level and Value
        relevant_cols = [
            col for col in df_copy.columns if col.startswith(("CHAPTER", "SUBCHAPTER", "PROGRAM_3"))
        ] + ["VALUE", "ROOT", "BUDGET_TYPE"]

    if viewby == "PROGRAM":
        # Remove Everything but lowest level and Value
        classified_rows = df_copy["BUDGET_TYPE"] == "CLASSIFIED"
        relevant_cols = [
            col
            for col in df_copy.columns
            if col.startswith(("PROGRAM_0", "PROGRAM_1", "PROGRAM_3"))
        ] + ["VALUE", "ROOT", "BUDGET_TYPE"]
        # For classified rows, copy values from CHAPTER columns to PROGRAM_1 columns
        # and set PROGRAM_3 columns to None
        for col in df_copy.columns:
            if col.startswith("CHAPTER") and "NAME" in col:
                target_col = col.replace("CHAPTER", "PROGRAM_1")
                df_copy.loc[classified_rows, target_col] = df_copy.loc[classified_rows, col].values
            if col.startswith("PROGRAM_3") and "NAME" in col:
                df_copy.loc[classified_rows, col] = None

    df_copy = df_copy[relevant_cols]

    return df_copy
