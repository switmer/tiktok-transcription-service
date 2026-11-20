import os
import re
import subprocess
import hashlib
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

def _validate_audio(audio_path: str) -> tuple:
    """Check if an audio file is valid using ffprobe. Returns (is_valid, info_string)."""
    if not os.path.exists(audio_path):
        return False, "file does not exist"
    file_size = os.path.getsize(audio_path)
    if file_size == 0:
        return False, "file is 0 bytes"
    try:
        probe = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration,size',
             '-show_entries', 'stream=codec_name,sample_rate,channels',
             '-of', 'json', audio_path],
            capture_output=True, text=True, timeout=10
        )
        if probe.returncode != 0:
            return False, f"ffprobe failed: {probe.stderr.strip()[:200]}"
        import json as _json
        info = _json.loads(probe.stdout)
        duration = float(info.get('format', {}).get('duration', 0))
        if duration < 0.1:
            return False, f"duration={duration}s, size={file_size}B"
        codec = info.get('streams', [{}])[0].get('codec_name', 'unknown')
        return True, f"codec={codec}, duration={duration:.1f}s, size={file_size}B"
    except Exception as e:
        return False, f"ffprobe error: {str(e)[:200]}"


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
    """Get appropriate Referer header for the URL's platform."""
    domain = urlparse(url).netloc.lower()
    if "instagram.com" in domain or "instagr.am" in domain:
        return "https://www.instagram.com/"
    if "facebook.com" in domain or "fb.watch" in domain or "fb.gg" in domain:
        return "https://www.facebook.com/"
    if "tiktok.com" in domain:
        return "https://www.tiktok.com/"
    if "youtube.com" in domain or "youtu.be" in domain:
        return "https://www.youtube.com/"
    if "x.com" in domain or "twitter.com" in domain:
        return "https://x.com/"
    if "reddit.com" in domain or "redd.it" in domain:
        return "https://www.reddit.com/"
    if "vimeo.com" in domain:
        return "https://vimeo.com/"
    if "twitch.tv" in domain:
        return "https://www.twitch.tv/"
    if "linkedin.com" in domain:
        return "https://www.linkedin.com/"
    if "threads.net" in domain:
        return "https://www.threads.net/"
    if "loom.com" in domain:
        return "https://www.loom.com/"
    if "spotify.com" in domain:
        return "https://open.spotify.com/"
    return "https://www.tiktok.com/"

def _get_cookie_file_for_url(url: str) -> str | None:
    """Get cookie file path for the URL's platform. Cookie env vars are optional."""
    domain = urlparse(url).netloc.lower()
    
    # Platform-specific cookie env vars, with fallbacks
    if "instagram.com" in domain or "instagr.am" in domain:
        env_vars = ["INSTAGRAM_COOKIE_PATH", "YTDLP_COOKIE_PATH"]
    elif "facebook.com" in domain or "fb.watch" in domain or "fb.gg" in domain:
        env_vars = ["FACEBOOK_COOKIE_PATH", "YTDLP_COOKIE_PATH"]
    elif "tiktok.com" in domain:
        env_vars = ["TIKTOK_COOKIE_PATH", "YTDLP_COOKIE_PATH"]
    elif "x.com" in domain or "twitter.com" in domain:
        env_vars = ["X_COOKIE_PATH", "TWITTER_COOKIE_PATH", "YTDLP_COOKIE_PATH"]
    elif "youtube.com" in domain or "youtu.be" in domain:
        env_vars = ["YOUTUBE_COOKIE_PATH", "YTDLP_COOKIE_PATH"]
    elif "reddit.com" in domain or "redd.it" in domain:
        env_vars = ["REDDIT_COOKIE_PATH", "YTDLP_COOKIE_PATH"]
    elif "twitch.tv" in domain:
        env_vars = ["TWITCH_COOKIE_PATH", "YTDLP_COOKIE_PATH"]
    else:
        env_vars = ["YTDLP_COOKIE_PATH"]

    for env_var in env_vars:
        cookie_path = os.environ.get(env_var)
        if cookie_path and os.path.exists(cookie_path):
            logger.info(f"Found cookie file via {env_var}: {cookie_path}")
            return cookie_path
        if cookie_path:
            logger.debug(f"{env_var} is set to '{cookie_path}', but the file was not found.")

    logger.debug("No cookie file configured for this URL. Proceeding without cookies.")
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

            # Extract transcript — API returns {'data': {'text': '...', 'chunks': [...]}, 'status': 'success'}
            transcript = data.get("transcript") or (data.get("data", {}).get("text") if isinstance(data.get("data"), dict) else None) or ""
            if transcript:
                # Format transcript with simple line breaks (matching Edge Function style)
                transcript_text = transcript.strip()

                # Fetch title via YouTube oEmbed (free, no API key)
                title = normalized_metadata.get("title") or data.get("title")
                thumbnail_url = normalized_metadata.get("thumbnail_url")
                uploader = normalized_metadata.get("uploader")
                if not title:
                    try:
                        oembed = requests.get(
                            f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json",
                            timeout=5
                        ).json()
                        title = oembed.get("title")
                        uploader = uploader or oembed.get("author_name")
                        thumbnail_url = thumbnail_url or oembed.get("thumbnail_url")
                    except Exception:
                        pass
                title = title or "YouTube Video"
                # YouTube thumbnails are deterministic from video_id
                thumbnail_url = thumbnail_url or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

                logger.info(f"YouTube RapidAPI success - video_id: {video_id}, title: {title}")
                return {
                    "video_id": video_id,
                    "title": title,
                    "description": normalized_metadata.get("description"),
                    "transcript": transcript_text,
                    "platform": "youtube",
                    "thumbnail_url": thumbnail_url,
                    "uploader": uploader,
                    "channel": normalized_metadata.get("channel") or uploader,
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


def fetch_youtube_captions(url: str, proxy: str = None) -> dict:
    """Get YouTube captions (with timestamps) via youtube-transcript-api.

    Returns {"status": ...} where status is one of:
      "found"       - also has "result" (same shape as download_youtube_rapidapi)
      "no_captions" - video has no captions (or is unavailable)
      "blocked"     - YouTube blocked our IP (RequestBlocked / IpBlocked); NOT the same as no captions
      "error"       - anything else
    """
    from youtube_transcript_api import (
        YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled,
        VideoUnavailable, RequestBlocked,
    )
    from youtube_transcript_api.proxies import GenericProxyConfig

    match = re.search(r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)([^&\n?#]+)', clean_url_for_api(url))
    if not match:
        return {"status": "error", "message": "could not find video id"}
    video_id = match.group(1)

    try:
        proxy_config = GenericProxyConfig(http_url=proxy, https_url=proxy) if proxy else None
        api = YouTubeTranscriptApi(proxy_config=proxy_config)
        transcript_list = api.list(video_id)
        try:
            transcript = transcript_list.find_transcript(["en"])
        except NoTranscriptFound:
            transcript = next(iter(transcript_list))  # any language is better than Whisper on a long video
        fetched = transcript.fetch()
    except RequestBlocked as e:  # IpBlocked is a subclass
        logger.warning(f"YouTube captions blocked for {video_id}: {type(e).__name__}")
        return {"status": "blocked", "message": type(e).__name__}
    except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable, StopIteration) as e:
        logger.info(f"No YouTube captions for {video_id}: {type(e).__name__}")
        return {"status": "no_captions", "message": type(e).__name__}
    except Exception as e:
        logger.error(f"YouTube captions failed for {video_id}: {e}")
        return {"status": "error", "message": str(e)}

    segments = [{"text": sn.text, "start": sn.start, "duration": sn.duration} for sn in fetched.snippets]
    text = " ".join(seg["text"].replace("\n", " ").strip() for seg in segments).strip()
    if not text:
        return {"status": "no_captions", "message": "empty transcript"}

    title, uploader, thumbnail_url = None, None, None
    try:
        oembed = requests.get(
            f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json",
            timeout=5
        ).json()
        title = oembed.get("title")
        uploader = oembed.get("author_name")
        thumbnail_url = oembed.get("thumbnail_url")
    except Exception:
        pass

    return {
        "status": "found",
        "result": {
            "video_id": video_id,
            "title": title or "YouTube Video",
            "description": None,
            "transcript": text,
            "platform": "youtube",
            "thumbnail_url": thumbnail_url or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            "uploader": uploader,
            "channel": uploader,
            "duration": int(segments[-1]["start"] + segments[-1]["duration"]),
            "download_method": "youtube_transcript_api",
            "transcribed_at": datetime.now().isoformat(),
            # Timestamped segments live in raw_metadata (no new column)
            "metadata": {"captions": {
                "language": fetched.language_code,
                "is_generated": fetched.is_generated,
                "segments": segments,
            }},
        },
    }


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
                            '-ab', '192k', '-ar', '44100', '-ac', '1', '-y', audio_path
                        ], check=True, capture_output=True)

                        # Validate the extracted audio
                        audio_valid, audio_info = _validate_audio(audio_path)
                        if not audio_valid:
                            logger.warning(f"MP3 extraction produced invalid audio ({audio_info}), retrying as WAV")
                            wav_path = os.path.join(output_dir, f"{video_id}.wav")
                            subprocess.run([
                                'ffmpeg', '-i', video_path, '-vn', '-acodec', 'pcm_s16le',
                                '-ar', '16000', '-ac', '1', '-y', wav_path
                            ], check=True, capture_output=True)
                            wav_valid, wav_info = _validate_audio(wav_path)
                            if wav_valid:
                                audio_path = wav_path
                                logger.info(f"WAV fallback succeeded: {wav_info}")
                            else:
                                logger.error(f"WAV fallback also invalid ({wav_info}), video may have no audio track")
                                return None
                        else:
                            logger.info(f"Audio extracted successfully: {audio_path} ({audio_info})")
                        
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
        'retries': 10,         # More retries for transient issues
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
            'http_headers': ydl_opts['http_headers'],
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
        logger.error(f"Error downloading video via yt-dlp: {str(e)}", exc_info=True)
        return None, None, None

