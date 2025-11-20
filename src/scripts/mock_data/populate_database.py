from datetime import date
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


def generate_budgets(num_entries: int = 10) -> list[Budget]:
    """Populate the database with mock budget data."""
    fake = Faker()
    budgets = []
    for _ in range(num_entries):
        published_at = fake.date_between("-5y", date.today())
        planned_at = fake.date_between_dates("-10y", published_at)
        budget = Budget(
            original_identifier=fake.uuid4(),
            name=fake.word(),
            name_translated=fake.word(),
            description=fake.text(),
            description_translated=fake.text(),
            type=fake.random_element(elements=BudgetTypeLiteral.__args__),
            scope=fake.random_element(elements=BudgetScopeLiteral.__args__),
            published_at=published_at,
            planned_at=planned_at,
        )
        budgets.append(budget)
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


def generate_dimensions(num_entries: int = 100) -> list[Dimension]:
    """Generate mock dimensions."""
    fake = Faker()
    dimensions: list[Dimension] = []
    for _ in range(num_entries):
        dimension = Dimension(
            type=fake.random_element(elements=DimensionTypeLiteral.__args__),
            original_identifier=fake.uuid4(),
            name=fake.word(),
            name_translated=fake.word(),
        )
        dimensions.append(dimension)

    return dimensions


def assign_parent_dimensions(
    dimensions: list[Dimension],
) -> None:
    """Assign parent dimensions to create a hierarchy.
    Guarantees that parent dimensions are of the same type as their children.
    Guarantees no circular references within the hierarchy and
    that at least some dimensions have no parent.
    Limits the depth of the hierarchy."""
    fake = Faker()
    dimension_dict = {d.id: d for d in dimensions}

    def _check_depth(
        dimension: Dimension,
        current_depth: int = 0,
    ) -> int:
        parent_dimension = dimension_dict.get(dimension.parent_id)
        if parent_dimension is None:
            return current_depth
        return _check_depth(parent_dimension, current_depth + 1)

    def _check_for_cycles_recursively(
        start_dimension: Dimension,
        current_dimension: Dimension | None,
        visited: set[int] = set(),
    ) -> bool:
        if current_dimension is None:
            return False
        if current_dimension.parent_id is None:
            return False
        if current_dimension.parent_id in visited:
            return True
        visited.add(current_dimension.parent_id)
        parent_dimension = dimension_dict.get(current_dimension.parent_id)
        if parent_dimension is None:
            return False
        return _check_for_cycles_recursively(start_dimension, parent_dimension, visited)

    def choose_parent(dimension: Dimension) -> Dimension | None:
        potential_parents = [
            d
            for d in dimensions
            if d.id != dimension.id
            and d.type == dimension.type
            and _check_for_cycles_recursively(dimension, d) is False
        ]
        if not potential_parents:
            return None

        # Sort list by depth (favor deeper hierarchies)
        potential_parents.sort(key=lambda d: _check_depth(d), reverse=True)

        # Slice highest depth parents to increase chance of existing parents
        for _ in range(4, 0, -1):
            depth_filtered = [d for d in potential_parents if _check_depth(d) >= _]
            if depth_filtered and len(depth_filtered) > 2:
                potential_parents = depth_filtered
                break

        # Slice to favor top 20% of deeper hierarchies
        if len(potential_parents) > 10:
            top_n = max(1, len(potential_parents) // 2)
            potential_parents = potential_parents[:top_n]

        return fake.random_element(elements=potential_parents)

    for dimension in dimensions:
        # 2% chance to have no parent
        if fake.random_int(1, 100) <= 2:
            continue

        parent = choose_parent(dimension)
        if parent is None:
            # Try again for 10 times
            for _ in range(10):
                parent = choose_parent(dimension)
                if parent is not None:
                    break

        if parent is not None:
            dimension.parent_id = parent.id


def assign_dimensions_to_expenses(
    expenses: list[Expense],
    dimensions: list[Dimension],
) -> None:
    """Assign random dimensions to expenses. Each expense can have 1 dimension per dimension type."""
    fake = Faker()
    dimension_types = DimensionTypeLiteral.__args__
    dimensions_by_type = {
        dim_type: [d for d in dimensions if d.type == dim_type] for dim_type in dimension_types
    }
    for expense in expenses:
        for dim_type in dimensions_by_type.keys():
            possible_dimensions = dimensions_by_type[dim_type]
            if possible_dimensions:
                dimension = fake.random_element(elements=possible_dimensions)
                expense.dimensions.append(dimension)


def main() -> None:
    """Populate the database with mock data."""
    with get_sync_session() as session:
        # Generate budgets
        budgets = generate_budgets(50)
        session.add_all(budgets)
        session.flush()  # Ensure budgets have IDs assigned

        # Generate expenses
        expenses = generate_expenses(budgets)
        session.add_all(expenses)
        session.flush()  # Ensure expenses have IDs assigned

        # Generate dimensions
        dimensions = generate_dimensions(50)
        session.add_all(dimensions)
        session.flush()  # Ensure dimensions have IDs assigned

        # Assign parent dimensions
        assign_parent_dimensions(dimensions)

        # Assign dimensions to expenses
        assign_dimensions_to_expenses(expenses, dimensions)


if __name__ == "__main__":
    main()
