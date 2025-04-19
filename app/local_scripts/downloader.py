import yt_dlp
import argparse
import logging
import os
import json
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from pydub import AudioSegment
import shutil
from datetime import datetime
import re
from textblob import TextBlob
from rake_nltk import Rake
from langdetect import detect
import cv2
import subprocess

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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

def my_hook(d):
    if d['status'] == 'downloading':
        print(f"\rDownloading: {d['filename']} | {d['_percent_str']} of {d['_total_bytes_str']} at {d['_speed_str']}", end='', flush=True)
    elif d['status'] == 'finished':
        print(f"\nFinished downloading {d['filename']}")

def split_audio(file_path, chunk_length_ms=600000, max_size_bytes=25*1024*1024):
    audio = AudioSegment.from_mp3(file_path)
    chunks = []
    for i, chunk in enumerate(audio[::chunk_length_ms]):
        chunk_path = f"{file_path[:-4]}_chunk{i}.mp3"
        chunk.export(chunk_path, format="mp3")
        if os.path.getsize(chunk_path) > max_size_bytes:
            os.remove(chunk_path)
            chunk_length_ms = int(chunk_length_ms * 0.9)  # Reduce chunk size by 10%
            return split_audio(file_path, chunk_length_ms, max_size_bytes)
        chunks.append(chunk_path)
    return chunks

def transcribe_audio(file_path):
    audio = AudioSegment.from_mp3(file_path)
    duration_seconds = len(audio) / 1000  # pydub works in milliseconds

    with open(file_path, "rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            response_format="verbose_json"
        )
    return transcript.model_dump(), duration_seconds

def format_transcript(transcript):
    formatted_transcript = []
    current_time = 0
    timestamp_interval = 30  # Add a timestamp every 30 seconds

    logging.info(f"Transcript object type: {type(transcript)}")
    logging.info(f"Transcript content: {transcript}")

    segments = transcript.get('segments', [])
    logging.info(f"Number of segments: {len(segments)}")

    # Always start with 00:00 timestamp
    formatted_transcript.append(f"\n{format_timestamp(0)}")

    for segment in segments:
        start = int(float(segment.get('start', 0)))
        
        # Add a timestamp if we've passed the interval
        while start >= current_time + timestamp_interval:
            current_time += timestamp_interval
            formatted_transcript.append(f"\n{format_timestamp(current_time)}")
        
        text = segment.get('text', '').strip()
        formatted_transcript.append(f"- {text}")

    if len(formatted_transcript) == 1:  # Only the 00:00 timestamp
        formatted_transcript.append("No transcript content available.")

    return "\n".join(formatted_transcript)

def format_timestamp(seconds):
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

def sanitize_filename(filename):
    # Remove invalid characters
    sanitized = re.sub(r'[\\/*?:"<>|]', "", filename)
    # Replace spaces with underscores
    sanitized = sanitized.replace(' ', '_')
    # Take only the first 50 characters to avoid "filename too long" error
    sanitized = sanitized[:50]
    return sanitized

def create_job_folder(title):
    folder_name = sanitize_filename(title)
    if os.path.exists(folder_name):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder_name = f"{folder_name}_{timestamp}"
    os.makedirs(folder_name, exist_ok=True)
    return folder_name

def perform_llm_analysis(text, task):
    print(f"Performing {task} analysis using LLM...")
    # Create a temporary JSON file with the text
    with open('temp_input.json', 'w') as f:
        json.dump({"text": text}, f)
    
    # Call the Node.js script
    result = subprocess.run(['node', 'llm_analysis.js', task], capture_output=True, text=True)
    
    # Remove the temporary file
    os.remove('temp_input.json')
    
    if result.returncode != 0:
        print(f"Error in LLM analysis: {result.stderr}")
        return None
    
    return result.stdout.strip()

def extract_video_metadata(job_folder):
    print("Extracting video metadata...")
    json_files = [f for f in os.listdir(job_folder) if f.endswith('.info.json')]
    if json_files:
        with open(os.path.join(job_folder, json_files[0]), 'r') as f:
            return json.load(f)
    return None

def extract_thumbnail(job_folder):
    print("Extracting thumbnail...")
    video_files = [f for f in os.listdir(job_folder) if f.endswith('.mp4')]
    if video_files:
        video_path = os.path.join(job_folder, video_files[0])
        vidcap = cv2.VideoCapture(video_path)
        success, image = vidcap.read()
        if success:
            cv2.imwrite(os.path.join(job_folder, "thumbnail.jpg"), image)
            return "thumbnail.jpg"
    return None

