import yt_dlp
import os
import argparse
import json
from datetime import datetime
import re
from pydub import AudioSegment
from openai import OpenAI
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Initialize OpenAI client (replace with your API key)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def sanitize_filename(filename):
    sanitized = re.sub(r'[\\/*?:"<>|]', "", filename)
    sanitized = sanitized.replace(' ', '_')
    return sanitized[:200]

def create_job_folder(title):
    folder_name = sanitize_filename(title)
    if os.path.exists(folder_name):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder_name = f"{folder_name}_{timestamp}"
    os.makedirs(folder_name, exist_ok=True)
    return folder_name

def download_audio(url, output_path):
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'outtmpl': output_path,
        'writeinfojson': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        return True
    except Exception as e:
        logging.error(f"Error downloading audio: {str(e)}")
        return False

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

    try:
        with open(file_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                response_format="verbose_json"
            )
        return transcript.model_dump(), duration_seconds
    except Exception as e:
        logging.error(f"Error transcribing audio: {str(e)}")
        return None, duration_seconds

def format_transcript(transcript):
    formatted_transcript = []
    current_time = 0
    timestamp_interval = 30  # Add a timestamp every 30 seconds

    segments = transcript.get('segments', [])
    formatted_transcript.append(f"\n{format_timestamp(0)}")

    for segment in segments:
        start = int(float(segment.get('start', 0)))
        while start >= current_time + timestamp_interval:
            current_time += timestamp_interval
            formatted_transcript.append(f"\n{format_timestamp(current_time)}")
        text = segment.get('text', '').strip()
        formatted_transcript.append(f"- {text}")

    if len(formatted_transcript) == 1:
        formatted_transcript.append("No transcript content available.")

    return "\n".join(formatted_transcript)

def format_timestamp(seconds):
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

def summarize_fantasy_football(text, title, url, metadata):
    try:
        description = metadata.get('description', '')
        uploader = metadata.get('uploader', '')
        upload_date = metadata.get('upload_date', '')

        prompt = f"""Analyze the following fantasy football podcast/video transcript and provide a comprehensive summary. The content is titled "{title}" and was uploaded by {uploader} on {upload_date}. The URL is {url}.

        Please structure the summary as follows:

        1. Overview: Briefly summarize the main topics discussed in the podcast/video.

        2. Key Player Analysis:
           - Highlight players discussed, including their current performance, potential, and any relevant statistics.
           - Note any changes in player values or roles.

        3. Injury Report:
           - List any injuries mentioned and their potential impact on fantasy teams.

        4. Start/Sit Advice:
           - Summarize any specific start/sit recommendations given for players.
           - Include the reasoning behind these recommendations.

        5. Waiver Wire Picks:
           - List any players recommended for waiver wire pickups.
           - Briefly explain why these players are considered valuable.

        6. Match-up Analysis:
           - Highlight any favorable or unfavorable match-ups discussed for specific players or teams.

        7. Fantasy Strategies:
           - Summarize any general fantasy football strategies or tips mentioned.

        8. Betting Insights:
           - Note any information that could be relevant for sports betting (e.g., over/under predictions, player prop bets).

        9. Key Takeaways:
           - List the most important points or advice from the podcast/video.

        Use bullet points where appropriate to break down information. Integrate any relevant details from the following description:

        {description}

        Here's the transcript:

        {text}

        Please provide a comprehensive yet concise summary based on this structure, focusing on actionable fantasy football advice and insights."""

        response = client.chat.completions.create(
            model="gpt-4-1106-preview",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that creates comprehensive fantasy football summaries."},
                {"role": "user", "content": prompt}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        logging.error(f"Error summarizing text: {str(e)}")
        return None

def extract_video_metadata(job_folder):
    json_files = [f for f in os.listdir(job_folder) if f.endswith('.info.json')]
    if json_files:
        with open(os.path.join(job_folder, json_files[0]), 'r') as f:
            return json.load(f)
    return None

def process_fantasy_football_video(url):
    try:
        logging.info(f"Starting to process video: {url}")
        
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info['title']
        logging.info(f"Video title: {title}")

        job_folder = create_job_folder(sanitize_filename(title))
        logging.info(f"Created job folder: {job_folder}")

        output_path = os.path.join(job_folder, f"{sanitize_filename(title)}.mp3")

        if not download_audio(url, os.path.join(job_folder, '%(title)s.%(ext)s')):
            logging.error("Failed to download audio")
            return

        logging.info(f"Audio downloaded successfully: {output_path}")

        mp3_files = [f for f in os.listdir(job_folder) if f.endswith('.mp3')]
        if not mp3_files:
            raise FileNotFoundError("No MP3 file found after download")
        actual_output_path = os.path.join(job_folder, mp3_files[0])

        chunks = split_audio(actual_output_path)
        logging.info("Audio split into chunks.")

        full_transcript = []
        cumulative_duration = 0
        transcript_path = os.path.join(job_folder, "transcript.txt")
        with open(transcript_path, "w", encoding="utf-8") as f:
            f.write(f"Transcription for: {title}\nURL: {url}\n\n")
            for i, chunk in enumerate(chunks):
                logging.info(f"Transcribing chunk {i+1}/{len(chunks)}")
                chunk_transcript, chunk_duration = transcribe_audio(chunk)
                if chunk_transcript and 'segments' in chunk_transcript:
                    for segment in chunk_transcript['segments']:
                        segment['start'] += cumulative_duration
                        segment['end'] += cumulative_duration
                    formatted_chunk = format_transcript({'segments': chunk_transcript['segments']})
                    f.write(formatted_chunk + "\n")
                    full_transcript.extend(chunk_transcript['segments'])
                else:
                    logging.warning(f"Unexpected transcript format for chunk {i+1}")
                cumulative_duration += chunk_duration
                os.remove(chunk)

        logging.info(f"Transcription completed and saved to: {transcript_path}")

        metadata = extract_video_metadata(job_folder)
        if metadata:
            metadata_path = os.path.join(job_folder, "video_metadata.json")
            with open(metadata_path, "w") as f:
                json.dump(metadata, f, indent=4)
            logging.info(f"Video metadata extracted and saved to: {metadata_path}")

        if full_transcript:
            formatted_transcript = format_transcript({'segments': full_transcript})
            summary = summarize_fantasy_football(formatted_transcript, title, url, metadata)
            if summary:
                summary_path = os.path.join(job_folder, "fantasy_football_summary.txt")
                with open(summary_path, "w", encoding="utf-8") as f:
                    f.write(f"Fantasy Football Summary for: {title}\nURL: {url}\n\n{summary}")
                logging.info(f"Fantasy Football summary generated and saved to: {summary_path}")

        logging.info(f"Processing completed for: {url}")
        logging.info(f"All files are in the folder: {job_folder}")

    except Exception as e:
        logging.exception(f"Error processing video {url}: {str(e)}")

def main():
    parser = argparse.ArgumentParser(description="Download, transcribe, and summarize Fantasy Football video/podcast")
    parser.add_argument("input", help="YouTube video URL or file containing URLs")
    args = parser.parse_args()

    logging.info(f"Starting script with input: {args.input}")

    try:
        if os.path.isfile(args.input):
            with open(args.input, 'r') as file:
                urls = file.read().splitlines()
            for url in urls:
                process_fantasy_football_video(url.strip())
        else:
            process_fantasy_football_video(args.input)
    except Exception as e:
        logging.exception(f"An error occurred during execution: {str(e)}")

if __name__ == "__main__":
    main()