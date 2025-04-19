import pandas as pd

def count_excel_rows(excel_file: str) -> None:
    """Count rows in all sheets of an Excel file."""
    print(f"\nCounting rows in {excel_file}...")
    
    # Read all sheets
    xlsx = pd.ExcelFile(excel_file)
    total_rows = 0
    
    print("\nRows per sheet (excluding header row):")
    print("-" * 40)
    
    for sheet_name in xlsx.sheet_names:
        df = pd.read_excel(excel_file, sheet_name=sheet_name)
        rows = len(df)
        total_rows = rows if sheet_name == 'All Comments' else total_rows
        print(f"{sheet_name}: {rows:,} rows")
    
    print("-" * 40)
    print(f"Total rows in 'All Comments' sheet: {total_rows:,}")

if __name__ == "__main__":
    excel_file = "/Users/stevewitmer/Desktop/Youtube/youtube_downloader/For Sarah/dougweaver_comments/all_comments.xlsx"
    count_excel_rows(excel_file) 