# Alias so callers can use the platform-specific name
download_youtube_ytdlp = download_tiktok_ytdlp

def _is_tiktok_url(url: str) -> bool:
    """Check if URL is a TikTok video URL."""
    return bool(re.search(
        r'(?:tiktok\.com/@[^/]+/video/|tiktok\.com/t/|vm\.tiktok\.com/)',
        url, re.IGNORECASE
    ))

def _is_instagram_url(url: str) -> bool:
    """Check if URL is an Instagram video URL.
    Supports: /reel/, /reels/, /p/, /tv/, username-prefixed paths,
    share links (/share/, /share/reel/), and instagr.am short URLs.
    """
    # Match instagr.am short URLs
    if re.search(r'instagr\.am/', url, re.IGNORECASE):
        return True
    # Match instagram.com with various path patterns
    # Direct: /reel/, /reels/, /p/, /tv/
    # Username-prefixed: /@username/reel/, /username/reel/
    # Share links: /share/reel/, /share/p/, /share/<shortcode>
    return bool(re.search(
        r'instagram\.com/(?:(?:reel|reels|p|tv)/|[^/]+/(?:reel|reels|p|tv)/|share/(?:reel|p|video/)?[^/]+)',
        url, re.IGNORECASE
    ))

def _is_facebook_url(url: str) -> bool:
    """Check if URL is a Facebook video URL."""
    return bool(re.search(r'facebook\.com/(?:.*/videos/|watch\?v=|reel/)|fb\.watch/|fb\.gg/v/', url, re.IGNORECASE))

def _is_spotify_url(url: str) -> bool:
    """Check if URL is a Spotify podcast episode URL."""
    return bool(re.search(r'open\.spotify\.com/episode/', url, re.IGNORECASE))

def _is_youtube_url(url: str) -> bool:
    """Check if URL is a YouTube video URL.
    Supports: watch?v=, youtu.be/, shorts/, live/, embed/, m.youtube.com, music.youtube.com,
    and v= anywhere in query string.
    """
    # Standard patterns
    if re.search(r'(?:youtube\.com/(?:watch|shorts|live|embed)|youtu\.be/)', url, re.IGNORECASE):
        return True
    # v= anywhere in youtube.com URL query string
    if re.search(r'youtube\.com.*[?&]v=[\w-]{11}', url, re.IGNORECASE):
        return True
    # m.youtube.com or music.youtube.com
    if re.search(r'(?:m\.youtube\.com|music\.youtube\.com)/watch', url, re.IGNORECASE):
        return True
    return False

