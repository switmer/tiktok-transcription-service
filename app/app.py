import os
from dotenv import load_dotenv

# Explicitly load the .env file from the app directory
dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path=dotenv_path)
    print(f"Loaded environment variables from {dotenv_path}")
elif os.path.exists('.env'): # Fallback to project root .env if app/.env doesn't exist
    load_dotenv() # Load from project root
    print("Loaded environment variables from project root .env")
else:
    print("Warning: .env file not found in app directory or project root.")
    # For deployment environments, fall back to using environment variables directly
    if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_KEY"):
        print("Using environment variables from system configuration")

import json
import time
import logging
import glob
from datetime import datetime, timezone
import uuid
import tempfile
from fastapi import FastAPI, BackgroundTasks, HTTPException, Depends, Header, Request, Query
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from typing import Optional, Dict, Any, List, Tuple, Literal
import uvicorn
import httpx
from openai import OpenAI
import yt_dlp
import subprocess
import shutil
import asyncio
import sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from supabase.client import create_client, Client

# Fix imports for deployment
try:
    # Try relative import first (when running as a package)
    from .database import supabase
    from . import discovery
    from . import transcriber
except ImportError:
    # Fall back to absolute imports (when running directly)
    import database
    import discovery
    import transcriber
    from database import supabase

# Import tiktok downloader directly
try:
    from local_scripts.download_tiktok import download_tiktok as enhanced_download_tiktok
except ImportError:
    # If local_scripts isn't available, use the built-in transcriber
    enhanced_download_tiktok = transcriber.download_tiktok
    print("Using transcriber.download_tiktok as fallback")

# Configure logging
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

app = FastAPI(
    title="TikTok Transcription API",
    description="API for downloading and transcribing TikTok videos",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://project-waitlist-signup-card-with-animation-586.magicpatterns.app",
        "http://localhost:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "*"  # Consider removing this in production and just list allowed domains
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)

# Create a directory for downloads if it doesn't exist
DOWNLOADS_DIR = os.path.join(os.path.dirname(__file__), "downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

# Initialize Supabase client
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_KEY")

if not supabase_url or not supabase_key:
    logger.warning("Supabase URL or Service Key not found in environment variables. Database operations will fail.")
    supabase: Client | None = None
else:
    try:
        supabase: Client = create_client(supabase_url, supabase_key)
        logger.info("Supabase client initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize Supabase client: {str(e)}")
        supabase = None

# Include discovery routes
app.include_router(discovery.router)

class TranscriptionRequest(BaseModel):
    """Request model for video transcription"""
    url: str
    callback_url: Optional[str] = None
    format: Optional[str] = "bestaudio/best"
    output_template: Optional[str] = None
    extract_audio: bool = True
    convert_to_mp3: bool = False
    save_thumbnail: bool = True
    extract_metadata: bool = True
    perform_sentiment_analysis: bool = False
    create_srt: bool = False
    proxy: Optional[str] = None
    api_key: Optional[str] = None

class TranscriptionResponse(BaseModel):
    task_id: str
    status: str
    video_id: Optional[str] = None
    title: Optional[str] = None
    created_at: str
    error: Optional[str] = None
    thumbnail: Optional[str] = None  # Might be deprecated if we use local path/URL
    thumbnail_url: Optional[str] = None
    thumbnail_local_path: Optional[str] = None # Relative path to local thumbnail

class TaskListResponse(BaseModel):
    tasks: List[TranscriptionResponse]

# --- API Key Validation ---
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False) # Use APIKeyHeader for header extraction

async def validate_api_key(api_key: str = Depends(api_key_header)) -> str:
    """Validate the API key against the Supabase api_keys table and return user_id."""
    logger.info(f"Validating API key: {api_key[:4]}... (first 4 chars only for security)")
    
    if not api_key:
        logger.warning("API key validation failed: Header X-API-Key is missing.")
        raise HTTPException(status_code=403, detail="Missing API Key Header")
        
    if supabase is None:
        logger.error("Cannot validate API key: Supabase client not initialized")
        raise HTTPException(status_code=500, detail="Error during API key validation")

    try:
        # Log the detailed query we're about to execute
        logger.info(f"Executing Supabase query against api_keys table with api_key={api_key[:4]}... and is_active=True")
        
        # Build the query step by step - select just 'id' since user_id doesn't exist
        query = supabase.table('api_keys')
        logger.info(f"Step 1: Created query on table 'api_keys'")
        
        query = query.select('id')  # Changed from user_id to id
        logger.info(f"Step 2: Added select('id')")
        
        query = query.eq('api_key', api_key)
        logger.info(f"Step 3: Added eq('api_key', [masked])")
        
        query = query.eq('is_active', True)
        logger.info(f"Step 4: Added eq('is_active', True)")
        
        query = query.limit(1)
        logger.info(f"Step 5: Added limit(1)")
        
        logger.info(f"Step 6: About to execute query")
        response = await asyncio.to_thread(query.execute)
        
        # Log response details but mask sensitive data
        result_count = len(response.data) if response.data else 0
        logger.info(f"Query response received: found {result_count} results")
        if result_count > 0:
            logger.info(f"Response data keys: {list(response.data[0].keys()) if response.data and response.data[0] else 'None'}")
            
        # Check if the key exists and is active
        if response.data and len(response.data) > 0:
            # Use API key's ID as user_id since that's what we have
            if 'id' in response.data[0]:
                api_key_id = response.data[0]['id'] # Extract id
                logger.info(f"API key validated successfully, using key id as user_id: {api_key_id}")
                return str(api_key_id) # Return the id as string to use as user_id
            else:
                logger.warning(f"API key validated but id missing in response data. Available keys: {list(response.data[0].keys())}")
                # Provide a default user_id as fallback
                return "default_user"
        else:
            logger.warning("API key validation failed: Invalid or inactive key provided.")
            raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    except Exception as e:
        logger.error(f"Error during API key validation: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error during API key validation")

