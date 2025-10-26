import argparse
import os
from openai import OpenAI
import logging
from pydub import AudioSegment # Added for chunking
from dotenv import load_dotenv # Added for .env loading

# Specify the path relative to the script's execution directory
DOTENV_PATH = 'app/.env' 

# Load environment variables from the specified .env file path
loaded = load_dotenv(dotenv_path=DOTENV_PATH)

# Set up basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

if loaded:
    logging.info(f"Loaded environment variables from: {DOTENV_PATH}")
else:
    logging.warning(f".env file not found at specified path: {DOTENV_PATH}. Relying on system environment variables.")

# Initialize OpenAI client (now uses key loaded from .env or system env)
try:
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    if not client.api_key:
        raise ValueError("OPENAI_API_KEY not found in environment or .env file.")
except Exception as e:
    logging.error(f"Failed to initialize OpenAI client: {e}")
    exit(1)

def split_audio(file_path, chunk_length_ms=600000, max_size_bytes=25*1024*1024):
    """Splits an audio file into chunks based on duration and size limits."""
    try:
        # Determine the format from the file extension
        file_extension = os.path.splitext(file_path)[1].lower()
        if file_extension == '.wav':
            audio = AudioSegment.from_wav(file_path)
        elif file_extension == '.mp3':
             audio = AudioSegment.from_mp3(file_path)
        # Add other formats as needed (e.g., .m4a, .ogg)
        # elif file_extension == '.m4a':
        #     audio = AudioSegment.from_file(file_path, format="m4a")
        else:
            logging.warning(f"Unsupported audio format {file_extension}. Attempting generic load.")
            audio = AudioSegment.from_file(file_path)

    except FileNotFoundError:
        logging.error(f"Error: Audio file not found at {file_path} during splitting.")
        return []
    except Exception as e:
        logging.error(f"Error loading audio file {file_path} with pydub: {e}")
        return []

    chunks = []
    base_name = os.path.splitext(file_path)[0]
    output_format = file_extension[1:] # e.g., 'wav' or 'mp3'

    # Check if the original file is already small enough
    original_size_bytes = os.path.getsize(file_path)
    if original_size_bytes <= max_size_bytes:
        logging.info(f"Audio file is small enough ({original_size_bytes / (1024*1024):.2f} MB), no chunking needed.")
        # Return the original path in a list for consistency
        return [file_path]

    logging.info(f"Audio file is larger than {max_size_bytes / (1024*1024):.0f}MB, starting chunking...")

    current_chunk_start = 0
    i = 0
    while current_chunk_start < len(audio):
        # Tentative end based on desired chunk length
        tentative_end = current_chunk_start + chunk_length_ms
        chunk = audio[current_chunk_start:tentative_end]
        chunk_path = f"{base_name}_chunk{i}.{output_format}"

        try:
            chunk.export(chunk_path, format=output_format)
            chunk_size_bytes = os.path.getsize(chunk_path)

            # If chunk is too big, reduce length and retry *this specific chunk*
            if chunk_size_bytes > max_size_bytes:
                logging.warning(f"Chunk {i} ({chunk_size_bytes / (1024*1024):.2f} MB) exceeds limit. Reducing chunk length and retrying.")
                os.remove(chunk_path)
                # Calculate a smaller chunk length based on the oversized chunk
                # Estimate new length: current_length * (max_size / actual_size)
                # Use a safety factor (e.g., 0.9) to avoid hitting the limit exactly
                estimated_length = int(chunk_length_ms * (max_size_bytes / chunk_size_bytes) * 0.9)
                if estimated_length < 1000: # Prevent excessively small chunks
                     estimated_length = 1000
                chunk = audio[current_chunk_start : current_chunk_start + estimated_length]
                chunk.export(chunk_path, format=output_format)
                # Update the end point for the next iteration
                current_chunk_start += len(chunk)
            else:
                 # Chunk is fine, move to the next segment
                 current_chunk_start = tentative_end

            chunks.append(chunk_path)
            i += 1
        except Exception as e:
            logging.error(f"Error exporting chunk {i}: {e}")
            # Clean up potentially created chunk file
            if os.path.exists(chunk_path):
                os.remove(chunk_path)
            # Attempt to skip this problematic section and continue
            current_chunk_start = tentative_end # Move past the potentially problematic section
            # Optionally, break or return [] if one chunk failure is critical

    return chunks

def transcribe_local_wav(file_path):
    """
    Transcribes a local audio file (WAV, MP3, etc.) using the OpenAI Whisper API,
    handling chunking for large files.

    Args:
        file_path (str): The path to the local audio file.

    Returns:
        str: The concatenated transcribed text, or None if an error occurs.
    """
    if not os.path.exists(file_path):
        logging.error(f"Error: File not found at {file_path}")
        return None

    logging.info(f"Starting transcription process for: {file_path}")

    # Split audio into manageable chunks
    # Use the file's original format for chunks if supported, else default to mp3
    audio_chunks = split_audio(file_path)

    if not audio_chunks:
        logging.error("Failed to split audio into chunks or no audio found.")
        return None

    full_transcription = []
    is_original_file_chunk = len(audio_chunks) == 1 and audio_chunks[0] == file_path

    for i, chunk_path in enumerate(audio_chunks):
        logging.info(f"Transcribing chunk {i+1}/{len(audio_chunks)}: {os.path.basename(chunk_path)}")
        try:
            with open(chunk_path, "rb") as audio_file:
                transcript = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file
                    # Use response_format="verbose_json" if you need timestamps
                )
            full_transcription.append(transcript.text)
            logging.info(f"Chunk {i+1} transcribed successfully.")
        except Exception as e:
            logging.error(f"Error transcribing chunk {chunk_path}: {str(e)}")
            # Decide if you want to continue or fail the whole process
            # return None # Uncomment to fail on first chunk error
        finally:
            # Clean up chunk files unless it was the original file
            if not is_original_file_chunk and os.path.exists(chunk_path):
                 try:
                     os.remove(chunk_path)
                     logging.debug(f"Removed chunk file: {chunk_path}")
                 except OSError as oe:
                     logging.warning(f"Could not remove chunk file {chunk_path}: {oe}")

    if not full_transcription:
        logging.error("Transcription failed for all chunks.")
        return None

    logging.info("All chunks processed. Concatenating transcription.")
    # Join the transcriptions from all chunks
    return " ".join(full_transcription)

def main():
    parser = argparse.ArgumentParser(description="Transcribe a local audio file (e.g., WAV, MP3) using OpenAI Whisper, with auto-chunking.")
    parser.add_argument("audio_file", help="Path to the input audio file.")
    args = parser.parse_args()

    logging.info(f"Starting transcription job for: {args.audio_file}")

    transcribed_text = transcribe_local_wav(args.audio_file)

    if transcribed_text:
        print("\n--- Full Transcription ---")
        print(transcribed_text)
        print("------------------------\n")
        # Optionally, save to a file
        output_filename = os.path.splitext(args.audio_file)[0] + "_transcript.txt"
        try:
            with open(output_filename, "w", encoding="utf-8") as f:
                f.write(transcribed_text)
            logging.info(f"Full transcription saved to: {output_filename}")
        except IOError as e:
            logging.error(f"Failed to save transcription to {output_filename}: {e}")
    else:
        logging.error("Transcription job failed.")

if __name__ == "__main__":
    main() 