def _is_x_twitter_url(url: str) -> bool:
    """Check if URL is an X/Twitter status URL."""
    return bool(re.search(r'(?:x\.com|(?:www\.|mobile\.)?twitter\.com)/[^/]+/status/\d+', url, re.IGNORECASE))

def _is_reddit_url(url: str) -> bool:
    """Check if URL is a Reddit video URL."""
    return bool(re.search(r'(?:reddit\.com/r/[^/]+/(?:comments|s)/|redd\.it/|v\.redd\.it/)', url, re.IGNORECASE))

def _is_vimeo_url(url: str) -> bool:
    """Check if URL is a Vimeo video URL."""
    return bool(re.search(
        r'(?:vimeo\.com/(?:\d+|channels/[^/]+/\d+|groups/[^/]+/videos/\d+)|player\.vimeo\.com/video/\d+)',
        url, re.IGNORECASE
    ))

def _is_twitch_url(url: str) -> bool:
    """Check if URL is a Twitch clip or VOD URL."""
    return bool(re.search(r'(?:clips\.twitch\.tv/|twitch\.tv/(?:[^/]+/clip/|videos/))', url, re.IGNORECASE))

def _is_linkedin_url(url: str) -> bool:
    """Check if URL is a LinkedIn post URL (may contain video)."""
    return bool(re.search(r'linkedin\.com/(?:posts/|feed/update/|video/)', url, re.IGNORECASE))

def _is_threads_url(url: str) -> bool:
    """Check if URL is a Threads post URL."""
    return bool(re.search(r'threads\.net/@[^/]+/post/', url, re.IGNORECASE))

def _is_loom_url(url: str) -> bool:
    """Check if URL is a Loom video URL."""
    return bool(re.search(r'loom\.com/share/', url, re.IGNORECASE))

# Values allowed by transcriptions.platform CHECK constraint.
STORED_PLATFORMS = frozenset({
    'tiktok',
    'youtube',
    'instagram',
    'twitter',
    'facebook',
    'linkedin',
    'spotify',
    'reddit',
    'vimeo',
    'twitch',
    'threads',
    'loom',
    'web',
})

# Aliases used by the SMS edge function / older code.
_PLATFORM_ALIASES = {
    'webpage': 'web',
    'x': 'twitter',
    'x/twitter': 'twitter',
}


def _detect_platform(url: str) -> str:
    """Detect the platform from a URL.

    Returns a known platform name, 'web' for generic http(s) pages, or
    'unknown' when the input is empty / not a URL.
    """
    if not url:
        return 'unknown'
    if _is_tiktok_url(url):
        return 'tiktok'
    if _is_youtube_url(url):
        return 'youtube'
    if _is_instagram_url(url):
        return 'instagram'
    if _is_facebook_url(url):
        return 'facebook'
    if _is_x_twitter_url(url):
        return 'twitter'
    if _is_reddit_url(url):
        return 'reddit'
    if _is_vimeo_url(url):
        return 'vimeo'
    if _is_twitch_url(url):
        return 'twitch'
    if _is_linkedin_url(url):
        return 'linkedin'
    if _is_threads_url(url):
        return 'threads'
    if _is_loom_url(url):
        return 'loom'
    if _is_spotify_url(url):
        return 'spotify'
    if re.match(r'^https?://', url.strip(), re.IGNORECASE):
        return 'web'
    return 'unknown'


def canonical_platform(url: str = '', detected: str | None = None) -> str:
    """Return the platform value to persist (matches the DB constraint).

    Never falls back to 'tiktok'. Generic http(s) pages become 'web'.
    """
    platform = detected if detected not in (None, '') else _detect_platform(url)
    platform = _PLATFORM_ALIASES.get(platform, platform)
    if platform in STORED_PLATFORMS:
        return platform
    if platform in (None, '', 'unknown'):
        candidate = (url or '').strip()
        if candidate.lower().startswith(('http://', 'https://')):
            return 'web'
        return 'unknown'
    return 'web' if (url or '').lower().startswith(('http://', 'https://')) else 'unknown'


def needs_video_discovery(platform: str | None) -> bool:
    """True when the URL is a generic web page, not a known video host."""
    if not platform:
        return True
    mapped = _PLATFORM_ALIASES.get(platform, platform)
    return mapped in ('web', 'unknown')

def clean_url_trailing_punctuation(url: str) -> str:
    """Clean trailing punctuation from URLs that may be added by users or SMS clients."""
    if not url:
        return url
    return re.sub(r'[).\,!?;:]+$', '', url)

def _extract_spotify_episode_id(url: str):
    """Extract Spotify episode ID from URL."""
    match = re.search(r'open\.spotify\.com/episode/([a-zA-Z0-9]+)', url)
    return match.group(1) if match else None

def _is_direct_video_url(url: str) -> bool:
    """Check if URL points directly to a video file (e.g. LinkedIn CDN)."""
    parsed = urlparse(url)
    path = parsed.path.lower()
    return any(ext in path for ext in ('.mp4', '.webm', '.mov', '/mp4-'))

