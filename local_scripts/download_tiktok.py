import sys
import os
from datetime import datetime
import yt_dlp
import openai
import json

def download_tiktok(url: str) -> None:
    """Download a single TikTok video and transcribe its audio."""
    
    # Create output directory with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = f"downloads/tiktok_{timestamp}"
    os.makedirs(output_dir, exist_ok=True)
    
    # Configure yt-dlp options
    ydl_opts = {
        'format': 'best',  # Download best quality
        'outtmpl': os.path.join(output_dir, '%(id)s.%(ext)s'),  # Output template
        'writeinfojson': True,  # Save video metadata
        'writethumbnail': True,  # Save thumbnail
        'extract_audio': True,  # Extract audio
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
        }],
        'quiet': False,  # Show progress
        'no_warnings': False,
        'extract_flat': False
    }
    
    try:
        print(f"\nDownloading video from: {url}")
        print(f"Output directory: {output_dir}\n")
        
        # Download video and extract audio
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            video_id = info['id']
        
        # Find the MP3 file
        mp3_file = None
        for file in os.listdir(output_dir):
            if file.endswith(".mp3"):
                mp3_file = os.path.join(output_dir, file)
                break
        
        if mp3_file:
            print("\nTranscribing audio...")
            # Open the audio file
            with open(mp3_file, "rb") as audio_file:
                # Transcribe using OpenAI's Whisper
                client = openai.OpenAI()
                transcript = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    response_format="text"
                )
            
            # Save transcript
            transcript_file = os.path.join(output_dir, f"{video_id}_transcript.txt")
            with open(transcript_file, "w", encoding="utf-8") as f:
                f.write(transcript)
            
            print("Transcript saved to:", transcript_file)
            
        print(f"\nDownload completed successfully!")
        print(f"Files saved in: {output_dir}")
        
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python download_tiktok.py <tiktok_url>")
        sys.exit(1)
        
    url = sys.argv[1]
    download_tiktok(url) 