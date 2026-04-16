"""add view: report classified spending per chapter

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-16

"""

from alembic import op
from sqlalchemy import and_, case, cast, func, Integer, literal, select
from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect

from models import Budget, Expense, Dimension, assoc_table
from models.classified_spending_views import LawClassifiedSpendingPerChapter
from utils.definitions import budget_config


# revision identifiers, used by Alembic.
revision = "0005"  # pragma: allowlist secret
down_revision = "0004"  # pragma: allowlist secret
branch_labels = None
depends_on = None

VIEW_NAME = "v_report_classified_spending_per_chapter"


def _build_view_select():
    """
    Build the SELECT for the REPORT classified spending view.

    For each quarterly period (months 3/6/9/12) and each chapter present in the LAW view:

      open_spending              = Σ abs(REPORT expenses) for that chapter + period
      total_budget_classified    = Σ abs(TOTAL-EXPENSE expenses, undimensioned) − Σ open
      chapter_total_value        = Σ abs(TOTAL-EXPENSE expenses per chapter), if available
      chapter_classified_share   = (chapter_total − open) / total_classified, if chapter data exists
      estimated_classified       = total_budget_classified × law_classified_share (LAW-share estimate)

    For 2018–2021, TOTAL-EXPENSE budgets carry both an undimensioned sum AND per-chapter
    dimension associations, so chapter_total_value and chapter_classified_share are populated.
    From 2022 onward only the undimensioned sum is available, so those two columns are NULL
    and the LAW-share estimate must be used instead.
    """
    quarterly_months = budget_config.quarterly_months  # [3, 6, 9, 12]

    year_expr = cast(func.strftime("%Y", Budget.published_at), Integer)
    month_expr = cast(func.strftime("%m", Budget.published_at), Integer)

    # ── CTE 1: open REPORT spending per chapter + quarter-end period ─────────────
    open_report_cte = (
        select(
            year_expr.label("year"),
            month_expr.label("month"),
            Dimension.original_identifier.label("original_identifier"),
            Dimension.name.label("chapter_name"),
            Dimension.name_translated.label("chapter_name_translated"),
            func.sum(func.abs(Expense.value)).label("open_value"),
        )
        .select_from(Budget)
        .join(Expense, Budget.id == Expense.budget_id)
        .join(assoc_table, Expense.id == assoc_table.c.expense_id)
        .join(Dimension, assoc_table.c.dimension_id == Dimension.id)
        .where(Budget.type == "REPORT")
        .where(Dimension.type == "CHAPTER")
        .where(month_expr.in_(quarterly_months))
        .group_by(
            year_expr,
            month_expr,
            Dimension.original_identifier,
            Dimension.name,
            Dimension.name_translated,
        )
        .cte("open_report")
    )

    # ── CTE 2: TOTAL(EXPENSE) undimensioned sum per period ───────────────────────
    # Used as the basis for total_budget_classified across all years.
    total_report_cte = (
        select(
            year_expr.label("year"),
            month_expr.label("month"),
            func.sum(func.abs(Expense.value)).label("total_value"),
        )
        .select_from(Budget)
        .join(Expense, Budget.id == Expense.budget_id)
        .join(assoc_table, Expense.id == assoc_table.c.expense_id, isouter=True)
        .join(Dimension, assoc_table.c.dimension_id == Dimension.id, isouter=True)
        .where(Budget.type == "TOTAL")
        .where(Budget.original_identifier.like("%EXPENSE%"))
        .where(Dimension.type.is_(None))
        .where(month_expr.in_(quarterly_months))
        .group_by(year_expr, month_expr)
        .cte("total_report")
    )

    # ── CTE 3: TOTAL(EXPENSE) per chapter per period (2018–2021 only) ────────────
    # Some years have per-chapter breakdowns in the TOTAL-EXPENSE budget; others do not.
    total_chapter_report_cte = (
        select(
            year_expr.label("year"),
            month_expr.label("month"),
            Dimension.original_identifier.label("original_identifier"),
            func.sum(func.abs(Expense.value)).label("chapter_total_value"),
        )
        .select_from(Budget)
        .join(Expense, Budget.id == Expense.budget_id)
        .join(assoc_table, Expense.id == assoc_table.c.expense_id)
        .join(Dimension, assoc_table.c.dimension_id == Dimension.id)
        .where(Budget.type == "TOTAL")
        .where(Budget.original_identifier.like("%EXPENSE%"))
        .where(Dimension.type == "CHAPTER")
        .where(month_expr.in_(quarterly_months))
        .group_by(year_expr, month_expr, Dimension.original_identifier)
        .cte("total_chapter_report")
    )

    # ── CTE 4: sum of all open chapter spending per period ───────────────────────
    open_all_cte = (
        select(
            open_report_cte.c.year,
            open_report_cte.c.month,
            func.sum(open_report_cte.c.open_value).label("total_open"),
        )
        .select_from(open_report_cte)
        .group_by(open_report_cte.c.year, open_report_cte.c.month)
        .cte("open_all_chapters")
    )

    # ── CTE 5: total classified per period = TOTAL(EXPENSE) − all open chapters ──
    classified_total_cte = (
        select(
            total_report_cte.c.year,
            total_report_cte.c.month,
            (
                total_report_cte.c.total_value
                - func.coalesce(open_all_cte.c.total_open, literal(0.0))
            ).label("total_classified"),
        )
        .select_from(total_report_cte)
        .join(
            open_all_cte,
            and_(
                total_report_cte.c.year == open_all_cte.c.year,
                total_report_cte.c.month == open_all_cte.c.month,
            ),
            isouter=True,
        )
        .cte("total_classified_per_period")
    )

    # ── CTE 6: chapter-level classified shares from the LAW view ─────────────────
    # Used to distribute total_classified across chapters for years without chapter breakdowns.
    law_shares_cte = select(
        LawClassifiedSpendingPerChapter.year,
        LawClassifiedSpendingPerChapter.original_identifier,
        LawClassifiedSpendingPerChapter.chapter_name_translated,
        LawClassifiedSpendingPerChapter.classified_share_of_budget,
    ).cte("law_shares")

    open_value_expr = func.coalesce(open_report_cte.c.open_value, literal(0.0))
    chapter_total = total_chapter_report_cte.c.chapter_total_value

    # ── Final SELECT ──────────────────────────────────────────────────────────────
    # Drive from (period × law chapter) so every chapter appears for every period,
    # even if no REPORT expenses were recorded for that chapter in that period.
    return (
        select(
            classified_total_cte.c.year,
            classified_total_cte.c.month,
            # quarter: month / 3  (3→1, 6→2, 9→3, 12→4)
            (classified_total_cte.c.month / 3).label("quarter"),
            law_shares_cte.c.original_identifier,
            # Fall back to the chapter identifier when the name is unavailable.
            func.coalesce(
                open_report_cte.c.chapter_name,
                law_shares_cte.c.original_identifier,
            ).label("chapter_name"),
            func.coalesce(
                open_report_cte.c.chapter_name_translated,
                law_shares_cte.c.chapter_name_translated,
            ).label("chapter_name_translated"),
            open_value_expr.label("open_spending"),
            classified_total_cte.c.total_classified.label("total_budget_classified"),
            law_shares_cte.c.classified_share_of_budget.label("law_classified_share"),
            # Per-chapter TOTAL from the execution budget, NULL when no chapter breakdown exists.
            chapter_total.label("chapter_total_value"),
            # Real classified spending for this chapter: chapter_total − open spending.
            # NULL when chapter_total_value is not available (i.e. from 2022 onward).
            case(
                (
                    chapter_total.isnot(None),
                    chapter_total - open_value_expr,
                ),
                else_=None,
            ).label("chapter_classified_spending"),
            # Share of total classified attributable to this chapter based on the direct TOTAL data.
            # NULL when chapter_total_value is not available.
            case(
                (
                    chapter_total.isnot(None),
                    (chapter_total - open_value_expr) / classified_total_cte.c.total_classified,
                ),
                else_=None,
            ).label("chapter_classified_share"),
            # Fallback estimate: distribute total_classified by LAW budget chapter shares.
            case(
                (
                    law_shares_cte.c.classified_share_of_budget.isnot(None),
                    classified_total_cte.c.total_classified
                    * law_shares_cte.c.classified_share_of_budget,
                ),
                else_=None,
            ).label("estimated_classified_spending"),
        )
        .select_from(classified_total_cte)
        # Every chapter in the LAW view for the same year gets a row.
        .join(law_shares_cte, classified_total_cte.c.year == law_shares_cte.c.year)
        # Open REPORT spending — optional, many chapters may have none in a given period.
        .join(
            open_report_cte,
            and_(
                classified_total_cte.c.year == open_report_cte.c.year,
                classified_total_cte.c.month == open_report_cte.c.month,
                law_shares_cte.c.original_identifier == open_report_cte.c.original_identifier,
            ),
            isouter=True,
        )
        # Per-chapter TOTAL — only available for some years (2018–2021).
        .join(
            total_chapter_report_cte,
            and_(
                classified_total_cte.c.year == total_chapter_report_cte.c.year,
                classified_total_cte.c.month == total_chapter_report_cte.c.month,
                law_shares_cte.c.original_identifier
                == total_chapter_report_cte.c.original_identifier,
            ),
            isouter=True,
        )
        .order_by(
            classified_total_cte.c.year,
            classified_total_cte.c.month,
            law_shares_cte.c.original_identifier,
        )
    )


def upgrade() -> None:
    stmt = _build_view_select()
    compiled_sql = stmt.compile(
        dialect=sqlite_dialect(),
        compile_kwargs={"literal_binds": True},
    )
    op.execute(f"CREATE VIEW IF NOT EXISTS {VIEW_NAME} AS {compiled_sql}")


def downgrade() -> None:
    op.execute(f"DROP VIEW IF EXISTS {VIEW_NAME}")
