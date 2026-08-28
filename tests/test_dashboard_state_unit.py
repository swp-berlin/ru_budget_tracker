"""Regression tests for state shared by the Treemap and Time Series pages."""

from urllib.parse import parse_qs

import pandas as pd

from callbacks.callback import _build_switch_query, hide_timeseries_title
from callbacks.callback_timeseries import _calculate_values, _resolve_filter_context
from callbacks.callback_treemap import remap_selected_id
from callbacks.helper import build_compact_node_map, shape_for_viewby
from utils.transform_treemap import CLASSIFIED_PARENT_ID
from utils.transform_timeseries import TimeseriesTransformer


def test_page_switch_uses_current_shared_stores_instead_of_stale_url() -> None:
    query = _build_switch_query(
        "?budget_id=1&spending_type=MILITARY&unit=PERCENT_GDP_FULL_YEAR"
        "&language=RU&focus=1,2&viewby=MINISTRY&tracking=kept",
        destination="timeseries",
        budget_id=43,
        viewby="CHAPTER",
        period="Q4",
        spending_type="ALL",
        unit="ABSOLUTE",
        language="EN",
        selected_id="7",
        compact_node_map={"7": {"leaf": "20", "ctx": [10]}},
    )

    params = parse_qs(query)
    assert params == {
        "budget_id": ["43"],
        "spending_type": ["ALL"],
        "unit": ["ABSOLUTE"],
        "language": ["EN"],
        "viewby": ["CHAPTER"],
        "focus": ["10,20"],
        "period": ["Q4"],
        "tracking": ["kept"],
    }


def test_page_switch_keeps_direct_link_focus_until_a_selection_is_available() -> None:
    query = _build_switch_query(
        "?focus=10,20&period=Q2",
        destination="treemap",
        budget_id=43,
        viewby="CHAPTER",
        period="Q4",
        spending_type="MILITARY",
        unit="PERCENT_GDP_FULL_YEAR",
        language="RU",
        selected_id=None,
        compact_node_map=None,
    )

    params = parse_qs(query)
    assert params["focus"] == ["10,20"]
    assert params["viewby"] == ["CHAPTER"]
    assert "period" not in params


def test_page_switch_drops_focus_when_selected_id_is_stale() -> None:
    query = _build_switch_query(
        "?focus=10,20",
        destination="timeseries",
        budget_id=43,
        viewby="CHAPTER",
        period="ALL",
        spending_type="MILITARY",
        unit="ABSOLUTE",
        language="EN",
        selected_id="99",
        compact_node_map={"1": {"leaf": "20", "ctx": [10]}},
    )

    assert "focus" not in parse_qs(query)


def test_treemap_selection_is_remapped_by_semantic_identity() -> None:
    previous = {"8": {"leaf": "20", "ctx": [10]}}
    rebuilt = {
        "1": {"leaf": "10", "ctx": []},
        "2": {"leaf": "20", "ctx": [10]},
    }

    assert remap_selected_id("8", previous, rebuilt) == "2"


def test_treemap_selection_uses_a_rendered_duplicate_identity() -> None:
    previous = {"8": {"leaf": "20", "ctx": [10]}}
    rebuilt = {
        "1": {"leaf": "20", "ctx": [10]},
        "2": {"leaf": "20", "ctx": [10]},
    }

    assert remap_selected_id("8", previous, rebuilt, {"2"}) == "2"


def test_treemap_selection_falls_back_to_root_when_node_is_missing() -> None:
    previous = {"8": {"leaf": "20", "ctx": [10]}}
    military_only = {"1": {"leaf": "10", "ctx": []}}

    assert remap_selected_id("8", previous, military_only) is None


def test_timeseries_direct_link_keeps_full_ancestor_context() -> None:
    node = {
        "dimension_id": 20,
        "dimension_original_identifier": "SOCIAL",
        "language": "EN",
    }
    node_map = {"10 - Parent/20 - Social spending": node}

    selected, classified_only, ancestors, path = _resolve_filter_context(
        None,
        None,
        node_map,
        "EN",
        "?focus=10,20",
    )

    assert selected == node
    assert classified_only is False
    assert ancestors == (10,)
    assert path == "10 - Parent/20 - Social spending"


