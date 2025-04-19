import json
import csv
import os
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

def process_file(input_file: str) -> None:
    """Process a single JSON file and create corresponding CSV."""
    try:
        # Create output filename by replacing .json with .csv
        output_file = input_file.rsplit('.', 1)[0] + '.csv'
        
        with open(input_file, 'r', encoding='utf-8') as f:
            comments = json.load(f)
        
        process_comments(comments, output_file)
        print(f"Successfully converted {input_file} to {output_file}")
        
    except FileNotFoundError:
        print(f"Error: Could not find input file {input_file}")
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON format in {input_file}")
    except Exception as e:
        print(f"Error: An unexpected error occurred with {input_file}: {str(e)}")

def main():
    # List of files to process
    files = [
        "dougweaver_comments/comments_7415285469769895210.json",
        "dougweaver_comments/comments_7415779028139019566.json",
        "dougweaver_comments/comments_7416381536112610603.json",
        "dougweaver_comments/comments_7416481991069240622.json",
        "dougweaver_comments/comments_7417984018265820459.json",
        "dougweaver_comments/comments_7418627229191638315.json",
        "dougweaver_comments/comments_7418982269664234794.json",
        "dougweaver_comments/comments_7421004532341247278.json",
        "dougweaver_comments/comments_7421221846776925483.json",
        "dougweaver_comments/comments_7421707587009170730.json",
        "dougweaver_comments/comments_7423434235672874283.json",
        "dougweaver_comments/comments_7436579380832292138.json",
        "dougweaver_comments/comments_7437317085937831214.json",
        "dougweaver_comments/comments_7437963742912122158.json",
        "dougweaver_comments/comments_7439808937446133035.json",
        "dougweaver_comments/comments_7440984230907137323.json",
        "dougweaver_comments/comments_7442033581901466926.json",
        "dougweaver_comments/comments_7442513727909350698.json",
        "dougweaver_comments/comments_7458078908940946719.json"
    ]
    
    print(f"Starting to process {len(files)} files...")
    
    for file in files:
        process_file(file)
    
    print("Processing complete!")

if __name__ == "__main__":
    main() 