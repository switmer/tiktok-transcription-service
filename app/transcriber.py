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
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
import asyncio
import threading

# Initialize logger
logger = logging.getLogger(__name__)

# Cost tracking helper - fire-and-forget for sync functions
def _track_cost_async(coro):
    """Run an async cost tracking coroutine from sync code without blocking."""
    def run():
        try:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(coro)
            loop.close()
        except Exception as e:
            logger.debug(f"Cost tracking background task error: {e}")
    thread = threading.Thread(target=run, daemon=True)
    thread.start()

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

def _get_referer_for_url(url: str) -> str:
    domain = urlparse(url).netloc.lower()
    if "instagram.com" in domain:
        return "https://www.instagram.com/"
    if "facebook.com" in domain or "fb.watch" in domain:
        return "https://www.facebook.com/"
    if "tiktok.com" in domain:
        return "https://www.tiktok.com/"
    if "youtube.com" in domain or "youtu.be" in domain:
        return "https://www.youtube.com/"
    return "https://www.tiktok.com/"

def _get_cookie_file_for_url(url: str) -> str | None:
    domain = urlparse(url).netloc.lower()
    if "instagram.com" in domain:
        env_vars = ["INSTAGRAM_COOKIE_PATH", "YTDLP_COOKIE_PATH", "TIKTOK_COOKIE_PATH"]
    elif "facebook.com" in domain or "fb.watch" in domain:
        env_vars = ["FACEBOOK_COOKIE_PATH", "YTDLP_COOKIE_PATH", "TIKTOK_COOKIE_PATH"]
    elif "tiktok.com" in domain:
        env_vars = ["TIKTOK_COOKIE_PATH", "YTDLP_COOKIE_PATH"]
    else:
        env_vars = ["YTDLP_COOKIE_PATH", "TIKTOK_COOKIE_PATH"]

    for env_var in env_vars:
        cookie_path = os.environ.get(env_var)
        if cookie_path and os.path.exists(cookie_path):
            logger.info(f"Found cookie file via {env_var}: {cookie_path}")
            return cookie_path
        if cookie_path:
            logger.warning(f"{env_var} is set to '{cookie_path}', but the file was not found.")

    logger.info("No cookie file configured for this URL. Proceeding without cookies.")
    return None

def _pick_first_value(data: dict, keys: list):
    for key in keys:
        value = data.get(key)
        if value is not None and value != "":
            return value
    return None

def _extract_thumbnail_url(value):
    if isinstance(value, str) and value:
        return value
    if isinstance(value, dict):
        if value.get("url"):
            return value["url"]
        for candidate in value.values():
            if isinstance(candidate, dict) and candidate.get("url"):
                return candidate["url"]
    return None