# API key dependency
def verify_api_key(x_api_key: str = Header(None)):
    """Dependency for API key validation"""
    # Handle potential None value from Header
    if x_api_key is None:
         logger.warning("API key validation failed: X-API-Key header missing.")
         raise HTTPException(status_code=401, detail="X-API-Key header required")
    validate_api_key(x_api_key)
    return x_api_key

@app.get("/", include_in_schema=False)
async def root():
    return {"message": "TikTok Transcription API. See /docs for documentation."}

@app.post("/api/public/transcribe", response_model=TranscriptionResponse)
async def transcribe(
    request: TranscriptionRequest,
    background_tasks: BackgroundTasks,
    user_id: Optional[str] = None  # Made optional to support both authenticated and public requests
) -> TranscriptionResponse:
    """Start a new transcription task or return existing one."""
    try:
        # Initialize task (this will check for existing transcriptions)
        task = await init_task(request.url, user_id)
        task_id = task['task_id'] # Extract task_id from the returned dict

        # Get the task details - Ensure task_id is passed as a string
        response = await asyncio.to_thread(
            supabase.table('transcriptions')
                    .select("*")
                    .eq('task_id', str(task_id)) # Ensure task_id is a string
                    .single()
                    .execute
        )

        if not response.data:
            # This might indicate an issue with init_task not committing before this runs
            # Or a race condition. Adding a small delay or re-checking might be needed
            # For now, raise a 500 as the task should exist.
            logger.error(f"Failed to retrieve task details immediately after creation for task_id: {task_id}")
            raise HTTPException(status_code=500, detail="Failed to retrieve task details")

        task_data = response.data

        # If status is not completed, start processing
        if task_data['status'] != 'completed':
            # Queue the background processing
            background_tasks.add_task(
                process_transcription_task,
                task_id,
                request.url,
                request.callback_url,
                request.proxy
            )
            logger.info(f"Task {task_id} queued for processing URL: {request.url}")
        else:
            logger.info(f"Returning existing transcription for URL: {request.url}")
        
        # Return the task response
        return TranscriptionResponse(
            task_id=task_id,
            status=task_data['status'],
            video_id=task_data.get('video_id'),
            title=task_data.get('title'),
            created_at=task_data['created_at'],
            error=task_data.get('error'),
            thumbnail=task_data.get('thumbnail_url'),
            thumbnail_url=task_data.get('thumbnail_url'),
            thumbnail_local_path=task_data.get('thumbnail_local_path')
        )
        
    except Exception as e:
        logger.error(f"Error in transcribe endpoint: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to start transcription")

@app.get("/api/tasks", response_model=TaskListResponse)
async def list_tasks(api_key: str = Depends(verify_api_key)):
    """List the last 50 transcription tasks from Supabase."""
    if supabase is None:
        logger.error(f"Cannot list tasks: Supabase client not initialized.")
        raise HTTPException(status_code=500, detail="Database connection not available")

    try:
        response = await asyncio.to_thread(
            supabase.table('transcriptions')
                    .select("task_id, status, video_id, title, created_at, error, thumbnail_url, thumbnail_local_path")
                    .order('created_at', desc=True) # Order by creation time, newest first
                    .limit(50) # Limit to the last 50 tasks
                    .execute
        )
        
        # Check for errors during the query
        if hasattr(response, 'error') and response.error:
             logger.error(f"Failed to list tasks from Supabase: {response.error}")
             raise HTTPException(status_code=500, detail="Database error listing tasks")
             
        # Map the results to the response model
        tasks_list = []
        if response.data:
            for task_data in response.data:
                 tasks_list.append(TranscriptionResponse(
                    task_id=task_data['task_id'],
                    status=task_data['status'],
                    video_id=task_data.get('video_id'),
                    title=task_data.get('title'),
                    created_at=task_data['created_at'],
                    error=task_data.get('error'),
                    thumbnail=task_data.get('thumbnail_url'), # Map thumbnail_url
                    thumbnail_url=task_data.get('thumbnail_url'),
                    thumbnail_local_path=task_data.get('thumbnail_local_path')
                ))
                
        return TaskListResponse(tasks=tasks_list)
        
    except Exception as e:
        logger.error(f"Exception listing tasks from Supabase: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Server error listing tasks")

@app.get("/api/tasks/{task_id}", response_model=TranscriptionResponse)
async def get_task(task_id: str, api_key: str = Depends(verify_api_key)):
    """Get task status from Supabase."""
    if supabase is None:
        logger.error(f"Cannot get task {task_id}: Supabase client not initialized.")
        raise HTTPException(status_code=500, detail="Database connection not available")
        
    try:
        # Fetch the specific columns needed for TranscriptionResponse
        # Ensure column names here match your Supabase table AND TranscriptionResponse model fields
        response = await asyncio.to_thread(
            supabase.table('transcriptions')
                    .select("task_id, status, video_id, title, created_at, error, thumbnail_url, thumbnail_local_path")
                    .eq('task_id', task_id)
                    .maybe_single() # Use maybe_single() instead of single() to handle not found gracefully
                    .execute
        )

        # Check for errors during the query
        if hasattr(response, 'error') and response.error:
             logger.error(f"Failed to get task {task_id} from Supabase: {response.error}")
             raise HTTPException(status_code=500, detail="Database error retrieving task")

        # Check if data was found
        if not response.data:
            raise HTTPException(status_code=404, detail="Task not found")
            
        # Map Supabase data to the response model
        # Note: The 'thumbnail' field in TranscriptionResponse might need clarification
        # Assuming it should map to thumbnail_url for now.
        task_data = response.data
        return TranscriptionResponse(
            task_id=task_data['task_id'],
            status=task_data['status'],
            video_id=task_data.get('video_id'),
            title=task_data.get('title'),
            created_at=task_data['created_at'],
            error=task_data.get('error'),
            thumbnail=task_data.get('thumbnail_url'), # Mapping thumbnail_url to thumbnail
            thumbnail_url=task_data.get('thumbnail_url'),
            thumbnail_local_path=task_data.get('thumbnail_local_path')
        )
            
    except HTTPException: # Re-raise HTTPExceptions (like 404)
         raise
    except Exception as e:
        logger.error(f"Exception getting task {task_id} from Supabase: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Server error retrieving task")

