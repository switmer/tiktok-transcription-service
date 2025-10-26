import csv
import os
from typing import Dict, List
import argparse
import json

# Video ID to title mapping
VIDEO_DETAILS = {
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

def extract_video_id(filename: str) -> str:
    """Extract video ID from filename."""
    base = os.path.basename(filename)
    return base.split('_')[1].split('.')[0]

def combine_csv_files(csv_files: List[str], output_file: str, base_dir: str) -> None:
    """Combine multiple CSV files into one, adding video details to each row."""
    
    # Define the fieldnames for our combined CSV
    fieldnames = ['video_id', 'video_title', 'level', 'username', 'text', 'timestamp', 'likes']
    
    with open(output_file, 'w', newline='', encoding='utf-8') as outfile:
        writer = csv.DictWriter(outfile, fieldnames=fieldnames)
        writer.writeheader()
        
        # Process each CSV file
        for file in csv_files:
            video_id = extract_video_id(file)
            video_title = VIDEO_DETAILS.get(video_id)

            if video_title is None:
                # Try metadata JSON in standard directory structure
                meta_path = os.path.join(
                    os.path.dirname(base_dir),
                    f"TikTok_@dougweaverart_{video_id}",
                    "video_metadata.json",
                )
                if os.path.exists(meta_path):
                    try:
                        with open(meta_path, "r", encoding="utf-8") as mf:
                            meta = json.load(mf)
                            video_title = meta.get("title") or meta.get("fulltitle")
                    except Exception:
                        pass
            if not video_title:
                video_title = "Unknown Title"
            
            try:
                with open(file, 'r', encoding='utf-8') as infile:
                    reader = csv.DictReader(infile)
                    
                    for row in reader:
                        # Add video details to each row
                        new_row = {
                            'video_id': video_id,
                            'video_title': video_title,
                            'level': row['level'],
                            'username': row['username'],
                            'text': row['text'],
                            'timestamp': row['timestamp'],
                            'likes': row['likes']
                        }
                        writer.writerow(new_row)
                        
                print(f"Processed {file}")
            except Exception as e:
                print(f"Error processing {file}: {str(e)}")

def main():
    parser = argparse.ArgumentParser(description="Combine TikTok comment CSVs with video details")
    parser.add_argument("--dir", default="outputs/For Sarah/dougweaver_comments", help="Directory containing comments_*.csv files")
    args = parser.parse_args()

    base_dir = args.dir
    csv_files = [
        os.path.join(base_dir, f) for f in os.listdir(base_dir)
        if f.startswith("comments_") and f.endswith(".csv") and f != "all_comments_combined.csv"
    ]

    output_file = os.path.join(base_dir, "all_comments_combined.csv")
    print(f"Starting to combine {len(csv_files)} files…")
    combine_csv_files(sorted(csv_files), output_file, base_dir)
    print(f"Successfully created combined file: {output_file}")

if __name__ == "__main__":
    main() 