def download_spotify_rapidapi(url: str, output_dir: str):
    """Download Spotify podcast episode audio using RapidAPI service."""
    try:
        from spotify_service import spotify_service
    except ImportError:
        logger.warning("spotify_service not available, skipping Spotify download")
        return None

    episode_id = _extract_spotify_episode_id(url)
    if not episode_id:
        logger.error(f"Could not extract Spotify episode ID from: {url}")
        return None

    logger.info(f"Attempting Spotify RapidAPI download for episode: {episode_id}")
    result = spotify_service.get_episode_info(url)

    if not result.get('success') or not result.get('data'):
        logger.error(f"Spotify API failed: {result.get('error', 'unknown error')}")
        return None

    data = result['data']
    audio_info = data.get('audio', {})
    play_url = audio_info.get('play_url')
    if not play_url:
        logger.error("No playable audio URL in Spotify response")
        return None

    title = data.get('title', 'Spotify Episode')
    cover_url = audio_info.get('cover')

    # Download audio file directly
    logger.info(f"Downloading Spotify audio: {play_url[:80]}...")
    audio_resp = requests.get(play_url, stream=True, timeout=300, headers={
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
    })
    audio_resp.raise_for_status()

    content_type = audio_resp.headers.get('Content-Type', '')
    is_mp3 = 'mp3' in content_type or 'mpeg' in content_type
    raw_ext = '.mp3' if is_mp3 else '.mp4'
    raw_path = os.path.join(output_dir, f"{episode_id}_raw{raw_ext}")

    downloaded = 0
    with open(raw_path, 'wb') as f:
        for chunk in audio_resp.iter_content(chunk_size=8192):
            downloaded += len(chunk)
            f.write(chunk)
    logger.info(f"Downloaded Spotify audio: {downloaded:,} bytes")

    # Always re-encode to low-bitrate mono for Whisper's 25MB upload limit.
    # 64kbps mono 16kHz is fine for podcast speech and handles ~60min in one shot.
    audio_path = os.path.join(output_dir, f"{episode_id}.mp3")
    logger.info("Re-encoding audio to 64kbps mono 16kHz for Whisper size limit...")
    subprocess.run([
        'ffmpeg', '-i', raw_path, '-vn', '-acodec', 'libmp3lame',
        '-ab', '64k', '-ar', '16000', '-ac', '1', '-y', audio_path
    ], check=True, capture_output=True)
    os.remove(raw_path)
    logger.info(f"Re-encoded size: {os.path.getsize(audio_path):,} bytes")

    # Validate audio
    is_valid, info = _validate_audio(audio_path)
    if not is_valid:
        logger.error(f"Spotify audio validation failed: {info}")
        return None

    logger.info(f"Spotify audio validated: {info}")

    # Save metadata as .info.json
    metadata_path = os.path.join(output_dir, f"{episode_id}.info.json")
    with open(metadata_path, 'w') as f:
        json.dump(data, f, indent=2, default=str)

    return {
        "video_id": episode_id,
        "title": title,
        "audio_file": audio_path,
        "video_file": None,
        "metadata_file": metadata_path,
        "video_url": play_url,
        "thumbnail_url": cover_url,
    }


MAX_DIRECT_VIDEO_BYTES = 500 * 1024 * 1024  # 500 MB

def download_direct_video(url: str, output_dir: str):
    """Download a direct video URL (e.g. LinkedIn CDN mp4) and extract audio."""
    try:
        video_id = hashlib.md5(url.encode()).hexdigest()[:12]
        title = "Direct Video"

        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        }

        logger.info(f"Downloading direct video URL: {url}")
        response = requests.get(url, timeout=120, stream=True, headers=headers)
        response.raise_for_status()

        # Validate content type
        content_type = response.headers.get('Content-Type', '')
        if content_type and not content_type.startswith(('video/', 'application/octet-stream')):
            logger.error(f"Direct video download got unexpected Content-Type: {content_type}")
            return None

        # Check content length if provided
        content_length = response.headers.get('Content-Length')
        if content_length and int(content_length) > MAX_DIRECT_VIDEO_BYTES:
            logger.error(f"Direct video too large: {int(content_length)} bytes")
            return None

        video_path = os.path.join(output_dir, f"{video_id}.mp4")
        downloaded = 0
        with open(video_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                downloaded += len(chunk)
                if downloaded > MAX_DIRECT_VIDEO_BYTES:
                    logger.error(f"Direct video exceeded {MAX_DIRECT_VIDEO_BYTES} byte limit during download")
                    f.close()
                    os.remove(video_path)
                    return None
                f.write(chunk)

        logger.info(f"Direct video downloaded: {video_path} ({downloaded} bytes)")

        # Extract audio using ffmpeg
        audio_path = os.path.join(output_dir, f"{video_id}.mp3")
        subprocess.run([
            'ffmpeg', '-i', video_path, '-vn', '-acodec', 'libmp3lame',
            '-ab', '192k', '-ar', '44100', '-y', audio_path
        ], check=True, capture_output=True)

        logger.info(f"Audio extracted: {audio_path}")

        return {
            "video_id": video_id,
            "title": title,
            "audio_file": audio_path,
            "video_file": video_path,
            "metadata_file": None,
            "video_url": url
        }

    except Exception as e:
        logger.error(f"Direct video download failed: {e}")
        return None

def download_tiktok(url: str, output_dir: str, proxy=None):
    """Download video with platform-aware fallback chain.

    Supported platforms:
    - TikTok: TikTok RapidAPI -> yt-dlp
    - YouTube: YouTube RapidAPI -> yt-dlp
    - Instagram: Instagram RapidAPI -> yt-dlp
    - Facebook: Facebook RapidAPI -> yt-dlp
    - Spotify: Spotify RapidAPI (no yt-dlp fallback for podcasts)
    - X/Twitter, Reddit, Vimeo, Twitch, LinkedIn, Threads, Loom: yt-dlp
    """

    # Clean URL before processing (tracking params and trailing punctuation)
    clean_url = clean_url_trailing_punctuation(clean_url_for_api(url))

    # Detect platform using comprehensive detection
    platform = _detect_platform(clean_url)
    logger.info(f"Detected platform: {platform} for URL: {clean_url}")

    # Method 1: Try platform-specific RapidAPI first
    rapidapi_result = None

    if platform == 'spotify':
        logger.info("Attempting Spotify RapidAPI download...")
        rapidapi_result = download_spotify_rapidapi(url, output_dir)
        if rapidapi_result:
            rapidapi_result['platform'] = 'spotify'
            logger.info("Spotify RapidAPI download successful!")
            return rapidapi_result
        logger.warning("Spotify RapidAPI failed, falling back to yt-dlp...")

    elif platform == 'youtube':
        logger.info("Attempting YouTube RapidAPI download...")
        rapidapi_result = download_youtube_rapidapi(url)
        if rapidapi_result:
            rapidapi_result['platform'] = 'youtube'
            logger.info("YouTube RapidAPI download successful!")
            return rapidapi_result
        logger.warning("YouTube RapidAPI failed, falling back to yt-dlp...")

    elif platform == 'tiktok':
        logger.info("Attempting TikTok RapidAPI download...")
        rapidapi_result = download_tiktok_rapidapi(url, output_dir)
        if rapidapi_result:
            rapidapi_result['platform'] = 'tiktok'
            logger.info("TikTok RapidAPI download successful!")
            return rapidapi_result
        logger.warning("TikTok RapidAPI failed, falling back to yt-dlp...")

    elif platform == 'instagram':
        logger.info("Attempting Instagram RapidAPI download...")
        rapidapi_result = download_instagram_rapidapi(url, output_dir)
        if rapidapi_result:
            rapidapi_result['platform'] = 'instagram'
            logger.info("Instagram RapidAPI download successful!")
            return rapidapi_result
        logger.warning("Instagram RapidAPI failed, falling back to yt-dlp...")

    elif platform == 'facebook':
        logger.info("Attempting Facebook RapidAPI download...")
        rapidapi_result = download_facebook_rapidapi(url, output_dir)
        if rapidapi_result:
            rapidapi_result['platform'] = 'facebook'
            logger.info("Facebook RapidAPI download successful!")
            return rapidapi_result
        logger.warning("Facebook RapidAPI failed, falling back to yt-dlp...")

    elif _is_direct_video_url(clean_url):
        logger.info("Direct video URL detected, downloading directly...")
        direct_result = download_direct_video(clean_url, output_dir)
        if direct_result:
            direct_result['platform'] = canonical_platform(clean_url, platform)
            return direct_result
        logger.error("Direct video download failed — no fallback for raw CDN URLs")
        return None

    else:
        # For X/Twitter, Reddit, Vimeo, Twitch, LinkedIn, Threads, Loom - go straight to yt-dlp
        logger.info(f"Platform '{platform}' uses yt-dlp directly...")

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
            "video_url": None,  # yt-dlp doesn't provide direct video URL
            "platform": canonical_platform(clean_url, platform)
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

WHISPER_MAX_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB OpenAI limit
WHISPER_REENCODE_THRESHOLD = 24 * 1024 * 1024  # Re-encode if over 24 MB
CHUNK_DURATION_SECONDS = 600  # 10-minute chunks for splitting

# Language detection settings
DEFAULT_LANGUAGE = os.environ.get("TRANSCRIBE_DEFAULT_LANGUAGE", "en")
LANGUAGE_DETECTION_SAMPLE_SECONDS = 30  # ~30s sample for language detection
LANGUAGE_DETECTION_SKIP_SECONDS = 60  # Skip first minute if audio is long enough
LANGUAGE_DETECTION_MIN_CONFIDENCE = 0.5  # Minimum confidence to trust detected language

# ISO 639-1 language codes Whisper supports (subset of most common)
WHISPER_SUPPORTED_LANGUAGES = {
    'en', 'zh', 'de', 'es', 'ru', 'ko', 'fr', 'ja', 'pt', 'tr', 'pl', 'ca',
    'nl', 'ar', 'sv', 'it', 'id', 'hi', 'fi', 'vi', 'he', 'uk', 'el', 'ms',
    'cs', 'ro', 'da', 'hu', 'ta', 'no', 'th', 'ur', 'hr', 'bg', 'lt', 'la',
    'mi', 'ml', 'cy', 'sk', 'te', 'fa', 'lv', 'bn', 'sr', 'az', 'sl', 'kn',
    'et', 'mk', 'br', 'eu', 'is', 'hy', 'ne', 'mn', 'bs', 'kk', 'sq', 'sw',
    'gl', 'mr', 'pa', 'si', 'km', 'sn', 'yo', 'so', 'af', 'oc', 'ka', 'be',
    'tg', 'sd', 'gu', 'am', 'yi', 'lo', 'uz', 'fo', 'ht', 'ps', 'tk', 'nn',
    'mt', 'sa', 'lb', 'my', 'bo', 'tl', 'mg', 'as', 'tt', 'haw', 'ln', 'ha',
    'ba', 'jw', 'su',
}


def _get_audio_duration(audio_path: str) -> float:
    """Get audio duration in seconds using ffprobe."""
    try:
        probe = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', audio_path],
            capture_output=True, text=True, timeout=10
        )
        if probe.returncode == 0 and probe.stdout.strip():
            return float(probe.stdout.strip())
    except Exception as e:
        logger.warning(f"Could not get audio duration: {e}")
    return 0.0


