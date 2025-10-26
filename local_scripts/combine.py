import json
import re

def load_json(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return json.load(file)

def save_json(data, file_path):
    with open(file_path, 'w', encoding='utf-8') as file:
        json.dump(data, file, indent=2, ensure_ascii=False)

def extract_video_id(content):
    # Match the last sequence of digits in the URL
    match = re.search(r'/(\d+)/?(?:\?|$)', content)
    return match.group(1) if match else None

def enrich_user_data(user_data, connected_data):
    video_id_to_data = {item['id']: item for item in connected_data}
    print(f"Loaded {len(video_id_to_data)} videos from connected_tiktok_data.json")
    
    enriched_data = []
    enriched_count = 0
    for message in user_data:
        enriched_message = message.copy()
        
        content = message['Content']
        video_id = extract_video_id(content)
        
        if video_id and video_id in video_id_to_data:
            video_data = video_id_to_data[video_id]
            enriched_message['enriched_data'] = {
                'author': video_data.get('author'),
                'nickname': video_data.get('nickname'),
                'desc': video_data.get('desc'),
                'createTime': video_data.get('createTime'),
                'stats': video_data.get('stats'),
                'challenges': video_data.get('challenges'),
                'music': {
                    'title': video_data.get('music', {}).get('title'),
                    'authorName': video_data.get('music', {}).get('authorName'),
                    'duration': video_data.get('music', {}).get('duration')
                },
                'video': {
                    'duration': video_data.get('video', {}).get('duration'),
                    'cover': video_data.get('video', {}).get('cover')
                }
            }
            enriched_count += 1
        elif 'tiktok.com' in content:
            print(f"Found TikTok link but no matching data: {content}")
        
        enriched_data.append(enriched_message)
    
    print(f"Enriched {enriched_count} messages out of {len(user_data)} total messages")
    return enriched_data

# Load the data
user_data = load_json('/Users/stevewitmer/Desktop/Youtube/youtube_downloader/user_data_tiktok.json')
connected_data = load_json('connected_tiktok_data.json')

print(f"Loaded {len(user_data)} messages from user_data_tiktok.json")
print(f"Loaded {len(connected_data)} items from connected_tiktok_data.json")

# Enrich the user data
enriched_user_data = enrich_user_data(user_data, connected_data)

# Save the enriched data
save_json(enriched_user_data, 'enriched_user_data_tiktok.json')

print("Enriched data saved to enriched_user_data_tiktok.json")