def _coerce_int(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

def clean_url_for_api(url: str) -> str:
    """
    Strip tracking parameters from URLs before sending to RapidAPI.
    This improves API success rate by removing params that cause parsing failures.

    Removes: igsh, utm_*, fbclid, si, feature, share_id, etc.
    """
    try:
        parsed = urlparse(url)

        # List of tracking parameter prefixes to remove
        tracking_prefixes = ('igsh', 'utm_', 'fbclid', 'si', 'feature', 'share_id',
                            'ref', 'source', 's_src', 'tt_from', 'tt_chain_token',
                            '_r', 'checksum', 'sender_device', 'sender_web_id')

        # Parse existing query params
        if parsed.query:
            params = parse_qs(parsed.query)
            # Filter out tracking params
            clean_params = {
                k: v for k, v in params.items()
                if not any(k.lower().startswith(prefix) for prefix in tracking_prefixes)
            }
            # Rebuild URL with cleaned params
            clean_query = urlencode(clean_params, doseq=True)
            clean_parsed = parsed._replace(query=clean_query)
            clean_url = urlunparse(clean_parsed)

            if clean_url != url:
                logger.info(f"Cleaned URL: {url} -> {clean_url}")

            return clean_url

        return url

    except Exception as e:
        logger.warning(f"Error cleaning URL, using original: {e}")
        return url

def _extract_youtube_metadata(data: dict) -> dict:
    if not isinstance(data, dict):
        return {}

    snippet = data.get("snippet") if isinstance(data.get("snippet"), dict) else {}
    title = _pick_first_value(data, ["title", "video_title", "name"]) or snippet.get("title")
    description = _pick_first_value(data, ["description", "caption", "video_description", "summary"]) or snippet.get("description")

    thumbnail_value = _pick_first_value(data, ["thumbnail_url", "thumbnail", "thumbnailUrl"])
    thumbnail_url = _extract_thumbnail_url(thumbnail_value) or _extract_thumbnail_url(snippet.get("thumbnails"))

    author_value = data.get("author") or data.get("uploader") or data.get("channel")
    uploader = None
    channel = None
    if isinstance(author_value, dict):
        uploader = _pick_first_value(author_value, ["name", "title", "channel_name", "username", "uploader"])
        channel = _pick_first_value(author_value, ["channel", "channel_name", "title"])
    elif isinstance(author_value, str):
        uploader = author_value
        channel = author_value

    duration_value = _pick_first_value(data, ["duration", "duration_seconds", "length_seconds", "lengthSeconds"])
    duration = _coerce_int(duration_value)

    metadata = {
        "title": title,
        "description": description,
        "thumbnail_url": thumbnail_url,
        "uploader": uploader,
        "channel": channel,
        "duration": duration
    }
    return {k: v for k, v in metadata.items() if v is not None}

def download_youtube_rapidapi(url: str) -> dict:
    """Transcribe YouTube video instantly using RapidAPI service"""
    rapidapi_key = os.environ.get("RAPIDAPI_KEY")
    if not rapidapi_key:
        logger.warning("RAPIDAPI_KEY not found, skipping YouTube RapidAPI method")
        return None

    try:
        # Clean URL to remove tracking parameters
        clean_url = clean_url_for_api(url)

        # Extract video ID from URL
        import re
        video_id_match = re.search(r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)([^&\n?#]+)', clean_url)
        video_id = video_id_match.group(1) if video_id_match else "unknown"
        
        # RapidAPI YouTube Transcript service (same as Edge Function)
        rapidapi_url = "https://youtube-transcribe-fastest-youtube-transcriber.p.rapidapi.com/transcript"
        headers = {
            "x-rapidapi-key": rapidapi_key,
            "x-rapidapi-host": "youtube-transcribe-fastest-youtube-transcriber.p.rapidapi.com"
        }
        params = {
            "lang": "en",
            "url": clean_url,
            "video_id": video_id
        }

        logger.info(f"Attempting YouTube RapidAPI transcription for: {clean_url} (video_id: {video_id})")
        response = requests.get(rapidapi_url, headers=headers, params=params, timeout=60)
        
        if response.status_code == 200:
            data = response.json()
            logger.info(f"YouTube RapidAPI response received")
            normalized_metadata = _extract_youtube_metadata(data)

            # Track RapidAPI cost (fire-and-forget)
            try:
                from .cost_tracker import log_rapidapi_cost
                _track_cost_async(log_rapidapi_cost(
                    platform="youtube",
                    video_id=video_id,
                    success=True
                ))
            except ImportError:
                pass

            # Extract transcript
            transcript = data.get("transcript", "")
            if transcript:
                # Format transcript with simple line breaks (matching Edge Function style)
                transcript_text = transcript.strip()

                logger.info(f"YouTube RapidAPI success - video_id: {video_id}")
                return {
                    "video_id": video_id,
                    "title": normalized_metadata.get("title") or data.get("title", "YouTube Video"),
                    "description": normalized_metadata.get("description"),
                    "transcript": transcript_text,
                    "platform": "youtube",
                    "thumbnail_url": normalized_metadata.get("thumbnail_url"),
                    "uploader": normalized_metadata.get("uploader"),
                    "channel": normalized_metadata.get("channel"),
                    "duration": normalized_metadata.get("duration"),
                    "download_method": "rapidapi_youtube_fastest",
                    "transcribed_at": datetime.now().isoformat(),
                    "metadata": data
                }
            else:
                logger.error(f"No transcript found in YouTube RapidAPI response: {data}")
                return None

        else:
            logger.error(f"YouTube RapidAPI request failed: {response.status_code}: {response.text}")
            # Track failed RapidAPI call
            try:
                from .cost_tracker import log_rapidapi_cost
                _track_cost_async(log_rapidapi_cost(
                    platform="youtube",
                    video_id=video_id,
                    success=False,
                    error_message=f"HTTP {response.status_code}"
                ))
            except ImportError:
                pass
            return None

    except Exception as e:
        logger.error(f"YouTube RapidAPI transcription failed: {str(e)}")
        return None


def download_tiktok_rapidapi(url: str, output_dir: str):
    """Download TikTok video using RapidAPI service"""
    rapidapi_key = os.environ.get("RAPIDAPI_KEY")
    if not rapidapi_key:
        logger.warning("RAPIDAPI_KEY not found, skipping RapidAPI method")
        return None

    try:
        # Clean URL to remove tracking parameters that cause RapidAPI parsing failures
        clean_url = clean_url_for_api(url)

        # RapidAPI TikTok Video Downloader
        rapidapi_url = "https://tiktok-video-no-watermark2.p.rapidapi.com/"
        headers = {
            "X-RapidAPI-Key": rapidapi_key,
            "X-RapidAPI-Host": "tiktok-video-no-watermark2.p.rapidapi.com"
        }
        params = {"url": clean_url, "hd": "1"}

        logger.info(f"Attempting RapidAPI download for: {clean_url} (original: {url})")
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
                logger.info(f"Downloading video from RapidAPI URL: {video_url}")
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
                        
                        logger.info(f"RapidAPI success - returning video_url: {video_url}")

                        # Track TikTok RapidAPI cost (fire-and-forget)
                        try:
                            from .cost_tracker import log_rapidapi_cost
                            _track_cost_async(log_rapidapi_cost(
                                platform="tiktok",
                                video_id=video_id,
                                success=True
                            ))
                        except ImportError:
                            pass

                        return {
                            "video_id": video_id,
                            "title": title,
                            "audio_file": audio_path,
                            "video_file": video_path,
                            "metadata_file": metadata_path,
                            "video_url": video_url  # Direct CDN URL for database storage
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
            # Track failed RapidAPI call
            try:
                from .cost_tracker import log_rapidapi_cost
                _track_cost_async(log_rapidapi_cost(
                    platform="tiktok",
                    success=False,
                    error_message=f"HTTP {response.status_code}"
                ))
            except ImportError:
                pass
            return None

    except Exception as e:
        logger.error(f"RapidAPI download failed: {str(e)}")
        return None


def download_instagram_rapidapi(url: str, output_dir: str):
    """Download Instagram video using RapidAPI service"""
    rapidapi_key = os.environ.get("RAPIDAPI_KEY")
    if not rapidapi_key:
        logger.warning("RAPIDAPI_KEY not found, skipping Instagram RapidAPI method")
        return None

    try:
        # Clean URL to remove tracking parameters
        clean_url = clean_url_for_api(url)

        # RapidAPI Instagram Reels Downloader
        rapidapi_url = "https://instagram-reels-downloader-api.p.rapidapi.com/download"
        headers = {
            "X-RapidAPI-Key": rapidapi_key,
            "X-RapidAPI-Host": "instagram-reels-downloader-api.p.rapidapi.com"
        }
        params = {"url": clean_url}

        logger.info(f"Attempting Instagram RapidAPI download for: {clean_url}")
        response = requests.get(rapidapi_url, headers=headers, params=params, timeout=60)

        if response.status_code == 200:
            data = response.json()
            logger.info(f"Instagram RapidAPI response received")

            # Check for success status
            if data.get('success') is False or data.get('error'):
                logger.error(f"Instagram API returned error: {data.get('message', 'Unknown error')}")
                return None

            # Extract from nested data structure (actual API format)
            api_data = data.get('data', data)

            # Extract video URL from medias array (primary format)
            video_url = None
            if api_data.get('medias'):
                for media in api_data['medias']:
                    if media.get('type') == 'video' and media.get('url'):
                        video_url = media['url']
                        break

            # Fallback to other possible locations
            if not video_url:
                video_url = (
                    api_data.get('video_url') or
                    api_data.get('videoUrl') or
                    api_data.get('url') or
                    data.get('video_url')
                )

            if not video_url:
                logger.error(f"No video URL found in Instagram RapidAPI response: {data}")
                return None

            # Extract metadata from actual API format
            video_id = api_data.get('shortcode') or api_data.get('id') or 'instagram_video'
            title = api_data.get('title') or api_data.get('caption') or 'Instagram Reel'

            # Get author info
            author = api_data.get('author') or api_data.get('owner', {}).get('username') or 'Unknown'
            thumbnail = api_data.get('thumbnail') or api_data.get('thumbnail_url')
            if len(title) > 100:
                title = title[:100] + '...'

            # Download the video file
            logger.info(f"Downloading Instagram video from: {video_url}")
            video_response = requests.get(video_url, timeout=120)

            if video_response.status_code == 200:
                # Save video file
                video_filename = f"{video_id}.mp4"
                video_path = os.path.join(output_dir, video_filename)

                with open(video_path, 'wb') as f:
                    f.write(video_response.content)

                logger.info(f"Instagram video downloaded: {video_path}")

                # Extract audio using ffmpeg
                audio_filename = f"{video_id}.mp3"
                audio_path = os.path.join(output_dir, audio_filename)

                import subprocess
                try:
                    subprocess.run([
                        'ffmpeg', '-i', video_path, '-vn', '-acodec', 'libmp3lame',
                        '-ab', '192k', '-ar', '44100', '-y', audio_path
                    ], check=True, capture_output=True)

                    logger.info(f"Instagram audio extracted: {audio_path}")

                    # Save metadata
                    metadata = {
                        "id": video_id,
                        "title": title,
                        "url": url,
                        "platform": "instagram",
                        "download_method": "rapidapi_instagram",
                        "downloaded_at": datetime.now().isoformat(),
                        "thumbnail_url": thumbnail,
                        "author": author,
                        "data": api_data
                    }

                    metadata_path = os.path.join(output_dir, f"{video_id}.info.json")
                    with open(metadata_path, 'w') as f:
                        json.dump(metadata, f, indent=2)

                    # Track Instagram RapidAPI cost (fire-and-forget)
                    try:
                        from .cost_tracker import log_rapidapi_cost
                        _track_cost_async(log_rapidapi_cost(
                            platform="instagram",
                            video_id=video_id,
                            success=True
                        ))
                    except ImportError:
                        pass

                    return {
                        "video_id": video_id,
                        "title": title,
                        "audio_file": audio_path,
                        "video_file": video_path,
                        "metadata_file": metadata_path,
                        "video_url": video_url,
                        "platform": "instagram"
                    }

                except subprocess.CalledProcessError as e:
                    logger.error(f"FFmpeg failed for Instagram: {e}")
                    return None
            else:
                logger.error(f"Failed to download Instagram video: {video_response.status_code}")
                return None
        elif response.status_code == 429:
            logger.warning("Instagram RapidAPI rate limit exceeded")
            # Track rate limit as failed call
            try:
                from .cost_tracker import log_rapidapi_cost
                _track_cost_async(log_rapidapi_cost(
                    platform="instagram",
                    success=False,
                    error_message="Rate limit exceeded"
                ))
            except ImportError:
                pass
            return None
        else:
            logger.error(f"Instagram RapidAPI request failed: {response.status_code}")
            return None

    except Exception as e:
        logger.error(f"Instagram RapidAPI download failed: {str(e)}")
        return None


def download_facebook_rapidapi(url: str, output_dir: str):
    """Download Facebook video using RapidAPI service"""
    rapidapi_key = os.environ.get("RAPIDAPI_KEY")
    if not rapidapi_key:
        logger.warning("RAPIDAPI_KEY not found, skipping Facebook RapidAPI method")
        return None

    try:
        # Clean URL to remove tracking parameters
        clean_url = clean_url_for_api(url)

        # Primary: facebook-video-downloader9.p.rapidapi.com
        rapidapi_url = "https://facebook-video-downloader9.p.rapidapi.com/api/v1/videos/download"
        headers = {
            "X-RapidAPI-Key": rapidapi_key,
            "X-RapidAPI-Host": "facebook-video-downloader9.p.rapidapi.com"
        }
        params = {"url": clean_url}

        logger.info(f"Attempting Facebook RapidAPI download for: {clean_url}")
        response = requests.get(rapidapi_url, headers=headers, params=params, timeout=60)

        video_url = None
        video_id = 'facebook_video'
        title = 'Facebook Video'
        thumbnail = None

        if response.status_code == 200:
            data = response.json()
            logger.info(f"Facebook RapidAPI response received")

            # Check for success status
            if data.get('status') == 'success' and data.get('data'):
                api_data = data['data']

                # Extract video URL - prefer HD, fallback to SD
                download = api_data.get('download', {})
                video_url = (
                    download.get('hd', {}).get('url') or
                    download.get('sd', {}).get('url')
                )

                # Extract metadata
                video_info = api_data.get('video', {})
                video_id = video_info.get('id') or 'facebook_video'
                title = video_info.get('title') or video_info.get('description') or 'Facebook Video'
                thumbnail = video_info.get('thumbnail_url')

        # If primary API failed, try backup API
        if not video_url:
            logger.info("Primary Facebook API failed, trying backup API...")
            backup_url = "https://facebook-videos-reels-downloader.p.rapidapi.com/get-video-info"
            backup_headers = {
                "X-RapidAPI-Key": rapidapi_key,
                "X-RapidAPI-Host": "facebook-videos-reels-downloader.p.rapidapi.com"
            }

            backup_response = requests.get(backup_url, headers=backup_headers, params=params, timeout=60)

            if backup_response.status_code == 200:
                backup_data = backup_response.json()

                if backup_data.get('status') == 'ok' and backup_data.get('video'):
                    video_info = backup_data['video']
                    video_url = video_info.get('hd_video_url') or video_info.get('sd_video_url')
                    video_id = video_info.get('video_id') or 'facebook_video'
                    thumbnail = video_info.get('thumbnail_url')

        if not video_url:
            logger.error(f"No video URL found from any Facebook API")
            return None

        if len(title) > 100:
            title = title[:100] + '...'

        # Download the video file
        logger.info(f"Downloading Facebook video from: {video_url}")
        video_response = requests.get(video_url, timeout=120)

        if video_response.status_code == 200:
            # Save video file
            video_filename = f"{video_id}.mp4"
            video_path = os.path.join(output_dir, video_filename)

            with open(video_path, 'wb') as f:
                f.write(video_response.content)

            logger.info(f"Facebook video downloaded: {video_path}")

            # Extract audio using ffmpeg
            audio_filename = f"{video_id}.mp3"
            audio_path = os.path.join(output_dir, audio_filename)

            import subprocess
            try:
                subprocess.run([
                    'ffmpeg', '-i', video_path, '-vn', '-acodec', 'libmp3lame',
                    '-ab', '192k', '-ar', '44100', '-y', audio_path
                ], check=True, capture_output=True)

                logger.info(f"Facebook audio extracted: {audio_path}")

                # Save metadata
                metadata = {
                    "id": video_id,
                    "title": title,
                    "url": url,
                    "platform": "facebook",
                    "download_method": "rapidapi_facebook",
                    "downloaded_at": datetime.now().isoformat(),
                    "thumbnail_url": thumbnail,
                    "data": {"video_id": video_id, "title": title}
                }

                metadata_path = os.path.join(output_dir, f"{video_id}.info.json")
                with open(metadata_path, 'w') as f:
                    json.dump(metadata, f, indent=2)

                # Track Facebook RapidAPI cost (fire-and-forget)
                try:
                    from .cost_tracker import log_rapidapi_cost
                    _track_cost_async(log_rapidapi_cost(
                        platform="facebook",
                        video_id=video_id,
                        success=True
                    ))
                except ImportError:
                    pass

                return {
                    "video_id": video_id,
                    "title": title,
                    "audio_file": audio_path,
                    "video_file": video_path,
                    "metadata_file": metadata_path,
                    "video_url": video_url,
                    "platform": "facebook"
                }

            except subprocess.CalledProcessError as e:
                logger.error(f"FFmpeg failed for Facebook: {e}")
                return None
        else:
            logger.error(f"Failed to download Facebook video: {video_response.status_code}")
            return None

    except Exception as e:
        logger.error(f"Facebook RapidAPI download failed: {str(e)}")
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
    cookie_file_to_use = _get_cookie_file_for_url(url)
    # ------------------------------------------------------------

    referer = _get_referer_for_url(url)
    
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
            'Referer': referer,
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

def _is_tiktok_url(url: str) -> bool:
    """Check if URL is a TikTok video URL."""
    return bool(re.search(r'tiktok\.com|vm\.tiktok\.com', url, re.IGNORECASE))

def _is_instagram_url(url: str) -> bool:
    """Check if URL is an Instagram video URL."""
    return bool(re.search(r'instagram\.com/(?:reel|p|tv)/', url, re.IGNORECASE))

def _is_facebook_url(url: str) -> bool:
    """Check if URL is a Facebook video URL."""
    return bool(re.search(r'facebook\.com/.*/videos/|facebook\.com/reel/|fb\.watch/', url, re.IGNORECASE))

def download_tiktok(url: str, output_dir: str, proxy=None):
    """Download video with platform-aware fallback chain.

    - TikTok: TikTok RapidAPI -> yt-dlp
    - Instagram: Instagram RapidAPI -> yt-dlp
    - Facebook: Facebook RapidAPI -> yt-dlp
    """

    # Clean URL before processing
    clean_url = clean_url_for_api(url)

    # Detect platform
    is_tiktok = _is_tiktok_url(clean_url)
    is_instagram = _is_instagram_url(clean_url)
    is_facebook = _is_facebook_url(clean_url)

    platform = "tiktok" if is_tiktok else "instagram" if is_instagram else "facebook" if is_facebook else "unknown"
    logger.info(f"Detected platform: {platform} for URL: {clean_url}")

    # Method 1: Try platform-specific RapidAPI first
    rapidapi_result = None

    if is_tiktok:
        logger.info("Attempting TikTok RapidAPI download...")
        rapidapi_result = download_tiktok_rapidapi(url, output_dir)
        if rapidapi_result:
            logger.info("TikTok RapidAPI download successful!")
            return rapidapi_result
        logger.warning("TikTok RapidAPI failed, falling back to yt-dlp...")

    elif is_instagram:
        logger.info("Attempting Instagram RapidAPI download...")
        rapidapi_result = download_instagram_rapidapi(url, output_dir)
        if rapidapi_result:
            logger.info("Instagram RapidAPI download successful!")
            return rapidapi_result
        logger.warning("Instagram RapidAPI failed, falling back to yt-dlp...")

    elif is_facebook:
        logger.info("Attempting Facebook RapidAPI download...")
        rapidapi_result = download_facebook_rapidapi(url, output_dir)
        if rapidapi_result:
            logger.info("Facebook RapidAPI download successful!")
            return rapidapi_result
        logger.warning("Facebook RapidAPI failed, falling back to yt-dlp...")

    else:
        logger.info(f"Unknown platform, trying yt-dlp directly...")

    # Method 2: yt-dlp fallback (works for all platforms with proper cookies)
    logger.info(f"Attempting yt-dlp download for {platform}...")
    ytdlp_result = download_tiktok_ytdlp(url, output_dir, proxy)
    
    if ytdlp_result[0]:  # Check if audio_file is not None
        logger.info("yt-dlp download successful!")
        # Convert yt-dlp tuple result to dict format for consistency
        audio_file, video_id, title = ytdlp_result
        return {
            "audio_file": audio_file,
            "video_id": video_id,
            "title": title,
            "video_file": None,  # yt-dlp doesn't provide video file
            "metadata_file": None,  # yt-dlp doesn't provide metadata file  
            "video_url": None  # yt-dlp doesn't provide direct video URL
        }
    
    # Both methods failed
    logger.error("All download methods failed for the provided URL")
    return None

def format_timestamped_transcript(transcript_data, max_duration_seconds=None):
    """Formats verbose_json transcript data with timestamps and bullet points."""
    formatted_lines = []
    timestamp_interval = 30  # Add timestamp every 30 seconds
    last_printed_timestamp_section = -1
    
    # Log if we have duration info
    if max_duration_seconds:
        logger.info(f"Formatting transcript with max duration: {max_duration_seconds} seconds")

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

def transcribe_audio(audio_file: str, output_dir: str, video_id: str, user_phone: str = None, task_id: str = None):
    """Transcribe audio file using OpenAI Whisper, always requesting verbose_json."""
    if client is None:
        logger.error("Cannot transcribe audio: OpenAI client not initialized")
        return None, None

    try:
        logger.info(f"Transcribing audio file: {audio_file} (Requesting verbose_json)")

        # Get audio file size for cost tracking
        audio_file_size = os.path.getsize(audio_file) if os.path.exists(audio_file) else None

        # Always request verbose_json for timestamped data
        openai_format = "verbose_json"

        with open(audio_file, "rb") as audio:
            transcript_response = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio,
                response_format=openai_format
            )

        # Extract duration for cost tracking (from verbose_json response)
        duration_seconds = 0
        if hasattr(transcript_response, 'duration'):
            duration_seconds = transcript_response.duration
        elif isinstance(transcript_response, dict) and 'duration' in transcript_response:
            duration_seconds = transcript_response['duration']

        # Track Whisper cost (fire-and-forget)
        try:
            from .cost_tracker import log_whisper_cost
            _track_cost_async(log_whisper_cost(
                duration_seconds=duration_seconds,
                user_phone=user_phone,
                task_id=task_id or video_id,
                audio_file_size_bytes=audio_file_size,
                success=True
            ))
        except ImportError:
            pass  # Cost tracking module not available

        # Always format the verbose_json response
        final_transcript_text = format_timestamped_transcript(transcript_response)

        # Log when Whisper returns empty/short — helps distinguish silence vs extraction failure
        raw_text = ""
        if hasattr(transcript_response, 'text'):
            raw_text = transcript_response.text or ""
        elif isinstance(transcript_response, dict):
            raw_text = transcript_response.get('text', '') or ""
        if len(raw_text.strip()) == 0:
            logger.warning(
                f"Whisper returned empty transcript: task={task_id}, video={video_id}, "
                f"audio_duration={duration_seconds}s, audio_file_size={audio_file_size} bytes"
            )
        elif len(raw_text.strip()) < 200:
            logger.info(
                f"Whisper returned short transcript ({len(raw_text.strip())} chars): task={task_id}, "
                f"audio_duration={duration_seconds}s, audio_file_size={audio_file_size} bytes"
            )

        # Save the formatted transcript to file
        transcript_file = os.path.join(output_dir, f"{video_id}_transcript.txt")
        with open(transcript_file, "w", encoding="utf-8") as f:
            f.write(final_transcript_text)

        logger.info(f"Transcript saved to: {transcript_file}")
        # Return the raw verbose_json response and the file path
        return transcript_response, transcript_file

    except Exception as e:
        logger.error(f"Error transcribing audio: {str(e)}")
        # Track failed transcription cost attempt
        try:
            from .cost_tracker import log_whisper_cost
            _track_cost_async(log_whisper_cost(
                duration_seconds=0,
                user_phone=user_phone,
                task_id=task_id or video_id,
                success=False,
                error_message=str(e)
            ))
        except ImportError:
            pass
        return None, None

def generate_quote_and_tldr(transcript_text: str, title: str = "", description: str = "", user_phone: str = None, task_id: str = None) -> dict:
    """Generate a shareable quote and TLDR summary from transcript text"""
    if client is None:
        logger.error("Cannot generate quote+TLDR: OpenAI client not initialized")
        return {"quote": None, "tldr": None}

    # Gate: skip generation for empty or very short transcripts
    clean_text = (transcript_text or "").strip()
    word_count = len(clean_text.split())

    if not clean_text:
        logger.warning(f"Skipping quote/TLDR generation: transcript is empty (task={task_id})")
        return {"quote": None, "tldr": None, "skipped": "empty_transcript"}

    if len(clean_text) < 200 or word_count < 40:
        logger.info(f"Transcript too short for full summary ({len(clean_text)} chars, {word_count} words, task={task_id}), returning raw text")
        return {
            "quote": clean_text[:200] if len(clean_text) > 50 else clean_text,
            "tldr": ["Transcript was very short — here's the raw text above."],
            "skipped": "short_transcript",
        }

    try:
        # Truncate transcript if too long (GPT-3.5 has token limits)
        max_chars = 3000
        truncated_transcript = transcript_text[:max_chars] + "..." if len(transcript_text) > max_chars else transcript_text
        safe_title = (title or "").strip()
        safe_description = (description or "").strip()

        prompt = f"""You are ScribeTok's AI that extracts memorable quotes and detailed insights from video content. Your job is to capture the REAL value - the specific advice, unique perspectives, and actionable wisdom that people actually want to save and share.

Use the title/description to resolve names, topics, and context. If anything conflicts, trust the transcript.

QUOTE Guidelines:
- Find the most quotable line that captures the speaker's unique perspective
- It should make people go "YES, exactly!" or want to share it
- Can be philosophical, funny, controversial, or deeply relatable
- Don't pick generic feel-good lines - pick the MEAT

TLDR Guidelines:
- 3-4 bullet points that capture the specific, actionable content
- Include concrete examples, methods, or unique approaches mentioned
- Focus on what someone could actually DO or specific perspectives they shared
- Each bullet should teach something valuable or surprising
- Write conversationally, like you're telling a friend the good parts

Respond STRICTLY in this JSON format (no other text):
{{
  "quote": "the most memorable, shareable line that captures their unique take",
  "tldr": ["Specific insight #1 with concrete details", "Actionable advice #2 with examples", "Unique perspective #3 that's worth remembering", "Additional valuable point #4 if there's more gold"]
}}

Title:
{safe_title}

Description:
{safe_description}

Transcript:
\"\"\"
{truncated_transcript}
\"\"\""""

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=600,
            temperature=0.8
        )

        # Track GPT cost (fire-and-forget)
        tokens_used = None
        if hasattr(response, 'usage') and response.usage:
            tokens_used = response.usage.total_tokens
        try:
            from .cost_tracker import log_gpt_cost
            _track_cost_async(log_gpt_cost(
                model="gpt-3.5-turbo",
                tokens_used=tokens_used,
                user_phone=user_phone,
                task_id=task_id,
                purpose="quote_tldr",
                success=True
            ))
        except ImportError:
            pass

        # Parse the JSON response
        result_text = response.choices[0].message.content.strip()
        logger.info(f"Quote+TLDR raw response: {result_text}")

        # Try to parse JSON
        try:
            parsed_result = json.loads(result_text)
            quote = parsed_result.get("quote", "").strip('"')  # Remove extra quotes
            tldr = parsed_result.get("tldr", [])

            # Validate results
            if not quote or not tldr:
                logger.warning("Quote or TLDR missing from response")
                return {"quote": None, "tldr": None}

            logger.info(f"Generated quote: {quote}")
            logger.info(f"Generated TLDR: {tldr}")

            return {"quote": quote, "tldr": tldr}

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse quote+TLDR JSON: {e}")
            logger.error(f"Raw response was: {result_text}")
            return {"quote": None, "tldr": None}

    except Exception as e:
        logger.error(f"Error generating quote+TLDR: {str(e)}")
        # Track failed GPT call
        try:
            from .cost_tracker import log_gpt_cost
            _track_cost_async(log_gpt_cost(
                model="gpt-3.5-turbo",
                user_phone=user_phone,
                task_id=task_id,
                purpose="quote_tldr",
                success=False,
                error_message=str(e)
            ))
        except ImportError:
            pass
        return {"quote": None, "tldr": None} 