def _extract_language_from_metadata(metadata_file: str) -> str | None:
    """Extract language code from yt-dlp or RapidAPI metadata file.
    
    Returns ISO 639-1 language code if found, None otherwise.
    Handles various metadata formats from different platforms.
    """
    if not metadata_file or not os.path.exists(metadata_file):
        return None
    
    try:
        with open(metadata_file, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
        
        # Try various fields where language might be stored
        # yt-dlp format
        lang = metadata.get('language')
        if lang and isinstance(lang, str):
            code = lang[:2].lower()
            if code in WHISPER_SUPPORTED_LANGUAGES:
                logger.info(f"Found language in metadata: {lang} -> {code}")
                return code
        
        # Spotify format (in nested 'data' or directly)
        data = metadata.get('data', metadata)
        if isinstance(data, dict):
            # Spotify languages array
            languages = data.get('languages', [])
            if languages and isinstance(languages, list) and len(languages) > 0:
                code = languages[0][:2].lower() if isinstance(languages[0], str) else None
                if code and code in WHISPER_SUPPORTED_LANGUAGES:
                    logger.info(f"Found language in Spotify metadata: {code}")
                    return code
            
            # Direct language field
            lang = data.get('language')
            if lang and isinstance(lang, str):
                code = lang[:2].lower()
                if code in WHISPER_SUPPORTED_LANGUAGES:
                    logger.info(f"Found language in data.language: {code}")
                    return code
        
        # YouTube RapidAPI format
        if 'lang' in metadata:
            code = metadata['lang'][:2].lower() if isinstance(metadata['lang'], str) else None
            if code and code in WHISPER_SUPPORTED_LANGUAGES:
                logger.info(f"Found language from RapidAPI lang field: {code}")
                return code
        
    except Exception as e:
        logger.warning(f"Error reading metadata for language extraction: {e}")
    
    return None


def _extract_audio_sample(audio_path: str, output_dir: str, video_id: str) -> str | None:
    """Extract a ~30s sample from the middle of audio for language detection.
    
    For longer audio (>2 min), skips the first minute to avoid music/silence intros.
    Returns path to sample file, or None if extraction fails.
    """
    duration = _get_audio_duration(audio_path)
    
    if duration <= 0:
        logger.warning("Cannot extract sample: unknown duration")
        return None
    
    # For short audio (<90s), just use the whole thing
    if duration < 90:
        logger.info(f"Audio is short ({duration:.1f}s), using full file for language detection")
        return audio_path
    
    # Calculate sample start position - skip intro if possible
    if duration > 120:  # Longer than 2 minutes
        start_time = min(LANGUAGE_DETECTION_SKIP_SECONDS, duration / 3)
    else:
        start_time = duration / 4  # Start at 25% for shorter audio
    
    # Ensure we don't exceed audio duration
    sample_duration = min(LANGUAGE_DETECTION_SAMPLE_SECONDS, duration - start_time)
    
    sample_path = os.path.join(output_dir, f"{video_id}_lang_sample.mp3")
    
    try:
        cmd = [
            'ffmpeg', '-i', audio_path,
            '-ss', str(start_time),
            '-t', str(sample_duration),
            '-vn', '-acodec', 'libmp3lame',
            '-ab', '64k', '-ar', '16000', '-ac', '1',
            '-y', sample_path
        ]
        subprocess.run(cmd, check=True, capture_output=True, timeout=30)
        
        if os.path.exists(sample_path) and os.path.getsize(sample_path) > 100:
            logger.info(f"Extracted {sample_duration:.1f}s sample starting at {start_time:.1f}s for language detection")
            return sample_path
    except Exception as e:
        logger.warning(f"Failed to extract audio sample: {e}")
    
    return None


def _detect_language_from_sample(audio_path: str, output_dir: str, video_id: str) -> tuple[str | None, float]:
    """Detect language from an audio sample using Whisper verbose_json.
    
    Returns (language_code, confidence) tuple.
    Confidence is 0.0-1.0 based on how consistent the detected language is.
    """
    if client is None:
        logger.warning("Cannot detect language: OpenAI client not initialized")
        return None, 0.0
    
    # Extract a representative sample from the middle of the audio
    sample_path = _extract_audio_sample(audio_path, output_dir, video_id)
    if not sample_path:
        return None, 0.0
    
    is_sample_file = sample_path != audio_path
    
    try:
        with open(sample_path, "rb") as audio:
            response = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio,
                response_format="verbose_json"
            )
        
        # Extract detected language
        detected_lang = None
        if hasattr(response, 'language'):
            detected_lang = response.language
        elif isinstance(response, dict) and 'language' in response:
            detected_lang = response['language']
        
        if not detected_lang:
            logger.warning("Whisper did not return language in response")
            return None, 0.0
        
        # Normalize to ISO 639-1 (Whisper returns full names sometimes)
        lang_code = detected_lang[:2].lower() if len(detected_lang) >= 2 else detected_lang.lower()
        
        # Validate it's a supported language
        if lang_code not in WHISPER_SUPPORTED_LANGUAGES:
            logger.warning(f"Detected language '{detected_lang}' not in supported list")
            return None, 0.0
        
        # Calculate confidence based on transcript content
        confidence = 1.0
        text = ""
        if hasattr(response, 'text'):
            text = response.text or ""
        elif isinstance(response, dict):
            text = response.get('text', '')
        
        # Low confidence if transcript is very short or empty
        if len(text.strip()) < 50:
            confidence = 0.3
            logger.info(f"Low confidence ({confidence}) due to short transcript ({len(text.strip())} chars)")
        elif len(text.strip()) < 200:
            confidence = 0.6
        
        logger.info(f"Detected language from sample: {lang_code} (confidence: {confidence:.2f})")
        return lang_code, confidence
        
    except Exception as e:
        logger.warning(f"Language detection failed: {e}")
        return None, 0.0
    finally:
        # Clean up sample file
        if is_sample_file and os.path.exists(sample_path):
            try:
                os.remove(sample_path)
            except:
                pass


