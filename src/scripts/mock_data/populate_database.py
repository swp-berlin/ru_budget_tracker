from datetime import date
import logging
from models import (
    Budget,
    Expense,
    Dimension,
    BudgetTypeLiteral,
    BudgetScopeLiteral,
    DimensionTypeLiteral,
)
from faker import Faker
from database import get_sync_session
from itertools import combinations


def _create_budgets() -> list[Budget]:
    """Generate one dependent budget per type with the same original identifier."""
    fake = Faker()
    budgets = []
    original_identifier = fake.uuid4()
    last_published_at: date = fake.date_between("-5y", date.today())
    allowed_types = ["DRAFT", "LAW", "REPORT", "TOTAL"]
    for budget_type in allowed_types:
        budget = Budget(
            original_identifier=original_identifier,
            name=fake.word(),
            name_translated=fake.word(),
            description=fake.text(),
            description_translated=fake.text(),
            type=budget_type,
            scope="YEARLY",
            published_at=last_published_at,
            planned_at=last_published_at,
        )
        budgets.append(budget)
        # Update last_published_at for next budget
        last_published_at = fake.date_between_dates(last_published_at, date.today())
    return budgets


def generate_budgets(num_budgets: int = 10) -> list[Budget]:
    """Generate a list of mock budgets."""
    budgets: list[Budget] = []
    for _ in range(num_budgets):
        budgets.extend(_create_budgets())
    return budgets


def generate_expenses(
    budgets: list[Budget],
    num_expenses_per_budget_min: int = 5,
    num_expenses_per_budget_max: int = 20,
) -> list[Expense]:
    """Generate mock expenses for each budget."""
    fake = Faker()
    expenses = []
    for budget in budgets:
        for _ in range(fake.random_int(num_expenses_per_budget_min, num_expenses_per_budget_max)):
            expense = Expense(
                budget_id=budget.id,
                value=fake.pyfloat(left_digits=5, right_digits=2, positive=True),
            )
            expenses.append(expense)
    return expenses


def _generate_dimension(
    dimension_type: DimensionTypeLiteral,
    parent_dimension: Dimension | None,
    invalid_names: set[str] | None = None,
) -> Dimension:
    """Generate mock dimensions."""
    fake = Faker()
    # Generate a dimension name based on type
    name = ""
    if dimension_type == "MINISTRY":
        # highest level
        number = fake.random_int(1, 20)
        name = f"{number:02d} {dimension_type.title()}"
    if dimension_type == "CHAPTER" and parent_dimension is not None:
        # second level, take digits from parent ministry and add a number
        parent_number = parent_dimension.name.split(" ")[0]
        number = fake.random_int(1, 20)
        name = f"{parent_number}.{number:02d} {dimension_type.title()}"
    if dimension_type == "PROGRAMM" and parent_dimension is not None:
        # third or more level, take digits from parent chapter and add a number
        parent_number = parent_dimension.name.split(" ")[0]
        number = fake.random_int(1, 50)
        # Ensure unique numbers at this level
        name = f"{parent_number}.{number:02d} {dimension_type.title()}"
        if invalid_names is not None:
            while name in invalid_names:
                number = fake.random_int(1, 50)
                name = f"{parent_number}.{number:02d} {dimension_type.title()}"
    if dimension_type == "EXPENSE_TYPE":
        # lowest level, just a name
        name = dimension_type.title()

    dimension = Dimension(
        type=dimension_type,
        original_identifier=fake.uuid4(),
        name=name,
        name_translated=name,
        parent=parent_dimension,
    )

    return dimension


