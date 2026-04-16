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
      total_budget_classified    = Σ abs(TOTAL-EXPENSE expenses) − Σ open across all chapters
      estimated_classified       = total_budget_classified × law_classified_share

    TOTAL-EXPENSE budgets carry no per-chapter dimension associations, so only the
    Budget → Expense join is used there (no association_table join).
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
        .group_by(year_expr, month_expr, Dimension.original_identifier, Dimension.name, Dimension.name_translated)
        .cte("open_report")
    )

    # ── CTE 2: TOTAL(EXPENSE) per period — no dimension join (expenses are undimensioned) ─
    total_report_cte = (
        select(
            year_expr.label("year"),
            month_expr.label("month"),
            func.sum(func.abs(Expense.value)).label("total_value"),
        )
        .select_from(Budget)
        .join(Expense, Budget.id == Expense.budget_id)
        .where(Budget.type == "TOTAL")
        .where(Budget.original_identifier.like("%EXPENSE%"))
        .where(month_expr.in_(quarterly_months))
        .group_by(year_expr, month_expr)
        .cte("total_report")
    )

    # ── CTE 3: sum of all open chapter spending per period ───────────────────────
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

    # ── CTE 4: total classified per period = TOTAL(EXPENSE) − all open chapters ──
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

    # ── CTE 5: chapter-level classified shares from the LAW view ─────────────────
    # Used to distribute total_classified across chapters when no per-chapter TOTAL exists.
    law_shares_cte = (
        select(
            LawClassifiedSpendingPerChapter.year,
            LawClassifiedSpendingPerChapter.original_identifier,
            LawClassifiedSpendingPerChapter.chapter_name_translated,
            LawClassifiedSpendingPerChapter.classified_share_of_budget,
        )
        .cte("law_shares")
    )

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
            func.coalesce(open_report_cte.c.open_value, literal(0.0)).label("open_spending"),
            classified_total_cte.c.total_classified.label("total_budget_classified"),
            law_shares_cte.c.classified_share_of_budget.label("law_classified_share"),
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
