"""
Test script to import all budget data from 2018 to 2025.
Run this script to populate the database with all available budget years.
"""
import sys
from pathlib import Path

# Add parent directory to path to import modules
sys.path.insert(0, str(Path(__file__).parent.parent))

import logging
from example_import_script import import_budget, import_dimensions_and_expenses

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """Import all budget years from 2018 to 2025."""
    
    print("\n" + "="*60)
    print("BUDGET IMPORT SCRIPT - 2018 to 2025")
    print("="*60 + "\n")
    
    # Years to import
    years = range(2018, 2026)  # 2018 to 2025 inclusive
    
    successful_imports = []
    failed_imports = []
    
    for year in years:
        file_path = Path(f"data/import_files/clean/laws/law_{year}.xlsx")
        
        print(f"\n{'='*60}")
        print(f"Processing year: {year}")
        print(f"File: {file_path}")
        print(f"{'='*60}")
        
        # Check if file exists
        if not file_path.exists():
            logger.warning(f"File not found: {file_path}")
            failed_imports.append((year, "File not found"))
            continue
        
        try:
            # Step 1: Import budget
            logger.info(f"Step 1/2: Importing budget for {year}...")
            budget_db_id = import_budget(file_path)
            logger.info(f"✓ Budget imported with ID: {budget_db_id}")
            
            # Step 2: Import dimensions and expenses
            logger.info(f"Step 2/2: Importing dimensions and expenses for {year}...")
            import_dimensions_and_expenses(file_path, budget_db_id)
            logger.info(f"✓ Dimensions and expenses imported for {year}")
            
            successful_imports.append(year)
            print(f"\n✓ Successfully imported year {year}")
            
        except Exception as e:
            logger.error(f"✗ Failed to import year {year}: {e}", exc_info=True)
            failed_imports.append((year, str(e)))
            print(f"\n✗ Failed to import year {year}: {e}")
    
    # Summary
    print("\n" + "="*60)
    print("IMPORT SUMMARY")
    print("="*60)
    print(f"Total years attempted: {len(years)}")
    print(f"Successfully imported: {len(successful_imports)}")
    print(f"Failed imports: {len(failed_imports)}")
    
    if successful_imports:
        print(f"\n✓ Successfully imported years: {', '.join(map(str, successful_imports))}")
    
    if failed_imports:
        print(f"\n✗ Failed to import:")
        for year, error in failed_imports:
            print(f"  - {year}: {error}")
    
    print("\n" + "="*60)
    
    if failed_imports:
        sys.exit(1)  # Exit with error code if any imports failed
    else:
        print("\n🎉 All imports completed successfully!")
        sys.exit(0)


if __name__ == "__main__":
    main()