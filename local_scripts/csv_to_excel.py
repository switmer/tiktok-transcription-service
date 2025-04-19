import pandas as pd
import os
from openpyxl.utils import get_column_letter

def adjust_column_widths(worksheet, df):
    """Helper function to adjust column widths based on content."""
    for idx, column in enumerate(df.columns, 1):
        column_width = max(
            df[column].astype(str).str.len().max(),
            len(str(column))
        )
        adjusted_width = min(column_width + 2, 100)  # Cap width at 100
        worksheet.column_dimensions[get_column_letter(idx)].width = adjusted_width

def get_video_title(video_id):
    """Get video title from the video ID."""
    titles = {
        "7415285469769895210": "Just think about the great teachers who would love",
        "7415779028139019566": "The whole point of these videos is that this school",
        "7416381536112610603": "I think it's long past time for this school district",
        "7416481991069240622": "It is vitally important that as students that you",
        "7417984018265820459": "We're done sweeping it under the rug. #sthelens #j",
        "7418627229191638315": "@dougweaverart I'm interested to know how they will",
        "7418982269664234794": "I'm super proud of the students who are doing everything",
        "7421004532341247278": "If you want context, I can give you context. #memo",
        "7421221846776925483": "They have avoided accountability and oversight for",
        "7421707587009170730": "For context @dougweaverart Clearly talking about",
        "7423434235672874283": "I am so proud of everyone who has found the courage",
        "7436579380832292138": "This has been going on for far too long. Its about",
        "7437317085937831214": "@dougweaverart I have a feeling this is just the beginning",
        "7437963742912122158": "Replying to @findmeinthewoodsordont We have a long",
        "7439808937446133035": "I have been in advocacy groups for a long time and",
        "7440984230907137323": "I am so proud of St. Helens for standing up and standing",
        "7442033581901466926": "You can view my video about her letter here@dougweaver",
        "7442513727909350698": "This was a very unexpected but important moment for",
        "7458078908940946719": "There should never have been 12 victims, and the accountability"
    }
    return titles.get(video_id, "Unknown Title")

def combine_csv_files():
    """Combine all individual CSV files into one."""
    csv_files = [
        "dougweaver_comments/comments_7415285469769895210.csv",
        "dougweaver_comments/comments_7415779028139019566.csv",
        "dougweaver_comments/comments_7416381536112610603.csv",
        "dougweaver_comments/comments_7416481991069240622.csv",
        "dougweaver_comments/comments_7417984018265820459.csv",
        "dougweaver_comments/comments_7418627229191638315.csv",
        "dougweaver_comments/comments_7418982269664234794.csv",
        "dougweaver_comments/comments_7421004532341247278.csv",
        "dougweaver_comments/comments_7421221846776925483.csv",
        "dougweaver_comments/comments_7421707587009170730.csv",
        "dougweaver_comments/comments_7423434235672874283.csv",  # Added missing video
        "dougweaver_comments/comments_7436579380832292138.csv",
        "dougweaver_comments/comments_7437317085937831214.csv",
        "dougweaver_comments/comments_7437963742912122158.csv",
        "dougweaver_comments/comments_7439808937446133035.csv",
        "dougweaver_comments/comments_7440984230907137323.csv",
        "dougweaver_comments/comments_7442033581901466926.csv",
        "dougweaver_comments/comments_7442513727909350698.csv",
        "dougweaver_comments/comments_7458078908940946719.csv"
    ]
    
    print("Combining CSV files...")
    dfs = []
    for file in csv_files:
        if os.path.exists(file):
            # Extract video ID from filename
            video_id = os.path.basename(file).split('_')[1].split('.')[0]
            video_title = get_video_title(video_id)
            
            # Read CSV and add video information
            df = pd.read_csv(file)
            df['video_id'] = video_id
            df['video_title'] = video_title
            
            # Reorder columns to put video info first
            cols = ['video_id', 'video_title'] + [col for col in df.columns if col not in ['video_id', 'video_title']]
            df = df[cols]
            
            dfs.append(df)
            print(f"Processed {video_id} - {len(df)} comments")
        else:
            print(f"Warning: File not found - {file}")
    
    combined_df = pd.concat(dfs, ignore_index=True)
    output_csv = "dougweaver_comments/all_comments_combined.csv"
    combined_df.to_csv(output_csv, index=False)
    print(f"\nCreated combined CSV file with {len(combined_df)} comments")
    return output_csv

def csv_to_excel_by_video(input_csv: str, output_xlsx: str) -> None:
    """Convert combined CSV to Excel with separate sheets for each video."""
    
    print("Reading combined CSV file...")
    # Read the CSV file
    df = pd.read_csv(input_csv)
    
    # Debug information
    print("\nAll unique video IDs and their titles:")
    for video_id in sorted(df['video_id'].unique()):
        title = df[df['video_id'] == video_id]['video_title'].iloc[0]
        print(f"ID: {video_id} - Title: {title}")
    print(f"\nFound {len(df)} total comments across {len(df['video_id'].unique())} videos")
    
    # Create Excel writer object
    with pd.ExcelWriter(output_xlsx, engine='openpyxl') as writer:
        # Create a summary sheet with all data
        print("\nCreating 'All Comments' sheet...")
        df.to_excel(writer, sheet_name='All Comments', index=False)
        adjust_column_widths(writer.sheets['All Comments'], df)
        
        # Group by video_id and create separate sheets
        for video_id in sorted(df['video_id'].unique()):
            video_df = df[df['video_id'] == video_id]
            video_title = video_df['video_title'].iloc[0]
            
            # Create a valid sheet name (Excel has a 31 character limit)
            sheet_name = f"{str(video_id)[-4:]} - {video_title[:25]}"
            print(f"Creating sheet for video: {video_id} ({len(video_df)} comments)")
            
            # Remove video_id and video_title columns from individual sheets
            sheet_df = video_df.drop(['video_id', 'video_title'], axis=1)
            sheet_df.to_excel(writer, sheet_name=sheet_name, index=False)
            adjust_column_widths(writer.sheets[sheet_name], sheet_df)

def main():
    try:
        # First combine all CSV files
        input_csv = combine_csv_files()
        output_xlsx = "dougweaver_comments/all_comments.xlsx"
        
        # Then convert to Excel
        csv_to_excel_by_video(input_csv, output_xlsx)
        print(f"\nSuccessfully created Excel file: {output_xlsx}")
        print("Each video's comments are in a separate sheet, with an 'All Comments' summary sheet.")
        
    except Exception as e:
        print(f"Error: An unexpected error occurred: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main() 