import logging
from sqlalchemy import delete, insert
from database.sessions import get_sync_session
from models.treemap_cache import MAX_PROGRAM_LEVELS, TreemapExpenseHierarchy
from utils.fetch_treemap import (
    TreemapDataFetcher,
    fetch_budgets_for_dropdown,
    fetch_treemap_hierarchy,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def populate_treemap_hierarchy(budget_id: int) -> None:
    """Compute flat hierarchy for budget_id and persist to treemap_expense_hierarchy."""
    from utils.transform_treemap import TreemapTransformer

    logger.info("Treemap hierarchy: budget_id=%s populating", budget_id)

    fetcher = TreemapDataFetcher()
    budget_type, published_at = fetcher.get_budget_meta(budget_id)
    dimensions, programs, classified = fetcher.fetch_data(
        budget_id=budget_id,
        budget_type=budget_type,
        published_at=published_at,
    )

    transformer = TreemapTransformer(dimensions, programs, classified, spending_type="ALL")
    df = transformer.transform_data()

    # Exclude classified rows — they are dynamic and generated at render time.
    df = df[df["BUDGET_TYPE"] != "CLASSIFIED"].copy()

    df["expense_id"] = df.index
    df["budget_id"] = budget_id
    df = df.drop(columns=["ROOT"], errors="ignore")

    # Ensure all PROGRAM_* columns exist even if this budget has fewer program levels.
    for i in range(MAX_PROGRAM_LEVELS):
        for suffix in ("DIM_ID", "ORIG_ID", "NAME", "NAME_TRANSLATED"):
            col = f"PROGRAM_{i}_{suffix}"
            if col not in df.columns:
                df[col] = None

    rows = df.where(df.notna(), other=None).to_dict("records")

    from sqlalchemy.exc import OperationalError

    # try:
    with get_sync_session() as session:
        session.execute(
            delete(TreemapExpenseHierarchy).where(TreemapExpenseHierarchy.budget_id == budget_id)
        )
        if rows:
            session.execute(insert(TreemapExpenseHierarchy), rows)
    # except OperationalError:
    #     pass


def pre_calc_budgets() -> None:
    try:
        budgets = fetch_budgets_for_dropdown()
        budgets = sorted(budgets, key=lambda b: b["id"])

        if not budgets:
            return

        for budget in budgets:
            budget_id = budget["id"]

            if fetch_treemap_hierarchy(budget_id):
                logger.info("Treemap hierarchy: budget_id=%s already cached", budget_id)
            else:
                populate_treemap_hierarchy(budget_id)

    except Exception:
        logger.warning("Pre-calculation of budgets failed", exc_info=True)


# def pre_calc_timeseries() -> None:

if __name__ == "__main__":
    logger.info("Pre-calculating budgets caches")
    pre_calc_budgets()
