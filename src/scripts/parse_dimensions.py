"""
Simple script to parse dimensions from Excel files.
Simplified version with straightforward row merging.
"""

import pandas as pd
from pathlib import Path
from models import Dimension
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)


def extract_expense_type_name_from_parentheses(full_text: str) -> str:
    """
    Extract expense type name from the last parenthesis pair in text.
    If no parenthesis found, return full text.
    
    Args:
        full_text: The complete text that may contain parentheses
        
    Returns:
        Extracted text from last parenthesis, or full text if no parenthesis
    """
    # Simple approach: find the LAST closing parenthesis and its matching opening
    last_close_pos = full_text.rfind(')')
    
    if last_close_pos != -1:
        # Found a closing paren - now find its matching opening by going backwards
        depth = 0
        matching_open = -1
        
        for i in range(last_close_pos - 1, -1, -1):
            if full_text[i] in (')', '）', '\uff09'):
                depth += 1
            elif full_text[i] in ('(', '（', '\uff08'):
                if depth == 0:
                    matching_open = i
                    break
                depth -= 1
        
        if matching_open != -1:
            # Extract content between matching pair
            return full_text[matching_open + 1:last_close_pos].strip()
    
    # No parenthesis found or couldn't match - return full text
    return full_text


def find_header_row(df: pd.DataFrame) -> int:
    """
    Find the row where the data table starts.
    Looks for row containing: Наименование, Мин, Рз, etc.
    """
    for idx, row in df.iterrows():
        row_str = ' '.join(str(val) for val in row if pd.notna(val))
        if 'Наименование' in row_str and ('Мін' in row_str or 'Мин' in row_str):
            return idx
    raise ValueError("Could not find header row with Наименование, Мін")


def get_column_mapping(header_row: pd.Series) -> Dict[str, int]:
    """
    Map column names to their indices.
    
    Args:
        header_row: The header row from the DataFrame
        
    Returns:
        Dictionary mapping column purpose to index
    """
    col_mapping = {}
    
    for col_idx, col_name in enumerate(header_row):
        if pd.isna(col_name):
            continue
        col_str = str(col_name).strip()
        
        if 'наименование' in col_str.lower():
            col_mapping['name'] = col_idx
        elif col_str == 'Мин' or col_str == 'Мін':
            col_mapping['ministry'] = col_idx
        elif col_str == 'Рз':
            col_mapping['chapter'] = col_idx
        elif col_str == 'ПР':
            col_mapping['subchapter'] = col_idx
        elif col_str == 'ЦСР':
            col_mapping['program'] = col_idx
        elif col_str == 'ВР':
            col_mapping['expense_type'] = col_idx
    
    # The value column is the column immediately after expense_type
    if 'expense_type' in col_mapping:
        col_mapping['value'] = col_mapping['expense_type'] + 1
    
    logger.info(f"Column mapping: {col_mapping}")
    return col_mapping


def clean_code_value(value) -> str | None:
    """
    Clean and validate a code value from the DataFrame.
    
    Args:
        value: Raw value from DataFrame cell
        
    Returns:
        Cleaned string value or None if empty/invalid
    """
    if pd.isna(value):
        return None
    
    cleaned = str(value).strip()
    if cleaned.lower() == 'nan' or cleaned == '':
        return None
    
    return cleaned