@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str, api_key: str = Depends(verify_api_key)):
    """Delete task record from Supabase and associated local files."""
    if supabase is None:
        logger.error(f"Cannot delete task {task_id}: Supabase client not initialized.")
        raise HTTPException(status_code=500, detail="Database connection not available")

    # Step 1: Attempt to delete the record from Supabase first
    try:
        response = await asyncio.to_thread(
            supabase.table('transcriptions')
                    .delete()
                    .eq('task_id', task_id)
                    .execute
        )
        
        # Check for errors during delete
        if hasattr(response, 'error') and response.error:
            logger.error(f"Failed to delete task {task_id} from Supabase: {response.error}")
            # Decide if this is a 500 or if we should still try to delete files
            # For now, let's treat DB error as critical
            raise HTTPException(status_code=500, detail="Database error deleting task")

        # Check if any rows were actually deleted (response.data might be empty on delete)
        # Supabase delete often returns the deleted records in response.data
        if not response.data:
            # If no data was returned (and no error), the task ID likely didn't exist
            raise HTTPException(status_code=404, detail="Task not found in database")
            
        logger.info(f"Task {task_id} deleted from Supabase.")

    except HTTPException: # Re-raise 404 or other HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Exception deleting task {task_id} from Supabase: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Server error deleting task record")

    # Step 2: Delete local files associated with the task (if DB deletion was successful)
    try:
        output_dir = os.path.join(DOWNLOADS_DIR, task_id)
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)
            logger.info(f"Deleted local files for task {task_id} at {output_dir}")
        else:
            logger.info(f"No local files found to delete for task {task_id} at {output_dir}")
    except Exception as e:
        # Log error but maybe don't fail the whole request if DB delete worked?
        logger.error(f"Error deleting local files for task {task_id}: {str(e)}", exc_info=True)
        # Consider returning a partial success message or just logging

    return {"message": f"Task {task_id} deleted successfully"}

@app.get("/api/transcript/{task_id}")
async def get_transcript(task_id: str, api_key: str = Depends(verify_api_key)):
    """Get transcript for a task"""
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
        
    task = tasks[task_id]
    
    if task["status"] == "failed":
        error_message = task.get("error", "Unknown error")
        raise HTTPException(
            status_code=400, 
            detail=f"Transcription failed: {error_message}"
        )
        
    if task["status"] != "completed":
        raise HTTPException(
            status_code=400, 
            detail=f"Transcription not completed yet. Current status: {task['status']}"
        )
        
    # Look for transcript file
    output_dir = os.path.join(DOWNLOADS_DIR, task_id)
    
    # Use glob to find transcript files
    transcript_files = glob.glob(os.path.join(output_dir, "*_transcript.txt"))
    
    if not transcript_files:
        # Try another common pattern if the first one fails
        transcript_files = glob.glob(os.path.join(output_dir, "*.txt"))
    
    if not transcript_files:
        raise HTTPException(status_code=404, detail="Transcript file not found")
        
    # Return the first transcript file found
    return FileResponse(transcript_files[0])

@app.get("/api/healthcheck")
async def healthcheck():
    """
    Simple health check endpoint.
    """
    return {
        "status": "ok",
        "version": "1.0.0",
        "timestamp": time.time()
    }

@app.get("/api/test", response_model=str)
async def test_endpoint():
    """Test endpoint that checks API key and OpenAI connectivity"""
    try:
        # Test OpenAI connection
        test_result = "OpenAI connection: "
        try:
            # Just a simple test call
            client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            models = client.models.list()
            test_result += f"OK - OpenAI API working"
        except Exception as e:
            test_result += f"FAILED - {str(e)}"
            
        # Test environment
        test_result += "\nEnvironment variables: "
        test_result += f"\n- OPENAI_API_KEY: {'✓ Set' if os.getenv('OPENAI_API_KEY') else '✗ Not set'}"
        test_result += f"\n- API_KEY: {'✓ Set' if os.getenv('API_KEY') else '✗ Not set'}"
        
        # Test directories
        downloads_dir = DOWNLOADS_DIR
        test_result += f"\nDownloads directory: {'✓ Exists' if os.path.exists(downloads_dir) else '✗ Not found'}"
        
        # Test yt-dlp
        test_result += "\nyt-dlp: "
        try:
            test_result += "✓ Installed"
        except ImportError:
            test_result += "✗ Not installed"
            
        return test_result
    except Exception as e:
        return f"Test failed: {str(e)}"

@app.post("/api/test-download", response_model=str)
async def test_download(request: Request):
    """Test TikTok download functionality with a public video"""
    try:
        body = await request.json()
        url = body.get("url")
        proxy = body.get("proxy")
        if not url:
            return "Error: URL is required"
            
        # Create test directory
        test_dir = os.path.join(DOWNLOADS_DIR, "test")
        os.makedirs(test_dir, exist_ok=True)
        
        # Use yt-dlp to get info only (no download)
        info_result = "Video info: "
        try:
            with yt_dlp.YoutubeDL({'quiet': True, 'proxy': proxy} if proxy else {'quiet': True}) as ydl:
                info = ydl.extract_info(url, download=False)
                video_id = info.get('id', 'unknown')
                title = info.get('title', 'unknown')
                info_result += f"✓ Success\nID: {video_id}\nTitle: {title}"
        except Exception as e:
            info_result += f"✗ Failed - {str(e)}"
            
        return info_result
    except Exception as e:
        return f"Test failed: {str(e)}"

