import pandas as pd
import re
from datetime import date
from models import Budget
from database.sessions import get_sync_session
from pathlib import Path


def extract_budget_metadata_from_filename(excel_file_path: Path) -> dict:
    """
    Extrahiert Metadaten aus dem Dateinamen.
    
    Filename patterns:
    - Laws: law_2024.xlsx → type=LAW, year=2024, scope=YEARLY
    - Reports: report_2024_03.xlsx → type=REPORT, year=2024, month=03, scope=QUARTERLY
    - Drafts: draft_2024.xlsx → type=DRAFT, year=2024, scope=YEARLY
    
    Returns:
        Dict mit Budget-relevanten Feldern
    """
    
    filename = excel_file_path.stem  # Dateiname ohne Extension
    filename_lower = filename.lower()
    
    # Budget Type bestimmen
    if filename_lower.startswith('law'):
        budget_type = "LAW"
        title = "Federal Budget Law"
        scope = "YEARLY"
    elif filename_lower.startswith('report'):
        budget_type = "REPORT"
        title = "Federal Budget Report"
        scope = "QUARTERLY"
    elif filename_lower.startswith('draft'):
        budget_type = "DRAFT"
        title = "Federal Budget Draft"
        scope = "YEARLY"
    else:
        raise ValueError(f"Unknown file type: {filename}. Expected law_*, report_*, or draft_*")
    
    # Jahr extrahieren
    year_match = re.search(r'(\d{4})', filename)
    if not year_match:
        raise ValueError(f"No year found in filename: {filename}")
    year = int(year_match.group(1))
    
    # Monat extrahieren (nur für Reports)
    month = None
    if budget_type == "REPORT":
        month_match = re.search(r'_(\d{2})(?:\.|$)', filename)
        if month_match:
            month = int(month_match.group(1))
    
    # Original Identifier erstellen
    # Format: LAW-2024, REPORT-2024-03, DRAFT-2024
    if budget_type == "REPORT" and month:
        original_identifier = f"{budget_type}-{year}-{month:02d}"
    else:
        original_identifier = f"{budget_type}-{year}"
    
    return {
        'original_identifier': original_identifier,
        'title': title,
        'year': year,
        'month': month,
        'type': budget_type,
        'scope': scope
    }


def create_budget_from_excel(excel_file_path: Path) -> Budget:
    """
    Erstellt ein Budget Objekt aus einer Excel Datei.
    Metadaten werden aus dem Dateinamen extrahiert.
    
    Args:
        excel_file_path: Pfad zur (gefixten) Excel Datei
                        Format: law_2024.xlsx, report_2024_03.xlsx, draft_2024.xlsx
        
    Returns:
        Budget Objekt (noch nicht in DB gespeichert)
    """
    metadata = extract_budget_metadata_from_filename(excel_file_path)

    if metadata['month']:
        print(f"  Month: {metadata['month']}")

    # Published date bestimmen
    if metadata['month']:
        # Für Reports: Jahr + Monat
        published_at = date(metadata['year'], metadata['month'], 1)
    else:
        # Für Laws/Drafts: Jahr
        published_at = date(metadata['year'], 1, 1)
    
    # Budget Objekt erstellen
    budget = Budget(
        original_identifier=metadata['original_identifier'],
        name=metadata['title'],
        name_translated=None,
        description=f"{metadata['title']} {metadata['year']}" + (f"-{metadata['month']:02d}" if metadata['month'] else ""),
        description_translated=None,
        type=metadata['type'],
        scope=metadata['scope'],
        published_at=published_at,
        planned_at=None
    )
    
    return budget