def _generate_nested_dimension(
    num_chapters: int = 1,
    num_programms: int = 1,
    depth_subprograms_min: int = 0,
    depth_subprograms_max: int = 0,
    invalid_names: set[str] = set(),
) -> tuple[list[Dimension], list[int]]:
    """Generate nested dimensions up to a certain depth."""
    dimensions: list[Dimension] = []
    # Generate one ministry
    ministry = _generate_dimension("MINISTRY", None)
    invalid_names.add(ministry.name)
    dimensions.append(ministry)
    # Generate chapters
    for _ in range(num_chapters):
        chapter = _generate_dimension("CHAPTER", ministry)
        invalid_names.add(chapter.name)
        dimensions.append(chapter)

    # Generate programms
    leaf_ids = []
    for chapter in [d for d in dimensions if d.type == "CHAPTER"]:
        for _ in range(num_programms):
            programm = _generate_dimension("PROGRAMM", chapter, invalid_names)
            invalid_names.add(programm.name)
            dimensions.append(programm)
            # Generate subprograms if depth > 0
            parent = programm
            if depth_subprograms_max == 0:
                leaf_ids.append(programm.id)
                continue
            # Determine random depth for subprograms
            fake = Faker()
            depth = fake.random_int(depth_subprograms_min, depth_subprograms_max)
            subprogramm: Dimension | None = None
            for _ in range(depth):
                subprogramm = _generate_dimension("PROGRAMM", parent, invalid_names)
                invalid_names.add(subprogramm.name)
                dimensions.append(subprogramm)
                parent = subprogramm
            if subprogramm is not None:
                leaf_ids.append(subprogramm.id)

    return dimensions, leaf_ids


def generate_dimensions(num_dimensions: int = 10) -> tuple[list[Dimension], list[int]]:
    """Generate a list of mock nested dimensions."""
    dimensions: list[Dimension] = []
    leaf_ids: list[int] = []
    for _ in range(num_dimensions):
        # Randomly decide on number of chapters, programms, and depth of subprograms
        fake = Faker()
        num_chapters = fake.random_int(1, 3)
        num_programms = fake.random_int(1, 5)
        depth_subprograms_min = 0
        depth_subprograms_max = fake.random_int(0, 5)
        nested_dimensions, current_leaf_ids = _generate_nested_dimension(
            num_chapters=num_chapters,
            num_programms=num_programms,
            depth_subprograms_min=depth_subprograms_min,
            depth_subprograms_max=depth_subprograms_max,
            invalid_names={d.name for d in dimensions},
        )
        dimensions.extend(nested_dimensions)
        leaf_ids.extend(current_leaf_ids)

    return dimensions, leaf_ids


def assign_dimensions_to_expenses(
    expenses: list[Expense],
    dimensions: list[Dimension],
    expenses_per_dimension_min: int = 1,
    expenses_per_dimension_max: int = 3,
) -> None:
    """Assign between min and max expenses per most deeply nested dimension."""
    fake = Faker()
    for expense in expenses:
        if not dimensions:
            logging.warning("No more dimensions available to assign to expenses.")
            break
        # Pop a randomly chosen set of dimensions from the available dimensions
        if expenses_per_dimension_max > len(dimensions):
            num_dimensions = len(dimensions)
        else:
            num_dimensions = fake.random_int(expenses_per_dimension_min, expenses_per_dimension_max)
        random_dimensions = fake.random_sample(dimensions, num_dimensions)
        expense.dimensions.extend(random_dimensions)
        # Remove dimensions from pool once assigned
        for dim in random_dimensions:
            dimensions.remove(dim)


def main() -> None:
    """Populate the database with mock data."""
    with get_sync_session() as session:
        # Generate budgets
        budgets = generate_budgets(5)
        session.add_all(budgets)
        session.flush()  # Ensure budgets have IDs assigned

        # Generate expenses
        expenses = generate_expenses(budgets, 15, 30)
        session.add_all(expenses)

        # Generate dimensions
        dimensions, leaf_ids = generate_dimensions(100)
        session.add_all(dimensions)

        # Assign dimensions to expenses
        leaf_dimensions = [d for d in dimensions if d.id in leaf_ids]
        assign_dimensions_to_expenses(expenses, leaf_dimensions)


if __name__ == "__main__":
    main()