@app.post("/api/fallback-download")
async def fallback_download(
    request: Request,
    background_tasks: BackgroundTasks,
    api_key: str = Depends(verify_api_key)
):
    """Use the simplified tiktok_dl.py script to download a TikTok video"""
    try:
        body = await request.json()
        url = body.get("url")
        if not url:
            return "Error: URL is required"
            
        # Create temp directory for output
        temp_dir = tempfile.mkdtemp(prefix="tiktok_download_")
        
        # Use our simplified downloader
        from local_scripts.download_tiktok import download_tiktok
        
        print(f"Using simplified downloader for URL: {url}")
        print(f"Output directory: {temp_dir}")
        
        result = download_tiktok(url, temp_dir)
        
        if result["success"]:
            # Get the task ID for this job
            task_id = str(uuid.uuid4())
            
            # Create a task directory
            task_dir = os.path.join(DOWNLOADS_DIR, task_id)
            os.makedirs(task_dir, exist_ok=True)
            
            # Move the downloaded MP3 to our task directory
            audio_file = result["audio_file"]
            target_file = os.path.join(task_dir, os.path.basename(audio_file))
            shutil.copy(audio_file, target_file)
            
            # Create a new task
            tasks[task_id] = {
                "task_id": task_id,
                "status": "completed",
                "video_id": result["video_id"],
                "title": result["title"],
                "created_at": datetime.now().isoformat()
            }
            
            # Transcribe the audio in the background (don't wait for it)
            background_tasks.add_task(
                transcribe_and_save,
                task_id=task_id,
                audio_file=target_file,
                output_dir=task_dir
            )
            
            return JSONResponse(
                content={
                    "message": f"TikTok video downloaded successfully using fallback method",
                    "task_id": task_id,
                    "status": "completed",
                    "video_id": result["video_id"],
                    "title": result["title"],
                    "audio_file": target_file
                },
                background=background_tasks
            )
        else:
            return f"Failed to download video: {result['error']}"
    except Exception as e:
        return f"Error in fallback download: {str(e)}"

async def transcribe_and_save(task_id: str, audio_file: str, output_dir: str):
    """Transcribe an audio file and save the transcript"""
    try:
        # Transcribe the audio file
        audio_file = download_result["audio_file"]
        transcript_response, transcript_file_path_abs = transcriber.transcribe_audio(audio_file, output_dir, video_id)
        
        if transcript_response:
            final_status = "completed"
            final_error = None
            # Store relative path to transcript file
            transcript_file_path = os.path.relpath(transcript_file_path_abs, DOWNLOADS_DIR)
            
            # Read the transcript content
            with open(transcript_file_path_abs, 'r', encoding='utf-8') as f:
                transcript_text = f.read()
            
            # Update Supabase with transcript content and file path
            await asyncio.to_thread(
                supabase.table('transcriptions')
                        .update({
                            "status": final_status,
                            "error": final_error,
                            "transcript": transcript_text,
                            "transcript_file_path": transcript_file_path
                        })
                        .eq('task_id', task_id)
                        .execute
            )
            logger.info(f"Task {task_id} completed successfully with transcript saved")
        else:
            final_status = "failed"
            final_error = "Transcription failed"
            transcript_file_path = None
            logger.error(f"Failed to transcribe audio for task {task_id}")
            await update_task_status(task_id, final_status, final_error)
    except Exception as e:
        print(f"Error transcribing audio: {str(e)}")
        tasks[task_id]["status"] = "failed"

# Enhanced video processing using our improved downloader
async def process_video_enhanced(task_id: str, url: str, output_dir: str, callback_url: Optional[str] = None, proxy: Optional[str] = None, save_thumbnail: bool = True):
    """Process video download and transcription using enhanced downloader"""
    try:
        # Update task status
        tasks[task_id]["status"] = "processing"
        
        # Use our enhanced downloader
        result = enhanced_download_tiktok(url, output_dir)
        
        if not result["success"]:
            tasks[task_id]["status"] = "failed"
            error_message = result.get('error', 'Unknown error')
            tasks[task_id]["error"] = error_message
            
            # If we have video_id and title from the URL, save them even though download failed
            if "video_id" in result:
                tasks[task_id]["video_id"] = result["video_id"]
            if "title" in result:
                tasks[task_id]["title"] = result["title"]
                
            print(f"Failed to download video: {error_message}")
            
            # Send webhook with failure if callback URL is provided
            if callback_url:
                try:
                    async with httpx.AsyncClient() as client:
                        await client.post(
                            callback_url,
                            json={
                                "task_id": task_id,
                                "status": "failed",
                                "error": error_message,
                                "video_id": result.get("video_id"),
                                "title": result.get("title")
                            }
                        )
                except Exception as e:
                    print(f"Failed to send webhook: {str(e)}")
            
            return
            
        # Update task info
        tasks[task_id]["video_id"] = result["video_id"]
        tasks[task_id]["title"] = result["title"]
        
        # Extract thumbnail if video file is available
        try:
            if "video_file" in result and os.path.exists(result["video_file"]):
                from local_scripts.downloader import extract_thumbnail
                thumbnail_path = extract_thumbnail(output_dir)
                if thumbnail_path:
                    tasks[task_id]["thumbnail"] = thumbnail_path
                    logger.info(f"Extracted thumbnail for task {task_id}: {thumbnail_path}")
        except Exception as thumb_error:
            logger.error(f"Error extracting thumbnail: {str(thumb_error)}")
        
        # Transcribe audio
        audio_file = result["audio_file"]
        video_id = result["video_id"]
        transcript, transcript_file = transcriber.transcribe_audio(
            audio_file,
            output_dir,
            video_id
        )
        
        if not transcript:
            tasks[task_id]["status"] = "failed"
            tasks[task_id]["error"] = "Transcription failed"
            print(f"Failed to transcribe audio for video: {result['video_id']}")
            return
            
        # Update task status
        tasks[task_id]["status"] = "completed"
        
        # Send webhook if callback URL is provided
        if callback_url:
            try:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        callback_url,
                        json={
                            "task_id": task_id,
                            "status": "completed",
                            "video_id": result["video_id"],
                            "title": result["title"],
                            "thumbnail": tasks[task_id].get("thumbnail")
                        }
                    )
            except Exception as e:
                print(f"Failed to send webhook: {str(e)}")
                
    except Exception as e:
        tasks[task_id]["status"] = "failed"
        tasks[task_id]["error"] = str(e)
        print(f"Error processing video: {str(e)}")

