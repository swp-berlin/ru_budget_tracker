"""Regression tests for state shared by the Treemap and Time Series pages."""

from urllib.parse import parse_qs

from callbacks.callback import _build_switch_query
from callbacks.callback_timeseries import _resolve_filter_context
from callbacks.callback_treemap import remap_selected_id


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
