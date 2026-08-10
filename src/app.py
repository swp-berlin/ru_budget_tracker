"""Dash Plotly App."""

import logging
import threading

import dash_bootstrap_components as dbc
from dash import Dash

from settings import settings

logger = logging.getLogger(__name__)

# The app must be created before importing layout or callbacks, because
# get_asset_url (used in layout.py) requires the Dash instance to exist.
app = Dash(
    __name__,
    use_pages=True,
    external_stylesheets=[dbc.themes.BOOTSTRAP],
    suppress_callback_exceptions=True,  # Required for pages with callbacks referencing shared stores
    update_title=None,  # type: ignore
    url_base_pathname=settings.app.url_base_pathname,
)

server = app.server


@app.server.route("/healthz")
def healthz():
    return {"status": "ok"}


from layout import serve_layout, validation_layout  # noqa: E402
import callbacks  # noqa: E402, F401 — registers all @callback and clientside_callback decorators

app.layout = serve_layout

# Validation layout includes all components that callbacks might reference.
# This prevents "component not found" warnings during callback validation.
app.validation_layout = validation_layout


def _prewarm_treemap_cache() -> None:
    try:
        from utils.fetch_treemap import (
            fetch_budgets_for_dropdown,
        )
        from callbacks.callback_treemap import fetch_treemap_data, transform_treemap_data

        budgets = fetch_budgets_for_dropdown()
        if not budgets:
            return

        # Warm the in-memory lru_cache for the most recent budget only.
        budget_id = budgets[0]["id"]
        fetch_treemap_data(budget_id)
        transform_treemap_data(budget_id, "ALL", "ABSOLUTE")
        logger.info("Treemap cache pre-warmed for all %s budgets", len(budgets))
    except Exception:
        logger.warning("Treemap cache pre-warm failed", exc_info=True)


# def _prewarm_treemap_cache_old() -> None:
#     try:
#         from utils.fetch_treemap import (
#             fetch_budgets_for_dropdown,
#             fetch_treemap_hierarchy,
#             populate_treemap_hierarchy,
#         )
#         from callbacks.callback_treemap import fetch_treemap_data, transform_treemap_data

#         budgets = fetch_budgets_for_dropdown()
#         if not budgets:
#             return

#         for budget in budgets:
#             budget_id = budget["id"]
#             if not fetch_treemap_hierarchy(budget_id):
#                 logger.info("Treemap hierarchy: populating budget_id=%s", budget_id)
#                 populate_treemap_hierarchy(budget_id)

#         # Warm the in-memory lru_cache for the most recent budget only.
#         budget_id = budgets[0]["id"]
#         fetch_treemap_data(budget_id)
#         transform_treemap_data(budget_id, "ALL", "ABSOLUTE")
#         logger.info("Treemap cache pre-warmed for all %s budgets", len(budgets))
#     except Exception:
#         logger.warning("Treemap cache pre-warm failed", exc_info=True)


def _prewarm_timeseries_cache() -> None:
    try:
        from utils.fetch_treemap import fetch_budgets_for_dropdown
        from utils.definitions import unit_config, UnitTypeLiteral
        from callbacks.callback_timeseries import fetch_timeseries_data

        logger.info("Timeseries prewarm: raw SQL caches filled, starting full pipeline warmup")
        budgets = fetch_budgets_for_dropdown()
        seed_ids: dict[str, int | None] = {"LAW": None, "REPORT": None}
        for b in budgets:
            if b["type"] in seed_ids and seed_ids[b["type"]] is None:
                seed_ids[b["type"]] = b["id"]
            if all(v is not None for v in seed_ids.values()):
                break

        units: list[UnitTypeLiteral] = [u for _, u in unit_config.options]
        for budget_type, budget_id in seed_ids.items():
            if budget_id is None:
                continue
            for spending_type in ["ALL", "MILITARY"]:
                for unit in units:
                    logger.info(
                        "Timeseries prewarm: budget_type=%s budget_id=%s spending_type=%s unit=%s",
                        budget_type,
                        budget_id,
                        spending_type,
                        unit,
                    )
                    try:
                        fetch_timeseries_data(
                            budget_id=budget_id,
                            spending_type=spending_type,
                            unit=unit,
                        )
                    except Exception:
                        logger.warning(
                            "Timeseries prewarm: skipped budget_type=%s spending_type=%s unit=%s",
                            budget_type,
                            spending_type,
                            unit,
                            exc_info=True,
                        )

        logger.info("Timeseries cache pre-warmed for all spending types, units, and budget types")
    except Exception:
        logger.warning("Timeseries cache pre-warm failed", exc_info=True)


# def _prewarm_timeseries_cache_old() -> None:
#     try:
#         from utils.fetch_treemap import fetch_budgets_for_dropdown
#         from utils.fetch_timeseries import TimeseriesDataFetcher
#         from utils.definitions import unit_config, UnitTypeLiteral
#         from callbacks.callback_timeseries import fetch_timeseries_data

#         logger.info("Timeseries prewarm: filling raw SQL caches")
#         # See also utils/definitions.SpendingTypeLiteral
#         for spending_type in ["ALL", "MILITARY"]:
#             logger.info(
#                 "Timeseries prewarm: fetching execution budgets for spending_type=%s", spending_type
#             )
#             fetcher = TimeseriesDataFetcher(spending_type)
#             fetcher._fetch_execution_budget_expenses()
#             logger.info(
#                 "Timeseries prewarm: fetching law budgets for spending_type=%s", spending_type
#             )
#             fetcher._fetch_law_budget_expenses()

#         logger.info("Timeseries prewarm: raw SQL caches filled, starting full pipeline warmup")
#         budgets = fetch_budgets_for_dropdown()
#         seed_ids: dict[str, int | None] = {"LAW": None, "REPORT": None}
#         for b in budgets:
#             if b["type"] in seed_ids and seed_ids[b["type"]] is None:
#                 seed_ids[b["type"]] = b["id"]
#             if all(v is not None for v in seed_ids.values()):
#                 break

#         units: list[UnitTypeLiteral] = [u for _, u in unit_config.options]
#         for budget_type, budget_id in seed_ids.items():
#             if budget_id is None:
#                 continue
#             for spending_type in ["ALL", "MILITARY"]:
#                 for unit in units:
#                     logger.info(
#                         "Timeseries prewarm: budget_type=%s budget_id=%s spending_type=%s unit=%s",
#                         budget_type,
#                         budget_id,
#                         spending_type,
#                         unit,
#                     )
#                     try:
#                         fetch_timeseries_data(
#                             budget_id=budget_id,
#                             spending_type=spending_type,
#                             unit=unit,
#                         )
#                     except Exception:
#                         logger.warning(
#                             "Timeseries prewarm: skipped budget_type=%s spending_type=%s unit=%s",
#                             budget_type,
#                             spending_type,
#                             unit,
#                             exc_info=True,
#                         )

#         logger.info("Timeseries cache pre-warmed for all spending types, units, and budget types")
#     except Exception:
#         logger.warning("Timeseries cache pre-warm failed", exc_info=True)


threading.Thread(target=_prewarm_treemap_cache, daemon=True).start()
threading.Thread(target=_prewarm_timeseries_cache, daemon=True).start()


# Only for Debugging
if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
