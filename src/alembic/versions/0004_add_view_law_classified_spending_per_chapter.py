"""add view: law classified spending per chapter

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-16

"""

from alembic import op
from sqlalchemy import and_, case, cast, func, Integer, literal, select
from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect

from models import Budget, Expense, Dimension, assoc_table
from utils.definitions import budget_config


# revision identifiers, used by Alembic.
revision = "0004"  # pragma: allowlist secret
down_revision = "0003"  # pragma: allowlist secret
branch_labels = None
depends_on = None

VIEW_NAME = "v_law_classified_spending_per_chapter"


def _build_view_select():
    """
    Build the SELECT statement for the classified spending view using SQLAlchemy Core.

    Classified spending per chapter = TOTAL(LAW) × 1000 − open LAW spending per chapter.
    LAW values for 2018–2019 are halved because the source data doubles them.
    """
    # ── CTE 1: open (published) LAW spending per chapter ──────────────────────────
    open_year = cast(func.strftime("%Y", Budget.published_at), Integer).label("year")
    open_cte = (
        select(
            open_year,
            Dimension.original_identifier.label("original_identifier"),
            Dimension.name.label("chapter_name"),
            Dimension.name_translated.label("chapter_name_translated"),
            func.sum(func.abs(Expense.value)).label("open_value"),
        )
        .select_from(Budget)
        .join(Expense, Budget.id == Expense.budget_id)
        .join(assoc_table, Expense.id == assoc_table.c.expense_id)
        .join(Dimension, assoc_table.c.dimension_id == Dimension.id)
        .where(Budget.type == "LAW")
        .where(Dimension.type == "CHAPTER")
        .group_by(
            open_year, Dimension.original_identifier, Dimension.name, Dimension.name_translated
        )
        .cte("open_spending")
    )

    # ── CTE 2: aggregate totals from TOTAL(LAW) budgets per chapter × 1000 ───────
    total_year = cast(func.strftime("%Y", Budget.published_at), Integer).label("year")
    total_cte = (
        select(
            total_year,
            Dimension.original_identifier.label("original_identifier"),
            Dimension.name.label("chapter_name"),
            Dimension.name_translated.label("chapter_name_translated"),
            (func.sum(func.abs(Expense.value)) * budget_config.law_total_value_multiplier).label(
                "total_value"
            ),
        )
        .select_from(Budget)
        .join(Expense, Budget.id == Expense.budget_id)
        .join(assoc_table, Expense.id == assoc_table.c.expense_id)
        .join(Dimension, assoc_table.c.dimension_id == Dimension.id)
        .where(Budget.type == "TOTAL")
        .where(Budget.original_identifier.like("%LAW%"))
        .where(Dimension.type == "CHAPTER")
        .group_by(
            total_year, Dimension.original_identifier, Dimension.name, Dimension.name_translated
        )
        .cte("total_spending")
    )

    # ── CTE 3: classified = total − open per chapter ───────────────────────────
    open_value = func.coalesce(open_cte.c.open_value, literal(0.0))
    classified_cte = (
        select(
            total_cte.c.year,
            total_cte.c.original_identifier,
            total_cte.c.chapter_name,
            total_cte.c.chapter_name_translated,
            open_value.label("open_spending"),
            total_cte.c.total_value.label("total_spending"),
            (total_cte.c.total_value - open_value).label("classified_spending"),
        )
        .select_from(total_cte)
        .join(
            open_cte,
            and_(
                total_cte.c.year == open_cte.c.year,
                total_cte.c.original_identifier == open_cte.c.original_identifier,
            ),
            isouter=True,
        )
        .cte("classified")
    )

    # ── CTE 4: total classified across all chapters per year ─────────────────────
    total_classified_cte = (
        select(
            classified_cte.c.year,
            func.sum(classified_cte.c.classified_spending).label("total_classified"),
        )
        .select_from(classified_cte)
        .group_by(classified_cte.c.year)
        .cte("total_classified_per_year")
    )

    # ── Final SELECT ─────────────────────────────────────────────────────────────
    return (
        select(
            classified_cte.c.year,
            classified_cte.c.original_identifier,
            classified_cte.c.chapter_name,
            classified_cte.c.chapter_name_translated,
            classified_cte.c.open_spending,
            classified_cte.c.total_spending,
            classified_cte.c.classified_spending,
            case(
                (
                    total_classified_cte.c.total_classified > 0,
                    classified_cte.c.classified_spending / total_classified_cte.c.total_classified,
                ),
                else_=None,
            ).label("classified_share_of_budget"),
        )
        .select_from(classified_cte)
        .join(total_classified_cte, classified_cte.c.year == total_classified_cte.c.year)
        .order_by(classified_cte.c.year, classified_cte.c.original_identifier)
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