def merge_rows(
    df: pd.DataFrame,
    header_row_idx: int,
    col_mapping: Dict[str, int]
) -> List[Dict[str, Any]]:
    """
    Merge multi-row entries by accumulating rows without codes.
    
    Rules:
    1. If a row has no codes, check previous row with codes:
       - If previous has expense_type and doesn't end with ')', append to previous
       - Otherwise accumulate forward
    2. If a row has codes, create entry with accumulated text + current text
    
    Args:
        df: The DataFrame containing the data
        header_row_idx: Index of the header row
        col_mapping: Dictionary mapping column purposes to indices
        
    Returns:
        List of dictionaries containing merged row data with keys:
        - row_idx: Original row index
        - name: Merged name text
        - ministry_code, chapter_code, subchapter_code, program_code, expense_type_code
        - value: Float value in rubles (from column after expense_type)
    """
    logger.info("Merging multi-row entries...")
    
    merged_rows = []
    accumulated_name = ""
    first_data_row = True
    name_idx = col_mapping.get('name', 0)
    
    for idx in range(header_row_idx + 1, len(df)):
        row = df.iloc[idx]
        
        # Get and clean name
        name = row.iloc[name_idx]
        if pd.isna(name) or str(name).strip() == '':
            continue
        
        # Clean name: replace newlines with spaces and normalize whitespace
        name = str(name).replace('\n', ' ').replace('\r', ' ')
        name = ' '.join(name.split())
        
        # Skip first data row if it's a total row
        if first_data_row:
            first_data_row = False
            if 'всего' in name.replace(' ', '').lower():
                logger.debug(f"Row {idx}: Skipping total row")
                continue
        
        # Get and clean codes
        ministry_code = clean_code_value(
            row.iloc[col_mapping['ministry']] if 'ministry' in col_mapping else None
        )
        chapter_code = clean_code_value(
            row.iloc[col_mapping['chapter']] if 'chapter' in col_mapping else None
        )
        subchapter_code = clean_code_value(
            row.iloc[col_mapping['subchapter']] if 'subchapter' in col_mapping else None
        )
        program_code = clean_code_value(
            row.iloc[col_mapping['program']] if 'program' in col_mapping else None
        )
        expense_type_code = clean_code_value(
            row.iloc[col_mapping['expense_type']] if 'expense_type' in col_mapping else None
        )
        
        has_codes = any([
            ministry_code, 
            chapter_code, 
            subchapter_code, 
            program_code, 
            expense_type_code
        ])
        
        if not has_codes:
            # Check if we should append to previous row or accumulate forward
            if merged_rows:
                prev_entry = merged_rows[-1]
                prev_has_expense_type = prev_entry['expense_type_code'] is not None
                prev_ends_with_paren = prev_entry['name'].endswith(')')
                current_ends_with_quote = name.endswith('"')
                
                # Case 1: Previous has expense_type and doesn't end with )
                if prev_has_expense_type and not prev_ends_with_paren:
                    prev_entry['name'] += " " + name
                    logger.debug(f"Row {idx}: Appended to previous row (has expense_type, no closing paren)")
                    continue
                
                # Case 2: Previous has NO expense_type and current ends with "
                if not prev_has_expense_type and current_ends_with_quote:
                    prev_entry['name'] += " " + name
                    logger.debug(f"Row {idx}: Appended to previous row (no expense_type, ends with quote)")
                    continue
            
            # Otherwise accumulate forward
            accumulated_name = name if not accumulated_name else accumulated_name + " " + name
            logger.debug(f"Row {idx}: No codes, accumulating text")
            continue
        
        # Has codes: create entry with accumulated text (if any) + current text
        full_name = (accumulated_name + " " + name) if accumulated_name else name
        accumulated_name = ""  # Reset accumulation
        
        # Get value (from column after expense_type)
        value = None
        if 'value' in col_mapping:
            value_raw = row.iloc[col_mapping['value']]
            if pd.notna(value_raw):
                try:
                    value = float(value_raw)
                except (ValueError, TypeError):
                    logger.debug(f"Row {idx}: Could not convert value '{value_raw}' to float")
        
        merged_rows.append({
            'row_idx': idx,
            'name': full_name,
            'ministry_code': ministry_code,
            'chapter_code': chapter_code,
            'subchapter_code': subchapter_code,
            'program_code': program_code,
            'expense_type_code': expense_type_code,
            'value': value
        })
        logger.debug(f"Row {idx}: Created entry with codes")
    
    logger.info(f"Merged {len(merged_rows)} entries")
    return merged_rows