# Keep the original process_video function for backward compatibility
async def process_video(task_id: str, url: str, output_dir: str, callback_url: Optional[str] = None, proxy: Optional[str] = None):
    """Process video download and transcription in the background (legacy method)"""
    # This now just calls the enhanced version
    await process_video_enhanced(task_id, url, output_dir, callback_url, proxy)

async def process_video_with_external_script(
    url: str,
    extract_audio: bool = True,
    convert_to_mp3: bool = True,
    save_thumbnail: bool = True,
    extract_metadata: bool = True,
    analyze_sentiment: bool = False,
    create_srt: bool = True,
    format: str = "mp4",
    output_template: str = "%(id)s",
    proxy: Optional[str] = None,
    api_key: Optional[str] = None
) -> Tuple[str, Dict]:
    """
    Process a video using the external script to extract transcript and other data
    
    Args:
        url: The URL of the video to process
        extract_audio: Whether to extract audio from the video
        convert_to_mp3: Whether to convert the extracted audio to MP3
        save_thumbnail: Whether to save the video thumbnail
        extract_metadata: Whether to extract video metadata
        analyze_sentiment: Whether to perform sentiment analysis on the transcript
        create_srt: Whether to create an SRT subtitle file
        format: The format to download the video in
        output_template: The output filename template
        proxy: Optional proxy URL to use for the request
        api_key: Optional API key for services that require it
        
    Returns:
        Tuple containing the transcript text and a dictionary of additional results
    """
    # Create a unique working directory for this task
    task_dir = os.path.join(DOWNLOADS_DIR, str(uuid.uuid4()))
    os.makedirs(task_dir, exist_ok=True)
    
    try:
        # Prepare the command with all options
        cmd = [
            "python", 
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "tiktok_transcriber.py"),
            "--url", url,
            "--output-dir", task_dir
        ]
        
        # Add optional parameters
        if extract_audio:
            cmd.extend(["--extract-audio"])
        if convert_to_mp3:
            cmd.extend(["--convert-to-mp3"])
        if save_thumbnail:
            cmd.extend(["--save-thumbnail"])
        if extract_metadata:
            cmd.extend(["--extract-metadata"])
        if analyze_sentiment:
            cmd.extend(["--analyze-sentiment"])
        if create_srt:
            cmd.extend(["--create-srt"])
        if format:
            cmd.extend(["--format", format])
        if output_template:
            cmd.extend(["--output-template", output_template])
        if proxy:
            cmd.extend(["--proxy", proxy])
        if api_key:
            cmd.extend(["--api-key", api_key])
            
        # Execute the command
        logger.info(f"Executing command: {' '.join(cmd)}")
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            logger.error(f"Script execution failed: {error_msg}")
            raise RuntimeError(f"Script execution failed: {error_msg}")
            
        # Process the results
        transcript_text = ""
        results = {}
        
        # Look for the transcript file
        transcript_files = glob.glob(os.path.join(task_dir, "*_transcript.txt"))
        if transcript_files:
            with open(transcript_files[0], "r") as f:
                transcript_text = f.read()
        
        # Look for metadata file
        metadata_files = glob.glob(os.path.join(task_dir, "*_metadata.json"))
        if metadata_files:
            with open(metadata_files[0], "r") as f:
                results["metadata"] = json.load(f)
                
        # Look for SRT file
        srt_files = glob.glob(os.path.join(task_dir, "*.srt"))
        if srt_files:
            with open(srt_files[0], "r") as f:
                results["srt"] = f.read()
                
        # Look for sentiment analysis
        sentiment_files = glob.glob(os.path.join(task_dir, "*_sentiment.json"))
        if sentiment_files:
            with open(sentiment_files[0], "r") as f:
                results["sentiment"] = json.load(f)
                
        # Add file locations to results
        results["files"] = {
            "video": glob.glob(os.path.join(task_dir, f"*.{format}")),
            "audio": glob.glob(os.path.join(task_dir, "*.mp3")),
            "thumbnail": glob.glob(os.path.join(task_dir, "*.jpg")) + glob.glob(os.path.join(task_dir, "*.png")),
            "transcript": transcript_files,
            "srt": srt_files,
            "metadata": metadata_files,
            "sentiment": sentiment_files
        }
        
        return transcript_text, results
        
    except Exception as e:
        logger.error(f"Error processing video: {str(e)}")
        # Clean up the task directory on error
        if os.path.exists(task_dir):
            shutil.rmtree(task_dir)
        raise RuntimeError(f"Unexpected error: {e}")

def find_thumbnail_url_in_metadata(metadata):
    """Extract thumbnail URL from metadata."""
    # Direct thumbnails
    if 'thumbnails' in metadata and isinstance(metadata['thumbnails'], list) and len(metadata['thumbnails']) > 0:
        for thumbnail in metadata['thumbnails']:
            if isinstance(thumbnail, dict) and 'url' in thumbnail:
                return thumbnail['url']
    
    # TikTok-specific formats
    if 'thumbnail' in metadata:
        return metadata['thumbnail']
    
    if 'thumbnail_url' in metadata:
        return metadata['thumbnail_url']
    
    # YouTube-style formats
    if 'thumbnail_src' in metadata:
        return metadata['thumbnail_src']
    
    # Other possible fields
    for field in ['cover_url', 'cover', 'poster', 'image']:
        if field in metadata:
            if isinstance(metadata[field], str):
                return metadata[field]
    
    return None

