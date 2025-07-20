import os
import re
from datetime import datetime, timedelta
import yt_dlp
from openai import OpenAI
import random
import time
from typing import Literal
import logging
import requests
import json

# Initialize logger
logger = logging.getLogger(__name__)

# Initialize OpenAI client with explicit API key and timeout
api_key = os.environ.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
client = None
if not api_key:
    logger.error("OPENAI_API_KEY environment variable not found")
else:
    try:
        import httpx
        # Create client with 5-minute timeout for transcription
        http_client = httpx.Client(timeout=300.0)
        client = OpenAI(api_key=api_key, http_client=http_client)
        logger.info("OpenAI client initialized successfully with timeout")
    except Exception as e:
        logger.error(f"Failed to initialize OpenAI client: {str(e)}")

class MyLogger(object):
    def debug(self, msg):
        if msg.startswith('[debug] '):
            pass
        else:
            self.info(msg)

    def info(self, msg):
        print(msg)

    def warning(self, msg):
        print(f"Warning: {msg}")

    def error(self, msg):
        print(f"Error: {msg}")

def download_tiktok_rapidapi(url: str, output_dir: str):
    """Download TikTok video using RapidAPI service"""
    rapidapi_key = os.environ.get("RAPIDAPI_KEY")
    if not rapidapi_key:
        logger.warning("RAPIDAPI_KEY not found, skipping RapidAPI method")
        return None
    
    try:
        # RapidAPI TikTok Video Downloader
        rapidapi_url = "https://tiktok-video-no-watermark2.p.rapidapi.com/"
        headers = {
            "X-RapidAPI-Key": rapidapi_key,
            "X-RapidAPI-Host": "tiktok-video-no-watermark2.p.rapidapi.com"
        }
        params = {"url": url, "hd": "1"}
        
        logger.info(f"Attempting RapidAPI download for: {url}")
        response = requests.get(rapidapi_url, headers=headers, params=params, timeout=60)  # Increased timeout
        
        if response.status_code == 200:
            data = response.json()
            logger.info(f"RapidAPI response: {data}")
            
            # Extract video info
            if data.get("code") == 0 and data.get("data"):
                video_data = data["data"]
                video_id = video_data.get("id", "unknown")
                title = video_data.get("title", "TikTok Video")
                
                # Get video download URL
                video_url = video_data.get("hdplay") or video_data.get("play")
                if not video_url:
                    logger.error("No video URL found in RapidAPI response")
                    return None
                
                # Download the video file
                logger.info(f"Downloading video from: {video_url}")
                video_response = requests.get(video_url, timeout=120)  # Increased timeout for video download
                
                if video_response.status_code == 200:
                    # Save video file
                    video_filename = f"{video_id}.mp4"
                    video_path = os.path.join(output_dir, video_filename)
                    
                    with open(video_path, 'wb') as f:
                        f.write(video_response.content)
                    
                    logger.info(f"Video downloaded successfully: {video_path}")
                    
                    # Extract audio using ffmpeg
                    audio_filename = f"{video_id}.mp3"
                    audio_path = os.path.join(output_dir, audio_filename)
                    
                    # Use ffmpeg to extract audio
                    import subprocess
                    try:
                        subprocess.run([
                            'ffmpeg', '-i', video_path, '-vn', '-acodec', 'libmp3lame', 
                            '-ab', '192k', '-ar', '44100', '-y', audio_path
                        ], check=True, capture_output=True)
                        
                        logger.info(f"Audio extracted successfully: {audio_path}")
                        
                        # Save metadata - include full RapidAPI response for rich metadata extraction
                        metadata = {
                            "id": video_id,
                            "title": title,
                            "url": url,
                            "download_method": "rapidapi",
                            "downloaded_at": datetime.now().isoformat(),
                            "thumbnail_url": video_data.get("cover") or video_data.get("origin_cover") or video_data.get("ai_dynamic_cover"),
                            # Include full RapidAPI response data for rich metadata extraction
                            "data": video_data  # This contains likes, comments, author info, etc.
                        }
                        
                        metadata_path = os.path.join(output_dir, f"{video_id}.info.json")
                        with open(metadata_path, 'w') as f:
                            json.dump(metadata, f, indent=2)
                        
                        return {
                            "video_id": video_id,
                            "title": title,
                            "audio_file": audio_path,
                            "video_file": video_path,
                            "metadata_file": metadata_path
                        }
                        
                    except subprocess.CalledProcessError as e:
                        logger.error(f"FFmpeg failed: {e}")
                        return None
                        
                else:
                    logger.error(f"Failed to download video: {video_response.status_code}")
                    return None
                    
            else:
                logger.error(f"RapidAPI returned error: {data}")
                return None
                
        else:
            logger.error(f"RapidAPI request failed: {response.status_code}")
            return None
            
    except Exception as e:
        logger.error(f"RapidAPI download failed: {str(e)}")
        return None