def download_video(url, ydl_opts, args):
    try:
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            print(f"Extracting video info for {url}")
            info = ydl.extract_info(url, download=False)
            title = info['title']

        job_folder = create_job_folder(sanitize_filename(title))
        base_filename = sanitize_filename(title)
        
        ydl_opts.update({
            'outtmpl': os.path.join(job_folder, f'{base_filename}.%(ext)s'),
            'writeinfojson': True,
            'writethumbnail': True
        })

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            print(f"Downloading video: {title}")
            ydl.download([url])

        mp3_filename = next(f for f in os.listdir(job_folder) if f.endswith('.mp3'))
        mp3_path = os.path.join(job_folder, mp3_filename)
        base_filename = os.path.splitext(mp3_filename)[0]

        print(f"Downloaded: {mp3_path}")

        print("Splitting audio into chunks...")
        chunks = split_audio(mp3_path)

        print("Transcribing audio...")
        full_transcription = []
        cumulative_duration = 0
        for i, chunk in enumerate(chunks):
            print(f"Transcribing chunk {i+1}/{len(chunks)}")
            chunk_transcript, chunk_duration = transcribe_audio(chunk)
            if 'segments' in chunk_transcript:
                for segment in chunk_transcript['segments']:
                    segment['start'] += cumulative_duration
                    segment['end'] += cumulative_duration
                full_transcription.extend(chunk_transcript['segments'])
            else:
                print(f"Warning: Unexpected transcript format for chunk {i+1}")
            cumulative_duration += chunk_duration
            os.remove(chunk)

        formatted_transcript = format_transcript({'segments': full_transcription})

        transcript_filename = os.path.join(job_folder, f"{base_filename}_transcript.txt")
        with open(transcript_filename, 'w', encoding='utf-8') as f:
            f.write(formatted_transcript)

        print(f"Formatted transcription saved to: {transcript_filename}")

        # Perform additional analyses based on command-line arguments
        if args.sentiment:
            sentiment = perform_llm_analysis(formatted_transcript, "sentiment")
            if sentiment:
                with open(os.path.join(job_folder, "sentiment_analysis.txt"), "w") as f:
                    f.write(f"Sentiment Analysis: {sentiment}")
                print(f"Sentiment analysis saved: {sentiment}")

        if args.keywords:
            keywords = perform_llm_analysis(formatted_transcript, "keywords")
            if keywords:
                with open(os.path.join(job_folder, "keywords.txt"), "w") as f:
                    f.write(keywords)
                print(f"Keywords extracted and saved: {keywords}")

        if args.language:
            language = detect_language(formatted_transcript)
            with open(os.path.join(job_folder, "language.txt"), "w") as f:
                f.write(f"Detected Language: {language}")
            print(f"Detected language: {language}")

        if args.metadata:
            metadata = extract_video_metadata(job_folder)
            if metadata:
                with open(os.path.join(job_folder, "video_metadata.json"), "w") as f:
                    json.dump(metadata, f, indent=4)
                print("Video metadata extracted and saved")

        if args.thumbnail:
            thumbnail = extract_thumbnail(job_folder)
            if thumbnail:
                print(f"Thumbnail extracted: {thumbnail}")

        return job_folder

    except Exception as e:
        print(f"Error processing {url}: {str(e)}")
        return None

def download_videos_from_file(file_path, ydl_opts, args):
    with open(file_path, 'r') as file:
        urls = file.readlines()
        with ThreadPoolExecutor(max_workers=5) as executor:
            for url in urls:
                executor.submit(download_video, url.strip(), ydl_opts, args)

def parse_arguments():
    parser = argparse.ArgumentParser(description="Video Downloader and Transcriber")
    parser.add_argument("input", help="URL, file containing URLs, or JSON file to parse for URLs in 'Content' fields")
    parser.add_argument("-f", "--format", help="Preferred format (e.g., 'bestaudio/best')")
    parser.add_argument("-o", "--output", help="Output template (e.g., '%(title)s.%(ext)s')")
    parser.add_argument("-c", "--config", help="Path to configuration file (JSON format)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Increase verbosity")
    parser.add_argument("--sentiment", action="store_true", help="Perform sentiment analysis")
    parser.add_argument("--keywords", action="store_true", help="Extract keywords")
    parser.add_argument("--language", action="store_true", help="Detect language")
    parser.add_argument("--metadata", action="store_true", help="Extract video metadata")
    parser.add_argument("--thumbnail", action="store_true", help="Extract video thumbnail")
    return parser.parse_args()

def setup_logging(verbose):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format='%(asctime)s - %(levelname)s - %(message)s')

def load_config(config_path):
    if config_path and os.path.exists(config_path):
        with open(config_path, 'r') as file:
            return json.load(file)
    return {}

def extract_urls_from_json(file_path):
    with open(file_path, 'r') as f:
        data = json.load(f)
    urls = []
    for item in data:
        if 'Content' in item and item['Content'].startswith('https://www.tiktokv.com/share/video/'):
            urls.append(item['Content'])
    return urls

def main():
    args = parse_arguments()
    setup_logging(args.verbose)
    config = load_config(args.config)

    ydl_opts = {
        'format': args.format or config.get('format', 'bestaudio/best'),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'logger': MyLogger(),
        'progress_hooks': [my_hook],
        'noplaylist': True,
        'writeinfojson': True,
    }

    if args.input.endswith('.json'):
        urls = extract_urls_from_json(args.input)
        for url in urls:
            job_folder = download_video(url.strip(), ydl_opts, args)
            if job_folder:
                print(f"Job completed for {url}. Files are in the folder: {job_folder}")
    elif args.input.endswith('.txt'):
        with open(args.input, 'r') as file:
            urls = file.readlines()
        for url in urls:
            job_folder = download_video(url.strip(), ydl_opts, args)
            if job_folder:
                print(f"Job completed for {url.strip()}. Files are in the folder: {job_folder}")
    else:
        job_folder = download_video(args.input, ydl_opts, args)
        if job_folder:
            print(f"Job completed. All files are in the folder: {job_folder}")

if __name__ == "__main__":
    main()