def test_timeseries_direct_link_accepts_classified_parent_id() -> None:
    classified_parent = {
        "dimension_id": CLASSIFIED_PARENT_ID,
        "dimension_original_identifier": "CLASSIFIED_PARENT",
        "dimension_type": "MINISTRY",
        "language": "EN",
    }
    node_map = {"Classified spending": classified_parent}

    selected, classified_only, ancestors, path = _resolve_filter_context(
        None,
        None,
        node_map,
        "EN",
        f"?focus={CLASSIFIED_PARENT_ID}",
    )

    assert selected is None
    assert classified_only is True
    assert ancestors == ()
    assert path == "Classified spending"


def test_program_classified_parent_maps_to_aggregate_id() -> None:
    classified_rows = pd.DataFrame(
        [
            {
                "ROOT": "Federal budget",
                "BUDGET_TYPE": "CLASSIFIED",
                "VALUE": 10.0,
                "CHAPTER_NAME": "02 National Defence",
                "CHAPTER_NAME_TRANSLATED": "02 National Defence",
                "PROGRAM_0_DIM_ID": 1_000_002,
                "PROGRAM_0_ORIG_ID": "CLASSIFIED_02",
                "PROGRAM_0_NAME": "Classified spending",
                "PROGRAM_0_NAME_TRANSLATED": "Classified spending",
                "PROGRAM_1_DIM_ID": 1_000_002,
                "PROGRAM_1_ORIG_ID": "CLASSIFIED_02",
                "PROGRAM_1_NAME": "Classified spending",
                "PROGRAM_1_NAME_TRANSLATED": "Classified spending",
            },
            {
                "ROOT": "Federal budget",
                "BUDGET_TYPE": "CLASSIFIED",
                "VALUE": 20.0,
                "CHAPTER_NAME": "14 Interbudgetary Transfers",
                "CHAPTER_NAME_TRANSLATED": "14 Interbudgetary Transfers",
                "PROGRAM_0_DIM_ID": 1_000_014,
                "PROGRAM_0_ORIG_ID": "CLASSIFIED_14",
                "PROGRAM_0_NAME": "Classified spending",
                "PROGRAM_0_NAME_TRANSLATED": "Classified spending",
                "PROGRAM_1_DIM_ID": 1_000_014,
                "PROGRAM_1_ORIG_ID": "CLASSIFIED_14",
                "PROGRAM_1_NAME": "Classified spending",
                "PROGRAM_1_NAME_TRANSLATED": "Classified spending",
            },
        ]
    )

    shaped = shape_for_viewby(classified_rows, "PROGRAM")
    node_map = build_compact_node_map(shaped)

    assert set(shaped["PROGRAM_0_DIM_ID"]) == {CLASSIFIED_PARENT_ID}
    assert set(shaped["PROGRAM_1_DIM_ID"]) == {1_000_002, 1_000_014}
    assert {entry["leaf"] for entry in node_map.values() if entry["ctx"] == []} == {
        str(CLASSIFIED_PARENT_ID)
    }
    assert {
        (entry["leaf"], tuple(entry["ctx"]))
        for entry in node_map.values()
        if entry["ctx"]
    } == {
        ("1000002", (CLASSIFIED_PARENT_ID,)),
        ("1000014", (CLASSIFIED_PARENT_ID,)),
    }


def test_legacy_program_classified_container_link_resolves_to_aggregate() -> None:
    classified_parent = {
        "dimension_id": CLASSIFIED_PARENT_ID,
        "dimension_original_identifier": "CLASSIFIED_PARENT",
        "dimension_type": "MINISTRY",
        "language": "EN",
    }
    chapter = {
        "dimension_id": 14,
        "dimension_original_identifier": "14",
        "dimension_type": "CHAPTER",
        "language": "EN",
    }
    classified_chapter = {
        "dimension_id": 1_000_014,
        "dimension_original_identifier": "CLASSIFIED_14",
        "dimension_type": "PROGRAM",
        "language": "EN",
    }
    node_map = {
        "Federal budget/Classified spending": classified_parent,
        "Federal budget/Classified spending/14 Transfers": chapter,
        "Federal budget/Classified spending/14 Transfers/Classified spending": (
            classified_chapter
        ),
    }

    selected, classified_only, ancestors, path = _resolve_filter_context(
        None,
        None,
        node_map,
        "EN",
        "?viewby=PROGRAM&focus=1000014",
    )

    assert selected is None
    assert classified_only is True
    assert ancestors == ()
    assert path == "Federal budget/Classified spending"


