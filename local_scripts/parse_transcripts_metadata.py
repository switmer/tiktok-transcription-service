import os
import json
import csv
import logging
from pathlib import Path  # Corrected from Pathx to Path

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Path to the tiktoks folder
tiktoks_folder = Path('/Users/stevewitmer/Desktop/Youtube/youtube_downloader/tiktoks')

# Path to the enriched_user_data_tiktok.json file
enriched_data_file = Path('/Users/stevewitmer/Desktop/Youtube/youtube_downloader/enriched_user_data_tiktok.json')

# Prepare the CSV file
csv_file = Path('tiktok_data.csv')
csv_headers = ['ID', 'Title', 'Description', 'Duration', 'Upload Date', 'View Count', 'Like Count', 
               'Comment Count', 'Share Count', 'Artist', 'Channel', 'Uploader', 'Transcript']

def process_tiktok_folder(folder_path, enriched_data):
    tiktok_data = {}
    
    # Use folder name as initial title
    tiktok_data['Title'] = folder_path.name[:250]  # Increased character limit
    
    # Process the .json file
    json_file = next(folder_path.glob('*.json'), None)
    if json_file and json_file.is_file():
        try:
            with json_file.open('r', encoding='utf-8') as f:
                json_data = json.load(f)
                tiktok_data.update({
                    'ID': json_data.get('id', ''),
                    'Title': json_data.get('title', tiktok_data['Title'])[:250],  # Use JSON title if available, else keep folder name
                    'Description': json_data.get('description', '')[:250],  # Increased character limit
                    'Duration': json_data.get('duration', ''),
                    'Upload Date': json_data.get('upload_date', ''),
                    'View Count': json_data.get('view_count', ''),
                    'Like Count': json_data.get('like_count', ''),
                    'Comment Count': json_data.get('comment_count', ''),
                    'Share Count': json_data.get('repost_count', ''),
                    'Artist': ', '.join(json_data.get('artists', []))[:250],
                    'Channel': json_data.get('channel', '')[:250],
                    'Uploader': json_data.get('uploader', '')[:250]
                })
        except json.JSONDecodeError:
            logging.error(f"Invalid JSON in file: {json_file}")
        except Exception as e:
            logging.error(f"Error processing JSON file {json_file}: {str(e)}")

    # Process the .txt file (transcript)
    txt_file = next(folder_path.glob('*_transcript.txt'), None)  # Look specifically for _transcript.txt files
    if txt_file and txt_file.is_file():
        try:
            tiktok_data['Transcript'] = txt_file.read_text(encoding='utf-8').strip()[:1000]  # Increased character limit
        except Exception as e:
            logging.error(f"Error reading transcript file {txt_file}: {str(e)}")

    # Check if there's enriched data for this TikTok
    video_id = tiktok_data.get('ID') or folder_path.name
    if video_id in enriched_data:
        enriched = enriched_data[video_id]
        tiktok_data['View Count'] = enriched.get('stats', {}).get('playCount', tiktok_data['View Count'])
        tiktok_data['Like Count'] = enriched.get('stats', {}).get('diggCount', tiktok_data['Like Count'])
        tiktok_data['Comment Count'] = enriched.get('stats', {}).get('commentCount', tiktok_data['Comment Count'])
        tiktok_data['Share Count'] = enriched.get('stats', {}).get('shareCount', tiktok_data['Share Count'])

    return tiktok_data

def main():
    # Load the enriched data
    enriched_data = {}
    try:
        with enriched_data_file.open('r', encoding='utf-8') as f:
            data = json.load(f)
            for item in data:
                if 'enriched_data' in item:
                    video_id = item['Content'].split('/')[-1].rstrip('/')
                    enriched_data[video_id] = item['enriched_data']
    except Exception as e:
        logging.error(f"Error loading enriched data: {str(e)}")
        return

    with csv_file.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=csv_headers)
        writer.writeheader()

        # Iterate through each folder in the tiktoks directory
        for folder in tiktoks_folder.iterdir():
            if folder.is_dir():
                try:
                    tiktok_data = process_tiktok_folder(folder, enriched_data)
                    writer.writerow(tiktok_data)
                    logging.info(f"Processed TikTok: {folder.name[:50]}...")  # Truncate long folder names in logs
                except Exception as e:
                    logging.error(f"Error processing folder {folder.name[:50]}...: {str(e)}")

    logging.info(f"Data has been written to {csv_file}")

if __name__ == "__main__":
    main()