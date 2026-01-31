from datetime import date
from models import (
    Budget,
    Expense,
    Dimension,
    DimensionTypeLiteral,
)
from faker import Faker
import networkx as nx
from database import get_sync_session


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
    budget: Budget,
    num_expenses_per_budget_min: int = 5,
    num_expenses_per_budget_max: int = 20,
) -> list[Expense]:
    """Generate mock expenses for each budget."""
    fake = Faker()
    expenses = []
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
        while invalid_names is not None and name in invalid_names:
            number = fake.random_int(1, 1000)
            name = f"{number:02d} {dimension_type.title()}"
    if dimension_type == "CHAPTER" and parent_dimension is not None:
        # second level, take digits from parent ministry and add a number
        parent_number = parent_dimension.name.split(" ")[0]
        number = fake.random_int(1, 20)
        name = f"{parent_number}.{number:02d} {dimension_type.title()}"
        while invalid_names is not None and name in invalid_names:
            number = fake.random_int(1, 1000)
            name = f"{parent_number}.{number:02d} {dimension_type.title()}"
    if dimension_type == "PROGRAMM" and parent_dimension is not None:
        # third or more level, take digits from parent chapter and add a number
        parent_number = parent_dimension.name.split(" ")[0]
        number = fake.random_int(1, 50)
        # Ensure unique numbers at this level
        name = f"{parent_number}.{number:02d} {dimension_type.title()}"
        if invalid_names is not None:
            while name in invalid_names:
                number = fake.random_int(1, 1000)
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
) -> tuple[list[Dimension], set[str]]:
    """Generate nested dimensions up to a certain depth."""
    dimensions: list[Dimension] = []
    # Generate one ministry
    ministry = _generate_dimension("MINISTRY", None, invalid_names)
    invalid_names.add(ministry.name)
    dimensions.append(ministry)
    # Generate chapters
    for _ in range(num_chapters):
        chapter = _generate_dimension("CHAPTER", ministry, invalid_names)
        invalid_names.add(chapter.name)
        dimensions.append(chapter)

    # Generate programms
    for chapter in [d for d in dimensions if d.type == "CHAPTER"]:
        for _ in range(num_programms):
            programm = _generate_dimension("PROGRAMM", chapter, invalid_names)
            invalid_names.add(programm.name)
            dimensions.append(programm)
            # Generate subprograms if depth > 0
            parent = programm
            if depth_subprograms_max == 0:
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

    return dimensions, invalid_names


def generate_dimensions(
    num_dimensions: int = 10, dimension_names: set[str] = set()
) -> tuple[list[Dimension], set[str]]:
    """Generate a list of mock nested dimensions."""
    dimensions: list[Dimension] = []
    for _ in range(num_dimensions):
        # Randomly decide on number of chapters, programms, and depth of subprograms
        fake = Faker()
        num_chapters = fake.random_int(1, 3)
        num_programms = fake.random_int(1, 5)
        depth_subprograms_min = 0
        depth_subprograms_max = fake.random_int(0, 5)
        nested_dimensions, invalid_names = _generate_nested_dimension(
            num_chapters=num_chapters,
            num_programms=num_programms,
            depth_subprograms_min=depth_subprograms_min,
            depth_subprograms_max=depth_subprograms_max,
            invalid_names=dimension_names,
        )
        dimensions.extend(nested_dimensions)
        dimension_names.update(invalid_names)

    return dimensions, dimension_names


def calculate_hierarchy_paths(
    dimensions: list[Dimension],
) -> list[list[Dimension | None]]:
    """Calculate all paths from root to leaves in the hierarchy graph."""
    g = nx.DiGraph()
    g.add_edges_from([(d.parent, d) for d in dimensions if d.parent is not None])
    roots = (v for v, d in g.in_degree() if d == 0)
    leaves = [v for v, d in g.out_degree() if d == 0]
    all_paths = []
    for root in roots:
        paths = nx.all_simple_paths(g, root, leaves)
        all_paths.extend(paths)
    return all_paths


def assign_dimensions_to_expenses(
    expenses: list[Expense],
    dimensions: list[Dimension],
    expenses_per_dimension_min: int = 1,
    expenses_per_dimension_max: int = 1,
) -> None:
    """Assign between min and max expenses per most deeply nested dimension."""
    paths = calculate_hierarchy_paths(dimensions)
    seen_expense_ids = set()
    for path in paths:
        # Get the most deeply nested dimension
        leaf_dimension = path[-1]
        if leaf_dimension is None:
            continue
        # Randomly select expense to assign to this dimension
        valid_expenses = [e for e in expenses if e.id not in seen_expense_ids]
        if not valid_expenses:
            break
        fake = Faker()
        num_expenses = fake.random_int(expenses_per_dimension_min, expenses_per_dimension_max)
        selected_expenses = fake.random_elements(expenses, length=num_expenses, unique=True)
        for expense in selected_expenses:
            expense.dimensions.append(leaf_dimension)
            seen_expense_ids.add(expense.id)

    return None


def main() -> None:
    """Populate the database with mock data."""
    with get_sync_session() as session:
        # Generate budgets
        budgets = generate_budgets(2)
        session.add_all(budgets)
        session.flush()  # Ensure budgets have IDs assigned

    # Generate expenses
    dimension_names: set[str] = set()
    for budget in budgets:
        with get_sync_session() as session:
            budget = session.merge(budget)  # Re-attach budget to session
            expenses = generate_expenses(budget, 10, 20)
            session.add_all(expenses)

            # Generate dimensions
            dimensions, names = generate_dimensions(30, dimension_names)
            dimension_names.update(names)
            session.add_all(dimensions)

            # Assign dimensions to expenses
            assign_dimensions_to_expenses(expenses, dimensions)
            session.commit()


if __name__ == "__main__":
    main()