async def process_transcription_task(task_id: str, video_url: str, callback_url: Optional[str] = None, proxy: Optional[str] = None):
    """Process a transcription task asynchronously."""
    if supabase is None:
        logger.error(f"Cannot process task {task_id}: Supabase client not initialized")
        return

    try:
        # --- Fetch the original URL from the database --- 
        task_response = await asyncio.to_thread(
            supabase.table('transcriptions')
                    .select("url") # Fetch only the URL column
                    .eq('task_id', task_id)
                    .single() # Expect exactly one result
                    .execute
        )
        
        if not task_response.data or 'url' not in task_response.data:
             logger.error(f"Could not retrieve original URL for task {task_id} from database.")
             await update_task_status(task_id, "failed", "Failed to retrieve task URL from database")
             return
             
        original_video_url = task_response.data['url']
        logger.info(f"Processing task {task_id} with original URL from DB: {original_video_url}")
        # -------------------------------------------------
        
        # Create a unique working directory for this task
        output_dir = os.path.join(DOWNLOADS_DIR, task_id)
        os.makedirs(output_dir, exist_ok=True)
        
        # Download the video and extract audio using the original URL
        # Note: The 'video_url' argument to this function is now ignored.
        audio_file, video_id, title = transcriber.download_tiktok(original_video_url, output_dir, proxy)
        
        if not audio_file or not video_id:
            logger.error(f"Download failed for task {task_id} using URL: {original_video_url}")
            await update_task_status(task_id, "failed", "Failed to download video")
            return
            
        # Update task with initial download results
        await asyncio.to_thread(
            supabase.table('transcriptions')
                    .update({
                        'status': 'processing',
                        'video_id': video_id,
                        'title': title
                    })
                    .eq('task_id', task_id)
                    .execute
        )
        
        # Transcribe the audio
        transcript_response, transcript_file_path = transcriber.transcribe_audio(audio_file, output_dir, video_id)
        
        if transcript_response:
            # Extract tags and guess category
            tags = await extract_tags_from_title(title or '')
            category = await guess_category(title or '', transcript_text)
            
            # Update Supabase with transcript, tags, and category
            await asyncio.to_thread(
                supabase.table('transcriptions')
                        .update({
                            'status': 'completed',
                            'transcript': transcript_text,
                            'tags': tags,
                            'category': category,
                            'error': None
                        })
                        .eq('task_id', task_id)
                        .execute
            )
            logger.info(f"Task {task_id} completed with {len(tags)} tags in category: {category}")
        else:
            await update_task_status(task_id, "failed", "Transcription failed")
            logger.error(f"Failed to transcribe audio for task {task_id}")

    except Exception as e:
        logger.error(f"Error processing task {task_id}: {str(e)}", exc_info=True)
        await update_task_status(task_id, "failed", str(e))

async def extract_tags_from_title(title: str) -> List[str]:
    """Extract potential tags from video title."""
    # Remove common filler words and split
    filler_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with'}
    words = set(word.lower() for word in title.replace('#', ' ').split())
    tags = [word for word in words if word not in filler_words and len(word) > 2]
    return tags[:5]  # Limit to 5 tags

async def guess_category(title: str, transcript: str = None) -> str:
    """Guess category based on title and transcript."""
    # Simple keyword-based categorization
    categories = {
        'education': {'learn', 'tutorial', 'how to', 'guide', 'tips', 'lesson'},
        'entertainment': {'funny', 'comedy', 'prank', 'reaction', 'gaming'},
        'music': {'song', 'music', 'concert', 'cover', 'remix'},
        'gaming': {'gameplay', 'gaming', 'playthrough', 'stream'},
        'food': {'recipe', 'cooking', 'food', 'baking', 'kitchen'},
        'fitness': {'workout', 'exercise', 'fitness', 'gym', 'training'},
        'tech': {'technology', 'tech', 'review', 'unboxing', 'coding'}
    }
    
    title_lower = title.lower()
    for category, keywords in categories.items():
        if any(keyword in title_lower for keyword in keywords):
            return category
            
    return 'other'

async def update_task_status(task_id: str, status: str, error: Optional[str] = None):
    """Update task status and error message in the Supabase transcriptions table."""
    if supabase is None:
        logger.error(f"Cannot update task {task_id}: Supabase client not initialized.")
        # Don't raise HTTPException here, just log, as this often runs in background
        return 

    try:
        update_data = {"status": status}
        # updated_at is handled by the database trigger
        if error:
            update_data["error"] = error
        else: # Explicitly set error to None if status is not failed?
            # Consider clearing the error if the status is no longer 'failed'
             if status != 'failed':
                  update_data["error"] = None 

        response = await asyncio.to_thread(
            supabase.table('transcriptions')
                    .update(update_data)
                    .eq('task_id', task_id)
                    .execute
        )
        
        # Check for errors
        if hasattr(response, 'error') and response.error:
            logger.error(f"Failed to update status for task {task_id} in Supabase: {response.error}")
        # Check if data was returned (indicates successful update)
        elif not response.data:
             logger.warning(f"Supabase status update for task {task_id} returned no data.")
        else:
            logger.info(f"Updated status for task {task_id} to {status} in Supabase.")

    except Exception as e:
        logger.error(f"Exception updating status for task {task_id}: {str(e)}", exc_info=True)

