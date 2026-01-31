"""
GDP parser for Rosstat quarterly and Minekonom yearly data.

Reads GDP data and creates ConversionRate entries for database storage.
Values are stored in rubles (source files are in billions).

Usage:
    from parsers import parse_gdp_files
    quarterly, yearly = parse_gdp_files(rosstat_path, minekonom_path)
"""

import re
import pandas as pd
from datetime import date
from dateutil.relativedelta import relativedelta
from pathlib import Path
from typing import List, Tuple

from models import ConversionRate

BILLION = 1_000_000_000
ROMAN_TO_INT = {"I": 1, "II": 2, "III": 3, "IV": 4}


def parse_rosstat_quarterly(file_path: Path) -> pd.DataFrame:
    """Parse Rosstat quarterly GDP from sheet 3. Returns (year, quarter, value) in rubles."""
    df = pd.read_excel(file_path, sheet_name=2, header=None)
    years, quarters, values = df.iloc[2], df.iloc[3], df.iloc[4]

    records, year = [], None
    for col in range(len(df.columns)):
        if pd.notna(years.iloc[col]):
            match = re.search(r"(\d{4})", str(years.iloc[col]))
            if match:
                year = int(match.group(1))
        if year is None or pd.isna(quarters.iloc[col]):
            continue
        q_match = re.match(r"(IV|III|II|I)", str(quarters.iloc[col]))
        if not q_match:
            continue
        val = float(values.iloc[col]) * BILLION if pd.notna(values.iloc[col]) else None
        records.append({"year": year, "quarter": ROMAN_TO_INT[q_match.group(1)], "value": val})

    return pd.DataFrame(records).drop_duplicates(["year", "quarter"], keep="first")


def calculate_estimates(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate estimates for missing quarters using YoY growth."""
    df = df.copy().sort_values(["quarter", "year"])
    df["prev_value"] = df.groupby("quarter")["value"].shift(1)
    df["growth"] = df["value"] / df["prev_value"]
    df = df.sort_values(["year", "quarter"])
    df["estimate"] = df["growth"].shift(1) * df["prev_value"]
    return df


def create_quarterly_rates(df: pd.DataFrame) -> List[ConversionRate]:
    """Create quarterly ConversionRate entries."""
    rates = []
    needs_est = df[(df["value"].isna()) & (df["estimate"].notna())]
    last_est_idx = needs_est.index[-1] if len(needs_est) else None

    for idx, row in df.iterrows():
        year, q = int(row["year"]), int(row["quarter"])
        if pd.notna(row["value"]):
            val, suffix = row["value"], ""
        elif idx == last_est_idx:
            val, suffix = row["estimate"], "_estimate"
        else:
            continue

        start = date(year, (q - 1) * 3 + 1, 1)
        rates.append(ConversionRate(
            name=f"gdp_{year}_q{q}{suffix}",
            value=val,
            started_at=start,
            ended_at=start + relativedelta(months=3, days=-1),
        ))
    return rates


def parse_minekonom_yearly(file_path: Path) -> pd.DataFrame:
    """Parse Minekonom yearly estimates. Returns (year, value) in rubles."""
    df = pd.read_excel(file_path)
    df.columns = [c.lower() for c in df.columns]
    df["value"] = df["value"] * BILLION
    return df[["year", "value"]]


def create_yearly_rates(quarterly_df: pd.DataFrame, minekonom_df: pd.DataFrame) -> List[ConversionRate]:
    """Create yearly ConversionRate entries by aggregating quarterly + Minekonom estimates."""
    yearly = (
        quarterly_df[quarterly_df["value"].notna()]
        .groupby("year")
        .agg(value=("value", "sum"), n=("value", "size"))
        .query("n == 4")
        .drop(columns="n")
        .reset_index()
    )
    last_actual = yearly["year"].max() if len(yearly) else 0
    combined = pd.concat([yearly, minekonom_df]).drop_duplicates("year", keep="first")

    rates = []
    for _, row in combined.sort_values("year").iterrows():
        year = int(row["year"])
        suffix = "_estimate" if year > last_actual else ""
        rates.append(ConversionRate(
            name=f"gdp_{year}{suffix}",
            value=row["value"],
            started_at=date(year, 1, 1),
            ended_at=date(year, 12, 31),
        ))
    return rates


def parse_gdp_files(
    rosstat_path: Path, minekonom_path: Path
) -> Tuple[List[ConversionRate], List[ConversionRate]]:
    """
    Parse GDP files and return ConversionRate entries.

    Args:
        rosstat_path: Path to Rosstat quarterly Excel file
        minekonom_path: Path to Minekonom yearly estimates Excel file

    Returns:
        (quarterly_rates, yearly_rates) - lists of ConversionRate objects
    """
    quarterly_df = parse_rosstat_quarterly(rosstat_path)
    quarterly_df = calculate_estimates(quarterly_df)
    quarterly_rates = create_quarterly_rates(quarterly_df)

    minekonom_df = parse_minekonom_yearly(minekonom_path)
    yearly_rates = create_yearly_rates(quarterly_df, minekonom_df)

    return quarterly_rates, yearly_rates