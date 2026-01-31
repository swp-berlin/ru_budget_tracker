from typing import Sequence
import networkx as nx
import pandas as pd
from sqlalchemy import RowMapping

HIERARCHY_OBJECTS = ("MINISTRY", "CHAPTER", "PROGRAMM")


def calculate_hierarchy_paths(
    df: pd.DataFrame,
) -> list[list[int]]:
    """Calculate all paths from root to leaves in the hierarchy graph."""
    g = nx.DiGraph()
    g.add_edges_from(df[["dimension_id", "dimension_parent_id"]].to_records(index=False))
    roots = (v for v, d in g.in_degree() if d == 0)
    leaves = [v for v, d in g.out_degree() if d == 0]
    all_paths = []
    for root in roots:
        paths = nx.all_simple_paths(g, root, leaves)
        all_paths.extend(paths)
    return all_paths


def prep_dataframe(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """Configure dataframe columns to represent hierarchy levels."""
    # Rename columns
    colnames = []
    for i in range(df.shape[1]):
        if i == 0:
            colnames.append("root")
        if i == 1:
            colnames.append("ministry")
        if i == 2:
            colnames.append("chapter")
        if i > 2:
            colnames.append(f"program_lvl_{i - 2}")
    df.columns = colnames
    return df


def transform_data(rows: Sequence[RowMapping], translated: bool = False) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df = df[df.dimension_type.isin(HIERARCHY_OBJECTS)]
    # Calculate all paths between dimensions
    paths = calculate_hierarchy_paths(df)
    # For each path, get the expense value associated with the leaf node
    expense_column = []
    for path in paths:
        expense = df.expense_value[df.dimension_id == path[0]]
        expense_column.append(expense.values[0] if not expense.empty else 0)
    # reverse path order to have root at first position
    paths = [list(reversed(path)) for path in paths]
    # Create dataframe from paths
    hierarchy_df = pd.DataFrame(paths)
    hierarchy_df = prep_dataframe(hierarchy_df)
    hierarchy_df["expense_value"] = expense_column
    hierarchy_df["root"] = 0

    name_mapping = create_id_name_mapping(df, translated)
    hierarchy_df = replace_id_with_name(hierarchy_df, name_mapping, root_name="Federal Budget")

    return hierarchy_df


def create_id_name_mapping(raw_data: pd.DataFrame, translated: bool = False) -> dict[int, str]:
    mapping = {}
    for _, row in raw_data.iterrows():
        d_id = row["dimension_id"]
        d_name = row["dimension_name"] if not translated else row["dimension_name_translated"]
        mapping[d_id] = d_name
    return mapping


def replace_id_with_name(
    dataframe: pd.DataFrame,
    id_name_mapping: dict[int, str],
    root_name: str = "Federal Budget",
) -> pd.DataFrame:
    """Replace dimension IDs in the dataframe with their corresponding names."""
    for col in dataframe.columns:
        if col == "expense_value":
            continue
        if col == "root":
            dataframe[col] = root_name
            continue
        dataframe[col] = dataframe[col].map(id_name_mapping)
    return dataframe