def _get_language_for_transcription(
    audio_path: str, 
    output_dir: str, 
    video_id: str, 
    metadata_file: str | None = None
) -> str:
    """Determine the language to use for transcription.
    
    Priority order:
    1. Language from metadata (yt-dlp/RapidAPI) if available
    2. Language detected from audio sample (if confidence >= threshold)
    3. Default language (TRANSCRIBE_DEFAULT_LANGUAGE env var, defaults to 'en')
    
    Returns ISO 639-1 language code to pass to Whisper.
    """
    # Try metadata first
    metadata_lang = _extract_language_from_metadata(metadata_file)
    if metadata_lang:
        logger.info(f"Using language from metadata: {metadata_lang}")
        return metadata_lang
    
    # Try detecting from audio sample
    detected_lang, confidence = _detect_language_from_sample(audio_path, output_dir, video_id)
    
    if detected_lang and confidence >= LANGUAGE_DETECTION_MIN_CONFIDENCE:
        logger.info(f"Using detected language: {detected_lang} (confidence: {confidence:.2f})")
        return detected_lang
    
    # Fall back to default
    if detected_lang:
        logger.info(f"Detected language {detected_lang} has low confidence ({confidence:.2f}), falling back to default: {DEFAULT_LANGUAGE}")
    else:
        logger.info(f"No language detected, using default: {DEFAULT_LANGUAGE}")
    
    return DEFAULT_LANGUAGE


def _prepare_audio_for_whisper(audio_path: str, output_dir: str, video_id: str) -> str:
    """Re-encode audio to 64kbps mono 16kHz mp3 if needed for Whisper size limit.
    
    Uses the same encoding settings as Spotify audio preparation.
    Returns path to the prepared audio file (may be same as input if already small enough).
    """
    if not os.path.exists(audio_path):
        return audio_path
    
    file_size = os.path.getsize(audio_path)
    if file_size <= WHISPER_REENCODE_THRESHOLD:
        logger.info(f"Audio file under re-encode threshold: {file_size:,} bytes")
        return audio_path
    
    logger.info(f"Audio file over {WHISPER_REENCODE_THRESHOLD:,} bytes ({file_size:,}), re-encoding to 64kbps mono 16kHz...")
    
    prepared_path = os.path.join(output_dir, f"{video_id}_whisper.mp3")
    
    try:
        subprocess.run([
            'ffmpeg', '-i', audio_path, '-vn',
            '-acodec', 'libmp3lame',
            '-ab', '64k',
            '-ar', '16000',
            '-ac', '1',
            '-y', prepared_path
        ], check=True, capture_output=True, timeout=300)
        
        new_size = os.path.getsize(prepared_path)
        logger.info(f"Re-encoded audio: {file_size:,} -> {new_size:,} bytes (64kbps mono 16kHz)")
        
        if new_size <= WHISPER_MAX_SIZE_BYTES:
            return prepared_path
        else:
            logger.warning(f"Re-encoded file still too large ({new_size:,} bytes), will need to chunk")
            return prepared_path
            
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to re-encode audio: {e.stderr.decode() if e.stderr else e}")
        return audio_path


