from typing import Sequence
import networkx as nx
import pandas as pd
from sqlalchemy import RowMapping

from utils.definitions import HIERARCHY_OBJECTS


class TreemapTransformer:
    def __init__(self, rows: Sequence[RowMapping], translated: bool = False):
        self.rows = rows
        self.translated = translated

    def _calculate_hierarchy_paths(self, df: pd.DataFrame) -> list[list[int]]:
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

    def _prep_dataframe(
        self,
        df: pd.DataFrame,
    ) -> pd.DataFrame:
        """Configure dataframe columns to represent hierarchy levels."""
        # Rename columns
        colnames = []
        for i in range(df.shape[1]):
            if i == 0:
                colnames.append("ROOT")
            if i == 1:
                colnames.append("MINISTRY")
            if i == 2:
                colnames.append("CHAPTER")
            if i > 2:
                colnames.append(f"PROGRAM_LVL_{i - 2}")
        df.columns = colnames
        return df

    def _create_id_name_mapping(
        self, raw_data: pd.DataFrame, translated: bool = False
    ) -> dict[int, str]:
        mapping = {}
        for _, row in raw_data.iterrows():
            d_id = row["dimension_id"]
            d_name = row["dimension_name"] if not translated else row["dimension_name_translated"]
            mapping[d_id] = d_name
        return mapping

    def _replace_id_with_name(
        self,
        dataframe: pd.DataFrame,
        id_name_mapping: dict[int, str],
        root_name: str = "Federal Budget",
    ) -> pd.DataFrame:
        """Replace dimension IDs in the dataframe with their corresponding names."""
        for col in dataframe.columns:
            if col == "EXPENSE_VALUE":
                continue
            if col == "ROOT":
                dataframe[col] = root_name
                continue
            dataframe[col] = dataframe[col].map(id_name_mapping)
        return dataframe

    def transform_data(self) -> pd.DataFrame:
        """Transform raw rows into a hierarchical dataframe suitable for treemap visualization."""
        rows = self.rows
        translated = self.translated
        df = pd.DataFrame(rows)
        if df.empty:
            return pd.DataFrame()
        df = df[df.dimension_type.isin(HIERARCHY_OBJECTS)]
        # Calculate all paths between dimensions
        paths = self._calculate_hierarchy_paths(df)
        # For each path, get the expense value associated with the leaf node
        expense_column = []
        for path in paths:
            expense = df.expense_value[df.dimension_id == path[0]]
            expense_column.append(expense.values[0] if not expense.empty else 0)
        # reverse path order to have root at first position
        paths = [list(reversed(path)) for path in paths]
        # Create dataframe from paths
        hierarchy_df = pd.DataFrame(paths)
        hierarchy_df = self._prep_dataframe(hierarchy_df)
        hierarchy_df["EXPENSE_VALUE"] = expense_column
        hierarchy_df["ROOT"] = 0

        name_mapping = self._create_id_name_mapping(df, translated)
        hierarchy_df = self._replace_id_with_name(
            hierarchy_df, name_mapping, root_name="Federal Budget"
        )

        return hierarchy_df


class BarchartTransformer:
    def __init__(self, rows: Sequence[RowMapping], translated: bool = False):
        self.rows = rows
        self.translated = translated

    def transform_data(self) -> pd.DataFrame:
        """Transform raw rows into a dataframe suitable for barchart visualization."""
        rows = self.rows
        if not rows:
            return pd.DataFrame()
        expenses = [
            row["expense_value"] if row["type"] != "TOTAL" else -row["expense_value"]
            for row in rows
        ]
        dates = [row["published_at"] for row in rows]
        types = [row["type"] for row in rows]

        df = pd.DataFrame({"expenses": expenses, "dates": dates, "types": types})
        # Parse dates to datetime
        df["dates"] = pd.to_datetime(df["dates"])
        # Truncate dates to years
        df["dates"] = df["dates"].dt.to_period("Y").dt.to_timestamp()  # type: ignore

        return df
