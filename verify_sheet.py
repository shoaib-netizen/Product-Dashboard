"""
Quick verification script to check Google Sheet structure and data.
"""
from src.services import GoogleSheetsService

def main():
    print("Connecting to Google Sheet...")
    sheets = GoogleSheetsService()
    
    print(f"\n✓ Connected to sheet: {sheets.sheet.title}")
    print(f"✓ Spreadsheet: {sheets.sheet.spreadsheet.title}")
    
    # Check headers
    headers = sheets.sheet.row_values(1)
    print(f"\nHeaders ({len(headers)} columns):")
    for i, h in enumerate(headers, 1):
        print(f"  {i}. {h}")
    
    # Get last few rows
    print("\nLast 3 rows of data:")
    all_data = sheets.sheet.get_all_values()
    
    if len(all_data) > 1:
        for row in all_data[-3:]:
            print(f"\nRow {all_data.index(row) + 1}:")
            for i, (header, value) in enumerate(zip(headers, row), 1):
                if value:  # Only show non-empty values
                    print(f"  {header}: {value}")
    
    print(f"\nTotal rows (including header): {len(all_data)}")

if __name__ == "__main__":
    main()
