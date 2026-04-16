"""
Miscellaneous utility functions
"""

import colorsys
import hashlib

import pandas as pd

from utils.definitions import (
    Colors,
    MilitarySpending,
    SpendingTypeLiteral,
    UnitLiteral,
    ViewByDimensionTypeLiteral,
    unit_config,
)
from plotly import graph_objects as go


def get_unit_label(unit: UnitLiteral) -> str:
    """Return the human-readable label for a unit (used as CSV column header)."""
    return next(label for label, u in unit_config.options if u == unit)


def create_treemap_colors(
    node_ids: list[str],
    budget_types: list[str],
    spending_type: SpendingTypeLiteral,
    viewby: ViewByDimensionTypeLiteral,
    program_label_to_orig_id: dict[str, str] | None = None,
) -> list[str]:
    """Return marker colors for treemap nodes with ministry/root rules applied."""

    def _stable_deterministic_color(key: str) -> str:
        """Generate a unique, deterministic pastel color for a key via HSL.

        Uses the SHA-256 hash of the key to derive a hue that is evenly spread
        across the full 360° colour wheel, while keeping saturation and lightness
        fixed so that all generated colours have a consistent, readable tone.
        The same key always produces the same hex colour regardless of which
        budget is being viewed.
        """
        seed_bytes = hashlib.sha256(key.encode("utf-8")).digest()
        hue_int = int.from_bytes(seed_bytes[:2], "big")  # 0–65535
        hue = hue_int / 65536.0  # 0.0–1.0, maps uniformly over the colour wheel
        r, g, b = colorsys.hls_to_rgb(hue, l=0.72, s=0.50)
        return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"

    def _node_id_to_orig_ids(node_id: str) -> tuple[list[str], str]:
        """Transforms a node_id into a list of original IDs by
        first splitting the node_id at every forward slash and then extracting the original ID
        from the label of each node in the path.
        """
        path_ids = node_id.split("/")
        orig_ids = []
        label: str = path_ids[-1]  # The label is the last part of the node_id path
        for pid in path_ids:
            orig_id = pid.split(" ")[
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
            # Program labels are plain names without an orig_id prefix (unlike CHAPTER/MINISTRY).
            # Use the full PROGRAM_0 path segment to look up the language-agnostic orig_id so
            # that the color stays identical when the UI language changes.
            path_parts = node_id.split("/")
            program_label = path_parts[1] if len(path_parts) > 1 else node_id
            main_program_key = (
                program_label_to_orig_id.get(program_label, program_label)
                if program_label_to_orig_id
                else program_label
            )
            color = _stable_deterministic_color(main_program_key)

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
    if spending_type == "MILITARY":
        # Single-dimension patterns — vectorized str.match instead of row-by-row apply()
        single_mask = pd.Series(False, index=df.index)
        for dim, pattern in MilitarySpending.simple_patterns.items():
            if dim.endswith(("CHAPTER", "PROGRAM", "MINISTRY")):
                col = f"{dim}_ORIG_ID"
                if col in df.columns:
                    single_mask |= df[col].astype(str).str.match(pattern.pattern, na=False)

        # Combination patterns — each combination must match all dims simultaneously
        combo_mask = pd.Series(False, index=df.index)
        for combination in MilitarySpending.combination_patterns:
            sub_mask = pd.Series(True, index=df.index)
            valid = True
            for dim, pattern in combination.items():
                col = f"{dim}_ORIG_ID"
                if col not in df.columns:
                    valid = False
                    break
                sub_mask &= df[col].astype(str).str.match(pattern.pattern, na=False)
            if valid:
                combo_mask |= sub_mask

        # Custom classified patterns — must also have BUDGET_TYPE == "CLASSIFIED"
        classified_mask = pd.Series(False, index=df.index)
        for dim, pattern in MilitarySpending.custom_patterns.items():
            if dim.endswith(("CHAPTER", "PROGRAM", "MINISTRY")):
                col = f"{dim}_ORIG_ID"
                if col in df.columns:
                    classified_mask |= df[col].astype(str).str.match(pattern.pattern, na=False)
        classified_mask &= df["BUDGET_TYPE"] == "CLASSIFIED"

        # Synthetic REPORT classified tile: CHAPTER_ORIG_ID is "CLASSIFIED_CHAPTER"
        # (a placeholder that doesn't match any real pattern). Include it explicitly
        # so the aggregated military classified estimate appears in military mode.
        synthetic_report_classified_mask = (df["BUDGET_TYPE"] == "CLASSIFIED") & (
            df["CHAPTER_ORIG_ID"].astype(str).str.startswith("CLASSIFIED_")
        )

        df_military = (
            df[single_mask | combo_mask | classified_mask | synthetic_report_classified_mask]
            .drop_duplicates()
            .reset_index(drop=True)
            .copy()
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
