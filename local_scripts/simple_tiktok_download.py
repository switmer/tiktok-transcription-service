import os
import sys
import json
from datetime import datetime
import yt_dlp
import openai

# Initialize OpenAI client
client = openai.OpenAI()  # Will use OPENAI_API_KEY from environment

def create_output_directory(video_id):
    """Create output directory for the downloaded content"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = f"downloads/tiktok_{video_id}_{timestamp}"
    os.makedirs(output_dir, exist_ok=True)
    return output_dir

def download_tiktok(url, output_dir):
    """Download TikTok video and extract audio"""
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'outtmpl': os.path.join(output_dir, '%(id)s.%(ext)s'),
        'writeinfojson': True,  # Save video metadata
        'writethumbnail': True,  # Save video thumbnail
        'quiet': False,
    }
    
    try:
        # First extract info without downloading
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            video_id = info.get('id')
            title = info.get('title')
            print(f"Video ID: {video_id}")
            print(f"Title: {title}")
        
        # Download the video/audio
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            print(f"Downloading video from: {url}")
            ydl.download([url])
        
        # Find the downloaded mp3 file
        mp3_file = None
        for file in os.listdir(output_dir):
            if file.endswith('.mp3'):
                mp3_file = os.path.join(output_dir, file)
                break
        
        return mp3_file, video_id
    
    except Exception as e:
        print(f"Error downloading video: {str(e)}")
        return None, None

def transcribe_audio(audio_file, output_dir, video_id):
    """Transcribe audio file using OpenAI's Whisper API"""
    try:
        print(f"Transcribing audio file: {audio_file}")
        with open(audio_file, "rb") as audio:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio,
                response_format="text"
            )
        
        # Save transcript to file
        transcript_file = os.path.join(output_dir, f"{video_id}_transcript.txt")
        with open(transcript_file, "w", encoding="utf-8") as f:
            f.write(transcript)
        
        print(f"Transcript saved to: {transcript_file}")
        return transcript, transcript_file
    
    except Exception as e:
        print(f"Error transcribing audio: {str(e)}")
        return None, None

def main():
    if len(sys.argv) != 2:
        print("Usage: python simple_tiktok_download.py <tiktok_url>")
        sys.exit(1)
    
    url = sys.argv[1]
    
    print(f"Processing TikTok video: {url}")
    
    # Get video ID for naming
    try:
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            video_id = info.get('id')
    except Exception as e:
        print(f"Error getting video info: {str(e)}")
        sys.exit(1)
    
    # Create output directory
    output_dir = create_output_directory(video_id)
    print(f"Output directory: {output_dir}")
    
    # Download video and extract audio
    mp3_file, video_id = download_tiktok(url, output_dir)
    
    if not mp3_file:
        print("Failed to download video or extract audio")
        sys.exit(1)
    
    # Transcribe audio
    transcript, transcript_file = transcribe_audio(mp3_file, output_dir, video_id)
    
    if not transcript:
        print("Failed to transcribe audio")
        sys.exit(1)
    
    # Print transcript
    print("\n--- TRANSCRIPT ---")
    print(transcript)
    print("--- END TRANSCRIPT ---\n")
    
    print(f"Process completed. Files saved in: {output_dir}")

if __name__ == "__main__":
    main() 