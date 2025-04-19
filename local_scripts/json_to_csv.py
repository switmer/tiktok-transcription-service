import json
import csv
import sys
from typing import List, Dict

def process_comments(comments: List[Dict]) -> List[Dict]:
    """Process comments and their replies, adding level indicators."""
    processed = []
    
    for comment in comments:
        # Add main comment
        comment_data = {
            'level': '',  # Main comment has no indent
            'username': comment['username'],
            'text': comment['text'].replace('\n', ' '),  # Remove newlines from text
            'timestamp': comment['timestamp'],
            'likes': comment['likes']
        }
        processed.append(comment_data)
        
        # Add replies if any
        if 'replies' in comment and comment['replies']:
            for reply in comment['replies']:
                reply_data = {
                    'level': '└→',  # Add indent for replies
                    'username': reply['username'],
                    'text': reply['text'].replace('\n', ' '),  # Remove newlines from text
                    'timestamp': reply['timestamp'],
                    'likes': reply['likes']
                }
                processed.append(reply_data)
    
    return processed

def json_to_csv(json_file: str, csv_file: str) -> None:
    """Convert JSON comments file to CSV format."""
    try:
        # Read JSON file
        with open(json_file, 'r', encoding='utf-8') as f:
            comments = json.load(f)
        
        if not comments:
            print(f"Warning: No comments found in {json_file}")
            # Create empty CSV with headers
            with open(csv_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=['level', 'username', 'text', 'timestamp', 'likes'])
                writer.writeheader()
            return
        
        # Process comments
        processed_comments = process_comments(comments)
        
        # Write to CSV
        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['level', 'username', 'text', 'timestamp', 'likes'])
            writer.writeheader()
            writer.writerows(processed_comments)
        
        print(f"Successfully converted {len(processed_comments)} comments to CSV")
        
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)

def main():
    if len(sys.argv) != 3:
        print("Usage: python json_to_csv.py <input_json> <output_csv>")
        sys.exit(1)
    
    json_file = sys.argv[1]
    csv_file = sys.argv[2]
    json_to_csv(json_file, csv_file)

if __name__ == "__main__":
    main() 