def _split_audio_into_chunks(audio_path: str, output_dir: str, video_id: str, 
                             chunk_duration: int = CHUNK_DURATION_SECONDS) -> list:
    """Split audio file into chunks for transcription.
    
    If any chunk exceeds the size limit, recursively tries with 10% smaller chunks
    (matching the approach in local_scripts/downloader.py).
    
    Returns list of (chunk_path, start_time_seconds) tuples.
    """
    duration = _get_audio_duration(audio_path)
    
    if duration <= 0:
        logger.warning("Could not determine audio duration, returning single file")
        return [(audio_path, 0.0)]
    
    num_chunks = max(1, int(duration / chunk_duration) + (1 if duration % chunk_duration > 0 else 0))
    
    if num_chunks == 1:
        return [(audio_path, 0.0)]
    
    logger.info(f"Splitting {duration:.1f}s audio into {num_chunks} chunks of ~{chunk_duration}s each")
    
    chunks = []
    for i in range(num_chunks):
        start_time = i * chunk_duration
        chunk_path = os.path.join(output_dir, f"{video_id}_chunk_{i:03d}.mp3")
        
        try:
            cmd = [
                'ffmpeg', '-i', audio_path,
                '-ss', str(start_time),
                '-t', str(chunk_duration),
                '-vn', '-acodec', 'libmp3lame',
                '-ab', '64k', '-ar', '16000', '-ac', '1',
                '-y', chunk_path
            ]
            subprocess.run(cmd, check=True, capture_output=True, timeout=120)
            
            if os.path.exists(chunk_path) and os.path.getsize(chunk_path) > 100:
                chunk_size = os.path.getsize(chunk_path)
                
                # If chunk is still too large, reduce chunk duration by 10% and retry
                if chunk_size > WHISPER_MAX_SIZE_BYTES:
                    logger.warning(f"Chunk {i} too large ({chunk_size:,} bytes), reducing chunk duration by 10%")
                    # Clean up oversized chunks
                    for cp, _ in chunks:
                        if cp != audio_path:
                            try:
                                os.remove(cp)
                            except:
                                pass
                    try:
                        os.remove(chunk_path)
                    except:
                        pass
                    # Retry with smaller chunks
                    new_duration = int(chunk_duration * 0.9)
                    if new_duration < 60:  # Don't go below 1 minute
                        logger.error("Chunk duration too small, cannot split further")
                        return [(audio_path, 0.0)]
                    return _split_audio_into_chunks(audio_path, output_dir, video_id, new_duration)
                
                logger.info(f"Created chunk {i}: {chunk_size:,} bytes, starts at {start_time}s")
                chunks.append((chunk_path, float(start_time)))
            else:
                logger.warning(f"Chunk {i} was empty or too small, skipping")
                
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to create chunk {i}: {e}")
    
    if not chunks:
        logger.warning("No chunks created, falling back to original file")
        return [(audio_path, 0.0)]
    
    return chunks


def _transcribe_single_chunk(audio_path: str, time_offset: float = 0.0, language: str | None = None) -> tuple:
    """Transcribe a single audio chunk and return (response, duration) with adjusted timestamps.
    
    Args:
        audio_path: Path to audio chunk file
        time_offset: Cumulative duration offset for timestamp adjustment
        language: ISO 639-1 language code to pass to Whisper (avoids auto-detection per chunk)
    
    Offsets segment timestamps by cumulative duration (matching downloader.py approach).
    """
    if client is None:
        return None, 0
    
    try:
        with open(audio_path, "rb") as audio:
            # Build transcription kwargs
            transcribe_kwargs = {
                "model": "whisper-1",
                "file": audio,
                "response_format": "verbose_json"
            }
            # Pass language if provided to ensure consistent language across chunks
            if language:
                transcribe_kwargs["language"] = language
                logger.debug(f"Transcribing chunk with language hint: {language}")
            
            response = client.audio.transcriptions.create(**transcribe_kwargs)
        
        # Get chunk duration for cumulative offset tracking
        chunk_duration = 0
        if hasattr(response, 'duration'):
            chunk_duration = response.duration
        elif isinstance(response, dict) and 'duration' in response:
            chunk_duration = response['duration']
        
        # Offset timestamps by time_offset (cumulative duration of previous chunks)
        if time_offset > 0:
            if hasattr(response, 'segments') and response.segments:
                for segment in response.segments:
                    if hasattr(segment, 'start'):
                        segment.start += time_offset
                        segment.end += time_offset
                    elif isinstance(segment, dict):
                        segment['start'] = segment.get('start', 0) + time_offset
                        segment['end'] = segment.get('end', 0) + time_offset
            elif isinstance(response, dict) and 'segments' in response:
                for segment in response['segments']:
                    segment['start'] = segment.get('start', 0) + time_offset
                    segment['end'] = segment.get('end', 0) + time_offset
        
        return response, chunk_duration
    except Exception as e:
        logger.error(f"Error transcribing chunk: {e}")
        return None, 0


