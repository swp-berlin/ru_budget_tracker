import logging
from utils.fetch_timeseries import TimeseriesDataFetcher, _store_timeseries_summary

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def pre_calc_timeseries() -> None:

    logger.info("Timeseries prewarm: filling raw SQL caches")
    for spending_type in ["ALL", "MILITARY"]:
        fetcher = TimeseriesDataFetcher(spending_type)

        logger.info(
            "Timeseries pre-calc cache: calculating execution budgets for spending_type=%s",
            spending_type,
        )
        result = fetcher._aggregate_execution_budget_expenses()
        # populate SQL cache
        _store_timeseries_summary(result, spending_type, "REPORT")
        TimeseriesDataFetcher._execution_budget_cache[spending_type] = result

        fetcher._fetch_execution_budget_expenses()
        logger.info(
            "Timeseries prewarm: calculating law budgets for spending_type=%s",
            spending_type,
        )

        result = fetcher._aggregate_law_budget_expenses()
        # populate SQL cache
        _store_timeseries_summary(result, spending_type, "LAW")
        TimeseriesDataFetcher._law_budget_cache[spending_type] = result


if __name__ == "__main__":
    pre_calc_timeseries()


"""

_fetch_execution_budget_expenses
   _store_timeseries_summary(result, self.spending_type, "REPORT")

    union_stmt = report_stmt.union(total_stmt)
    with get_sync_session() as session:
        result = session.execute(union_stmt).mappings().all()
    _store_timeseries_summary(result, self.spending_type, "REPORT")
    TimeseriesDataFetcher._execution_budget_cache[self.spending_type] = result
    return result

    with get_sync_session() as session:
        raw = session.execute(stmt).mappings().all()
    result = cast(Sequence[RowMapping], self._precompute_classified_in_total_rows(raw))
    _store_timeseries_summary(result, self.spending_type, "REPORT")
    TimeseriesDataFetcher._execution_budget_cache[self.spending_type] = result
    return result

_fetch_law_budget_expenses
    _store_timeseries_summary(result, self.spending_type, "LAW")

    union_stmt = law_stmt.union(total_stmt)
    with get_sync_session() as session:
        result = session.execute(union_stmt).mappings().all()
    _store_timeseries_summary(result, self.spending_type, "LAW")
    TimeseriesDataFetcher._law_budget_cache[self.spending_type] = result
    return result

    union_stmt = law_ministry_stmt.union(total_chapter_stmt)
    with get_sync_session() as session:
        raw = session.execute(union_stmt).mappings().all()
    result = cast(Sequence[RowMapping], self._precompute_classified_in_total_rows(raw))
    _store_timeseries_summary(result, self.spending_type, "LAW")
    TimeseriesDataFetcher._law_budget_cache[self.spending_type] = result
    return result
"""
