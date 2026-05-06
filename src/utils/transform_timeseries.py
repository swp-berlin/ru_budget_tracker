from typing import Sequence
import pandas as pd
from sqlalchemy import RowMapping
from utils.definitions import budget_config, SpendingTypeLiteral


class TimeseriesTransformer:
    def _normalize_cumulative_expenses(
        self, budgets: Sequence[RowMapping], spending_type: SpendingTypeLiteral = "ALL"
    ) -> list[dict[str, str | float | int]]:
        """Normalize cumulative quarterly expenses by subtracting the previous quarter's value.

        Budgets are quarterly and cumulative, so Q4 includes Q1+Q2+Q3+Q4.
        This method calculates the actual quarterly value by subtracting the previous quarter.
        Q1 is the base (no subtraction), Q2 = Q2_cumulative - Q1_cumulative, etc.
        Normalization is done separately for each year and budget type (LAW, REPORT).
        """
        normalized_budgets: list[dict[str, str | float | int]] = []

        # Group budgets by year and type for independent normalization
        grouped: dict[tuple[int, str], list[RowMapping]] = {}
        for budget in budgets:
            key = (budget["published_at"].year, budget["type"])
            grouped.setdefault(key, []).append(budget)

        value_key = "military_value" if spending_type == "MILITARY" else "total_value"

        # Process each year-type group
        for (_, _), group_budgets in grouped.items():
            # Sort by date ascending to process in chronological order
            sorted_budgets = sorted(group_budgets, key=lambda b: b["published_at"])

            # Track previous quarter's cumulative value for subtraction
            prev_cumulative_value: float = 0.0

            for budget in sorted_budgets:
                # Convert RowMapping to mutable dict
                normalized = dict(budget)
                # TOTAL rows store pre-computed classified spending in total_value
                # (military_value is explicitly 0 in the fetch query for TOTAL rows).
                # Always read total_value for TOTAL rows regardless of spending_type.
                read_key = "total_value" if budget.get("type") == "TOTAL" else value_key
                current_cumulative = budget.get(read_key, 0.0) or 0.0

                # Calculate quarterly value by subtracting previous quarter
                quarterly_value = current_cumulative - prev_cumulative_value
                normalized["total_value"] = quarterly_value

                normalized_budgets.append(normalized)

                # Update previous value for next iteration
                prev_cumulative_value = current_cumulative

        return normalized_budgets

    def _transform_budget_totals(
        self,
        budgets: Sequence[RowMapping],
        normalize: bool,
        spending_type: SpendingTypeLiteral = "ALL",
    ) -> pd.DataFrame:
        """Transform law budget rows into a dataframe suitable for Timeseries visualization."""
        if not budgets:
            return pd.DataFrame()

        # For every published_at, subtract the law value from the total value
        # and set new value as Classified Spending
        budgets_corrected: Sequence[RowMapping] | list[dict[str, str | float | int]] = budgets
        if normalize:
            budgets_corrected = self._normalize_cumulative_expenses(budgets, spending_type)

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

            multiplicator: float = budget_config.law_total_value_multiplier
            if corresponding_budget["type"] == "REPORT":
                multiplicator = budget_config.report_total_value_multiplier

            total_value: float = budget["total_value"] * multiplicator  # type: ignore

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
        normalize: bool = True,
        spending_type: SpendingTypeLiteral = "ALL",
    ) -> pd.DataFrame:
        """Transform raw rows into a dataframe suitable for Timeseries visualization."""
        if not budgets:
            return pd.DataFrame()
        df = self._transform_budget_totals(budgets, normalize, spending_type)

        return df
