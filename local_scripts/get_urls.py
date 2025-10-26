import json
import os

def parse_tiktok_json(tiktok_json_path, tiktok2_json_path, extracted_json_path):
    with open(tiktok_json_path, 'r') as f:
        tiktok_data = json.load(f)
    
    with open(tiktok2_json_path, 'r') as f:
        tiktok2_data = json.load(f)

    with open(extracted_json_path, 'r') as f:
        extracted_data = json.load(f)

    # Create a dictionary from extracted_data for easy lookup
    extracted_dict = {item['id']: item for item in extracted_data}

    connected_data = []

    for item in tiktok_data:
        if 'props' in item and 'children' in item['props']:
            for child in item['props']['children']:
                if isinstance(child, dict) and 'props' in child and 'message' in child['props']:
                    message = child['props']['message']
                    if 'content' in message:
                        try:
                            tiktok1_content = json.loads(message['content'])
                            item_id = tiktok1_content.get('itemId')
                            
                            if item_id in tiktok2_data:
                                tiktok2_item = tiktok2_data[item_id]
                                extracted_item = extracted_dict.get(item_id, {})
                                
                                connected_item = {
                                    'id': item_id,
                                    'author': tiktok2_item.get('author', ''),
                                    'nickname': tiktok2_item.get('nickname', ''),
                                    'authorId': tiktok2_item.get('authorId', ''),
                                    'authorSecId': tiktok2_item.get('authorSecId', ''),
                                    'desc': tiktok2_item.get('desc', ''),
                                    'createTime': tiktok2_item.get('createTime', ''),
                                    'url': extracted_item.get('url') or f"https://www.tiktok.com/@{tiktok2_item.get('author', '')}/video/{item_id}",
                                    'digged': tiktok2_item.get('digged', False),
                                    'stats': tiktok2_item.get('stats', {}),
                                    'music': {
                                        'id': tiktok2_item.get('music', {}).get('id', ''),
                                        'title': tiktok2_item.get('music', {}).get('title', ''),
                                        'authorName': tiktok2_item.get('music', {}).get('authorName', ''),
                                        'duration': tiktok2_item.get('music', {}).get('duration', 0),
                                    },
                                    'video': {
                                        'duration': tiktok2_item.get('video', {}).get('duration', 0),
                                        'ratio': tiktok2_item.get('video', {}).get('ratio', ''),
                                        'cover': tiktok2_item.get('video', {}).get('cover', ''),
                                        'playAddr': tiktok2_item.get('video', {}).get('playAddr', ''),
                                        'downloadAddr': tiktok2_item.get('video', {}).get('downloadAddr', ''),
                                    },
                                    'challenges': [challenge.get('title', '') for challenge in tiktok2_item.get('challenges', [])],
                                    'tiktok1_data': {
                                        'createdAt': message.get('createdAt', ''),
                                        'sender': message.get('sender', ''),
                                        'conversationId': message.get('conversationId', ''),
                                    }
                                }
                                
                                connected_data.append(connected_item)
                        except json.JSONDecodeError:
                            print(f"Failed to parse content: {message['content'][:100]}...")  # Print first 100 characters of problematic content

    return connected_data

# Get the current script's directory
script_dir = os.path.dirname(os.path.abspath(__file__))

# Construct the full paths to the JSON files
tiktok_json_path = os.path.join(script_dir, 'tiktok.json')
tiktok2_json_path = os.path.join(script_dir, 'tiktok2.json')
extracted_json_path = os.path.join(script_dir, 'extracted_tiktok_data.json')

# Usage
connected_data = parse_tiktok_json(tiktok_json_path, tiktok2_json_path, extracted_json_path)

# Print a sample output (first item)
if connected_data:
    print(json.dumps(connected_data[0], indent=2))
    print(f"\nTotal connected items: {len(connected_data)}")
else:
    print("No connected data found.")

# Optionally, save the connected data to a new JSON file
output_file_path = os.path.join(script_dir, 'connected_tiktok_data.json')
with open(output_file_path, 'w') as outfile:
    json.dump(connected_data, outfile, indent=2)

print(f"\nConnected data has been saved to {output_file_path}")