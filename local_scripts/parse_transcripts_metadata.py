import os
import json
import csv
import logging
from pathlib import Path  # Corrected from Pathx to Path

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Path to the tiktoks folder
tiktoks_folder = Path('/Users/stevewitmer/Desktop/Youtube/youtube_downloader/outputs/For Sarah')

# Path to the enriched_user_data_tiktok.json file
enriched_data_file = Path('/Users/stevewitmer/Desktop/Youtube/youtube_downloader/outputs/enriched_user_data_tiktok.json')

# Prepare the CSV file
csv_file = Path('/Users/stevewitmer/Desktop/Youtube/youtube_downloader/outputs/For Sarah/video_metadata.csv')
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
            tiktok_data['Transcript'] = txt_file.read_text(encoding='utf-8').strip()
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
    if enriched_data_file.exists():
    try:
        with enriched_data_file.open('r', encoding='utf-8') as f:
            data = json.load(f)
            for item in data:
                if 'enriched_data' in item:
                    video_id = item['Content'].split('/')[-1].rstrip('/')
                    enriched_data[video_id] = item['enriched_data']
    except Exception as e:
        logging.error(f"Error loading enriched data: {str(e)}")
    else:
        logging.info("Enriched data file not found. Proceeding without enriched statistics.")

    with csv_file.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=csv_headers)
        writer.writeheader()

        # Collect rows for later sorting and txt output
        rows_for_csv = []
        rows_for_txt = []

        # Iterate through each folder in the tiktoks directory
        for folder in tiktoks_folder.iterdir():
            # Skip comment export folder
            if folder.name == 'dougweaver_comments':
                continue
            if folder.is_dir():
                try:
                    tiktok_data = process_tiktok_folder(folder, enriched_data)
                    rows_for_csv.append(tiktok_data)
                    rows_for_txt.append(tiktok_data)
                    logging.info(f"Processed TikTok: {folder.name[:50]}...")  # Truncate long folder names in logs
                except Exception as e:
                    logging.error(f"Error processing folder {folder.name[:50]}...: {str(e)}")

        # ---- write sorted CSV ---- #
        def upload_date_key(row):
            try:
                return int(row.get('Upload Date', 0))
            except Exception:
                return 0

        for row in sorted(rows_for_csv, key=upload_date_key):
            writer.writerow(row)

    logging.info(f"Data has been written to {csv_file} (sorted by Upload Date)")

    # ---------- Write Markdown table ---------- #
    txt_file = csv_file.with_suffix('.txt')
    headers_txt = [
        'Video Id', 'Title', 'Description', 'Channel', 'Uploader', 'Duration',
        'Duration String', 'Upload Date', 'View Count', 'Like Count',
        'Repost Count', 'Comment Count', 'Webpage Url'
    ]

    def format_duration_str(seconds):
        try:
            seconds = int(float(seconds))
        except Exception:
            return ''
        mins, secs = divmod(seconds, 60)
        return f"{mins}:{secs:02d}"

    # Build table rows
    table_lines = []
    for row in rows_for_txt:
        duration_str = format_duration_str(row.get('Duration', ''))
        table_lines.append([
            row.get('ID', ''),
            row.get('Title', '')[:60],  # truncate long to keep reasonable width
            row.get('Description', '')[:60],
            row.get('Channel', ''),
            row.get('Uploader', ''),
            row.get('Duration', ''),
            duration_str,
            row.get('Upload Date', ''),
            row.get('View Count', ''),
            row.get('Like Count', ''),
            row.get('Share Count', ''),
            row.get('Comment Count', ''),
            f"https://www.tiktok.com/@{row.get('Uploader','')}/video/{row.get('ID','')}"
        ])

    # Calculate summary statistics
    def to_int(val):
        try:
            return int(str(val).replace(',', '').replace('K','000').replace('M','000000'))
        except Exception:
            return 0

    total_views = sum(to_int(r[8]) for r in table_lines)
    total_likes = sum(to_int(r[9]) for r in table_lines)
    total_reposts = sum(to_int(r[10]) for r in table_lines)
    total_comments = sum(to_int(r[11]) for r in table_lines)
    total_videos = len(table_lines)
    engagement_rate = (total_likes + total_comments + total_reposts) / total_views * 100 if total_views else 0

    with txt_file.open('w', encoding='utf-8') as tf:
        tf.write('# TikTok Video Metadata\n\n')
        # Header row
        header_line = '| ' + ' | '.join(headers_txt) + ' |\n'
        separator_line = '|'+ '|'.join(['-'*len(h.center(3)) for h in headers_txt]) + '|\n'
        tf.write(header_line)
        tf.write(separator_line)
        for r in table_lines:
            tf.write('| ' + ' | '.join(str(cell) for cell in r) + ' |\n')

        # Summary
        tf.write('\n## Summary\n')
        tf.write(f'- Total Videos: {total_videos}\n')
        tf.write(f'- Total Views: {total_views:,}\n')
        tf.write(f'- Total Likes: {total_likes:,}\n')
        tf.write(f'- Total Comments: {total_comments:,}\n')
        tf.write(f'- Total Reposts: {total_reposts:,}\n')
        tf.write(f'- Average Engagement Rate: {engagement_rate:.1f}%\n')

    logging.info(f"Markdown summary written to {txt_file}")

if __name__ == "__main__":
    main()