def _stitch_transcriptions(chunk_responses: list, language: str | None = None) -> dict:
    """Combine multiple chunk transcription responses into a single response.
    
    Args:
        chunk_responses: List of transcription responses from individual chunks
        language: The language code that was used for transcription (reported in output)
    """
    if not chunk_responses:
        return None
    
    if len(chunk_responses) == 1:
        response = chunk_responses[0]
        # Ensure language is set in single-response case (use provided or default)
        if isinstance(response, dict):
            response['language'] = language or DEFAULT_LANGUAGE
        return response
    
    all_segments = []
    all_text_parts = []
    total_duration = 0
    
    for response in chunk_responses:
        if response is None:
            continue
            
        if hasattr(response, 'segments') and response.segments:
            # Convert segment objects to dicts for consistency
            for seg in response.segments:
                if hasattr(seg, 'start'):
                    all_segments.append({
                        'start': seg.start,
                        'end': seg.end,
                        'text': seg.text
                    })
                else:
                    all_segments.append(seg)
            all_text_parts.append(response.text or "")
            if hasattr(response, 'duration'):
                total_duration += response.duration
        elif isinstance(response, dict):
            all_segments.extend(response.get('segments', []))
            all_text_parts.append(response.get('text', ''))
            if 'duration' in response:
                total_duration += response['duration']
    
    # Use the provided language, or fall back to default
    final_language = language or DEFAULT_LANGUAGE
    
    combined = {
        'text': ' '.join(all_text_parts),
        'segments': all_segments,
        'duration': total_duration,
        'language': final_language
    }
    
    logger.info(f"Stitched {len(chunk_responses)} chunks: {len(all_segments)} segments, {len(combined['text'])} chars, {total_duration:.1f}s, language: {final_language}")
    return combined


def transcribe_audio(audio_file: str, output_dir: str, video_id: str, user_phone: str = None, task_id: str = None, metadata_file: str = None):
    """Transcribe audio file using OpenAI Whisper, always requesting verbose_json.
    
    Handles files larger than 25MB by:
    1. Re-encoding to 64kbps mono 16kHz mp3 (same as Spotify handling)
    2. If still too large, splitting into 10-minute chunks with timestamp offsets
    
    Language detection:
    - Uses language from metadata (yt-dlp/RapidAPI) if available
    - Otherwise detects language ONCE from a representative sample
    - Falls back to TRANSCRIBE_DEFAULT_LANGUAGE env var (default 'en') if detection fails
    - The same language is passed to all chunks to ensure consistency
    
    Args:
        audio_file: Path to the audio file to transcribe
        output_dir: Directory for temporary files and output
        video_id: Unique identifier for the video
        user_phone: Optional user phone for cost tracking
        task_id: Optional task ID for cost tracking
        metadata_file: Optional path to metadata JSON file for language extraction
    """
    if client is None:
        logger.error("Cannot transcribe audio: OpenAI client not initialized")
        return None, None

    try:
        # Validate audio before sending to Whisper
        audio_valid, audio_info = _validate_audio(audio_file)
        audio_file_size = os.path.getsize(audio_file) if os.path.exists(audio_file) else None
        logger.info(f"Transcribing audio file: {audio_file} ({audio_info})")
        if not audio_valid:
            logger.error(f"Audio file is not valid, skipping Whisper call: {audio_info}")
            return None, None

        # Detect language ONCE before any transcription
        # Priority: metadata language > detected from sample > default (env var or 'en')
        transcription_language = _get_language_for_transcription(
            audio_file, output_dir, video_id, metadata_file
        )
        logger.info(f"Using language for transcription: {transcription_language}")

        # Prepare audio for Whisper size limit (re-encode to 64kbps mono 16kHz if needed)
        prepared_audio = _prepare_audio_for_whisper(audio_file, output_dir, video_id)
        prepared_size = os.path.getsize(prepared_audio) if os.path.exists(prepared_audio) else 0
        
        # If still too large after re-encoding, split into chunks
        if prepared_size > WHISPER_MAX_SIZE_BYTES:
            logger.info(f"Audio still too large after re-encoding ({prepared_size:,} bytes), splitting into chunks...")
            chunks = _split_audio_into_chunks(prepared_audio, output_dir, video_id)
            
            chunk_responses = []
            cumulative_duration = 0.0
            for chunk_path, _ in chunks:
                chunk_size = os.path.getsize(chunk_path) if os.path.exists(chunk_path) else 0
                logger.info(f"Transcribing chunk at cumulative offset {cumulative_duration:.1f}s ({chunk_size:,} bytes)")
                
                # Use cumulative duration for offset and pass consistent language to all chunks
                response, chunk_duration = _transcribe_single_chunk(
                    chunk_path, cumulative_duration, language=transcription_language
                )
                if response:
                    chunk_responses.append(response)
                    cumulative_duration += chunk_duration
                
                # Clean up chunk file
                if chunk_path != prepared_audio and chunk_path != audio_file:
                    try:
                        os.remove(chunk_path)
                    except:
                        pass
            
            if not chunk_responses:
                logger.error("All chunk transcriptions failed")
                return None, None
            
            # Pass the detected language to stitching so it's reported correctly
            transcript_response = _stitch_transcriptions(chunk_responses, language=transcription_language)
            duration_seconds = cumulative_duration
            logger.info(f"Chunked transcription complete: {len(chunk_responses)} chunks, {duration_seconds:.1f}s total, language: {transcription_language}")
        else:
            # Normal path: single transcription with language hint
            openai_format = "verbose_json"
            
            with open(prepared_audio, "rb") as audio:
                transcript_response = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio,
                    response_format=openai_format,
                    language=transcription_language
                )
            
            # Extract duration for cost tracking
            duration_seconds = 0
            if hasattr(transcript_response, 'duration'):
                duration_seconds = transcript_response.duration
            elif isinstance(transcript_response, dict) and 'duration' in transcript_response:
                duration_seconds = transcript_response['duration']
        
        # Clean up prepared audio if different from original
        if prepared_audio != audio_file and os.path.exists(prepared_audio):
            try:
                os.remove(prepared_audio)
            except:
                pass

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
- EACH BULLET MUST BE UNDER 70 CHARACTERS. Be punchy, not wordy.
- Focus on what someone could actually DO or specific perspectives they shared
- Write conversationally, like you're telling a friend the good parts
- Think tweet-length: short, sharp, memorable

Respond STRICTLY in this JSON format (no other text):
{{
  "quote": "the most memorable, shareable line that captures their unique take",
  "tldr": ["Short punchy insight #1", "Actionable takeaway #2", "Key perspective #3", "Bonus point #4 if needed"]
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
            model="gpt-4.1-mini",
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
                model="gpt-4.1-mini",
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
                model="gpt-4.1-mini",
                user_phone=user_phone,
                task_id=task_id,
                purpose="quote_tldr",
                success=False,
                error_message=str(e)
            ))
        except ImportError:
            pass
        return {"quote": None, "tldr": None} 