def my_hook(d):
    if d['status'] == 'downloading':
        print(f"\rDownloading: {d['filename']} | {d.get('_percent_str', 'N/A')} of {d.get('_total_bytes_str', 'N/A')} at {d.get('_speed_str', 'N/A')}", end='', flush=True)
    elif d['status'] == 'finished':
        print(f"\nFinished downloading {d['filename']}")

def download_tiktok_ytdlp(url: str, output_dir: str, proxy=None):
    """Download TikTok video using yt-dlp (original method)"""
    # Set user agents to rotate
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36',
        'Mozilla/5.0 (iPhone; CPU iPhone OS 12_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148',
        'Mozilla/5.0 (iPad; CPU OS 12_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    ]
    
    # Use a random user agent
    user_agent = random.choice(user_agents)
    
    # --- Check for cookie file path from environment variable --- 
    cookie_path_env = os.environ.get("TIKTOK_COOKIE_PATH")
    cookie_file_to_use = None
    if cookie_path_env and os.path.exists(cookie_path_env):
        cookie_file_to_use = cookie_path_env
        logger.info(f"Found cookie file via TIKTOK_COOKIE_PATH: {cookie_file_to_use}")
    else:
        if cookie_path_env:
            logger.warning(f"TIKTOK_COOKIE_PATH is set to '{cookie_path_env}', but the file was not found.")
        else:
            logger.info("TIKTOK_COOKIE_PATH not set. Proceeding without cookies.")
    # ------------------------------------------------------------
    
    # Set up options with better defaults from downloader.py
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'outtmpl': os.path.join(output_dir, '%(id)s.%(ext)s'),
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
        'socket_timeout': 30,  # Longer timeout for connection issues
        'retries': 10          # More retries for transient issues
    }
    
    # Use cookies file if found via environment variable
    if cookie_file_to_use:
        ydl_opts['cookiefile'] = cookie_file_to_use
        logger.info(f"Passing cookie file to yt-dlp: {cookie_file_to_use}")
    
    # Add proxy if provided
    if proxy:
        ydl_opts['proxy'] = proxy
        print(f"Using proxy: {proxy}")
    
    try:
        # Add a small delay before starting (helps avoid rate limiting)
        time.sleep(random.uniform(1, 3))
        
        # Extract info without downloading
        info_opts = {
            'quiet': True, 
            'http_headers': ydl_opts['http_headers']
        }
        if proxy:
            info_opts['proxy'] = proxy
        # Pass cookies to info extraction as well
        if cookie_file_to_use:
            info_opts['cookiefile'] = cookie_file_to_use
            
        with yt_dlp.YoutubeDL(info_opts) as ydl:
            logger.info(f"Extracting video info for {url} with User-Agent: {user_agent}")
            info = ydl.extract_info(url, download=False)
            video_id = info.get('id')
            title = info.get('title')
            
            print(f"Video ID: {video_id}")
            print(f"Title: {title}")
        
        # Download the video
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            print(f"Downloading video: {title}")
            ydl.download([url])
        
        # Find the downloaded mp3 file
        mp3_file = None
        for file in os.listdir(output_dir):
            if file.endswith('.mp3'):
                mp3_file = os.path.join(output_dir, file)
                break
        
        return mp3_file, video_id, title
    
    except Exception as e:
        print(f"Error downloading video: {str(e)}")
        return None, None, None