def parse_dimensions_from_merged_rows(
    merged_rows: List[Dict[str, Any]]
) -> List[Dimension]:
    """
    Parse merged rows and create dimension objects.
    
    Args:
        merged_rows: List of merged row dictionaries from merge_rows()
        
    Returns:
        List of Dimension objects
    """
    logger.info("Parsing dimensions from merged entries...")
    
    dimensions_list = []
    
    # Helper function to find existing dimension by identifier and type
    def find_dimension(identifier: str, dim_type: str):
        for dim in dimensions_list:
            if dim.original_identifier == identifier and dim.type == dim_type:
                return dim
        return None
    
    # Parse each merged row and create dimensions
    for entry in merged_rows:
        name = entry['name']
        ministry_code = entry['ministry_code']
        chapter_code = entry['chapter_code']
        subchapter_code = entry['subchapter_code']
        program_code = entry['program_code']
        expense_type_code = entry['expense_type_code']
        
        # Create dimensions based on what codes are filled
        # Strategy: Create the MOST SPECIFIC dimension from each row
        
        # Priority (most specific first):
        # 1. Program with expense_type (handled separately below)
        # 2. Program without expense_type
        # 3. Subchapter
        # 4. Chapter
        # 5. Ministry
        
        # Program (without expense_type) - most specific after expense_type combo
        if program_code and not expense_type_code:
            program_id = program_code
            
            # Find parent program
            parent_program_id = None
            parts = program_code.strip().split()
            if len(parts) > 1:
                # Try progressively shorter versions to find parent PROGRAM
                for i in range(len(parts) - 1, 0, -1):
                    candidate_parts = parts[:i]
                    candidate_id = ' '.join(candidate_parts)
                    # Check if it exists as a PROGRAM (not chapter/subchapter)
                    if find_dimension(candidate_id, 'PROGRAM'):
                        parent_program_id = candidate_id
                        break
                
                # If still not found, try individual parts (for single-digit like "15")
                if not parent_program_id:
                    first_part = parts[0]
                    if find_dimension(first_part, 'PROGRAM'):
                        parent_program_id = first_part
            
            dimensions_list.append(Dimension(
                original_identifier=program_id,
                type='PROGRAM',
                name=name,
                name_translated=None,
                parent_id=parent_program_id
            ))
        
        # Subchapter
        if subchapter_code and not program_code:
            subchapter_id = f"{chapter_code}-{subchapter_code}"
            parent_chapter_id = chapter_code
            
            dimensions_list.append(Dimension(
                original_identifier=subchapter_id,
                type='SUBCHAPTER',
                name=name,
                name_translated=None,
                parent_id=parent_chapter_id
            ))
        
        # Chapter
        if chapter_code and not subchapter_code and not program_code:
            chapter_id = chapter_code
            dimensions_list.append(Dimension(
                original_identifier=chapter_id,
                type='CHAPTER',
                name=name,
                name_translated=None,
                parent_id=None
            ))
        
        # Ministry
        if ministry_code and not chapter_code and not program_code:
            dimensions_list.append(Dimension(
                original_identifier=ministry_code,
                type='MINISTRY',
                name=name,
                name_translated=None,
                parent_id=None
            ))
        
        # Expense Type (Extract name from LAST parenthesis pair)
        if expense_type_code:
            expense_type_id = expense_type_code
            # Use extraction function to get name from last parenthesis
            expense_type_name = extract_expense_type_name_from_parentheses(name)
            logger.debug(f"Processing expense type {expense_type_code}: extracted name '{expense_type_name[:100]}'")
            
            dimensions_list.append(Dimension(
                original_identifier=expense_type_id,
                type='EXPENSE_TYPE',
                name=expense_type_name,  # From last top-level parenthesis
                name_translated=None,
                parent_id=None
            ))
            
            # Also create the Program WITH expense type (this gets the actual name)
            if program_code:
                program_id = f"{program_code}-{expense_type_code}"
                
                # Find parent: Should be program_code, but if it doesn't exist,
                # walk up the hierarchy to find the nearest existing PROGRAM (not chapter!)
                parent_program_id = None
                
                # First try: full program_code (e.g., "01 3 02 90000")
                if find_dimension(program_code, 'PROGRAM'):
                    parent_program_id = program_code
                else:
                    # Walk up the hierarchy to find nearest existing PROGRAM
                    # Try progressively shorter versions: "15 4 09" → "15 4" → "15"
                    parts = program_code.strip().split()
                    
                    # First try multi-part combinations
                    for i in range(len(parts) - 1, 0, -1):
                        candidate_parts = parts[:i]
                        candidate_id = ' '.join(candidate_parts)
                        # Check if it exists as a PROGRAM (not chapter/subchapter)
                        if find_dimension(candidate_id, 'PROGRAM'):
                            parent_program_id = candidate_id
                            break
                    
                    # If still not found, try individual parts (for single-digit programs like "15")
                    if not parent_program_id and len(parts) > 1:
                        # Check if first part alone exists (e.g., "15" from "15 4 09")
                        first_part = parts[0]
                        if find_dimension(first_part, 'PROGRAM'):
                            parent_program_id = first_part
                
                dimensions_list.append(Dimension(
                    original_identifier=program_id,
                    type='PROGRAM',
                    name=name,  # This gets the specific name from the row
                    name_translated=None,
                    parent_id=parent_program_id  # Nearest existing parent
                ))
    
    logger.info(f"Extracted {len(dimensions_list)} dimensions")
    return dimensions_list


