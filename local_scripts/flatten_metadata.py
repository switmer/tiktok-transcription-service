import json
import csv
import os
from typing import Dict, List
from glob import glob

def flatten_metadata(json_data: Dict) -> Dict:
    """Extract relevant fields from the metadata JSON."""
    return {
        'video_id': json_data['id'],
        'title': json_data['title'],
        'description': json_data['description'],
        'channel': json_data['channel'],
        'uploader': json_data['uploader'],
        'duration': json_data['duration'],
        'duration_string': json_data['duration_string'],
        'upload_date': json_data['upload_date'],
        'view_count': json_data['view_count'],
        'like_count': json_data['like_count'],
        'repost_count': json_data['repost_count'],
        'comment_count': json_data['comment_count'],
        'webpage_url': json_data['webpage_url']
    }

def process_metadata_files(base_dir: str) -> None:
    """Process all metadata JSON files and create a flattened CSV."""
    # Find all metadata JSON files
    pattern = os.path.join(base_dir, "**/*_video_metadata.json")
    json_files = glob(pattern, recursive=True)
    
    if not json_files:
        print("No metadata JSON files found!")
        return
    
    # Sort files by video ID for consistent processing
    json_files.sort()
    
    print(f"\nFound {len(json_files)} metadata files:")
    print("-" * 80)
    for file in json_files:
        print(f"Found: {file}")
    print("-" * 80)
    
    flattened_data = []
    processed_ids = set()
    
    # Process each JSON file
    for json_file in json_files:
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                video_id = data['id']
                if video_id in processed_ids:
                    print(f"Warning: Duplicate video ID found: {video_id}")
                processed_ids.add(video_id)
                flattened = flatten_metadata(data)
                flattened_data.append(flattened)
                print(f"Processed video ID: {video_id} - {os.path.basename(json_file)}")
        except Exception as e:
            print(f"Error processing {json_file}: {str(e)}")
    
    # Write to CSV
    output_file = os.path.join(base_dir, "video_metadata.csv")
    fieldnames = list(flattened_data[0].keys())
    
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(flattened_data)
    
    print(f"\nCreated flattened metadata file: {output_file}")
    print(f"Total videos processed: {len(flattened_data)}")
    
    # Print all video IDs in order
    print("\nProcessed Video IDs:")
    for data in sorted(flattened_data, key=lambda x: x['video_id']):
        print(f"{data['video_id']}: {data['title'][:50]}...")

if __name__ == "__main__":
    base_dir = "/Users/stevewitmer/Desktop/Youtube/youtube_downloader/For Sarah"
    process_metadata_files(base_dir) 