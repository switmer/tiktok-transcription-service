import yt_dlp
import os
import json
import random
import logging
from datetime import datetime
import re
import time

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class MyLogger(object):
    def debug(self, msg):
        if msg.startswith('[debug] '):
            pass
        else:
            self.info(msg)

    def info(self, msg):
        logging.info(msg)

    def warning(self, msg):
        logging.warning(f"Warning: {msg}")

    def error(self, msg):
        logging.error(f"Error: {msg}")

def my_hook(d):
    if d['status'] == 'downloading':
        print(f"\rDownloading: {d['filename']} | {d.get('_percent_str', 'N/A')} of {d.get('_total_bytes_str', 'N/A')} at {d.get('_speed_str', 'N/A')}", end='', flush=True)
    elif d['status'] == 'finished':
        print(f"\nFinished downloading {d['filename']}")

def sanitize_filename(filename):
    # Remove invalid characters
    sanitized = re.sub(r'[\\/*?:"<>|]', "", filename)
    # Replace spaces with underscores
    sanitized = sanitized.replace(' ', '_')
    # Take only the first 50 characters to avoid "filename too long" error
    sanitized = sanitized[:50]
    return sanitized

def create_job_folder(title, base_dir=None):
    folder_name = sanitize_filename(title)
    if base_dir:
        folder_path = os.path.join(base_dir, folder_name)
    else:
        folder_path = folder_name
        
    if os.path.exists(folder_path):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder_path = f"{folder_path}_{timestamp}"
    os.makedirs(folder_path, exist_ok=True)
    return folder_path

def download_tiktok(url, output_dir=None):
    """Download TikTok video and extract audio"""
    # Set user agents to rotate
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36',
        'Mozilla/5.0 (iPhone; CPU iPhone OS 12_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148',
        'Mozilla/5.0 (iPad; CPU OS 12_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    ]
    
    user_agent = random.choice(user_agents)
    
    try:
        # Add a small delay before starting
        time.sleep(random.uniform(1, 3))
        
        # --- Initial Info Extraction (Get Title/ID if possible) ---
        video_id = None
        title = None
        username = "unknown"
        try:
            with yt_dlp.YoutubeDL({'quiet': True, 'logger': MyLogger(), 'skip_download': True}) as ydl_info:
                info = ydl_info.extract_info(url, download=False)
                video_id = info.get('id')
                title = info.get('title') or f"TikTok_{info.get('uploader_id', 'unknown')}_{video_id}"
                username = info.get('uploader_id', 'unknown')
        except Exception as info_e:
            logging.warning(f"Could not extract initial info from URL {url}: {info_e}")
            # Fallback to regex if info extraction fails (less reliable for short URLs)
            video_id_match = re.search(r'(?:video|item)/(\d+)', url)
            if video_id_match:
                video_id = video_id_match.group(1)
                url_parts = url.split('/')
                username = url_parts[-3] if '@' in url_parts[-3] and len(url_parts) >= 3 else "unknown"
            
            if not title:
                title = f"TikTok_{username}_{video_id if video_id else 'unknown_id'}"

        if not video_id:
             logging.warning(f"Could not determine video ID for {url}. Download might fail.")
             # Use a placeholder if ID extraction completely failed
             video_id = f"unknown_{int(time.time())}" 
        
        # Create job folder
        job_folder = create_job_folder(title, output_dir)
        base_filename = sanitize_filename(title)
        
        # Set download options
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': os.path.join(job_folder, f'{base_filename}.%(ext)s'),
            'writeinfojson': True,
            'writethumbnail': True,
            'logger': MyLogger(),
            'progress_hooks': [my_hook],
            'noplaylist': True,
            'http_headers': {
                'User-Agent': user_agent,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate, br',
                'Referer': 'https://www.tiktok.com/',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            },
            'socket_timeout': 30,
            'retries': 10,
            'extractor_args': {
                'tiktok': {
                    'embed_api': True,
                    'api_hostname': 'api22-normal-c-useast1a.tiktokv.com',
                    'app_id': '1233'
                }
            }
        }
            
        # Try downloading with the original URL first
        try:
            logging.info(f"Attempting download with original URL: {url}")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except Exception as e:
            error_msg = str(e)
            logging.error(f"Original URL download failed: {error_msg}")
            
            # --- Fallback to Alternative URLs if needed ---
            logging.info("Trying alternative download approaches...")
            success = False
            alternative_urls = [
                f"https://www.tiktok.com/embed/v2/{video_id}",
                f"https://www.tiktok.com/node/share/video/@{username}/{video_id}",
                f"https://m.tiktok.com/v/{video_id}",
            ]
            
            for alt_url in alternative_urls:
                try:
                    logging.info(f"Trying alternative URL: {alt_url}")
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl_alt:
                        ydl_alt.download([alt_url])
                    # Check if file exists after attempt
                    if any(f.endswith('.mp3') for f in os.listdir(job_folder)):
                        success = True
                        break # Exit loop if download succeeds
                except Exception as alt_e:
                    logging.warning(f"Alternative URL {alt_url} failed: {alt_e}")
            
            if not success:
                logging.error(f"All download attempts failed for URL: {url}")
                return {
                    "success": False,
                    "error": f"All download attempts failed. Last error: {error_msg}",
                    "video_id": video_id,
                    "title": title
                }

        # --- Verify Download and Return Result ---
        mp3_file = None
        for file in os.listdir(job_folder):
            if file.endswith('.mp3'):
                mp3_file = os.path.join(job_folder, file)
                break
                
        if mp3_file:
            logging.info(f"Successfully downloaded audio: {mp3_file}")
            return {
                "success": True,
                "folder": job_folder,
                "audio_file": mp3_file,
                "video_id": video_id,
                "title": title
            }
        else:
            logging.error("Failed to find downloaded audio file after attempts.")
            return {
                "success": False,
                "error": "Download attempted, but MP3 file not found.",
                "video_id": video_id,
                "title": title
            }
            
    except Exception as e:
        logging.error(f"Unexpected error in download_tiktok for {url}: {str(e)}", exc_info=True)
        return {
            "success": False,
            "error": f"Unexpected error: {str(e)}"
        }

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python tiktok_dl.py <tiktok_url> [output_directory]")
        sys.exit(1)
        
    url = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else None
    
    result = download_tiktok(url, output_dir)
    if result["success"]:
        print(f"Download successful!")
        print(f"Files are in: {result['folder']}")
        print(f"Audio file: {result['audio_file']}")
    else:
        print(f"Download failed: {result['error']}")
        sys.exit(1) 