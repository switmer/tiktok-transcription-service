import json
import csv
import sys
from typing import List, Dict, Any

def process_comments(comments: List[Dict[Any, Any]], output_file: str) -> None:
    """Process comments and write to CSV with nested reply visualization."""
    
    with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
        fieldnames = ['level', 'username', 'text', 'timestamp', 'likes']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        
        for comment in comments:
            # Write main comment
            writer.writerow({
                'level': '',  # No indent for main comments
                'username': comment['username'],
                'text': comment['text'],
                'timestamp': comment.get('timestamp', ''),
                'likes': comment.get('likes', '0')
            })
            
            # Process replies if they exist
            if 'replies' in comment and comment['replies']:
                for reply in comment['replies']:
                    writer.writerow({
                        'level': '└→',  # Visual indicator for replies
                        'username': reply['username'],
                        'text': reply['text'],
                        'timestamp': reply.get('timestamp', ''),
                        'likes': reply.get('likes', '0')
                    })

def main():
    if len(sys.argv) != 3:
        print("Usage: python json_to_csv_converter.py <input_json_file> <output_csv_file>")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2]
    
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            comments = json.load(f)
        
        process_comments(comments, output_file)
        print(f"Successfully converted {input_file} to {output_file}")
        
    except FileNotFoundError:
        print(f"Error: Could not find input file {input_file}")
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON format in {input_file}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: An unexpected error occurred: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main() 