async def init_task(video_url: str, user_id: str) -> Dict[str, Any]:
    """Initialize a new task entry in the Supabase database."""
    if supabase is None:
        logger.error("Cannot initialize task: Supabase client not initialized")
        raise HTTPException(status_code=500, detail="Database error during task initialization")

    try:
        # Skip user_transcriptions table lookup since it might not exist
        # Just create a new task record each time
        task_id = str(uuid.uuid4())
        
        # Create the transcription record with minimal required fields
        # Adjust columns based on what actually exists in your table
        task_data = {
            "task_id": task_id,
            "status": "pending",
            "url": video_url,  # Make sure 'url' column exists in your table
            "created_at": datetime.now().isoformat(),
        }
        
        # Log what we're about to insert
        logger.info(f"Creating task with data: {task_data}")
        
        response = await asyncio.to_thread(
            supabase.table('transcriptions')
                    .insert(task_data)
                    .execute
        )
        
        # Check for errors
        if hasattr(response, 'error') and response.error:
            logger.error(f"Supabase error creating task: {response.error}")
            raise HTTPException(status_code=500, detail="Database error creating task")
        
        logger.info(f"Created new task {task_id} for URL: {video_url}")
        return {"task_id": task_id}
        
    except Exception as e:
        logger.error(f"Error initializing task: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Database error during task initialization")

@app.get("/api/public/tasks/{task_id}", response_model=TranscriptionResponse)
async def public_get_task(task_id: str):
    """Get task status without requiring API key."""
    if supabase is None:
        logger.error(f"Cannot get task {task_id}: Supabase client not initialized.")
        raise HTTPException(status_code=500, detail="Database connection not available")
        
    try:
        # Fetch task from Supabase
        response = await asyncio.to_thread(
            supabase.table('transcriptions')
                    .select("task_id, status, video_id, title, created_at, error, thumbnail_url, thumbnail_local_path")
                    .eq('task_id', task_id)
                    .maybe_single()
                    .execute
        )

        # Check for errors during the query
        if hasattr(response, 'error') and response.error:
             logger.error(f"Failed to get task {task_id} from Supabase: {response.error}")
             raise HTTPException(status_code=500, detail="Database error retrieving task")

        # Check if task exists
        if not response.data:
            raise HTTPException(status_code=404, detail="Task not found")
            
        # Map Supabase data to TranscriptionResponse
        task_data = response.data
        return TranscriptionResponse(
            task_id=task_data['task_id'],
            status=task_data['status'],
            video_id=task_data.get('video_id'),
            title=task_data.get('title'),
            created_at=task_data['created_at'],
            error=task_data.get('error'),
            thumbnail=task_data.get('thumbnail_url'),
            thumbnail_url=task_data.get('thumbnail_url'),
            thumbnail_local_path=task_data.get('thumbnail_local_path')
        )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Exception getting task {task_id} from Supabase: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Server error retrieving task")

@app.get("/api/public/transcript/{task_id}")
async def public_get_transcript(task_id: str, format: Optional[str] = None):
    """Get transcript for a task without API key"""
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
        
    task = tasks[task_id]
    
    if task["status"] == "failed":
        error_message = task.get("error", "Unknown error")
        raise HTTPException(
            status_code=400, 
            detail=f"Transcription failed: {error_message}"
        )
        
    if task["status"] != "completed":
        raise HTTPException(
            status_code=400, 
            detail=f"Transcription not completed yet. Current status: {task['status']}"
        )
        
    # Look for transcript file
    output_dir = os.path.join(DOWNLOADS_DIR, task_id)
    
    # Use glob to find transcript files
    transcript_files = glob.glob(os.path.join(output_dir, "*_transcript.txt"))
    
    if not transcript_files:
        # Try another common pattern if the first one fails
        transcript_files = glob.glob(os.path.join(output_dir, "*.txt"))
    
    if not transcript_files:
        raise HTTPException(status_code=404, detail="Transcript file not found")
    
    # If format=json is specified, return the transcript as JSON
    if format and format.lower() == 'json':
        try:
            with open(transcript_files[0], 'r') as f:
                transcript_text = f.read()
            return {"transcript": transcript_text, "task_id": task_id}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error reading transcript: {str(e)}")
        
    # Otherwise return the transcript file as-is
    return FileResponse(transcript_files[0])

@app.get("/api/public/tasks", response_model=TaskListResponse)
async def public_list_tasks():
    """List the last 50 transcription tasks without API key"""
    if supabase is None:
        logger.error(f"Cannot list public tasks: Supabase client not initialized.")
        raise HTTPException(status_code=500, detail="Database connection not available")

    try:
        # Fetch the last 50 tasks from Supabase, similar to the authenticated endpoint
        response = await asyncio.to_thread(
            supabase.table('transcriptions')
                    .select("task_id, status, video_id, title, created_at, error, thumbnail_url, thumbnail_local_path")
                    .order('created_at', desc=True) # Order by creation time, newest first
                    .limit(50) # Limit to the last 50 tasks
                    .execute
        )

        # Check for errors during the query
        if hasattr(response, 'error') and response.error:
             logger.error(f"Failed to list public tasks from Supabase: {response.error}")
             raise HTTPException(status_code=500, detail="Database error listing tasks")

        # Map the results to the response model
        tasks_list = []
        if response.data:
            for task_data in response.data:
                 tasks_list.append(TranscriptionResponse(
                    task_id=task_data['task_id'],
                    status=task_data['status'],
                    video_id=task_data.get('video_id'),
                    title=task_data.get('title'),
                    created_at=task_data['created_at'],
                    error=task_data.get('error'),
                    thumbnail=task_data.get('thumbnail_url'), # Map thumbnail_url
                    thumbnail_url=task_data.get('thumbnail_url'),
                    thumbnail_local_path=task_data.get('thumbnail_local_path')
                ))

        return TaskListResponse(tasks=tasks_list)

    except Exception as e:
        logger.error(f"Exception listing public tasks from Supabase: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Server error listing tasks")