def deduplicate_dimensions(dimensions_list: List[Dimension]) -> List[Dimension]:
    """
    Remove duplicate dimensions and log cases where same identifier+type has different names.
    
    Args:
        dimensions_list: List of Dimension objects (may contain duplicates)
        
    Returns:
        List of unique Dimension objects
    """
    # Track all names per (identifier, type)
    identifier_type_names = {}
    
    for dim in dimensions_list:
        key = (dim.original_identifier, dim.type)
        if key not in identifier_type_names:
            identifier_type_names[key] = []
        identifier_type_names[key].append(dim.name)
    
    # Log cases where same identifier+type has different names
    for (identifier, dim_type), names in identifier_type_names.items():
        unique_names = set(names)
        if len(unique_names) > 1:
            logger.warning(f"Same {dim_type} '{identifier}' has {len(unique_names)} different names:")
            for name in sorted(unique_names):
                logger.warning(f"  - {name[:150]}")
    
    # Now deduplicate: Keep first occurrence of each (identifier, type, name)
    seen = set()
    unique_dimensions = []
    duplicates_removed = 0
    
    for dim in dimensions_list:
        key = (dim.original_identifier, dim.type, dim.name)
        if key not in seen:
            seen.add(key)
            unique_dimensions.append(dim)
        else:
            duplicates_removed += 1
            logger.debug(f"Removed duplicate: {dim.original_identifier} ({dim.type})")
    
    logger.info(f"Removed {duplicates_removed} exact duplicates, {len(unique_dimensions)} unique dimensions remain")
    
    # Count by type
    type_counts = {}
    for dim in unique_dimensions:
        type_counts[dim.type] = type_counts.get(dim.type, 0) + 1
    logger.info(f"Dimension types: {type_counts}")
    
    return unique_dimensions


def create_expenses_from_merged_rows(
    merged_rows: List[Dict[str, Any]],
    dimensions_list: List[Dimension],
    budget_id: int
) -> List['Expense']:
    """
    Create Expense objects from merged rows and link them to dimensions.
    
    Only rows with expense_type_code (and a value) become expenses.
    Each expense is linked to all relevant dimensions based on the codes in that row.
    
    Args:
        merged_rows: List of merged row dictionaries from merge_rows()
        dimensions_list: List of Dimension objects to match against
        budget_id: Database ID of the budget
        
    Returns:
        List of Expense objects with dimensions linked
    """
    from models.budget import Expense  # Import here to avoid circular imports
    
    logger.info("Creating expenses from merged rows...")
    
    # Build lookup dictionary: (type, identifier) -> Dimension object
    dim_lookup = {}
    for dim in dimensions_list:
        key = (dim.type, dim.original_identifier)
        dim_lookup[key] = dim
    
    expenses = []
    
    for row in merged_rows:
        # Only create expenses for rows with expense_type and a value
        if not row['expense_type_code'] or row['value'] is None:
            continue
        
        expense = Expense(
            budget_id=budget_id,
            value=row['value']
        )
        
        # Link all relevant dimensions to this expense
        linked_dims = []
        
        # Ministry
        if row['ministry_code']:
            dim = dim_lookup.get(('MINISTRY', row['ministry_code']))
            if dim:
                expense.dimensions.append(dim)
                linked_dims.append(f"MINISTRY:{row['ministry_code']}")
        
        # Chapter
        if row['chapter_code']:
            dim = dim_lookup.get(('CHAPTER', row['chapter_code']))
            if dim:
                expense.dimensions.append(dim)
                linked_dims.append(f"CHAPTER:{row['chapter_code']}")
        
        # Subchapter
        if row['subchapter_code'] and row['chapter_code']:
            subchapter_id = f"{row['chapter_code']}-{row['subchapter_code']}"
            dim = dim_lookup.get(('SUBCHAPTER', subchapter_id))
            if dim:
                expense.dimensions.append(dim)
                linked_dims.append(f"SUBCHAPTER:{subchapter_id}")
        
        # Program (without expense_type)
        if row['program_code'] and not row['expense_type_code']:
            dim = dim_lookup.get(('PROGRAM', row['program_code']))
            if dim:
                expense.dimensions.append(dim)
                linked_dims.append(f"PROGRAM:{row['program_code']}")
        
        # Program WITH expense_type (most specific)
        if row['program_code'] and row['expense_type_code']:
            program_expense_id = f"{row['program_code']}-{row['expense_type_code']}"
            dim = dim_lookup.get(('PROGRAM', program_expense_id))
            if dim:
                expense.dimensions.append(dim)
                linked_dims.append(f"PROGRAM:{program_expense_id}")
        
        # Expense Type
        if row['expense_type_code']:
            dim = dim_lookup.get(('EXPENSE_TYPE', row['expense_type_code']))
            if dim:
                expense.dimensions.append(dim)
                linked_dims.append(f"EXPENSE_TYPE:{row['expense_type_code']}")
        
        if expense.dimensions:
            expenses.append(expense)
            logger.debug(f"Created expense with value {row['value']}, linked to: {', '.join(linked_dims)}")
        else:
            logger.warning(f"Expense with value {row['value']} has no matching dimensions!")
    
    logger.info(f"Created {len(expenses)} expenses")
    return expenses


