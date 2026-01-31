"""
PPP parser for World Bank data.

Fetches PPP conversion factors and creates ConversionRate entries.
Imputes missing current/next year using last available data.

Usage:
    from parsers import fetch_ppp_rates, fetch_ppp_data, save_ppp_csv, fetch_ppp_api_data
    
    # Get ConversionRate objects for DB
    rates = fetch_ppp_rates()
    
    # Save raw data to CSV
    ppp_data = fetch_ppp_data()
    save_ppp_csv(ppp_data)
"""

import logging
import requests
from datetime import date
from pathlib import Path
from typing import Dict, List

import pandas as pd

from models import ConversionRate

logger = logging.getLogger(__name__)

COUNTRY = "RUS"
INDICATOR = "PA.NUS.PPP"
def _resolve_csv_path() -> Path:
    """Locate src/data/.../ppp.csv regardless of execution location."""
    target_suffix = Path("data") / "import_files" / "conversion_tables" / "ppp" / "ppp.csv"
    for parent in Path(__file__).resolve().parents:
        if parent.name == "src":
            return parent / target_suffix
    # Fallback to historical location relative to src/scripts
    return Path(__file__).resolve().parents[2] / target_suffix


CSV_PATH = _resolve_csv_path()


def fetch_ppp_api_data() -> Dict[int, float]:
    """Fetch PPP data from World Bank API. Returns {year: value}."""
    url = f"https://api.worldbank.org/v2/country/{COUNTRY}/indicator/{INDICATOR}"
    r = requests.get(url, params={"format": "json", "per_page": 20000}, timeout=30)
    r.raise_for_status()
    data = r.json()[1]
    return {int(row["date"]): float(row["value"]) for row in data if row["value"] is not None}


def _fetch_from_csv() -> Dict[int, float]:
    """Load PPP data from CSV fallback. Returns {year: value}."""
    df = pd.read_csv(CSV_PATH)
    return dict(zip(df["year"], df["value"]))


def fetch_ppp_data() -> Dict[int, float]:
    """Fetch PPP data from API, falling back to CSV on failure."""
    try:
        data = fetch_ppp_api_data()
        logger.info(f"Fetched PPP data from API ({len(data)} years)")
        return data
    except Exception as e:
        logger.warning(f"API failed ({e}), using CSV fallback")
        return _fetch_from_csv()


def save_ppp_csv(ppp_data: Dict[int, float], path: Path | None = None) -> Path:
    """Save PPP data to CSV."""
    path = path or CSV_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(sorted(ppp_data.items()), columns=["year", "value"])
    df.to_csv(path, index=False)
    logger.info(f"Saved PPP data to {path}")
    return path


def fetch_ppp_rates(target_year: int | None = None) -> List[ConversionRate]:
    """
    Fetch PPP rates and create ConversionRate entries.
    
    Imputes target_year and target_year+1 if not available, using last available year.
    Naming: ppp_{year} for actual, ppp_{year}_imputed_{source_year} for imputed.
    """
    if target_year is None:
        target_year = date.today().year
    
    ppp_data = fetch_ppp_data()
    if not ppp_data:
        raise ValueError("No PPP data available")
    
    last_year = max(ppp_data.keys())
    rates = []
    
    for year, value in sorted(ppp_data.items()):
        rates.append(ConversionRate(
            name=f"ppp_{year}",
            value=value,
            started_at=date(year, 1, 1),
            ended_at=date(year, 12, 31),
        ))
    
    for year in (target_year, target_year + 1):
        if year not in ppp_data:
            rates.append(ConversionRate(
                name=f"ppp_{year}_imputed_{last_year}",
                value=ppp_data[last_year],
                started_at=date(year, 1, 1),
                ended_at=date(year, 12, 31),
            ))
    
    return rates