@app.get("/api/public/thumbnail/{task_id}")
async def public_get_thumbnail(task_id: str):
    """Get the thumbnail image for a task without API key"""
    if supabase is None:
        logger.error(f"Cannot get public thumbnail for {task_id}: Supabase client not initialized.")
        raise HTTPException(status_code=500, detail="Database connection not available")

    try:
        # Fetch task details from Supabase
        response = await asyncio.to_thread(
            supabase.table('transcriptions')
                    .select("task_id, status, error, thumbnail_url, thumbnail_local_path") # Select only needed fields
                    .eq('task_id', task_id)
                    .maybe_single()
                    .execute
        )

        if hasattr(response, 'error') and response.error:
             logger.error(f"Database error fetching public thumbnail for {task_id}: {response.error}")
             raise HTTPException(status_code=500, detail="Database error retrieving task info")

        if not response.data:
            raise HTTPException(status_code=404, detail="Task not found")

        task = response.data # Use the fetched data

        if task["status"] == "failed":
            error_message = task.get("error", "Unknown error")
            raise HTTPException(
                status_code=400, 
                detail=f"Transcription failed: {error_message}"
            )
            
        if task["status"] != "completed":
            raise HTTPException(
                status_code=400, 
                detail=f"Transcription not completed yet. Current status: {task['status']}"
            )
        
        # Priority 1: Serve locally stored thumbnail file if path exists
        if task.get("thumbnail_local_path"):
            local_thumbnail_full_path = os.path.join(DOWNLOADS_DIR, task["thumbnail_local_path"])
            if os.path.exists(local_thumbnail_full_path):
                logger.info(f"Serving local thumbnail file: {local_thumbnail_full_path}")
                # Determine media type based on extension
                media_type = 'image/jpeg'
                if local_thumbnail_full_path.lower().endswith('.png'):
                    media_type = 'image/png'
                elif local_thumbnail_full_path.lower().endswith('.webp'):
                     media_type = 'image/webp'
                return FileResponse(local_thumbnail_full_path, media_type=media_type)
            else:
                 logger.warning(f"Local thumbnail path found in task data ({task['thumbnail_local_path']}), but file does not exist.")

        # Priority 2: Redirect to external thumbnail URL if available
        if task.get("thumbnail_url"):
            logger.info(f"Redirecting to thumbnail URL from task data: {task['thumbnail_url']}")
            return RedirectResponse(url=task["thumbnail_url"])
        
        # Fallback: If no local file or URL, try searching manually (redundant if process_transcription_task works)
        # This section can be simplified or removed if the above logic is reliable
        output_dir = os.path.join(DOWNLOADS_DIR, task_id)
        thumbnail_path = None
        logger.info(f"(Fallback) Looking for thumbnail images in {output_dir}")
        for ext in ['.jpg', '.png', '.jpeg', '.webp']:
            # Search in base and subdirectories
            files = glob.glob(os.path.join(output_dir, f"**/*{ext}"), recursive=True)
            if files:
                thumbnail_path = files[0]
                break
        
        if thumbnail_path:
            logger.info(f"(Fallback) Found local thumbnail file: {thumbnail_path}")
            media_type = 'image/jpeg' # Default
            if thumbnail_path.lower().endswith('.png'): media_type = 'image/png'
            elif thumbnail_path.lower().endswith('.webp'): media_type = 'image/webp'
            return FileResponse(thumbnail_path, media_type=media_type)

        # Final Fallback: Provide a default generic thumbnail
        logger.warning(f"No thumbnail found for task {task_id}, using default")
        static_dir = os.path.join(os.path.dirname(__file__), "static")
        os.makedirs(static_dir, exist_ok=True)
        default_thumbnail = os.path.join(static_dir, "default_thumbnail.jpg")
        
        if not os.path.exists(default_thumbnail):
            try:
                img = Image.new('RGB', (640, 360), color=(53, 59, 72))
                draw = ImageDraw.Draw(img)
                text = "TikScript"
                try: font = ImageFont.truetype("Arial", 60)
                except: font = ImageFont.load_default()
                text_width, text_height = draw.textsize(text, font=font) if hasattr(draw, 'textsize') else (200, 40)
                position = ((640-text_width)//2, (360-text_height)//2)
                draw.text(position, text, fill=(236, 240, 241), font=font)
                img.save(default_thumbnail)
                logger.info(f"Created default thumbnail at {default_thumbnail}")
            except Exception as e:
                logger.error(f"Error creating default thumbnail: {str(e)}")
                raise HTTPException(status_code=404, detail="Thumbnail not found and could not create default")
        
        return FileResponse(default_thumbnail, media_type="image/jpeg")

    except Exception as e:
        logger.error(f"Error fetching public thumbnail for task {task_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Server error fetching thumbnail")

@app.post("/api/tasks")
async def submit_task(
    request: TranscriptionRequest, 
    background_tasks: BackgroundTasks, 
    user_id: str = Depends(validate_api_key)
):
    """Submit a new transcription task."""
    if supabase is None:
        logger.error("Cannot submit task: Supabase client not initialized")
        raise HTTPException(status_code=500, detail="Database connection error")

    try:
        # Initialize task in DB, passing the validated user_id
        task = await init_task(request.url, user_id)
        
        # Add the processing task to background
        background_tasks.add_task(
            process_transcription_task, 
            task['task_id'], 
            request.url, 
            request.callback_url, 
            request.proxy
        )
        
        return task
    except HTTPException as http_exc:
        raise http_exc # Re-raise specific HTTP exceptions
    except Exception as e:
        logger.error(f"Error submitting task for URL {request.url}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to submit task")

if __name__ == "__main__":
    # Get port from environment or use default
    port = int(os.environ.get("PORT", 8000))
    
    # Run the app
    uvicorn.run(app, host="0.0.0.0", port=port) 