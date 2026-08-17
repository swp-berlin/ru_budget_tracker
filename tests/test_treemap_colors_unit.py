"""Unit tests for the treemap color assignment in callbacks.helper.

Pure functions, synthetic node lists, no data files or DB. These pin the two
invariants the palette design rests on — the program-view separation guarantee and
the label-contrast rule — because both are stated as promises in
docs/customization.md and neither is otherwise enforced.
"""

import pytest

from callbacks.helper import create_treemap_colors, create_treemap_text_colors
from utils.definitions import Colors

PROGRAM_COLORS = [color for color in Colors.filler_colors if color != Colors.BRAND_GREEN_DARK]


def _contrast(a: str, b: str) -> float:
    """WCAG relative-luminance contrast ratio between two hex colors."""

    def lum(h: str) -> float:
        def channel(c: float) -> float:
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

        r, g, b_ = (int(h[i : i + 2], 16) / 255 for i in (1, 3, 5))
        return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b_)

    hi, lo = max(lum(a), lum(b)), min(lum(a), lum(b))
    return (hi + 0.05) / (lo + 0.05)


def _program_nodes(tiles: list[tuple[str, float]]):
    """Build (node_ids, budget_types, values) for a ROOT + top-level-program figure."""
    node_ids = ["ROOT"] + [f"ROOT/{label}" for label, _ in tiles]
    budget_types = ["LAW"] * len(node_ids)
    values = [sum(v for _, v in tiles)] + [v for _, v in tiles]
    return node_ids, budget_types, values


class TestProgramSeparation:
    def test_top_slots_are_all_distinct(self):
        """The n largest programs must not repeat a color within one palette cycle."""
        n = len(PROGRAM_COLORS)
        tiles = [(f"P{i}", float(100 - i)) for i in range(n)]
        colors = create_treemap_colors(*_program_nodes(tiles), "ALL", "PROGRAM")
        assert len(set(colors[1:])) == n

    def test_repeats_are_a_full_cycle_apart(self):
        """Programs sharing a slot sit at least one program-palette cycle apart."""
        n = len(PROGRAM_COLORS)
        tiles = [(f"P{i}", float(1000 - i)) for i in range(n * 3)]
        colors = create_treemap_colors(*_program_nodes(tiles), "ALL", "PROGRAM")[1:]
        seen: dict[str, int] = {}
        for rank, color in enumerate(colors):
            if color in seen:
                assert rank - seen[color] >= n, f"{color} repeated after {rank - seen[color]} ranks"
            seen[color] = rank

    def test_duplicate_orig_id_does_not_collapse_ranks(self):
        """Regression: two tiles of one program are two ranks, not one.

        A program can render as two top-level tiles under different name variants
        that share a PROGRAM_0_ORIG_ID. Keying the rank map on orig_id collapsed them,
        dropped every value but the last, and corrupted all ranks below — which put
        two large same-colored tiles side by side, the exact artifact the ranking
        exists to prevent.
        """
        tiles = [("Space", 174.4), ("Space 2013-2020", 23.8), ("Economy", 180.1)]
        label_to_orig = {"Space": "21", "Space 2013-2020": "21", "Economy": "15"}
        colors = create_treemap_colors(*_program_nodes(tiles), "ALL", "PROGRAM", label_to_orig)[1:]
        assert len(set(colors)) == 3, "each rendered tile needs its own slot"
        # Economy (180.1) and Space (174.4) are adjacent in size — must not match.
        assert colors[2] != colors[0]

    def test_ranking_is_language_agnostic(self):
        """Renaming every label leaves each tile's color unchanged."""
        ru = [("Космос", 174.4), ("Экономика", 180.1), ("Оборона", 90.0)]
        en = [("Space", 174.4), ("Economy", 180.1), ("Defence", 90.0)]
        mapping = {
            "Космос": "21",
            "Space": "21",
            "Экономика": "15",
            "Economy": "15",
            "Оборона": "02",
            "Defence": "02",
        }
        ru_colors = create_treemap_colors(*_program_nodes(ru), "ALL", "PROGRAM", mapping)
        en_colors = create_treemap_colors(*_program_nodes(en), "ALL", "PROGRAM", mapping)
        assert ru_colors == en_colors

    def test_descendants_inherit_the_top_level_color(self):
        node_ids = ["ROOT", "ROOT/Big", "ROOT/Big/Sub", "ROOT/Big/Sub/Leaf", "ROOT/Small"]
        colors = create_treemap_colors(
            node_ids, ["LAW"] * 5, [30.0, 20.0, 10.0, 5.0, 10.0], "ALL", "PROGRAM"
        )
        assert colors[1] == colors[2] == colors[3]
        assert colors[4] != colors[1]

    def test_program_31_and_its_descendants_use_dark_green(self):
        node_ids = ["ROOT", "ROOT/Defence", "ROOT/Defence/Sub", "ROOT/Other"]
        mapping = {"Defence": "31", "Other": "99"}
        colors = create_treemap_colors(
            node_ids, ["LAW"] * 4, [30.0, 20.0, 10.0, 10.0], "ALL", "PROGRAM", mapping
        )
        assert colors[1] == colors[2] == Colors.BRAND_GREEN_DARK
        assert colors[3] == Colors.filler_colors[1]

    def test_only_exact_program_31_is_overridden(self):
        tiles = [("Program 310", 20.0), ("Program 31", 10.0)]
        mapping = {"Program 310": "310", "Program 31": "31"}
        colors = create_treemap_colors(*_program_nodes(tiles), "ALL", "PROGRAM", mapping)
        assert colors[1] == Colors.filler_colors[0]
        assert colors[2] == Colors.BRAND_GREEN_DARK

    def test_program_31_override_is_language_agnostic(self):
        ru = _program_nodes([("Оборона", 10.0)])
        en = _program_nodes([("Defence", 10.0)])
        mapping = {"Оборона": "31", "Defence": "31"}
        assert create_treemap_colors(*ru, "ALL", "PROGRAM", mapping) == create_treemap_colors(
            *en, "ALL", "PROGRAM", mapping
        )

    def test_dark_green_is_reserved_from_other_programs(self):
        tiles = [(f"P{i}", float(100 - i)) for i in range(len(PROGRAM_COLORS) * 2)]
        colors = create_treemap_colors(*_program_nodes(tiles), "ALL", "PROGRAM")[1:]
        assert Colors.BRAND_GREEN_DARK not in colors

    def test_rank_zero_is_not_treated_as_missing(self):
        """A single program must get slot 0, not the ROOT_WHITE fallback."""
        colors = create_treemap_colors(*_program_nodes([("Only", 5.0)]), "ALL", "PROGRAM")
        assert colors[1] == Colors.filler_colors[0]

    def test_classified_wins_over_rank(self):
        node_ids = ["ROOT", "ROOT/Open", "ROOT/Secret"]
        colors = create_treemap_colors(
            node_ids, ["LAW", "LAW", "CLASSIFIED"], [30.0, 20.0, 10.0], "ALL", "PROGRAM"
        )
        assert colors[2] == Colors.CLASSIFIED_GRAY

    def test_empty_input(self):
        assert create_treemap_colors([], [], [], "ALL", "PROGRAM") == []


