"""Regression tests for cumulative year-to-date values in the treemap."""

from datetime import date

import pandas as pd
import pytest

from callbacks import callback_treemap


@pytest.mark.parametrize(
    "unit",
    ["PERCENT_YEAR_TO_DATE_SPENDING", "PERCENT_YEAR_TO_DATE_REVENUE"],
)
def test_report_ytd_treemap_keeps_cumulative_values(monkeypatch, unit: str) -> None:
    """YTD treemaps must use the same cumulative numerator as their denominator."""

    class FakeTransformer:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def transform_from_flat(self, _rows) -> pd.DataFrame:
            return pd.DataFrame({"VALUE": [150.0]})

        def subtract_prev_quarter(
            self, _current: pd.DataFrame, _previous: pd.DataFrame
        ) -> pd.DataFrame:
            return pd.DataFrame({"VALUE": [50.0]})

    class IdentityCalculator:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def calculate_series(self, series: pd.Series) -> pd.Series:
            return series

    monkeypatch.setattr(
        callback_treemap,
        "fetch_treemap_data",
        lambda _budget_id: ([{"budget_type": "REPORT"}], [], None, date(2024, 6, 30)),
    )
    monkeypatch.setattr(
        callback_treemap,
        "fetch_treemap_hierarchy",
        lambda _budget_id: [{"value": 150.0}],
    )
    monkeypatch.setattr(
        callback_treemap, "find_prev_report_budget_id", lambda **_kwargs: 1, raising=False
    )
    monkeypatch.setattr(callback_treemap, "TreemapTransformer", FakeTransformer)
    monkeypatch.setattr(callback_treemap, "Calculator", IdentityCalculator)

    callback_treemap.transform_treemap_data.cache_clear()
    try:
        result = callback_treemap.transform_treemap_data(2, "ALL", unit)
    finally:
        callback_treemap.transform_treemap_data.cache_clear()

    assert result["VALUE"].tolist() == [150.0]