def download_tiktok(url: str, output_dir: str, proxy=None):
    """Download TikTok video with fallback chain: RapidAPI -> yt-dlp"""
    
    # Method 1: Try RapidAPI first (more reliable)
    logger.info("Attempting RapidAPI download method...")
    rapidapi_result = download_tiktok_rapidapi(url, output_dir)
    
    if rapidapi_result:
        logger.info("RapidAPI download successful!")
        return (
            rapidapi_result["audio_file"],
            rapidapi_result["video_id"],
            rapidapi_result["title"]
        )
    
    # Method 2: Fallback to yt-dlp
    logger.info("RapidAPI failed, falling back to yt-dlp...")
    ytdlp_result = download_tiktok_ytdlp(url, output_dir, proxy)
    
    if ytdlp_result[0]:  # Check if audio_file is not None
        logger.info("yt-dlp download successful!")
        return ytdlp_result
    
    # Both methods failed
    logger.error("All download methods failed for TikTok URL")
    return None, None, None

def format_timestamped_transcript(transcript_data):
    """Formats verbose_json transcript data with timestamps and bullet points."""
    formatted_lines = []
    timestamp_interval = 30  # Add timestamp every 30 seconds
    last_printed_timestamp_section = -1

    # Handle potential non-dict response if API changes or error occurs
    if not isinstance(transcript_data, dict):
        # Check if it's a Whisper TranscriptionVerbose object
        if hasattr(transcript_data, 'text'):
            return transcript_data.text
        elif hasattr(transcript_data, 'segments'):
            # Extract text from segments if available
            segments = transcript_data.segments
            return ' '.join([segment.text.strip() for segment in segments])
        else:
            # Last resort: convert to string but try to extract meaningful text
            text_str = str(transcript_data)
            # Try to extract text= value from the string representation
            import re
            text_match = re.search(r"text='([^']+)'", text_str)
            if text_match:
                return text_match.group(1)
            return text_str
    
    if 'segments' not in transcript_data:
        return transcript_data.get('text', '')

    for segment in transcript_data['segments']:
        start_time = segment['start']
        text = segment['text'].strip()

        # Calculate the current 30-second section
        current_timestamp_section = int(start_time // timestamp_interval)

        # Print timestamp if it's a new section
        if current_timestamp_section > last_printed_timestamp_section:
            # Format timestamp as MM:SS
            minutes = int(start_time // 60)
            seconds = int(start_time % 60)
            timestamp = f"{minutes:02d}:{seconds:02d}:{0:02d}"
            
            # Add empty line before timestamp if not the first one
            if last_printed_timestamp_section >= 0:
                formatted_lines.append("")
            
            formatted_lines.append(timestamp)
            last_printed_timestamp_section = current_timestamp_section
        
        # Add the transcribed text as bullet point
        if text:
            formatted_lines.append(f"- {text}")
        
    return '\n'.join(formatted_lines)

def transcribe_audio(audio_file: str, output_dir: str, video_id: str):
    """Transcribe audio file using OpenAI Whisper, always requesting verbose_json."""
    if client is None:
        logger.error("Cannot transcribe audio: OpenAI client not initialized")
        return None, None

    try:
        logger.info(f"Transcribing audio file: {audio_file} (Requesting verbose_json)")
        
        # Always request verbose_json for timestamped data
        openai_format = "verbose_json" 
        
        with open(audio_file, "rb") as audio:
            transcript_response = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio,
                response_format=openai_format
            )
        
        # Always format the verbose_json response
        final_transcript_text = format_timestamped_transcript(transcript_response)

        # Save the formatted transcript to file
        transcript_file = os.path.join(output_dir, f"{video_id}_transcript.txt")
        with open(transcript_file, "w", encoding="utf-8") as f:
            f.write(final_transcript_text)
        
        logger.info(f"Transcript saved to: {transcript_file}")
        # Return the raw verbose_json response and the file path
        return transcript_response, transcript_file 
    
    except Exception as e:
        logger.error(f"Error transcribing audio: {str(e)}")
        return None, None 