class TestChapterMapping:
    def test_no_two_chapters_share_a_slot(self):
        """docs/customization.md states this as a rule; nothing else enforces it."""
        mapping = Colors.color_mapping_chapters
        assert len(set(mapping.values())) == len(mapping)

    def test_chapter_colors_come_from_the_brand_palette(self):
        assert set(Colors.color_mapping_chapters.values()) <= set(Colors.filler_colors)


class TestLabelContrast:
    ALL_FILLS = [
        *Colors.filler_colors,
        *Colors.color_mapping_chapters.values(),
        Colors.CLASSIFIED_GRAY,
        Colors.ROOT_WHITE,
        Colors.MILITARY_GREEN,
    ]

    @pytest.mark.parametrize("fill", sorted(set(ALL_FILLS)))
    def test_picks_the_higher_contrast_label_color(self, fill: str):
        """Whatever the palette becomes, the label color must be the better of the two."""
        chosen = create_treemap_text_colors([fill])[0]
        other = Colors.TEXT_ON_LIGHT if chosen == Colors.TEXT_ON_DARK else Colors.TEXT_ON_DARK
        assert _contrast(fill, chosen) >= _contrast(fill, other)

    @pytest.mark.parametrize("fill", sorted(set(ALL_FILLS)))
    def test_clears_the_large_text_threshold(self, fill: str):
        """>= 3:1 on every fill the app can produce.

        This is the WCAG large-text bar, not the 4.5:1 normal-text bar; small tiles
        render small labels, so the palette does not fully clear normal text. Raising
        this to 4.5 is the goal if the tints are ever darkened.
        """
        chosen = create_treemap_text_colors([fill])[0]
        assert _contrast(fill, chosen) >= 3.0

    def test_dark_fills_tracks_the_dark_tints(self):
        """dark_fills is hand-maintained; pin it to the leading tint band."""
        assert Colors.dark_fills == frozenset(Colors.filler_colors[:6])

    def test_one_label_color_per_node(self):
        fills = [Colors.BRAND_GOLD_DARK, Colors.ROOT_WHITE, Colors.BRAND_GOLD_LIGHT]
        assert create_treemap_text_colors(fills) == [
            Colors.TEXT_ON_DARK,
            Colors.TEXT_ON_LIGHT,
            Colors.TEXT_ON_LIGHT,
        ]