def extract_dimensions_and_expenses_from_excel(
    excel_file_path: Path,
    budget_id: int
) -> tuple[List[Dimension], List['Expense']]:
    """
    Extract both dimensions and expenses from an Excel file in a single pass.
    
    This is more efficient than parsing twice, and ensures dimensions and expenses
    are matched correctly.
    
    Args:
        excel_file_path: Path to the Excel file
        budget_id: Database ID of the budget these belong to
        
    Returns:
        Tuple of (dimensions_list, expenses_list)
    """
    logger.info(f"Reading Excel file: {excel_file_path}")
    
    # Try to read with proper encoding handling for Cyrillic text
    try:
        df = pd.read_excel(excel_file_path, header=None, engine='openpyxl')
    except Exception as e:
        logger.error(f"Failed to read Excel with openpyxl: {e}")
        df = pd.read_excel(excel_file_path, header=None)
    
    # Find header row
    header_row_idx = find_header_row(df)
    logger.info(f"Found header at row {header_row_idx}")
    
    # Get column mapping
    header_row = df.iloc[header_row_idx]
    col_mapping = get_column_mapping(header_row)
    
    # Step 1: Merge rows based on code presence
    merged_rows = merge_rows(df, header_row_idx, col_mapping)
    
    # Step 2: Parse dimensions from merged rows
    dimensions_list = parse_dimensions_from_merged_rows(merged_rows)
    
    # Step 3: Deduplicate dimensions
    unique_dimensions = deduplicate_dimensions(dimensions_list)
    
    # Step 4: Create expenses and link to dimensions
    expenses = create_expenses_from_merged_rows(merged_rows, unique_dimensions, budget_id)
    
    return unique_dimensions, expenses


def load_dimensions_and_expenses_from_excel(
    excel_file_path: Path,
    budget_id: int = None
) -> dict:
    """
    Load both dimensions and expenses from an Excel file.
    Returns a dictionary with 'dimensions' and 'expenses' keys.
    
    This is the recommended entry point for parsing Excel files.
    
    Args:
        excel_file_path: Path to the Excel file
        budget_id: Optional budget ID (if None, expenses will be empty list)
        
    Returns:
        Dict with keys 'dimensions' and 'expenses'
    """
    if budget_id is None:
        # If no budget_id provided, just return dimensions
        dimensions = extract_dimensions_from_excel(excel_file_path)
        return {
            "dimensions": dimensions,
            "expenses": []
        }
    
    # Extract both dimensions and expenses
    dimensions, expenses = extract_dimensions_and_expenses_from_excel(excel_file_path, budget_id)
    
    return {
        "dimensions": dimensions,
        "expenses": expenses
    }


def extract_dimensions_from_excel(excel_file_path: Path) -> List[Dimension]:
    """
    Extract all dimensions from an Excel file.
    
    Columns:
    - Наименование: Name of the dimension
    - Мін: Ministry (type=MINISTRY)
    - Рз: Chapter (type=CHAPTER) 
    - ПР: Subchapter (type=SUBCHAPTER, parent=Chapter)
    - ЦСР: Program (type=PROGRAM)
    - ВР: Expense Type (type=EXPENSE_TYPE)
    
    Args:
        excel_file_path: Path to the Excel file
        
    Returns:
        List of unique Dimension objects
    """
    logger.info(f"Reading Excel file: {excel_file_path}")
    
    # Try to read with proper encoding handling for Cyrillic text
    try:
        df = pd.read_excel(excel_file_path, header=None, engine='openpyxl')
    except Exception as e:
        logger.error(f"Failed to read Excel with openpyxl: {e}")
        # Fallback: try with different engine
        df = pd.read_excel(excel_file_path, header=None)
    
    # Find header row
    header_row_idx = find_header_row(df)
    logger.info(f"Found header at row {header_row_idx}")
    
    # Get column mapping
    header_row = df.iloc[header_row_idx]
    col_mapping = get_column_mapping(header_row)
    
    # Step 1: Merge rows based on code presence
    merged_rows = merge_rows(df, header_row_idx, col_mapping)
    
    # Step 2: Parse dimensions from merged rows
    dimensions_list = parse_dimensions_from_merged_rows(merged_rows)
    
    # Step 3: Deduplicate
    unique_dimensions = deduplicate_dimensions(dimensions_list)
    
    return unique_dimensions