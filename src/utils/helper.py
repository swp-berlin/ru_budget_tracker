"""
Miscellaneous utility functions
"""

import zlib
from functools import lru_cache

import pandas as pd

from utils.definitions import (
    Colors,
    MilitarySpending,
    SpendingTypeLiteral,
    UnitTypeLiteral,
    ViewByDimensionTypeLiteral,
    unit_config,
)
from plotly import graph_objects as go


def get_unit_label(unit: UnitTypeLiteral) -> str:
    """Return the human-readable label for a unit (used as CSV column header)."""
    return next(label for label, u in unit_config.options if u == unit)


def create_treemap_colors(
    node_ids: list[str],
    budget_types: list[str],
    spending_type: SpendingTypeLiteral,
    viewby: ViewByDimensionTypeLiteral,
    program_label_to_orig_id: dict[str, str] | None = None,
    seed: str = "abcd",
) -> list[str]:
    """Return a color for each treemap node, in the same order as node_ids.

    Color assignment follows a fixed priority: root nodes are always white (or
    military green in MILITARY mode); classified nodes are always gray. For all
    other nodes, the color depends on viewby — MINISTRY uses a fixed gray for
    ministry-level nodes and chapter colors below; CHAPTER uses chapter colors
    directly; PROGRAM derives a color deterministically from the program's
    language-agnostic orig_id via CRC32, using seed to control the distribution.

    Args:
        node_ids: Slash-separated node paths, e.g. ``"ROOT/02 - Defence/0200 - …"``.
        budget_types: Budget type string for each node (e.g. ``"LAW"``, ``"CLASSIFIED"``).
        spending_type: Whether to render all spending or military only.
        viewby: The active hierarchy dimension driving color logic.
        program_label_to_orig_id: Optional mapping from display label to orig_id,
            used to keep program colors stable across UI language changes.
        seed: Arbitrary string mixed into the PROGRAM hash so the color
            distribution can be adjusted without changing the keys.

    Returns:
        List of hex color strings, one per node, in the same order as node_ids.
    """

    def _stable_deterministic_color(seed: str, key: str) -> str:
        index = zlib.crc32(f"{seed}:{key}".encode()) % len(Colors.filler_colors)
        return Colors.filler_colors[index]

    colors: list[str] = []
    for node_id, budget_type in zip(node_ids, budget_types):
        parts = node_id.split("/")
        depth = len(parts)

        # Root overrides everything else.
        if depth == 1:
            colors.append(
                Colors.MILITARY_GREEN if spending_type == "MILITARY" else Colors.ROOT_WHITE
            )
            continue

        # Classified overrides viewby coloring.
        if "CLASSIFIED" in budget_type.upper():
            colors.append(Colors.CLASSIFIED_GRAY)
            continue

        if viewby == "MINISTRY":
            if depth == 2:
                color = Colors.MINISTRY_GRAY
            else:
                # Path is ROOT/Ministry/Chapter/…; chapter sits at index 2.
                # Labels look like "0100 - General State", so split(" ")[0] gives the orig_id.
                color = Colors.color_mapping_chapters.get(parts[2].split(" ")[0], Colors.ROOT_WHITE)
        elif viewby == "CHAPTER":
            # Path is ROOT/Chapter/…; chapter is at index 1. Same orig_id extraction as above.
            color = Colors.color_mapping_chapters.get(parts[1].split(" ")[0], Colors.ROOT_WHITE)
        elif viewby == "PROGRAM":
            # Program labels are plain names without an orig_id prefix (unlike CHAPTER/MINISTRY).
            # Use the full PROGRAM_0 path segment to look up the language-agnostic orig_id so
            # that the color stays identical when the UI language changes.
            program_label = parts[1]
            main_program_key = (
                program_label_to_orig_id.get(program_label, program_label)
                if program_label_to_orig_id
                else program_label
            )
            color = _stable_deterministic_color(seed, main_program_key)
        else:
            color = Colors.ROOT_WHITE

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
            sub_mask = pd.Series(True, index=df.index)  # True so each dim ANDs down into it
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
        df_military["ROOT"] = "Military spending"
        return df_military
    return df


def shape_for_viewby(
    df: pd.DataFrame,
    viewby: ViewByDimensionTypeLiteral,
) -> pd.DataFrame:
    """Return the shape configuration for the given viewby dimension."""

    df_copy = df.copy()

    if viewby == "MINISTRY":
        relevant_cols = [
            col for col in df_copy.columns if col.startswith(("MINISTRY", "CHAPTER", "PROGRAM_3"))
        ] + ["VALUE", "ROOT", "BUDGET_TYPE"]
    elif viewby == "CHAPTER":
        relevant_cols = [
            col for col in df_copy.columns if col.startswith(("CHAPTER", "SUBCHAPTER", "PROGRAM_3"))
        ] + ["VALUE", "ROOT", "BUDGET_TYPE"]
    elif viewby == "PROGRAM":
        classified_rows = df_copy["BUDGET_TYPE"] == "CLASSIFIED"
        relevant_cols = [
            col
            for col in df_copy.columns
            if col.startswith(("PROGRAM_0", "PROGRAM_1", "PROGRAM_3"))
        ] + ["VALUE", "ROOT", "BUDGET_TYPE"]
        # Classified rows have no program hierarchy, so we bridge them into the PROGRAM view
        # by copying their CHAPTER label into PROGRAM_1 (making them appear at the top level)
        # and clearing PROGRAM_3 so no spurious leaf node is rendered.
        for col in df_copy.columns:
            if col.startswith("CHAPTER") and "NAME" in col:
                df_copy.loc[classified_rows, col.replace("CHAPTER", "PROGRAM_1")] = df_copy.loc[
                    classified_rows, col
                ].values
            elif col.startswith("PROGRAM_3") and "NAME" in col:
                df_copy.loc[classified_rows, col] = None
    else:
        return df_copy

    return df_copy[relevant_cols]


