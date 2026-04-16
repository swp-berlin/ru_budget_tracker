"""add view: report military open spending per chapter

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-16

"""

from alembic import op
from sqlalchemy import and_, case, cast, func, Integer, select, union
from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect

from models import Budget, Expense, Dimension, assoc_table
from models.classified_spending_views import ReportClassifiedSpendingPerChapter


# revision identifiers, used by Alembic.
revision = "0007"  # pragma: allowlist secret
down_revision = "0006"  # pragma: allowlist secret
branch_labels = None
depends_on = None

VIEW_NAME = "v_report_military_open_spending_per_chapter"


def _build_view_select():
    """
    Build the SELECT for the REPORT military open spending view.

    Mirrors the logic of transform_treemap._check_if_military() for open spending.
    An expense is military if ANY of its dimensions matches one of the patterns below.
    All matching expenses are then grouped by their CHAPTER dimension.

    Simple patterns:
        CHAPTER  = '02'           National Defense
        PROGRAMM LIKE '31%'       Federal programs starting with 31  (DB type is 'PROGRAMM')
        MINISTRY = '187'          Rosgvardia / National Guard

    Combination pattern:
        CHAPTER = '03'  AND  MINISTRY = '180'   FSB within Law Enforcement

    classified_spending for chapters 02 and 10 is sourced from
    ReportClassifiedSpendingPerChapter: chapter_classified_spending (direct, 2018–2021)
    with a fallback to estimated_classified_spending (LAW-share estimate, 2022+).
    """
    year_expr = cast(func.strftime("%Y", Budget.published_at), Integer)
    month_expr = cast(func.strftime("%m", Budget.published_at), Integer)

    # ── Helper: expense IDs that carry a specific dimension ──────────────────────
    def _expense_ids_for_dim(dim_type: str, orig_id_condition):
        return (
            select(assoc_table.c.expense_id)
            .join(Dimension, assoc_table.c.dimension_id == Dimension.id)
            .where(Dimension.type == dim_type)
            .where(orig_id_condition)
        )

    # Simple patterns
    chapter_02_sq = _expense_ids_for_dim("CHAPTER", Dimension.original_identifier == "02")
    programm_31_sq = _expense_ids_for_dim("PROGRAMM", Dimension.original_identifier.like("31%"))
    ministry_187_sq = _expense_ids_for_dim("MINISTRY", Dimension.original_identifier == "187")

    # Combination: Chapter-03 expenses that also have Ministry-180.
    # Written as IN subquery to avoid a parenthesised INTERSECT inside UNION
    # (not supported by SQLite).
    ministry_180_sq = _expense_ids_for_dim("MINISTRY", Dimension.original_identifier == "180")
    combo_sq = (
        select(assoc_table.c.expense_id)
        .join(Dimension, assoc_table.c.dimension_id == Dimension.id)
        .where(Dimension.type == "CHAPTER")
        .where(Dimension.original_identifier == "03")
        .where(assoc_table.c.expense_id.in_(ministry_180_sq))
    )

    military_ids_cte = union(
        chapter_02_sq,
        programm_31_sq,
        ministry_187_sq,
        combo_sq,
    ).cte("military_expense_ids")

    # Chapters with meaningful classified data (entire chapter is military).
    classified_chapters = ["02", "10"]

    # ── Aggregate matching expenses by (budget_id, chapter) ─────────────────────
    # Outer-join the report classified spending view to attach classified_spending and
    # classified_share_of_budget for chapters 02 (National Defense) and 10 (Social
    # Policy), where the entire chapter is military.  For other chapters (e.g.
    # Chapter 03 via the Ministry-180 combination) both values are NULL because only
    # a subset of that chapter is military.
    #
    # classified_spending = estimated_classified_spending = total_budget_classified ×
    # law_classified_share.  This LAW-share allocation is used consistently for all
    # years so that the share is always derived from the annual LAW budget structure.
    # classified_share_of_budget = law_classified_share (constant per chapter per year).
    return (
        select(
            Budget.id.label("budget_id"),
            Dimension.original_identifier.label("original_identifier"),
            Dimension.name.label("chapter_name"),
            Dimension.name_translated.label("chapter_name_translated"),
            func.sum(func.abs(Expense.value)).label("open_spending"),
            func.max(
                case(
                    (
                        Dimension.original_identifier.in_(classified_chapters),
                        ReportClassifiedSpendingPerChapter.estimated_classified_spending,
                    ),
                    else_=None,
                )
            ).label("classified_spending"),
            func.max(
                case(
                    (
                        Dimension.original_identifier.in_(classified_chapters),
                        ReportClassifiedSpendingPerChapter.law_classified_share,
                    ),
                    else_=None,
                )
            ).label("classified_share_of_budget"),
        )
        .select_from(Budget)
        .join(Expense, Budget.id == Expense.budget_id)
        .join(assoc_table, Expense.id == assoc_table.c.expense_id)
        .join(Dimension, assoc_table.c.dimension_id == Dimension.id)
        .join(
            ReportClassifiedSpendingPerChapter,
            and_(
                year_expr == ReportClassifiedSpendingPerChapter.year,
                month_expr == ReportClassifiedSpendingPerChapter.month,
                Dimension.original_identifier
                == ReportClassifiedSpendingPerChapter.original_identifier,
            ),
            isouter=True,
        )
        .where(Budget.type == "REPORT")
        .where(Dimension.type == "CHAPTER")
        .where(Expense.id.in_(select(military_ids_cte.c.expense_id)))
        .group_by(
            Budget.id,
            Dimension.original_identifier,
            Dimension.name,
            Dimension.name_translated,
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
