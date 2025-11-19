#!/usr/bin/env python3
"""Process Excel files from import_files/raw to import_files/clean."""

import re
import shutil
import zipfile
from pathlib import Path


def fix_corrupt_xlsx(input_file, output_file):
    """Fix Excel files with corrupt styles.xml."""
    minimal_styles = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="1">
    <font>
      <sz val="11"/>
      <name val="Calibri"/>
    </font>
  </fonts>
  <fills count="2">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
  </fills>
  <borders count="1">
    <border><left/><right/><top/><bottom/><diagonal/></border>
  </borders>
  <cellStyleXfs count="1">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>
  </cellStyleXfs>
  <cellXfs count="1">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
  </cellXfs>
</styleSheet>'''
    
    with zipfile.ZipFile(input_file, 'r') as zip_read:
        with zipfile.ZipFile(output_file, 'w', zipfile.ZIP_DEFLATED) as zip_write:
            for item in zip_read.infolist():
                if item.filename != 'xl/styles.xml':
                    data = zip_read.read(item.filename)
                    zip_write.writestr(item, data)
                else:
                    zip_write.writestr('xl/styles.xml', minimal_styles)
    
    return output_file


def process_laws(raw_dir, clean_dir):
    """Process laws: extract year, fix corruption, save as law_YYYY.xlsx."""
    raw_path = Path(raw_dir)
    clean_path = Path(clean_dir)
    clean_path.mkdir(parents=True, exist_ok=True)
    
    for xlsx_file in raw_path.glob("*.xlsx"):
        match = re.search(r'\d{4}', xlsx_file.name)
        if not match:
            continue
        
        year = match.group(0)
        output_path = clean_path / f"law_{year}.xlsx"
        
        try:
            fix_corrupt_xlsx(xlsx_file, output_path)
            print(f"✓ {xlsx_file.name} → law_{year}.xlsx")
        except Exception as e:
            print(f"✗ {xlsx_file.name}: {e}")


def process_reports(raw_dir, clean_dir):
    """Process reports: extract YYYY-MM, fix .xlsx or copy .xls."""
    raw_path = Path(raw_dir)
    clean_path = Path(clean_dir)
    clean_path.mkdir(parents=True, exist_ok=True)
    
    for file in list(raw_path.glob("*.xls")) + list(raw_path.glob("*.xlsx")):
        match = re.search(r'(\d{4})-(\d{2})', file.name)
        if not match:
            continue
        
        year, month = match.groups()
        output_filename = f"report_{year}_{month}{file.suffix}"
        output_path = clean_path / output_filename
        
        try:
            if file.suffix == '.xlsx':
                fix_corrupt_xlsx(file, output_path)
            else:
                shutil.copy2(file, output_path)
            print(f"✓ {file.name} → {output_filename}")
        except Exception as e:
            print(f"✗ {file.name}: {e}")


def main():
    base_dir = Path("src/data/import_files")
    
    print("Processing laws...")
    process_laws(base_dir / "raw/laws", base_dir / "clean/laws")
    
    print("\nProcessing reports...")
    process_reports(base_dir / "raw/reports", base_dir / "clean/reports")
    
    print("\nDone.")


if __name__ == "__main__":
    main()