def test_program_classified_chapter_link_keeps_chapter_filter() -> None:
    classified_parent = {
        "dimension_id": CLASSIFIED_PARENT_ID,
        "dimension_original_identifier": "CLASSIFIED_PARENT",
        "dimension_type": "PROGRAM",
        "language": "EN",
    }
    chapter = {
        "dimension_id": 14,
        "dimension_original_identifier": "14",
        "dimension_type": "CHAPTER",
        "language": "EN",
    }
    classified_chapter = {
        "dimension_id": 1_000_014,
        "dimension_original_identifier": "CLASSIFIED_14",
        "dimension_type": "PROGRAM",
        "language": "EN",
    }
    node_map = {
        "Federal budget/Classified spending": classified_parent,
        "Federal budget/Classified spending/14 Transfers": chapter,
        "Federal budget/Classified spending/14 Transfers/Classified spending": (
            classified_chapter
        ),
    }

    selected, classified_only, ancestors, path = _resolve_filter_context(
        None,
        None,
        node_map,
        "EN",
        "?viewby=PROGRAM&focus=-999999,1000014",
    )

    assert selected == chapter
    assert classified_only is True
    assert ancestors == ()
    assert path == "Federal budget/Classified spending/14 Transfers/Classified spending"


def test_timeseries_program_link_drops_same_type_hierarchy_context() -> None:
    node_map = {
        "Budget/Program": {
            "dimension_id": 2637,
            "dimension_original_identifier": "31",
            "dimension_type": "PROGRAM",
            "language": "EN",
        },
        "Budget/Program/Subprogram": {
            "dimension_id": 10093,
            "dimension_original_identifier": "31401",
            "dimension_type": "PROGRAM",
            "language": "EN",
        },
        "Budget/Program/Subprogram/Measure": {
            "dimension_id": 30815,
            "dimension_original_identifier": "3140190049-131",
            "dimension_type": "PROGRAM",
            "language": "EN",
        },
    }

    selected, classified_only, ancestors, path = _resolve_filter_context(
        None,
        None,
        node_map,
        "EN",
        "?focus=2637,10093,30815",
    )

    assert selected == node_map["Budget/Program/Subprogram/Measure"]
    assert classified_only is False
    assert ancestors == ()
    assert path == "Budget/Program/Subprogram/Measure"


def test_timeseries_classified_program_link_drops_synthetic_context() -> None:
    chapter = {
        "dimension_id": 40,
        "dimension_original_identifier": "10",
        "dimension_type": "CHAPTER",
        "language": "EN",
    }
    classified = {
        "dimension_id": 1000010,
        "dimension_original_identifier": "CLASSIFIED_10",
        "dimension_type": "SUBCHAPTER",
        "language": "EN",
    }
    node_map = {
        "Budget/10 Social Policy": chapter,
        "Budget/10 Social Policy/Classified spending": classified,
    }

    selected, classified_only, ancestors, path = _resolve_filter_context(
        None,
        None,
        node_map,
        "EN",
        "?focus=1000010,1000010",
    )

    assert selected == chapter
    assert classified_only is True
    assert ancestors == ()
    assert path == "Budget/10 Social Policy/Classified spending"


def test_empty_timeseries_transform_has_plot_columns() -> None:
    df = TimeseriesTransformer().transform_data([])

    assert list(df.columns) == ["expenses", "dates", "types", "budget_id"]
    assert _calculate_values(df, 43, "ABSOLUTE", "REPORT").empty


def test_timeseries_title_is_hidden_outside_timeseries_page(monkeypatch) -> None:
    monkeypatch.setattr("callbacks.callback.get_relative_path", lambda path: path)

    assert hide_timeseries_title("/") is True
    assert hide_timeseries_title("/about") is True
    assert hide_timeseries_title("/timeseries") is False