def build_name_cols(df: pd.DataFrame, name_ending: str, include_root: bool = False) -> list[str]:
    cols = [col for col in df.columns if col.endswith(name_ending)]
    return (["ROOT"] + cols) if include_root else cols


def shape_dataframe(
    df: pd.DataFrame,
    spending_type: SpendingTypeLiteral,
    viewby: ViewByDimensionTypeLiteral,
) -> pd.DataFrame:
    """Apply spending-type and viewby shaping in one call."""
    return shape_for_viewby(shape_for_spending_type(df, spending_type), viewby)


def build_compact_node_map(
    df: pd.DataFrame, path_to_short_id: dict[str, str] | None = None
) -> dict[str, dict]:
    """Build a compact {short_id: {leaf: dim_id, ctx: [ancestor_dim_ids]}} map.

    Each short_id is unique (assigned per path), so the same dim_id appearing under
    multiple parents gets a separate entry with distinct ancestor context. This allows
    the timeseries to filter by the same subchapter/chapter context as the clicked node.
    """
    compact: dict[str, dict] = {}
    records = df.to_dict("records")

    next_id = (
        max((int(v) for v in path_to_short_id.values()), default=-1) + 1 if path_to_short_id else 0
    )
    extra_path_to_id: dict[str, str] = {}

    for record in records:
        for name_ending in ("_NAME", "_NAME_TRANSLATED"):
            name_cols = build_name_cols(df, name_ending, include_root=True)
            labels: list[str] = []
            seen_dim_ids: list[int] = []
            for col in name_cols:
                label = record.get(col)
                if not label or pd.isna(label):
                    continue
                labels.append(str(label))
                if col == "ROOT":
                    continue
                dim_id = record.get(f"{col.replace(name_ending, '')}_DIM_ID")
                if pd.isnull(dim_id) or dim_id is None:
                    continue
                path = "/".join(labels)
                if path_to_short_id and path in path_to_short_id:
                    node_ref = path_to_short_id[path]
                elif path in extra_path_to_id:
                    node_ref = extra_path_to_id[path]
                else:
                    node_ref = str(next_id)
                    extra_path_to_id[path] = node_ref
                    next_id += 1
                dim_id_int = int(dim_id)
                compact[node_ref] = {"leaf": str(dim_id_int), "ctx": list(seen_dim_ids)}
                seen_dim_ids.append(dim_id_int)

    return compact


@lru_cache(maxsize=10)
def build_server_node_map(
    budget_id: int, spending_type: SpendingTypeLiteral, unit: UnitTypeLiteral
) -> dict:
    """Server-side cached node map for dimension resolution. Never sent to the browser.

    Uses lazy imports to avoid a circular dependency with pages.treemap.
    """
    from pages.treemap import transform_treemap_data  # noqa: PLC0415

    df = transform_treemap_data(budget_id=budget_id, spending_type=spending_type, unit=unit)

    node_map: dict[str, dict[str, int | str]] = {}
    records = df.to_dict("records")
    # Build entries for both languages so callers can look up paths in either RU or EN.
    for name_ending in ("_NAME", "_NAME_TRANSLATED"):
        name_cols = build_name_cols(df, name_ending, include_root=True)
        language = "EN" if name_ending == "_NAME_TRANSLATED" else "RU"
        for record in records:
            # labels accumulates the path segments as we walk the hierarchy columns left-to-right,
            # so "/".join(labels) always gives the full slash-separated path up to the current node.
            labels: list[str] = []
            for col in name_cols:
                label = record.get(col)
                if not label:
                    continue
                labels.append(str(label))
                if col == "ROOT":
                    continue
                base = col.replace(name_ending, "")
                dim_id = record.get(f"{base}_DIM_ID")
                dim_orig_id = record.get(f"{base}_ORIG_ID")
                if dim_id is not None and pd.notnull(dim_id) and pd.notnull(dim_orig_id):
                    node_map["/".join(labels)] = {
                        "dimension_id": int(dim_id),
                        "dimension_original_identifier": str(dim_orig_id),
                        # Collapse PROGRAM_0/1/3 variants to a single "PROGRAM" type.
                        "dimension_type": "PROGRAM" if base.startswith("PROGRAM_") else base,
                        "language": language,
                    }
    return node_map
