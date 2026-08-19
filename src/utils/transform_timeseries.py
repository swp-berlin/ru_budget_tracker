from typing import Sequence
import pandas as pd
from sqlalchemy import RowMapping
from utils.definitions import budget_config, SpendingTypeLiteral


class TimeseriesTransformer:
    def _transform_budget_totals(
        self,
        budgets: Sequence[RowMapping],
        spending_type: SpendingTypeLiteral = "ALL",
    ) -> pd.DataFrame:
        """Transform law budget rows into a dataframe suitable for Timeseries visualization."""
        if not budgets:
            return pd.DataFrame()

        # REPORT rows are cumulative year-to-date and are kept that way: every unit's
        # denominator in `utils.calculate` is cumulative through the same quarter, so
        # de-cumulating here would divide a single quarter by a year-to-date total.
        budgets_corrected: Sequence[RowMapping] = budgets

        # Use military_value for the OPEN bar when filtering for military spending.
        open_value_key = "military_value" if spending_type == "MILITARY" else "total_value"

        expenses = [
            budget[open_value_key] for budget in budgets_corrected if budget["type"] != "TOTAL"
        ]
        dates = [
            budget["published_at"] for budget in budgets_corrected if budget["type"] != "TOTAL"
        ]
        types = [budget["type"] for budget in budgets_corrected if budget["type"] != "TOTAL"]
        ids = [budget["id"] for budget in budgets_corrected if budget["type"] != "TOTAL"]

        df = pd.DataFrame({"expenses": expenses, "dates": dates, "types": types, "budget_id": ids})
        df["dates"] = pd.to_datetime(df["dates"], errors="coerce")

        # For every TOTAL budget, find the corresponding non-TOTAL budget and subtract its value
        for budget in [budget for budget in budgets_corrected if budget["type"] == "TOTAL"]:
            corresponding_budget = next(
                (
                    b
                    for b in budgets_corrected
                    if b["published_at"] == budget["published_at"] and b["type"] != "TOTAL"
                ),
                None,
            )
            if corresponding_budget is None:
                continue
            if budget["total_value"] is None:
                continue

            multiplicator: float = budget_config.law_total_value_multiplier
            if corresponding_budget["type"] == "REPORT":
                multiplicator = budget_config.report_total_value_multiplier

            total_value: float = budget["total_value"] * multiplicator

            # The fetch layer always pre-computes classified in TOTAL rows
            # (total_value = classified / multiplier, military_value = 0),
            # so no open spending needs to be subtracted here.
            open_value: float = 0.0
            classified_expense = total_value - open_value
            budget_id = budget["id"]
            df = pd.concat(
                [
                    df,
                    pd.DataFrame(
                        {
                            "expenses": [classified_expense],
                            # Keep dates as datetime by converting appended values.
                            "dates": [
                                pd.to_datetime(
                                    budget["published_at"], errors="coerce", format="%Y-%m-%d"
                                )
                            ],
                            "types": ["CLASSIFIED"],
                            "budget_id": [budget_id],
                        }
                    ),
                ],
                ignore_index=True,
            )

        return df

    def transform_data(
        self,
        budgets: Sequence[RowMapping],
        spending_type: SpendingTypeLiteral = "ALL",
    ) -> pd.DataFrame:
        """Transform raw rows into a dataframe suitable for Timeseries visualization."""
        if not budgets:
            return pd.DataFrame()
        df = self._transform_budget_totals(budgets, spending_type)

        return df
