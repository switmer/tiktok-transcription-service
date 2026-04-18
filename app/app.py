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
from datetime import datetime, timezone, timedelta
import uuid
import tempfile
from fastapi import FastAPI, BackgroundTasks, HTTPException, Depends, Header, Request, Query, Form, status
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse, Response, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
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
from functools import wraps
from PIL import Image, ImageDraw, ImageFont, ImageOps
try:
    from supabase.client import create_client, Client
except Exception:
    create_client = None
    Client = Any
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

# Fix imports for deployment
try:
    # Try relative import first (when running as a package)
    from .database import supabase
    from . import discovery
    from . import transcriber
    from . import sms
    from .tiktok_service import tiktok_service
    from . import health_check
    from .storage_utils import upload_thumbnail_to_supabase
    from .core.paths import BASE_DIR, DOWNLOADS_DIR, static_dir, templates
    from .core.errors import (
        ApiError, AUTH_REQUIRED, AUTH_INVALID, TASK_NOT_FOUND, TASK_NOT_RETRYABLE,
        TRANSCRIPT_NOT_READY, INSUFFICIENT_CREDITS, VALIDATION_ERROR,
        SERVICE_UNAVAILABLE, INTERNAL_ERROR,
    )
except ImportError:
    # Fall back to absolute imports (when running directly)
    import sys
    import os
    sys.path.insert(0, os.path.dirname(__file__))
    import database
    import discovery
    import transcriber
    import sms
    import health_check
    from database import supabase
    from tiktok_service import tiktok_service
    from storage_utils import upload_thumbnail_to_supabase
    from core.paths import BASE_DIR, DOWNLOADS_DIR, static_dir, templates
    from core.errors import (
        ApiError, AUTH_REQUIRED, AUTH_INVALID, TASK_NOT_FOUND, TASK_NOT_RETRYABLE,
        TRANSCRIPT_NOT_READY, INSUFFICIENT_CREDITS, VALIDATION_ERROR,
        SERVICE_UNAVAILABLE, INTERNAL_ERROR,
    )

# Import tiktok downloader directly
try:
    from local_scripts.download_tiktok import download_tiktok as enhanced_download_tiktok
except ImportError:
    # If local_scripts isn't available, use the built-in transcriber
    enhanced_download_tiktok = transcriber.download_tiktok
    print("Using transcriber.download_tiktok as fallback")

# Configure logging with redaction
from .log_redactor import RedactingFormatter

_handler = logging.StreamHandler()
_handler.setFormatter(RedactingFormatter('%(asctime)s - %(levelname)s - %(message)s'))
logging.root.addHandler(_handler)
logging.root.setLevel(logging.INFO)
logger = logging.getLogger(__name__)

# Task timeout decorator
def task_timeout(timeout_seconds=1800):  # 30 minutes default
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await asyncio.wait_for(func(*args, **kwargs), timeout=timeout_seconds)
            except asyncio.TimeoutError:
                task_id = args[0] if args else "unknown"
                logger.error(f"Task {task_id} timeout after {timeout_seconds}s")
                await update_task_status(task_id, "failed", f"Task timeout after {timeout_seconds}s")
                return None
        return wrapper
    return decorator

app = FastAPI(
    title="ScribeTok - TikTok/YouTube Transcription API",
    description="""
🎬 **Complete video transcription service with SMS integration and phone-first authentication**

## Key Features
- 📱 **SMS Integration** - Text video URLs for instant transcription
- 💬 **Web Chat** - Continue SMS conversations in browser with full responses
- 🔐 **Phone-First Auth** - No email required, OTP-based verification
- 🚀 **Viral Sharing** - Public transcript pages with social features
- 📊 **Rich Metadata** - 20+ fields from TikTok/YouTube videos
- 🔍 **Content Discovery** - Trending, similar, and recent transcriptions

## User Flow
1. **Text Video URL** → Instant transcription (no signup required)
2. **Text `/chat`** → Ask questions about your transcript via SMS
3. **Click Web Link** → Continue chat in browser with full-length AI responses
4. **Text `/register`** → Create account with full history preserved

Perfect for building viral social media tools and content analysis applications.
    """,
    version="1.0.0",
    contact={
        "name": "ScribeTok API Support",
        "url": "https://scribetok.com",
    },
    license_info={
        "name": "API License",
        "url": "https://scribetok.com/terms",
    },
    tags_metadata=[
        {
            "name": "Public Transcription",
            "description": "Start transcription tasks and access results. No authentication required.",
        },
        {
            "name": "Private Task Management", 
            "description": "Manage transcription tasks with full control. Requires API key authentication.",
        },
        {
            "name": "SMS Integration",
            "description": "SMS webhooks and phone-first authentication system.",
        },
        {
            "name": "Content Discovery",
            "description": "Discover trending, similar, and recent transcriptions.",
        },
        {
            "name": "Web Chat",
            "description": "Continue SMS conversations in the browser. Full-length AI responses without SMS character limits.",
        },
        {
            "name": "System & Health",
            "description": "Service health checks and system maintenance endpoints.",
        },
    ],
)

# Mount static files (only if directory exists)
import os
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# In-memory task map used by legacy test endpoints; keep defined to avoid runtime/lint errors
tasks: Dict[str, Dict[str, Any]] = {}

# CORS configuration
_DEFAULT_ORIGINS = [
    "https://scribetok.com",
    "https://www.scribetok.com",
    "https://share.scribetok.com",
    "https://api.scribetok.com",
]
_DEV_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://localhost:8001",
]

def _load_allowed_origins():
    extra = os.getenv("ALLOWED_ORIGINS", "")
    origins = list(_DEFAULT_ORIGINS)
    if os.getenv("ENVIRONMENT", "production") != "production":
        origins.extend(_DEV_ORIGINS)
    if extra:
        origins.extend([o.strip() for o in extra.split(",") if o.strip()])
    return origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=_load_allowed_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)

@app.exception_handler(ApiError)
async def api_error_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.detail, "details": exc.details}},
    )

# Scanner/bot filter patterns - silently reject common vulnerability probes
SCANNER_PATTERNS = {
    ".env", ".git", "wp-config", ".sql", ".key",
    ".pem", "id_rsa", "node_modules", "vendor",
    "admin/phpmyadmin", "database_backup"
}

@app.middleware("http")
async def filter_scanners(request: Request, call_next):
    path = request.url.path.lower()
    if any(pattern in path for pattern in SCANNER_PATTERNS):
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": "Not Found"}
        )
    return await call_next(request)

# Mount at /static so CSS/JS/images are served
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Initialize Supabase client
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_KEY")

if not supabase_url or not supabase_key:
    logger.warning("Supabase URL or Service Key not found in environment variables. Database operations will fail.")
    supabase: Client | None = None
elif create_client is None:
    logger.error("Supabase client library unavailable; database operations disabled.")
    supabase = None
else:
    try:
        supabase: Client = create_client(supabase_url, supabase_key)
        logger.info("Supabase client initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize Supabase client: {str(e)}")
        supabase = None

# Include discovery routes
app.include_router(discovery.router)

from .core.auth import validate_api_key, verify_api_key
from .models.schemas import (
    TranscriptionRequest,
    TranscriptionResponse,
    TaskListResponse,
    SearchHit,
    SearchResponse,
    TranscriptChatRequest,
    TranscriptChatResponse,
    HealthCheckResponse,
    SMSResponse,
    AccountLinkResponse,
    SmsChatRequest,
    SmsChatResponse,
    SmsChatResetResponse,
    SmsChatResetRequest,
    FetchCommentsRequest,
)


@app.get("/", include_in_schema=False)
async def root(ref: Optional[str] = None):
    """Landing page with optional referral code tracking"""
    if ref:
        # Track referral code for later use
        # Store in a simple way that can be retrieved when user texts
        try:
            # Store referral code with timestamp in database for tracking
            supabase.table("pending_referrals").insert({
                "referral_code": ref,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "expires_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
            }).execute()
        except:
            pass  # Continue even if tracking fails
        
        return {
            "message": "🎁 Welcome to ScribeTok! You've been referred by a friend.",
            "instructions": f"Text any TikTok or YouTube link to (774) 472-7423 to claim your 5 bonus credits!",
            "referral_code": ref,
            "phone_number": "+17744727423"
        }
    
    return {"message": "TikTok Transcription API. See /docs for documentation."}

@app.get("/robots.txt", include_in_schema=False)
async def robots_txt():
    """Serve robots.txt from static directory"""
    path = os.path.join(static_dir, "robots.txt")
    if not os.path.exists(path):
        return Response(status_code=404)
    return FileResponse(path, media_type="text/plain")

@app.get("/apple-touch-icon.png", include_in_schema=False)
@app.get("/apple-touch-icon-precomposed.png", include_in_schema=False)
async def apple_touch_icon():
    """Serve apple-touch-icon.png from static directory"""
    path = os.path.join(static_dir, "apple-touch-icon.png")
    if not os.path.exists(path):
        return Response(status_code=404)
    return FileResponse(path, media_type="image/png")

@app.get("/favicon.ico", include_in_schema=False)
async def favicon_ico():
    """Serve favicon.ico from static directory"""
    path = os.path.join(static_dir, "favicon.ico")
    if not os.path.exists(path):
        return Response(status_code=404)
    return FileResponse(path, media_type="image/x-icon")

# ===========================================
# HEALTH CHECK ENDPOINTS
# ===========================================

@app.get("/health", tags=["Health Check"])
async def health_simple():
    """Simple health check for load balancers"""
    return await health_check.get_simple_health()

@app.get("/health/detailed", tags=["Health Check"])
async def health_detailed():
    """Comprehensive health check with all service status"""
    return await health_check.get_health_status()

@app.get("/health/ready", tags=["Health Check"])
async def health_ready():
    """Readiness probe for orchestration systems"""
    return await health_check.get_readiness()

@app.get("/health/live", tags=["Health Check"])
async def health_live():
    """Liveness probe for orchestration systems"""
    try:
        # Basic liveness check - can we respond?
        return {
            "status": "alive",
            "timestamp": datetime.utcnow().isoformat(),
            "uptime_seconds": int(time.time() - health_check.health_checker.start_time)
        }
    except Exception as e:
        raise ApiError(503, SERVICE_UNAVAILABLE, f"Service not alive: {str(e)}")

# Public transcription endpoints moved to app/api/public.py

@app.get("/api/tasks", response_model=TaskListResponse, tags=["Private Task Management"])
async def list_tasks(api_key: str = Depends(verify_api_key)):
    """List the last 50 transcription tasks from Supabase."""
    if supabase is None:
        logger.error(f"Cannot list tasks: Supabase client not initialized.")
        raise ApiError(503, SERVICE_UNAVAILABLE, "Database connection not available")

    try:
        response = await asyncio.to_thread(
            lambda: supabase.table('transcriptions')
                            .select("task_id, status, video_id, title, description, created_at, error, thumbnail_url, thumbnail_local_path")
                            .order('created_at', desc=True)  # newest first
                            .limit(50)
                            .execute()
        )

        # Check for errors during the query
        if hasattr(response, 'error') and response.error:
             logger.error(f"Failed to list tasks from Supabase: {response.error}")
             raise ApiError(500, INTERNAL_ERROR, "Database error listing tasks")
             
        # Map the results to the response model
        tasks_list = []
        if response.data:
            for task_data in response.data:
                 tasks_list.append(TranscriptionResponse(
                    task_id=task_data['task_id'],
                    status=task_data['status'],
                    video_id=task_data.get('video_id'),
                    title=task_data.get('title'),
                    description=task_data.get('description'),
                    created_at=task_data['created_at'],
                    error=task_data.get('error'),
                    thumbnail=task_data.get('thumbnail_url'), # Map thumbnail_url
                    thumbnail_url=task_data.get('thumbnail_url'),
                    thumbnail_local_path=task_data.get('thumbnail_local_path')
                ))
                
        return TaskListResponse(tasks=tasks_list, total=len(tasks_list), limit=50, offset=0)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Exception listing tasks from Supabase: {str(e)}", exc_info=True)
        raise ApiError(500, INTERNAL_ERROR, "Server error listing tasks")

@app.get(
    "/api/tasks/{task_id}",
    response_model=TranscriptionResponse,
    tags=["Private Task Management"],
    responses={
        200: {
            "description": "Successful Response",
            "content": {
                "application/json": {
                    "example": {
                        "task_id": "550e8400-e29b-41d4-a716-446655440000",
                        "status": "completed",
                        "video_id": "7526401258786245902",
                        "title": "Amazing TikTok Video",
                        "created_at": "2025-07-20T12:00:00Z",
                        "error": None,
                        "thumbnail_url": "https://example.com/thumb.jpg",
                        "video_url": "https://cdn.tiktok.com/...",
                        "duration": 122,
                        "like_count": 1500,
                        "comment_count": 89,
                        "repost_count": 234,
                        "view_count": 15,
                        "platform": "tiktok",
                        "tags": ["tech", "viral"],
                        "category": "technology"
                    }
                }
            }
        },
        404: {
            "description": "Task not found",
            "content": {"application/json": {"example": {"detail": "Task not found"}}}
        },
        500: {
            "description": "Server error",
            "content": {"application/json": {"example": {"detail": "Database connection not available"}}}
        }
    }
)
async def get_task(task_id: str, api_key: str = Depends(verify_api_key)):
    """Get task status from Supabase."""
    if supabase is None:
        logger.error(f"Cannot get task {task_id}: Supabase client not initialized.")
        raise ApiError(503, SERVICE_UNAVAILABLE, "Database connection not available")
    try:
        response = await asyncio.to_thread(
            lambda: supabase.table('transcriptions')
                            .select("task_id, status, video_id, title, description, created_at, error, thumbnail_url, thumbnail_local_path, video_url, duration, like_count, comment_count, repost_count, view_count, platform, tags, category")
                            .eq('task_id', task_id)
                            .maybe_single()
                            .execute()
        )
        if hasattr(response, 'error') and response.error:
             logger.error(f"Failed to get task {task_id} from Supabase: {response.error}")
             raise ApiError(500, INTERNAL_ERROR, "Database error retrieving task")
        if not response.data:
            raise ApiError(404, TASK_NOT_FOUND, "Task not found")
        task_data = response.data
        return TranscriptionResponse(**task_data)
    except HTTPException:
         raise
    except Exception as e:
        logger.error(f"Exception getting task {task_id} from Supabase: {str(e)}", exc_info=True)
        raise ApiError(500, INTERNAL_ERROR, "Server error retrieving task")

@app.delete("/api/tasks/{task_id}", status_code=204, tags=["Private Task Management"])
async def delete_task(task_id: str, api_key: str = Depends(verify_api_key)):
    """Delete task record from Supabase and associated local files."""
    if supabase is None:
        logger.error(f"Cannot delete task {task_id}: Supabase client not initialized.")
        raise ApiError(503, SERVICE_UNAVAILABLE, "Database connection not available")

    # Step 1: Attempt to delete the record from Supabase first
    try:
        response = await asyncio.to_thread(
            lambda: supabase.table('transcriptions')
                            .delete()
                            .eq('task_id', task_id)
                            .execute()
        )
        
        # Check for errors during delete
        if hasattr(response, 'error') and response.error:
            logger.error(f"Failed to delete task {task_id} from Supabase: {response.error}")
            # Decide if this is a 500 or if we should still try to delete files
            # For now, let's treat DB error as critical
            raise ApiError(500, INTERNAL_ERROR, "Database error deleting task")

        # Check if any rows were actually deleted (response.data might be empty on delete)
        # Supabase delete often returns the deleted records in response.data
        if not response.data:
            # If no data was returned (and no error), the task ID likely didn't exist
            raise ApiError(404, TASK_NOT_FOUND, "Task not found in database")
            
        logger.info(f"Task {task_id} deleted from Supabase.")

    except HTTPException: # Re-raise 404 or other HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Exception deleting task {task_id} from Supabase: {str(e)}", exc_info=True)
        raise ApiError(500, INTERNAL_ERROR, "Server error deleting task record")

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

    return Response(status_code=204)

@app.get("/api/healthcheck", response_model=HealthCheckResponse, tags=["System & Health"])
async def healthcheck():
    """
    Health check endpoint with service status.
    """
    # Check service statuses
    services = {
        "openai": "connected" if os.getenv("OPENAI_API_KEY") else "disconnected",
        "supabase": "connected" if supabase is not None else "disconnected",
        "rapidapi": "connected" if os.getenv("RAPIDAPI_KEY") else "disconnected"
    }
    
    return {
        "status": "ok",
        "version": "1.0.0",
        "timestamp": time.time(),
        "services": services
    }

@app.get("/api/test", response_model=str, tags=["System & Health"])
async def test_endpoint(api_key: str = Depends(verify_api_key)):
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

@app.post("/api/test-download", response_model=str, tags=["System & Health"])
async def test_download(request: Request, api_key: str = Depends(verify_api_key)):
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

@app.post("/api/fallback-download", tags=["System & Health"])
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
                output_dir=task_dir,
                video_id=result["video_id"]
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

async def transcribe_and_save(task_id: str, audio_file: str, output_dir: str, video_id: str):
    """Transcribe an audio file and save the transcript"""
    try:
        # Transcribe the audio file (audio_file parameter is already the correct path)
        transcript_response, transcript_file_path_abs = transcriber.transcribe_audio(audio_file, output_dir, video_id)
        
        if transcript_response:
            final_status = "completed"
            final_error = None
            # Store relative path to transcript file
            transcript_file_path = os.path.relpath(transcript_file_path_abs, DOWNLOADS_DIR)
            
            # Read the transcript content
            with open(transcript_file_path_abs, 'r', encoding='utf-8') as f:
                transcript_text = f.read()
            
            # Generate quote and TLDR (skip if already exists from a previous run)
            quote_tldr_result = {}
            try:
                existing_qt = supabase.table('transcriptions').select('quote, tldr').eq('task_id', task_id).maybe_single().execute()
                if existing_qt.data and existing_qt.data.get('quote'):
                    logger.info(f"Skipping quote/TLDR generation for task {task_id} — already exists")
                    quote_tldr_result = {
                        "quote": existing_qt.data['quote'],
                        "tldr": json.loads(existing_qt.data['tldr']) if existing_qt.data.get('tldr') else []
                    }
                else:
                    quote_tldr_result = transcriber.generate_quote_and_tldr(
                        transcript_text,
                        title=ytdlp_title or "",
                        description=""
                    )
            except Exception as e:
                logger.error(f"Failed to generate quote/TLDR for task {task_id}: {str(e)}")
                # Continue without quote/TLDR rather than failing the entire enrichment
            
            # Update Supabase with transcript content, file path, quote and TLDR
            update_data = {
                "status": final_status,
                "error": final_error,
                "transcript": transcript_text,
                "transcript_file_path": transcript_file_path
            }
            
            # Add quote and TLDR if generated successfully
            if quote_tldr_result.get("quote"):
                update_data["quote"] = quote_tldr_result["quote"]
                logger.info(f"Generated quote: {quote_tldr_result['quote']}")
            
            if quote_tldr_result.get("tldr"):
                update_data["tldr"] = json.dumps(quote_tldr_result["tldr"])  # Store as JSON
                logger.info(f"Generated TLDR: {quote_tldr_result['tldr']}")
            
            result = supabase.table('transcriptions').update(update_data).eq('task_id', task_id).execute()
            if result.data:
                logger.info(f"Successfully updated transcription with quote/TLDR for task {task_id}")
            else:
                logger.warning(f"Quote/TLDR update returned no data for task {task_id}: {result}")
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

def is_youtube_url(url: str) -> bool:
    """Check if URL is a YouTube video."""
    import re
    youtube_patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/|m\.youtube\.com/watch\?v=)([^&\n?#]+)',
        r'(?:www\.)?youtube\.com/watch\?v=[\w-]+',
        r'(?:www\.)?youtu\.be/[\w-]+',
        r'(?:www\.)?youtube\.com/shorts/[\w-]+',
        r'(?:m\.)?youtube\.com/watch\?v=[\w-]+'
    ]
    return any(re.search(pattern, url, re.IGNORECASE) for pattern in youtube_patterns)

def normalize_proxy(proxy: Optional[str]) -> Optional[str]:
    """Return a well-formed proxy URL or None."""
    if not proxy:
        return None
    try:
        val = str(proxy).strip()
        parts = urlsplit(val)
        if parts.scheme and parts.netloc:
            return val
    except Exception:
        pass
    return None


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

def create_square_thumbnail(input_path: str, output_path: str, size: int = 1200) -> bool:
    """
    Create a square (1:1) thumbnail from an input image for optimal iMessage/WhatsApp previews.
    
    Args:
        input_path: Path to the original thumbnail image
        output_path: Path where the square thumbnail will be saved
        size: Size of the square (default 1200x1200 for OG images)
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        with Image.open(input_path) as img:
            # Convert to RGB if necessary (handles RGBA, grayscale, etc.)
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Center-crop to square using ImageOps.fit
            square_img = ImageOps.fit(img, (size, size), Image.Resampling.LANCZOS, centering=(0.5, 0.5))
            
            # Save with high quality
            square_img.save(output_path, "JPEG", quality=95, optimize=True)
            logger.info(f"Created square thumbnail: {output_path}")
            return True
            
    except Exception as e:
        logger.error(f"Error creating square thumbnail: {str(e)}")
        return False

@task_timeout(1800)  # 30-minute timeout
async def process_transcription_task(task_id: str, video_url: str, callback_url: Optional[str] = None, proxy: Optional[str] = None):
    """Process a transcription task asynchronously."""
    if supabase is None:
        logger.error(f"Cannot process task {task_id}: Supabase client not initialized")
        return

    try:
        # --- Fetch the original URL and user_phone from the database --- 
        task_response = await asyncio.to_thread(
            lambda: supabase.table('transcriptions')
                            .select("url, user_phone")  # Fetch URL and user_phone for SMS notifications
                            .eq('task_id', task_id)
                            .single()  # Expect exactly one result
                            .execute()
        )
        
        if not task_response.data or 'url' not in task_response.data:
             logger.error(f"Could not retrieve original URL for task {task_id} from database.")
             await update_task_status(task_id, "failed", "Failed to retrieve task URL from database")
             return
             
        original_video_url = task_response.data['url']
        user_phone = task_response.data.get('user_phone')  # Get user phone for SMS notifications
        logger.info(f"Processing task {task_id} with original URL from DB: {original_video_url}, SMS phone: {user_phone or 'none'}")

        url_lower = (original_video_url or "").lower()
        if "instagram.com" in url_lower:
            platform_hint = "instagram"
        elif "facebook.com" in url_lower or "fb.watch" in url_lower:
            platform_hint = "facebook"
        elif "youtube.com" in url_lower or "youtu.be" in url_lower:
            platform_hint = "youtube"
        elif "linkedin.com" in url_lower or "licdn.com" in url_lower:
            platform_hint = "linkedin"
        elif "spotify.com" in url_lower:
            platform_hint = "spotify"
        else:
            platform_hint = "tiktok"
        # -------------------------------------------------
        
        # Check if this is a YouTube URL for instant transcription
        if is_youtube_url(original_video_url):
            logger.info(f"Detected YouTube URL, attempting instant transcription: {original_video_url}")
            
            # Try YouTube instant transcription via RapidAPI
            youtube_result = transcriber.download_youtube_rapidapi(original_video_url)
            
            if youtube_result:
                logger.info(f"YouTube instant transcription successful for task {task_id}")
                
                # Update task with completed status and transcript
                # For YouTube, still do full enrichment to ensure complete rows
                transcript_text = youtube_result['transcript']
                video_id = youtube_result['video_id']
                title = youtube_result['title']
                platform = 'youtube'
                
                # Generate quote and TLDR for YouTube too (skip if already exists)
                quote_tldr_result = {}
                try:
                    existing_qt = supabase.table('transcriptions').select('quote, tldr').eq('task_id', task_id).maybe_single().execute()
                    if existing_qt.data and existing_qt.data.get('quote'):
                        logger.info(f"Skipping quote/TLDR generation for YouTube task {task_id} — already exists")
                        quote_tldr_result = {
                            "quote": existing_qt.data['quote'],
                            "tldr": json.loads(existing_qt.data['tldr']) if existing_qt.data.get('tldr') else []
                        }
                    else:
                        quote_tldr_result = transcriber.generate_quote_and_tldr(
                            transcript_text,
                            title=title or "",
                            description=youtube_result.get('description') or ""
                        )
                        logger.info(f"Generated quote/TLDR for YouTube video {video_id}")
                except Exception as e:
                    logger.warning(f"Failed to generate quote/TLDR for YouTube video: {str(e)}")
                
                # Prepare complete update data for YouTube
                update_data = {
                    'status': 'completed',
                    'video_id': video_id,
                    'title': title,
                    'description': youtube_result.get('description'),
                    'transcript': transcript_text,
                    'platform': platform,
                    'category': 'youtube-transcription',
                    'tags': ['sms-inbound', 'youtube'] if user_phone else ['youtube'],
                    'error': None,
                    'thumbnail_url': youtube_result.get('thumbnail_url'),
                    'duration': youtube_result.get('duration'),
                    'uploader': youtube_result.get('uploader'),
                    'channel': youtube_result.get('channel'),
                    'view_count': 1,  # Initialize view count
                    'visibility': 'public'
                }
                if youtube_result.get('metadata') is not None:
                    update_data['raw_metadata'] = youtube_result.get('metadata')
                
                # Add quote and TLDR if generated successfully
                if quote_tldr_result.get("quote"):
                    update_data["quote"] = quote_tldr_result["quote"]
                    logger.info(f"Generated quote: {quote_tldr_result['quote']}")
                if quote_tldr_result.get("tldr"):
                    update_data["tldr"] = json.dumps(quote_tldr_result["tldr"])
                    logger.info(f"Generated TLDR: {quote_tldr_result['tldr']}")
                
                # Add user_phone if available (SMS context)
                if user_phone:
                    update_data['user_phone'] = user_phone
                
                result = supabase.table('transcriptions').update(update_data).eq('task_id', task_id).execute()
                if result.data:
                    logger.info(f"Successfully updated transcription with download results for task {task_id}")
                else:
                    logger.warning(f"Download results update returned no data for task {task_id}: {result}")
                
                # Send SMS notification if user_phone is provided
                if user_phone:
                    try:
                        quote = quote_tldr_result.get("quote", "")
                        tldr_list = quote_tldr_result.get("tldr", [])
                        await send_completion_sms(task_id, user_phone, title or 'Video', transcript_text, quote, tldr_list)
                        logger.info(f"SMS completion notification sent for YouTube task {task_id}")
                    except Exception as sms_error:
                        logger.error(f"Failed to send SMS notification for YouTube task {task_id}: {str(sms_error)}")

                # Clean up - no local files needed for YouTube instant transcription
                output_dir = os.path.join(DOWNLOADS_DIR, task_id)
                if os.path.exists(output_dir):
                    shutil.rmtree(output_dir)
                    
                logger.info(f"YouTube instant transcription completed for task {task_id}")
                return
            else:
                logger.warning(f"YouTube instant transcription failed, attempting yt-dlp fallback for task {task_id}")
                # Try YouTube yt-dlp fallback path before generic pipeline
                try:
                    output_dir = os.path.join(DOWNLOADS_DIR, task_id)
                    os.makedirs(output_dir, exist_ok=True)
                    ytdlp_audio, ytdlp_video_id, ytdlp_title = transcriber.download_youtube_ytdlp(original_video_url, output_dir)
                    if ytdlp_audio and ytdlp_video_id:
                        # Proceed with transcription using downloaded audio
                        await update_task_status(task_id, "transcribing")
                        transcript_response, transcript_file_path = transcriber.transcribe_audio(ytdlp_audio, output_dir, ytdlp_video_id)
                        if transcript_response:
                            await update_task_status(task_id, "generating")
                            # Load transcript text
                            transcript_text = ""
                            if transcript_file_path and os.path.exists(transcript_file_path):
                                with open(transcript_file_path, 'r', encoding='utf-8') as f:
                                    transcript_text = f.read()
                            # Quote/TLDR (skip if already exists)
                            quote_tldr_result = {}
                            try:
                                existing_qt = supabase.table('transcriptions').select('quote, tldr').eq('task_id', task_id).maybe_single().execute()
                                if existing_qt.data and existing_qt.data.get('quote'):
                                    logger.info(f"Skipping quote/TLDR generation (yt-dlp path) for task {task_id} — already exists")
                                    quote_tldr_result = {
                                        "quote": existing_qt.data['quote'],
                                        "tldr": json.loads(existing_qt.data['tldr']) if existing_qt.data.get('tldr') else []
                                    }
                                else:
                                    quote_tldr_result = transcriber.generate_quote_and_tldr(
                                        transcript_text,
                                        title=ytdlp_title or "",
                                        description=""
                                    )
                            except Exception as e:
                                logger.error(f"Failed to generate quote/TLDR (yt-dlp path) for task {task_id}: {e}")
                            # Update DB
                            update_data = {
                                'status': 'completed',
                                'video_id': ytdlp_video_id,
                                'title': ytdlp_title,
                                'transcript': transcript_text,
                                'platform': 'youtube',
                                'category': 'youtube-transcription',
                                'tags': ['sms-inbound', 'youtube'] if user_phone else ['youtube'],
                                'error': None,
                                'view_count': 1,
                                'visibility': 'public'
                            }
                            if quote_tldr_result.get('quote'):
                                update_data['quote'] = quote_tldr_result['quote']
                            if quote_tldr_result.get('tldr'):
                                update_data['tldr'] = json.dumps(quote_tldr_result['tldr'])
                            supabase.table('transcriptions').update(update_data).eq('task_id', task_id).execute()
                            # SMS notify
                            if user_phone:
                                try:
                                    quote = quote_tldr_result.get("quote", "")
                                    tldr_list = quote_tldr_result.get("tldr", [])
                                    await send_completion_sms(task_id, user_phone, ytdlp_title or 'Video', transcript_text, quote, tldr_list)
                                except Exception as sms_error:
                                    logger.error(f"Failed to send SMS notification (yt-dlp path) for task {task_id}: {sms_error}")
                            # Cleanup
                            try:
                                if os.path.exists(output_dir):
                                    shutil.rmtree(output_dir)
                            except Exception:
                                pass
                            logger.info(f"YouTube yt-dlp fallback completed for task {task_id}")
                            return
                        else:
                            logger.error(f"Transcription failed on yt-dlp fallback for task {task_id}")
                    else:
                        logger.warning(f"yt-dlp fallback did not yield audio/video_id for task {task_id}")
                except Exception as e:
                    logger.error(f"YouTube yt-dlp fallback error for task {task_id}: {e}", exc_info=True)
                logger.warning(f"Falling back to generic pipeline for task {task_id}")
        
        # Standard TikTok processing or YouTube fallback
        # Create a unique working directory for this task
        output_dir = os.path.join(DOWNLOADS_DIR, task_id)
        os.makedirs(output_dir, exist_ok=True)
        
        # Download the video and extract audio using the original URL
        # Note: The 'video_url' argument to this function is now ignored.
        download_result = transcriber.download_tiktok(original_video_url, output_dir, proxy)
        
        # Handle dict return format with video_url (transcriber now always returns dict)
        audio_file = download_result.get("audio_file") if download_result else None
        video_id = download_result.get("video_id") if download_result else None
        title = download_result.get("title") if download_result else None
        direct_video_url = download_result.get("video_url") if download_result else None
        download_thumbnail_url = download_result.get("thumbnail_url") if download_result else None
        
        if not audio_file or not video_id:
            logger.error(f"Download failed for task {task_id} using URL: {original_video_url}")
            await update_task_status(task_id, "failed", "Failed to download video")
            if user_phone:
                try:
                    await sms.send_sms(
                        user_phone,
                        "❌ Sorry, we couldn't process that link. It may require login or be rate-limited. Try again later or text /help."
                    )
                except Exception as sms_error:
                    logger.error(f"Failed to send SMS failure notice for task {task_id}: {sms_error}")
            return
            
        # Update task with initial download results
        result = supabase.table('transcriptions').update({
            'status': 'processing',
            'video_id': video_id,
            'title': title
        }).eq('task_id', task_id).execute()
        
        if result.data:
            logger.info(f"Successfully updated task {task_id} to processing status")
        else:
            logger.warning(f"Processing status update returned no data for task {task_id}: {result}")
        
        # Extract rich metadata from .info.json files
        thumbnail_url = download_thumbnail_url  # May come from Spotify download result
        thumbnail_local_path = None
        rich_metadata = {}
        
        # Read metadata files for comprehensive data extraction
        metadata_files = glob.glob(os.path.join(output_dir, "*.info.json"))
        logger.info(f"Looking for metadata files in {output_dir}, found: {metadata_files}")
        
        if metadata_files:
            try:
                with open(metadata_files[0], 'r') as f:
                    metadata = json.load(f)
                    logger.info(f"Processing rich metadata from: {metadata_files[0]}")
                    logger.info(f"Metadata keys: {list(metadata.keys())}")
                    
                    # Extract thumbnail URL
                    thumbnail_url = metadata.get('thumbnail_url') or metadata.get('thumbnail') or metadata.get('cover')
                    if thumbnail_url:
                        logger.info(f"Found thumbnail URL in metadata: {thumbnail_url}")
                    
                    # Extract comprehensive metadata for database storage
                    # Handle RapidAPI, Spotify, and yt-dlp metadata formats
                    if 'podcast' in metadata:  # Spotify format
                        podcast = metadata.get('podcast', {})
                        author = metadata.get('author', {})
                        audio = metadata.get('audio', {})
                        thumbnail_url = thumbnail_url or audio.get('cover')
                        duration_sec = audio.get('duration')
                        rich_metadata = {
                            'description': metadata.get('description'),
                            'duration': int(duration_sec) if duration_sec else None,
                            'upload_date': podcast.get('release_date'),
                            'channel': podcast.get('show_name'),
                            'channel_id': podcast.get('show_id'),
                            'uploader': podcast.get('publisher') or podcast.get('show_name'),
                            'uploader_url': metadata.get('original_url'),
                            'like_count': None,
                            'comment_count': None,
                            'repost_count': None,
                            'view_count': None,
                            'acodec': 'mp3',
                            'language': podcast.get('language') or 'english',
                            'platform': 'spotify'
                        }
                    elif 'data' in metadata:  # RapidAPI format
                        data = metadata['data']
                        author = data.get('author', {})
                        rich_metadata = {
                            'description': data.get('title'),  # RapidAPI puts description in title
                            'duration': data.get('duration'),
                            'upload_date': None,  # Not available in RapidAPI
                            'timestamp': data.get('create_time'),
                            'channel': author.get('unique_id') or author.get('nickname'),
                            'channel_id': author.get('id'),
                            'uploader': author.get('unique_id') or author.get('nickname'),
                            'uploader_url': f"https://tiktok.com/@{author.get('unique_id')}" if author.get('unique_id') else None,
                            'like_count': data.get('digg_count', 0),  # ✅ Extract from raw_metadata
                            'comment_count': data.get('comment_count', 0),  # ✅ Extract from raw_metadata
                            'repost_count': data.get('share_count', 0),  # ✅ Extract from raw_metadata
                            'view_count': data.get('play_count', 0),  # ✅ Extract from raw_metadata
                            'resolution': None,  # Not directly available
                            'width': None,
                            'height': None,
                            'aspect_ratio': None,
                            'filesize': data.get('hd_size'),
                            'format_id': data.get('aweme_id'),  # Use aweme_id if available
                            'vcodec': 'h264',  # Assume h264 for TikTok
                            'acodec': 'aac',   # Assume aac for TikTok
                            'language': 'english',  # Default for now
                            'platform': 'tiktok'
                        }
                    else:  # yt-dlp format
                        rich_metadata = {
                            'description': metadata.get('description'),
                            'duration': metadata.get('duration'),
                            'upload_date': metadata.get('upload_date'),
                            'timestamp': metadata.get('timestamp'),
                            'channel': metadata.get('channel') or metadata.get('uploader_id'),
                            'channel_id': metadata.get('channel_id') or metadata.get('uploader_url'),
                            'uploader': metadata.get('uploader'),
                            'uploader_url': metadata.get('uploader_url'),
                            'like_count': metadata.get('like_count', 0),
                            'comment_count': metadata.get('comment_count', 0),
                            'repost_count': metadata.get('repost_count', 0),
                            'resolution': metadata.get('resolution'),
                            'width': metadata.get('width'),
                            'height': metadata.get('height'),
                            'aspect_ratio': metadata.get('aspect_ratio'),
                            'filesize': metadata.get('filesize'),
                            'format_id': metadata.get('format_id'),
                            'vcodec': metadata.get('vcodec'),
                            'acodec': metadata.get('acodec'),
                            'language': metadata.get('language') or 'english',
                            'platform': platform_hint
                        }
                    
                    # Clean up None values and convert to appropriate types
                    rich_metadata = {k: v for k, v in rich_metadata.items() if v is not None}
                    
                    logger.info(f"Extracted rich metadata: {list(rich_metadata.keys())}")
                    
            except Exception as e:
                logger.warning(f"Failed to read metadata for rich data extraction: {str(e)}")
        else:
            logger.warning(f"No metadata files found in {output_dir} - rich metadata will be empty")
        
        # Look for downloaded thumbnail files
        thumbnail_extensions = ['.jpg', '.jpeg', '.png', '.webp']
        supabase_thumbnail_url = None
        square_supabase_url = None
        for ext in thumbnail_extensions:
            thumbnail_files = glob.glob(os.path.join(output_dir, f"*{ext}"))
            if thumbnail_files:
                # Use the first thumbnail found
                thumbnail_file = thumbnail_files[0]
                # Save relative path for serving (legacy fallback)
                thumbnail_local_path = os.path.relpath(thumbnail_file, DOWNLOADS_DIR)
                logger.info(f"Found thumbnail file: {thumbnail_file}")
                
                # Upload to Supabase Storage for persistent storage
                try:
                    supabase_thumbnail_url = await upload_thumbnail_to_supabase(thumbnail_file, task_id, video_id)
                    if supabase_thumbnail_url:
                        logger.info(f"Uploaded thumbnail to Supabase: {supabase_thumbnail_url}")
                        # Use Supabase URL as primary thumbnail_url
                        thumbnail_url = supabase_thumbnail_url
                    else:
                        logger.warning(f"Failed to upload thumbnail to Supabase, using external URL fallback")
                except Exception as e:
                    logger.error(f"Error uploading thumbnail to Supabase: {str(e)}")
                
                # Create square thumbnail for optimal iMessage/WhatsApp previews
                square_thumbnail_path = os.path.join(output_dir, "thumbnail_square.jpg")
                if create_square_thumbnail(thumbnail_file, square_thumbnail_path):
                    logger.info(f"Created square thumbnail: {square_thumbnail_path}")
                    # Also upload square thumbnail to Supabase
                    try:
                        square_supabase_url = await upload_thumbnail_to_supabase(square_thumbnail_path, task_id, f"{video_id}_square")
                        if square_supabase_url:
                            logger.info(f"Uploaded square thumbnail to Supabase: {square_supabase_url}")
                    except Exception as e:
                        logger.error(f"Error uploading square thumbnail to Supabase: {str(e)}")
                break
        
        # If no thumbnail downloaded, try extracting from video
        if not thumbnail_local_path and not supabase_thumbnail_url:
            try:
                video_files = glob.glob(os.path.join(output_dir, "*.mp4"))
                if video_files and os.path.exists(video_files[0]):
                    import cv2
                    video_path = video_files[0]
                    vidcap = None
                    try:
                        vidcap = cv2.VideoCapture(video_path)
                        success, image = vidcap.read()
                        if success:
                            thumbnail_path = os.path.join(output_dir, "thumbnail.jpg")
                            cv2.imwrite(thumbnail_path, image)
                            thumbnail_local_path = os.path.relpath(thumbnail_path, DOWNLOADS_DIR)
                            logger.info(f"Extracted thumbnail from video: {thumbnail_path}")
                            
                            # Upload extracted thumbnail to Supabase Storage
                            try:
                                supabase_thumbnail_url = await upload_thumbnail_to_supabase(thumbnail_path, task_id, video_id)
                                if supabase_thumbnail_url:
                                    logger.info(f"Uploaded extracted thumbnail to Supabase: {supabase_thumbnail_url}")
                                    # Use Supabase URL as primary thumbnail_url
                                    thumbnail_url = supabase_thumbnail_url
                            except Exception as e:
                                logger.error(f"Error uploading extracted thumbnail to Supabase: {str(e)}")
                            
                            # Create square thumbnail for optimal iMessage/WhatsApp previews
                            square_thumbnail_path = os.path.join(output_dir, "thumbnail_square.jpg")
                            if create_square_thumbnail(thumbnail_path, square_thumbnail_path):
                                logger.info(f"Created square thumbnail from video extraction: {square_thumbnail_path}")
                                # Upload square thumbnail to Supabase
                                try:
                                    square_supabase_url = await upload_thumbnail_to_supabase(square_thumbnail_path, task_id, f"{video_id}_square")
                                    if square_supabase_url:
                                        logger.info(f"Uploaded extracted square thumbnail to Supabase: {square_supabase_url}")
                                except Exception as e:
                                    logger.error(f"Error uploading extracted square thumbnail to Supabase: {str(e)}")
                    finally:
                        if vidcap is not None:
                            vidcap.release()
            except Exception as e:
                logger.warning(f"Failed to extract thumbnail from video: {str(e)}")
        
        # Transcribe the audio
        transcript_response, transcript_file_path = transcriber.transcribe_audio(audio_file, output_dir, video_id)
        
        if transcript_response:
            # Extract tags and guess category
            tags = await extract_tags_from_title(title or '')
            # Read the properly formatted transcript from the saved file
            transcript_text = ""
            if transcript_file_path and os.path.exists(transcript_file_path):
                with open(transcript_file_path, 'r', encoding='utf-8') as f:
                    transcript_text = f.read()
                logger.info(f"Loaded full transcript ({len(transcript_text)} characters) from {transcript_file_path}")
            else:
                # Fallback: extract from TranscriptionVerbose object
                if hasattr(transcript_response, 'text'):
                    transcript_text = transcript_response.text
                elif isinstance(transcript_response, dict):
                    transcript_text = transcript_response.get('text', '')
                else:
                    transcript_text = str(transcript_response)
                logger.warning(f"Used fallback transcript extraction ({len(transcript_text)} characters)")
            category = await guess_category(title or '', transcript_text)
            
            # Generate quote and TLDR (skip if already exists)
            quote_tldr_result = {}
            try:
                existing_qt = supabase.table('transcriptions').select('quote, tldr').eq('task_id', task_id).maybe_single().execute()
                if existing_qt.data and existing_qt.data.get('quote'):
                    logger.info(f"Skipping quote/TLDR generation for task {task_id} — already exists")
                    quote_tldr_result = {
                        "quote": existing_qt.data['quote'],
                        "tldr": json.loads(existing_qt.data['tldr']) if existing_qt.data.get('tldr') else []
                    }
                else:
                    quote_tldr_result = transcriber.generate_quote_and_tldr(
                        transcript_text,
                        title=title or "",
                        description=rich_metadata.get('description') or ""
                    )
            except Exception as e:
                logger.error(f"Failed to generate quote/TLDR for task {task_id}: {str(e)}")
                # Continue without quote/TLDR rather than failing the entire enrichment
            
            # Update Supabase with transcript, tags, category, thumbnail, and rich metadata
            update_data = {
                'status': 'completed',
                'transcript': transcript_text,
                'tags': tags,
                'category': category,
                'error': None,
                'user_phone': user_phone,  # Include user_phone for SMS notification check
                'view_count': 1,  # Initialize view count for new videos
                'visibility': 'public',  # Default visibility
                'platform': platform_hint,  # Default platform for this path
                'language': 'english'  # Default language
            }
            
            # Add quote and TLDR if generated successfully
            if quote_tldr_result.get("quote"):
                update_data["quote"] = quote_tldr_result["quote"]
                logger.info(f"Generated quote: {quote_tldr_result['quote']}")
            
            if quote_tldr_result.get("tldr"):
                update_data["tldr"] = json.dumps(quote_tldr_result["tldr"])  # Store as JSON
                logger.info(f"Generated TLDR: {quote_tldr_result['tldr']}")
            
            # Add thumbnail info if available
            if thumbnail_url:
                update_data['thumbnail_url'] = thumbnail_url
            if thumbnail_local_path:
                update_data['thumbnail_local_path'] = thumbnail_local_path
            if supabase_thumbnail_url:
                update_data['supabase_thumbnail_url'] = supabase_thumbnail_url
                logger.info(f"Storing Supabase thumbnail URL: {supabase_thumbnail_url}")
            # Square thumbnail URL will be added if available
            if square_supabase_url:
                update_data['square_thumbnail_url'] = square_supabase_url
                logger.info(f"Storing square thumbnail URL: {square_supabase_url}")
                
            # Add direct video URL from CDN
            if direct_video_url:
                update_data['video_url'] = direct_video_url
                logger.info(f"Storing direct video URL: {direct_video_url}")
                
            # Add all rich metadata fields
            update_data.update(rich_metadata)
            
            # Add file paths for local assets
            audio_files = glob.glob(os.path.join(output_dir, "*.mp3"))
            if audio_files:
                update_data['audio_file_path'] = os.path.relpath(audio_files[0], DOWNLOADS_DIR)
                
            if metadata_files:
                update_data['info_file_path'] = os.path.relpath(metadata_files[0], DOWNLOADS_DIR)
                
                # Store complete raw metadata for analytics and debugging
                try:
                    with open(metadata_files[0], 'r') as f:
                        raw_metadata_content = json.load(f)
                        update_data['raw_metadata'] = raw_metadata_content
                        
                        # Store the original TikTok URL (from raw_metadata if available)
                        if 'url' in raw_metadata_content:
                            update_data['url'] = raw_metadata_content['url']
                            logger.info(f"Storing original URL: {raw_metadata_content['url']}")
                        
                        logger.info(f"Added raw_metadata with {len(raw_metadata_content)} keys")
                except Exception as e:
                    logger.warning(f"Failed to read raw metadata: {e}")
                
            # Add auto-extracted tags array (combine with existing tags)
            if rich_metadata.get('description'):
                # Extract hashtags from description
                import re
                hashtags = re.findall(r'#(\w+)', rich_metadata['description'])
                if hashtags:
                    all_tags = list(set(tags + hashtags))  # Combine and deduplicate
                    update_data['auto_tags'] = all_tags
                    
            logger.info(f"Updating task {task_id} with {len(update_data)} metadata fields")
            logger.info(f"Update data keys: {list(update_data.keys())}")
                
            # Use Edge Function to bypass PostGREST ON CONFLICT issue
            import requests
            
            def update_transcription_via_edge_function(task_id, update_data):
                """Update transcription using Edge Function to avoid PostGREST bugs"""
                try:
                    supabase_url = os.getenv('SUPABASE_URL')
                    supabase_key = os.getenv('SUPABASE_SERVICE_KEY')
                    
                    # Edge Function endpoint
                    endpoint = f"{supabase_url}/functions/v1/update-transcription"
                    
                    # Prepare headers
                    headers = {
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {supabase_key}"
                    }
                    
                    # Prepare request body
                    body = {
                        "task_id": task_id,
                        "update_data": update_data
                    }
                    
                    # Make the request
                    logger.info(f"Calling Edge Function at {endpoint} for task {task_id}")
                    logger.info(f"Update data keys: {list(update_data.keys())}")
                    response = requests.post(endpoint, headers=headers, json=body, timeout=30)
                    
                    logger.info(f"Edge Function response: {response.status_code}")
                    if response.status_code == 200:
                        result_data = response.json()
                        logger.info(f"Edge Function update successful for task {task_id}: {result_data.get('success', False)}")
                        # Create a mock result object to maintain compatibility
                        class MockResult:
                            def __init__(self, data):
                                self.data = [data.get('data')] if data.get('data') else []
                        return MockResult(result_data)
                    else:
                        error_text = response.text
                        logger.error(f"Edge Function update failed: {response.status_code}")
                        logger.error(f"Edge Function error response: {error_text}")
                        return None
                        
                except Exception as e:
                    logger.error(f"Edge Function request failed: {e}")
                    return None
            
            # Try the Edge Function approach
            result = update_transcription_via_edge_function(task_id, update_data)

            # If Edge Function fails, fall back to direct Supabase client update
            if result is None:
                logger.warning(f"Edge Function update failed for task {task_id}, trying direct Supabase update")
                try:
                    direct_result = await asyncio.to_thread(
                        lambda: supabase.table('transcriptions')
                                .update(update_data)
                                .eq('task_id', task_id)
                                .execute()
                    )
                    if direct_result.data:
                        logger.info(f"Direct Supabase update succeeded for task {task_id}")
                        result = direct_result
                    else:
                        logger.error(f"Direct Supabase update returned no data for task {task_id}")
                        raise Exception("All transcription update methods failed")
                except Exception as fallback_error:
                    logger.error(f"Direct Supabase update also failed for task {task_id}: {fallback_error}")
                    raise Exception(f"All transcription update methods failed: {fallback_error}")
            if result.data:
                logger.info(f"Successfully updated transcription record for task {task_id}")
            else:
                logger.warning(f"Update returned no data for task {task_id}: {result}")
            logger.info(f"Task {task_id} completed with {len(tags)} tags in category: {category}, thumbnail: {thumbnail_local_path or 'none'}")
            
            # Send SMS notification if this was an SMS request
            if update_data.get('user_phone'):
                try:
                    logger.info(f"Sending SMS completion notification to {update_data['user_phone']} for task {task_id}")
                    quote = quote_tldr_result.get("quote", "")
                    tldr_list = quote_tldr_result.get("tldr", [])
                    await send_completion_sms(task_id, update_data['user_phone'], title or 'Video', transcript_text, quote, tldr_list)
                except Exception as sms_error:
                    logger.error(f"Failed to send SMS notification for task {task_id}: {sms_error}")
            else:
                logger.info(f"No SMS notification needed for task {task_id} (no user_phone in update_data: {list(update_data.keys())})")
        else:
            await update_task_status(task_id, "failed", "Transcription failed")
            logger.error(f"Failed to transcribe audio for task {task_id}")
            
        # Clean up temporary files to prevent disk space issues
        try:
            if os.path.exists(output_dir):
                shutil.rmtree(output_dir)
                logger.info(f"Cleaned up temporary files for task {task_id}")
        except Exception as cleanup_error:
            logger.warning(f"Failed to cleanup files for task {task_id}: {str(cleanup_error)}")

    except Exception as e:
        logger.error(f"Error processing task {task_id}: {str(e)}", exc_info=True)
        await update_task_status(task_id, "failed", str(e))
        
        # Clean up temporary files even on error
        try:
            if os.path.exists(output_dir):
                shutil.rmtree(output_dir)
                logger.info(f"Cleaned up temporary files for failed task {task_id}")
        except Exception as cleanup_error:
            logger.warning(f"Failed to cleanup files for failed task {task_id}: {str(cleanup_error)}")

async def send_completion_sms(task_id: str, phone_number: str, title: str, transcript: str, quote: str = "", tldr_list: list = None):
    """Send SMS notification when transcription completes with modern credit/upsell logic."""
    try:
        logger.info(f"send_completion_sms called: task_id={task_id}, phone={phone_number}, quote={bool(quote)}, tldr={bool(tldr_list)}")

        # Idempotency: check if we already sent a completion SMS for this task
        # Only match messages with a real message_sid (actually sent via Twilio),
        # not phantom records created by DB triggers.
        try:
            existing_sms = await asyncio.to_thread(
                lambda: supabase.table('user_messages')
                        .select('id')
                        .eq('to_phone', phone_number)
                        .ilike('message_body', f'%{task_id}%')
                        .not_('message_sid', 'is', 'null')
                        .limit(1)
                        .execute()
            )
            if existing_sms.data:
                logger.info(f"Completion SMS already sent for task {task_id} to {phone_number}, skipping duplicate")
                return
        except Exception as dedup_err:
            logger.debug(f"SMS dedup check failed, proceeding with send: {dedup_err}")

        if not all([os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN')]):
            logger.warning("Twilio credentials not available, skipping SMS notification")
            return
            
        from twilio.rest import Client
        stripe_payment_link = os.getenv(
            "STRIPE_PAYMENT_LINK",
            "https://buy.stripe.com/4gMcN42NS6LFc3Ebl46Vq01",
        )
        
        # Get user's current credits from SMS users table
        normalized_phone = phone_number.replace('+1', '').replace('+', '') if phone_number.startswith('+1') else phone_number.replace('+', '')
        if len(normalized_phone) == 10:
            normalized_phone = f"+1{normalized_phone}"
        elif len(normalized_phone) == 11 and normalized_phone.startswith('1'):
            normalized_phone = f"+{normalized_phone}"
        
        credits_remaining = None
        try:
            response = await asyncio.to_thread(
                lambda: supabase.table('sms_users')
                               .select('credits_remaining')
                               .eq('phone_number', normalized_phone)
                               .single()
                               .execute()
            )
            credits_remaining = response.data.get('credits_remaining', 0) if response.data else 0
        except Exception as e:
            logger.warning(f"Could not fetch credits for {phone_number}: {e}")
        
        # Build transcript preview (first ~100 chars, break at word boundary)
        transcript_preview = ""
        if transcript:
            preview_text = transcript.strip().replace('\n', ' ')
            if len(preview_text) > 100:
                cut = preview_text.rfind(' ', 0, 100)
                if cut < 50:
                    cut = 100
                transcript_preview = preview_text[:cut] + "..."
            else:
                transcript_preview = preview_text

        # Helper: truncate at word boundary
        def _trunc(text, limit):
            if len(text) <= limit:
                return text
            cut = text.rfind(' ', 0, limit)
            if cut < limit // 2:
                cut = limit
            return text[:cut] + "..."

        share_url = f"share.scribetok.com/v/{task_id}"
        credits_str = str(credits_remaining) if credits_remaining is not None else "?"

        if quote and tldr_list:
            short_quote = _trunc(quote, 90)
            # Never truncate individual bullets — show fewer if over limit
            bullets = '\n'.join([f"- {item}" for item in tldr_list[:3]])

            message = f""""{short_quote}"

{transcript_preview}

TLDR:
{bullets}

See full transcript: {share_url}
{credits_str} credits left"""
        else:
            message = f"""{transcript_preview}

See full transcript: {share_url}
{credits_str} credits left"""

        # Add short upsell messages
        if credits_remaining is not None:
            if credits_remaining == 0:
                message += f"\n\n0 credits! 5 for $1.99: {stripe_payment_link}"
            elif credits_remaining == 1:
                message += f"\n\n1 credit left! 5 for $1.99: {stripe_payment_link}"

        # No emojis = GSM encoding (153 chars/concat segment). 600 chars is safe.
        # If over limit, drop bullets one at a time rather than truncating them.
        SMS_SAFE_LIMIT = 600
        if len(message) > SMS_SAFE_LIMIT and quote and tldr_list:
            logger.warning(f"SMS message too long ({len(message)} chars), reducing bullets")
            for max_bullets in (2, 1):
                short_q = _trunc(quote, 70)
                fewer_bullets = '\n'.join([f"- {item}" for item in tldr_list[:max_bullets]])
                message = f""""{short_q}"

{transcript_preview}

TLDR:
{fewer_bullets}

See full transcript: {share_url}
{credits_str} credits left"""
                if len(message) <= SMS_SAFE_LIMIT:
                    break

        if len(message) > SMS_SAFE_LIMIT:
            logger.warning(f"SMS still too long ({len(message)} chars), hard truncating")
            message = message[:SMS_SAFE_LIMIT - 3] + "..."
        
        logger.info(f"Sending SMS ({len(message)} chars) to {phone_number}")
        client = Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))
        
        # Include status callback for delivery tracking
        status_callback_url = f'{os.getenv("SUPABASE_URL")}/functions/v1/sms-status-callback' if os.getenv("SUPABASE_URL") else None
        
        sms = await asyncio.to_thread(
            client.messages.create,
            body=message,
            from_=os.getenv('TWILIO_PHONE_NUMBER', '+17744727423'),
            to=phone_number,
            status_callback=status_callback_url
        )
        
        logger.info(f"Completion SMS sent to {phone_number} for task {task_id}: {sms.sid}")
        
        # Log the outbound message to user_messages table
        try:
            # Normalize phone number function
            def normalize_phone(phone):
                digits = phone.replace('+', '').replace('-', '').replace('(', '').replace(')', '').replace(' ', '')
                if len(digits) == 10:
                    return f"+1{digits}"
                elif len(digits) == 11 and digits.startswith('1'):
                    return f"+{digits}"
                return phone
                
            await asyncio.to_thread(
                lambda: supabase.table('user_messages').insert({
                    'from_phone': os.getenv('TWILIO_PHONE_NUMBER', '+17744727423'),
                    'to_phone': normalize_phone(phone_number),
                    'message_body': message,
                    'direction': 'outbound',
                    'message_sid': sms.sid,
                    'delivery_status': sms.status or 'queued'
                }).execute()
            )
            logger.info(f"Logged completion SMS to user_messages: {sms.sid}")
        except Exception as log_error:
            logger.error(f"Error logging completion SMS to database: {log_error}")
        
    except Exception as e:
        logger.error(f"Failed to send completion SMS for task {task_id}: {str(e)}")

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
            lambda: supabase.table('transcriptions')
                            .update(update_data)
                            .eq('task_id', task_id)
                            .execute()
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

async def init_task(video_url: str, user_id: str = None, user_phone: str = None) -> Dict[str, Any]:
    """Initialize a new task entry in the Supabase database."""
    if supabase is None:
        logger.error("Cannot initialize task: Supabase client not initialized")
        raise ApiError(503, SERVICE_UNAVAILABLE, "Database connection not available")

    try:
        # Skip user_transcriptions table lookup since it might not exist
        # Just create a new task record each time
        task_id = str(uuid.uuid4())
        
        # Create the transcription record with minimal required fields
        task_data = {
            "task_id": task_id,
            "status": "pending",
            "url": video_url,  # Make sure 'url' column exists in your table
            "created_at": datetime.now().isoformat(),
        }
        
        # Add user identification if provided (both optional now)
        if user_id:
            task_data["user_id"] = user_id
        if user_phone:
            task_data["user_phone"] = user_phone
            # Tag SMS-created tasks so operational endpoints (like reprocess) can find them.
            # Also helps analytics and debugging in Supabase.
            task_data["tags"] = ["sms-inbound"]
            task_data["source"] = "sms"
        
        # Log what we're about to insert
        logger.info(f"Creating task with data: {task_data}")
        
        response = await asyncio.to_thread(
            lambda: supabase.table('transcriptions')
                            .insert(task_data)
                            .execute()
        )
        
        # Check for errors
        if hasattr(response, 'error') and response.error:
            logger.error(f"Supabase error creating task: {response.error}")
            raise ApiError(500, INTERNAL_ERROR, "Database error creating task")

        logger.info(f"Created new task {task_id} for URL: {video_url}")
        return {"task_id": task_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error initializing task: {str(e)}", exc_info=True)
        raise ApiError(500, INTERNAL_ERROR, "Database error during task initialization")

# Public endpoints moved to app/api/public.py

@app.post("/api/tasks", status_code=201, tags=["Private Task Management"])
async def submit_task(
    request: TranscriptionRequest, 
    background_tasks: BackgroundTasks, 
    user_id: str = Depends(validate_api_key)
):
    """Submit a new transcription task."""
    if supabase is None:
        logger.error("Cannot submit task: Supabase client not initialized")
        raise ApiError(503, SERVICE_UNAVAILABLE, "Database connection not available")

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
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting task for URL {request.url}: {str(e)}", exc_info=True)
        raise ApiError(500, INTERNAL_ERROR, "Failed to submit task")

@app.post("/api/tasks/{task_id}/retry", tags=["Private Task Management"])
async def retry_task(
    task_id: str,
    background_tasks: BackgroundTasks,
    api_key: str = Depends(verify_api_key)
):
    """Retry a failed transcription task."""
    if supabase is None:
        logger.error("Cannot retry task: Supabase client not initialized")
        raise ApiError(503, SERVICE_UNAVAILABLE, "Database connection not available")

    try:
        # Fetch the existing task
        response = await asyncio.to_thread(
            lambda: supabase.table('transcriptions')
                    .select("task_id, url, status")
                    .eq('task_id', task_id)
                    .single()
                    .execute()
        )

        if not response.data:
            raise ApiError(404, TASK_NOT_FOUND, "Task not found")

        task = response.data
        video_url = task.get('url')

        if not video_url:
            raise ApiError(400, TASK_NOT_RETRYABLE, "Task has no URL to retry")

        # Only allow retry for failed tasks (or optionally pending/stuck tasks)
        if task.get('status') not in ['failed', 'pending']:
            raise ApiError(
                400, TASK_NOT_RETRYABLE,
                f"Cannot retry task with status '{task.get('status')}'. Only failed tasks can be retried."
            )

        # Reset task status to pending and clear error
        await asyncio.to_thread(
            lambda: supabase.table('transcriptions')
                    .update({
                        "status": "pending",
                        "error": None,
                        "updated_at": datetime.now().isoformat()
                    })
                    .eq('task_id', task_id)
                    .execute()
        )

        logger.info(f"Retrying task {task_id} for URL: {video_url}")

        # Queue the task for reprocessing
        background_tasks.add_task(
            process_transcription_task,
            task_id,
            video_url,
            None,  # callback_url
            None   # proxy
        )

        return {
            "task_id": task_id,
            "status": "pending",
            "message": "Task queued for retry"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrying task {task_id}: {str(e)}", exc_info=True)
        raise ApiError(500, INTERNAL_ERROR, "Failed to retry task")

@app.post("/api/cleanup-stuck-tasks", tags=["System & Health"])
async def cleanup_stuck_tasks(api_key: str = Depends(verify_api_key)):
    """Mark long-pending tasks as failed (requires API key)"""
    return await _cleanup_stuck_tasks_logic()

@app.post("/api/reprocess-sms-jobs", tags=["System & Health"])
async def reprocess_sms_jobs(background_tasks: BackgroundTasks, api_key: str = Depends(verify_api_key)):
    """Reprocess stuck SMS transcription jobs (requires API key)"""
    return await _reprocess_sms_jobs_logic(background_tasks)

async def _reprocess_sms_jobs_logic(background_tasks: BackgroundTasks):
    """Find and reprocess stuck SMS jobs"""
    if supabase is None:
        logger.error("Cannot reprocess SMS jobs: Supabase client not initialized")
        raise ApiError(503, SERVICE_UNAVAILABLE, "Database connection not available")

    try:
        # Find pending SMS jobs
        response = await asyncio.to_thread(
            supabase.table('transcriptions')
            .select("task_id, url, tags")
            .eq('status', 'pending')
            .limit(500)
            .execute()
        )
        
        reprocessed_count = 0
        if response.data:
            for task in response.data:
                # Check if it's an SMS job
                tags = task.get('tags', [])
                if isinstance(tags, list) and 'sms-inbound' in tags:
                    task_id = task['task_id']
                    video_url = task['url']
                    
                    # Queue for reprocessing
                    background_tasks.add_task(
                        process_transcription_task,
                        task_id,
                        video_url,
                        None,  # callback_url
                        None   # proxy
                    )
                    reprocessed_count += 1
                    logger.info(f"Requeued SMS job {task_id} for processing")
        
        return {
            "status": "success", 
            "message": f"Requeued {reprocessed_count} SMS jobs for processing",
            "reprocessed_count": reprocessed_count
        }
        
    except Exception as e:
        logger.error(f"Error reprocessing SMS jobs: {str(e)}", exc_info=True)
        raise ApiError(500, INTERNAL_ERROR, "Failed to reprocess SMS jobs")

async def _cleanup_stuck_tasks_logic():
    """Shared cleanup logic"""
    if supabase is None:
        logger.error("Cannot cleanup stuck tasks: Supabase client not initialized")
        raise ApiError(503, SERVICE_UNAVAILABLE, "Database connection not available")

    try:
        # Find tasks pending for more than 30 minutes
        cutoff_time = (datetime.now() - timedelta(minutes=30)).isoformat()

        response = await asyncio.to_thread(
            supabase.table('transcriptions')
            .select("task_id")
            .eq('status', 'pending')
            .lt('created_at', cutoff_time)
            .limit(500)
            .execute()
        )
        
        cleaned_count = 0
        if response.data:
            for task in response.data:
                await update_task_status(task['task_id'], "failed", "Task stuck in pending state - auto-cleaned")
                cleaned_count += 1
                logger.warning(f"Marked stuck task as failed: {task['task_id']}")
        
        return {
            "cleaned_tasks": cleaned_count,
            "cutoff_time": cutoff_time,
            "message": f"Cleaned {cleaned_count} stuck tasks"
        }
        
    except Exception as e:
        logger.error(f"Error cleaning stuck tasks: {str(e)}", exc_info=True)
        raise ApiError(500, INTERNAL_ERROR, "Failed to cleanup stuck tasks")

# ===============================
# ACCOUNT LINKING & SMS ENDPOINTS MOVED TO app/api/sms.py

async def process_transcription_with_sms_notification(task_id: str, video_url: str, phone_number: str, job_id: str = None):
    """Process transcription and send SMS notification when complete"""
    try:
        # Update job status to processing
        if job_id:
            await asyncio.to_thread(
                supabase.table('transcript_jobs')
                        .update({'status': 'processing'})
                        .eq('id', job_id)
                        .execute()
            )
        
        # Run the normal transcription process
        await process_transcription_task(task_id, video_url, callback_url=None, proxy=None)
        
        # Get the completed task details
        response = await asyncio.to_thread(
            supabase.table('transcriptions')
                    .select("task_id, status, title, transcript, error")
                    .eq('task_id', task_id)
                    .single()
                    .execute()
        )
        
        if response.data:
            task_data = response.data
            
            if task_data['status'] == 'completed':
                # Update job status to completed
                if job_id:
                    public_link = f"{os.getenv('BASE_URL', 'https://share.scribetok.com')}/v/{task_id}"
                    await asyncio.to_thread(
                        supabase.table('transcript_jobs')
                                .update({
                                    'status': 'completed',
                                    'public_link': public_link
                                })
                                .eq('id', job_id)
                                .execute()
                    )
                
                # Idempotency: check if completion SMS was already sent for this task
                # Only match messages with a real message_sid (actually sent via Twilio).
                already_sent = False
                try:
                    existing_sms = await asyncio.to_thread(
                        lambda: supabase.table('user_messages')
                                .select('id')
                                .eq('to_phone', phone_number)
                                .ilike('message_body', f'%{task_id}%')
                                .not_('message_sid', 'is', 'null')
                                .limit(1)
                                .execute()
                    )
                    if existing_sms.data:
                        logger.info(f"Completion SMS already sent for task {task_id}, skipping duplicate")
                        already_sent = True
                except Exception as dedup_err:
                    logger.debug(f"SMS dedup check failed, proceeding with send: {dedup_err}")

                if not already_sent:
                    # Send success notification with enhanced message
                    title = task_data.get('title', 'Video')
                    transcript = task_data.get('transcript', '')

                    # Get first few lines for preview
                    preview_lines = []
                    if transcript:
                        lines = transcript.split('\n')
                        for line in lines:
                            if line.strip() and not line.strip().startswith('0'):  # Skip timestamps
                                preview_lines.append(line.strip())
                                if len(preview_lines) >= 2:
                                    break

                    preview = '\n'.join(preview_lines)[:150] + '...' if preview_lines else 'Transcript ready!'

                    # Enhanced SMS with public link
                    public_link = f"{os.getenv('BASE_URL', 'https://share.scribetok.com')}/v/{task_id}"

                    success_message = f"✅ Transcript ready!\n\n📄 {title}\n\n{preview}\n\n🔗 View full: {public_link}\n\nReply:\n1 - Key takeaways\n2 - Best quote\n3 - Draft a reply\nOr just ask a question!"

                    await sms.SMSHandler.send_sms(
                        to=phone_number,
                        body=success_message,
                        status_callback=f"{os.getenv('BASE_URL', '')}/api/sms/status"
                    )
                
            elif task_data['status'] == 'failed':
                # Update job status to failed
                if job_id:
                    await asyncio.to_thread(
                        supabase.table('transcript_jobs')
                                .update({
                                    'status': 'failed',
                                    'error': task_data.get('error', 'Unknown error')
                                })
                                .eq('id', job_id)
                                .execute()
                    )
                
                # Send failure notification
                error = task_data.get('error', 'Unknown error')
                await sms.SMSHandler.send_sms(
                    to=phone_number,
                    body=f"❌ Sorry, we couldn't transcribe your video.\n\nError: {error}\n\nPlease try a different link or text /help for support."
                )
        
    except Exception as e:
        logger.error(f"Error in SMS transcription process: {str(e)}", exc_info=True)
        
        # Update job status to failed
        if job_id:
            try:
                await asyncio.to_thread(
                    supabase.table('transcript_jobs')
                            .update({
                                'status': 'failed',
                                'error': str(e)
                            })
                            .eq('id', job_id)
                            .execute()
                )
            except:
                pass
        
        # Send error notification
        try:
            await sms.SMSHandler.send_sms(
                to=phone_number,
                body="❌ Something went wrong with your transcription. Please try again or text /help for support."
            )
        except:
            pass  # Don't let notification errors crash the process

@app.get("/v/{task_id}")
async def public_transcript_page(task_id: str, request: Request, ref: Optional[str] = Query(None, description="Referrer tracking")):
    """Serve HTML page with Open Graph meta tags for viral social media sharing."""
    return await rich_link_preview(task_id, request)

async def _track_referral(ref_code: str, task_id: str, visitor_ip: str) -> bool:
    """Track a referral and award credits"""
    try:
        if not supabase:
            return False
        
        # Log the referral event
        await asyncio.to_thread(
            supabase.table('referral_events').insert({
                'ref_code': ref_code,
                'task_id': task_id,
                'visitor_ip': visitor_ip,
                'event_type': 'view',
                'created_at': datetime.now(timezone.utc).isoformat()
            }).execute()
        )
        
        # Award credit to referrer (simplified - could be more complex)
        return True
        
    except Exception as e:
        logger.error(f"Referral tracking error: {str(e)}")
        return False

async def _get_viral_metrics(task_id: str) -> Tuple[int, int]:
    """Get view count and trending score for a transcript"""
    try:
        if not supabase:
            return 1, 999
        
        # Get view count from referral events
        response = await asyncio.to_thread(
            supabase.table('referral_events')
                    .select('id')
                    .eq('task_id', task_id)
                    .execute()
        )
        
        view_count = len(response.data) if response.data else 1
        
        # Simple trending score (lower = more trending)
        # Based on views in last 24 hours
        recent_response = await asyncio.to_thread(
            supabase.table('referral_events')
                    .select('id')
                    .eq('task_id', task_id)
                    .gte('created_at', (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat())
                    .execute()
        )
        
        recent_views = len(recent_response.data) if recent_response.data else 0
        trending_score = max(1, 1000 - (recent_views * 10))  # More recent views = lower trending score
        
        return view_count, trending_score
        
    except Exception as e:
        logger.error(f"Viral metrics error: {str(e)}")
        return 1, 999

def _extract_seo_keywords(transcript: str, title: str) -> str:
    """Extract keywords from transcript and title for SEO"""
    import re
    from collections import Counter
    
    # Combine title and transcript for keyword extraction
    text = f"{title} {transcript}"
    
    # Remove common words and extract meaningful keywords
    stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'is', 'are', 'was', 'were', 'been', 'be', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'this', 'that', 'these', 'those', 'i', 'me', 'my', 'myself', 'we', 'our', 'ours', 'ourselves', 'you', 'your', 'yours', 'yourself', 'yourselves', 'he', 'him', 'his', 'himself', 'she', 'her', 'hers', 'herself', 'it', 'its', 'itself', 'they', 'them', 'their', 'theirs', 'themselves'}
    
    # Extract words (3+ characters, alphanumeric)
    words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
    meaningful_words = [word for word in words if word not in stop_words]
    
    # Get most common keywords
    keyword_counts = Counter(meaningful_words)
    top_keywords = [word for word, count in keyword_counts.most_common(15)]
    
    # Add some standard keywords
    standard_keywords = ['transcript', 'video', 'tiktok', 'youtube', 'scribetok', 'ai', 'text', 'content']
    all_keywords = list(set(top_keywords + standard_keywords))
    
    return ', '.join(all_keywords[:20])  # Limit to 20 keywords

def _generate_referral_code(task_id: str) -> str:
    """Generate a unique referral code"""
    import hashlib
    import time
    
    # Create a unique code based on task_id and timestamp
    unique_string = f"{task_id}-{int(time.time())}-{uuid.uuid4().hex[:8]}"
    return hashlib.md5(unique_string.encode()).hexdigest()[:12]

async def _render_coming_soon_page():
    """Render coming soon page for non-existent transcripts"""
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Transcript Not Found - ScribeTok</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
                   text-align: center; padding: 50px 20px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                   min-height: 100vh; margin: 0; display: flex; align-items: center; justify-content: center; }
            .container { background: white; padding: 40px; border-radius: 12px; max-width: 500px; box-shadow: 0 10px 30px rgba(0,0,0,0.1); }
            h1 { color: #333; margin-bottom: 20px; }
            p { color: #666; margin-bottom: 30px; font-size: 18px; }
            .btn { display: inline-block; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                   color: white; padding: 15px 30px; text-decoration: none; border-radius: 8px; font-weight: 600; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🔍 Transcript Not Found</h1>
            <p>This transcript doesn't exist yet, but you can create one!</p>
            <a href="sms:+17744727423&body=Hi ScribeTok!" class="btn">📱 Text +1 (774) 472-7423 to get started</a>
        </div>
    </body>
    </html>
    """
    return Response(content=html_content, media_type="text/html")

async def _render_processing_page(title: str):
    """Render processing page for incomplete transcripts"""
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Processing... - ScribeTok</title>
        <meta http-equiv="refresh" content="30">
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
                   text-align: center; padding: 50px 20px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                   min-height: 100vh; margin: 0; display: flex; align-items: center; justify-content: center; }}
            .container {{ background: white; padding: 40px; border-radius: 12px; max-width: 500px; box-shadow: 0 10px 30px rgba(0,0,0,0.1); }}
            .spinner {{ width: 50px; height: 50px; border: 4px solid #f3f3f3; border-top: 4px solid #667eea; 
                       border-radius: 50%; animation: spin 1s linear infinite; margin: 20px auto; }}
            @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
            h1 {{ color: #333; margin-bottom: 20px; }}
            p {{ color: #666; margin-bottom: 30px; font-size: 18px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="spinner"></div>
            <h1>🎥 Processing "{title}"</h1>
            <p>Your transcript is being generated. This page will refresh automatically when it's ready!</p>
            <p style="font-size: 14px; color: #999;">Usually takes 30-60 seconds</p>
        </div>
    </body>
    </html>
    """
    return Response(content=html_content, media_type="text/html")

#

# TikTok API Adapter Endpoints
@app.get("/api/public/tiktok/video-info", tags=["TikTok API"])
async def get_tiktok_video_info(video_url: str = Query(..., description="TikTok video URL")):
    """
    Get TikTok video information using multiple API adapters with automatic failover.
    
    This endpoint demonstrates the API adapter pattern for handling rate limits
    and API failures by automatically switching between different TikTok APIs.
    """
    if not video_url:
        raise ApiError(400, VALIDATION_ERROR, "video_url parameter is required")
    
    try:
        result = tiktok_service.get_video_info(video_url)
        
        if result["success"]:
            return {
                "success": True,
                "data": result["data"],
                "rate_limit_info": result.get("rate_limit_info")
            }
        else:
            # Return error but don't raise exception to show adapter status
            return {
                "success": False,
                "error": result["error"],
                "status_code": result.get("status_code"),
                "adapters_status": tiktok_service.get_adapters_status()
            }
            
    except Exception as e:
        logger.error(f"Error in get_tiktok_video_info: {str(e)}")
        raise ApiError(500, INTERNAL_ERROR, "Failed to get video info")

@app.get("/api/public/tiktok/adapters-status", tags=["TikTok API"])
async def get_tiktok_adapters_status():
    """
    Get the status of all configured TikTok API adapters including rate limits.
    
    Useful for monitoring which APIs are available and their rate limit status.
    """
    try:
        status = tiktok_service.get_adapters_status()
        return status
    except Exception as e:
        logger.error(f"Error getting adapters status: {str(e)}")
        raise ApiError(500, INTERNAL_ERROR, "Failed to get adapters status")

@app.post("/api/tiktok/refresh-adapters", dependencies=[Depends(verify_api_key)], tags=["TikTok API"])
async def refresh_tiktok_adapters():
    """
    Refresh the TikTok API adapters configuration (requires API key).
    
    Useful when environment variables have been updated and you want to
    reinitialize the adapters without restarting the service.
    """
    try:
        tiktok_service.refresh_manager()
        return {
            "success": True,
            "message": "TikTok adapters refreshed",
            "status": tiktok_service.get_adapters_status()
        }
    except Exception as e:
        logger.error(f"Error refreshing adapters: {str(e)}")
        raise ApiError(500, INTERNAL_ERROR, "Failed to refresh adapters")

@app.post("/api/payments/create-checkout-session", tags=["Payment & Billing"])
async def create_checkout_session(
    price_id: str = Query(..., description="Stripe Price ID for the credit package"),
    request: Request = None
):
    """Create a Stripe Checkout session for credit purchases"""
    try:
        import stripe
        import json
        
        # Initialize Stripe
        stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
        if not stripe.api_key:
            raise ApiError(503, SERVICE_UNAVAILABLE, "Stripe not configured")
        
        # Get verified user ID from Supabase auth token
        auth_header = request.headers.get("authorization") if request else None
        user_id = None

        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.replace("Bearer ", "")
            try:
                user_response = supabase.auth.get_user(token)
                if user_response and user_response.user:
                    user_id = user_response.user.id
            except Exception:
                logger.warning("Failed to verify auth token for checkout, proceeding as anonymous")
                pass
        
        # Get frontend URL for redirects
        frontend_url = os.getenv("FRONTEND_URL", "https://scribetok.com")
        
        # Map price IDs to credit amounts (UPDATE THESE WITH YOUR ACTUAL STRIPE PRICE IDs)
        CREDIT_PACKAGES = {
            "price_123": {"credits": 10, "name": "Starter Pack"},
            "price_456": {"credits": 50, "name": "Pro Pack"},
            "price_789": {"credits": 200, "name": "Business Pack"}
        }
        
        package_info = CREDIT_PACKAGES.get(price_id)
        if not package_info:
            raise ApiError(400, VALIDATION_ERROR, "Invalid price ID")
        
        # Create metadata for webhook
        metadata = {
            'credits': str(package_info['credits']),
            'package_name': package_info['name'],
        }
        
        # Add user_id to metadata if available
        if user_id:
            metadata['user_id'] = user_id
        
        # Create checkout session
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price': price_id,
                'quantity': 1,
            }],
            mode='payment',
            success_url=f'{frontend_url}/app/settings?success=true&session_id={{CHECKOUT_SESSION_ID}}',
            cancel_url=f'{frontend_url}/app/settings?canceled=true',
            metadata=metadata,
            client_reference_id=user_id if user_id else "anonymous"
        )
        
        return {"sessionId": checkout_session.id, "url": checkout_session.url}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating checkout session: {str(e)}")
        raise ApiError(500, INTERNAL_ERROR, "Failed to create checkout session")

@app.get("/api/users/credits", tags=["Payment & Billing"])
async def get_user_credits(
    request: Request,
    api_key: Optional[str] = Header(None, alias="X-API-Key")
):
    """Get the current user's credit balance"""
    try:
        # Get verified user email from Supabase auth token
        user_email = None
        auth_header = request.headers.get("authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.replace("Bearer ", "")
            try:
                user_response = supabase.auth.get_user(token)
                if user_response and user_response.user:
                    user_email = user_response.user.email
            except Exception:
                logger.warning("Failed to verify auth token for credits lookup")
                pass

        if not user_email:
            # Try alternative: get email from user object directly
            # Return 0 for unauthenticated users
            return {"credits": 0}
        
        # Get user credits from sms_users table (using email)
        result = supabase.table("sms_users").select("credits_remaining").eq("email", user_email).execute()
        
        if result.data and len(result.data) > 0:
            credits = result.data[0].get("credits_remaining", 0)
            return {"credits": credits}
        else:
            # User doesn't exist, return 0 credits
            return {"credits": 0}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user credits: {str(e)}")
        raise ApiError(500, INTERNAL_ERROR, "Failed to get user credits")

@app.post("/api/webhook/stripe", tags=["Payment & Billing"])
async def handle_stripe_webhook(request: Request):
    """Handle Stripe webhooks for credit purchases"""
    try:
        from stripe_webhook import handle_stripe_webhook
        result = await handle_stripe_webhook(request)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error handling Stripe webhook: {str(e)}")
        raise ApiError(500, INTERNAL_ERROR, "Webhook processing failed")

@app.get("/pay", tags=["Payment & Billing"])
async def pay_redirect(p: str = Query(..., description="Base64url-encoded phone number"), c: int = Query(5, description="Credits")):
    """
    Short URL redirect to Stripe checkout.
    Creates a checkout session on click and redirects to Stripe.
    Phone number is base64url-encoded to avoid exposing it in plaintext.
    URL format: /pay?p=KzE2MTAzMjQ0MjUw&c=5
    """
    import stripe
    import base64
    stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

    if not stripe.api_key:
        raise ApiError(503, SERVICE_UNAVAILABLE, "Payment system not configured")

    # Decode phone number
    try:
        phone = base64.urlsafe_b64decode(p).decode('utf-8')
    except Exception:
        raise ApiError(400, VALIDATION_ERROR, "Invalid phone parameter")

    # Map credits to price IDs
    price_map = {
        5: os.getenv("STRIPE_5_CREDITS_PRICE_ID"),
        10: os.getenv("STRIPE_SMS_CREDITS_PRICE_ID"),
    }

    price_id = price_map.get(c)
    if not price_id:
        raise ApiError(400, VALIDATION_ERROR, "Invalid credit amount")

    try:
        frontend_url = os.getenv("FRONTEND_URL", "https://scribetok.com")
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{'price': price_id, 'quantity': 1}],
            mode='payment',
            success_url=f"{frontend_url}/sms-payment-success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{frontend_url}/sms-payment-canceled",
            metadata={
                'phone_number': phone,
                'credits': str(c),
                'source': 'sms_short_url'
            }
        )
        return RedirectResponse(url=session.url, status_code=303)
    except Exception as e:
        logger.error(f"Error creating checkout session: {str(e)}")
        raise ApiError(500, INTERNAL_ERROR, "Failed to create payment session")

@app.post("/api/webhook/supabase", tags=["System & Health"])
async def handle_supabase_webhook(
    request: Request,
    background_tasks: BackgroundTasks
):
    """Handle webhook from Supabase Edge Function to start transcription"""
    try:
        body = await request.json()
        job_id = body.get('job_id')
        from_phone = body.get('from_phone')
        video_url = body.get('video_url')
        action = body.get('task_action')
        
        logger.info(f"Received Supabase webhook: {action} for job {job_id}")
        
        if action == 'start_transcription' and job_id and from_phone and video_url:
            # Create transcription task
            task = await init_task(video_url, user_id=None, user_phone=from_phone)
            task_id = task['task_id']
            
            # Update the transcript job with the transcription task ID
            await asyncio.to_thread(
                lambda: supabase.table('transcript_jobs')
                               .update({'transcript_id': task_id})
                               .eq('id', job_id)
                               .execute()
            )
            
            # Store user phone number for notifications
            await asyncio.to_thread(
                lambda: supabase.table('transcriptions')
                               .update({'user_phone': from_phone})
                               .eq('task_id', task_id)
                               .execute()
            )
            
            # Queue background processing
            background_tasks.add_task(
                process_transcription_with_sms_notification,
                task_id,
                video_url,
                from_phone,
                job_id
            )
            
            logger.info(f"Started transcription {task_id} for Supabase job {job_id}")
            
            return {"status": "success", "task_id": task_id, "job_id": job_id}
        
        return {"status": "ignored", "reason": "Invalid action or missing data"}
        
    except Exception as e:
        logger.error(f"Error handling Supabase webhook: {str(e)}", exc_info=True)
        return {"status": "error", "message": str(e)}

# Duplicate route commented out - called by public_transcript_page above
async def rich_link_preview(task_id: str, request: Request):
    """
    Serve HTML page with Open Graph meta tags for viral social media sharing.
    
    When users share scribetok.com/v/{task_id} links, this creates rich cards with:
    - Video thumbnail as the preview image
    - Title, creator, and engagement stats
    - Direct link to read the full transcript
    """
    try:
        # Fetch task data from the public view (no phone numbers exposed)
        response = await asyncio.to_thread(
            lambda: supabase.table('public_transcriptions')
                           .select("*")
                           .eq('task_id', task_id)
                           .maybe_single()
                           .execute()
        )
        
        if not response.data:
            raise ApiError(404, TASK_NOT_FOUND, "Transcript not found")

        task = response.data

        # Parse JSONB fields from database
        if task.get('tldr'):
            try:
                # Parse tldr if it's a JSON string from database
                if isinstance(task['tldr'], str):
                    task['tldr'] = json.loads(task['tldr'])
                elif not isinstance(task['tldr'], list):
                    task['tldr'] = []
            except (json.JSONDecodeError, TypeError):
                logger.warning(f"Failed to parse tldr for task {task_id}: {task.get('tldr')}")
                task['tldr'] = []
        else:
            task['tldr'] = []
        
        # Generate dynamic meta tags based on the video data
        def format_number(num):
            """Format large numbers for display (e.g., 4744375 -> 4.7M)"""
            if not num or num == 0:
                return "0"
            if num >= 1000000:
                return f"{num/1000000:.1f}M"
            if num >= 1000:
                return f"{num/1000:.1f}K"
            return str(num)
        
        # Build the title - prioritize quote/TLDR format
        title = task.get('title') or 'TikTok Transcript'
        if len(title) > 60:
            title = title[:57] + "..."
        
        # Enhanced title for quote/TLDR content
        if task.get('quote'):
            # Use quote as the main title for maximum shareability
            og_title = f"\"{task['quote']}\" - ScribeTok"
        else:
            og_title = f"TikTok Transcript: '{title}'"
        
        # Build the description prioritizing quote and TLDR over transcript
        description_parts = []
        
        # Strategy: If we have a quote in the title, use TLDR + context in description
        if task.get('quote') and task.get('tldr') and isinstance(task['tldr'], list) and task['tldr']:
            # Quote is in title, so focus on TLDR + context
            tldr_text = " • ".join(task['tldr'][:2])  # Show first 2 TLDR points
            description_parts.append(f"Key insights: {tldr_text}")
            
            # Add creator and video context
            context_parts = []
            if task.get('uploader'):
                context_parts.append(f"by @{task['uploader']}")
            if task.get('duration'):
                context_parts.append(f"{task['duration']}s video")
            if task.get('like_count'):
                context_parts.append(f"{format_number(task['like_count'])} likes")
            
            if context_parts:
                description_parts.append(" • ".join(context_parts))
                
        else:
            # Fallback to original format when no quote/TLDR available
            # Priority 1: Use quote if available
            if task.get('quote'):
                description_parts.append(f"💡 \"{task['quote']}\"")
            
            # Priority 2: Add TLDR summary if available
            if task.get('tldr') and isinstance(task['tldr'], list) and task['tldr']:
                tldr_text = " • ".join(task['tldr'][:2])  # Show first 2 TLDR points
                description_parts.append(f"📝 {tldr_text}")
            
            # Add engagement stats if available
            if task.get('like_count') or task.get('comment_count'):
                likes = format_number(task.get('like_count', 0))
                comments = format_number(task.get('comment_count', 0))
                description_parts.append(f"{likes} likes, {comments} comments")
            
            # Add creator info
            if task.get('uploader'):
                description_parts.append(f"by {task['uploader']}")
        
        # Join all parts
        og_description = " • ".join(description_parts) if description_parts else "ScribeTok transcript"
        
        # Ensure LinkedIn length requirements (≥100 chars) - fallback to transcript preview
        if len(og_description) < 100 and task.get('transcript'):
            preview_snippet = task['transcript'][:120]
            if len(task['transcript']) > 120:
                preview_snippet += "..."
            og_description = f"{og_description} — \"{preview_snippet}\""
        
        # Final fallback padding
        if len(og_description) < 100:
            og_description += " — Get Quote + TLDR summaries and full transcripts on ScribeTok."
        
        # Use the thumbnail URL or fallback to ScribeTok branded image
        og_image = task.get('thumbnail_url', 'https://uploadthingy.s3.us-west-1.amazonaws.com/wLTDGGWCxxxDWormAJufuo/ScribeTok-bg.png')
        
        # For optimal iMessage/WhatsApp support, also generate square image URL
        og_image_square = f"https://share.scribetok.com/api/public/thumbnail_square/{task_id}"
        
        # Get the full URL for this page
        og_url = f"https://share.scribetok.com/v/{task_id}"
        
        # Get a preview of the transcript (first 150 chars)
        transcript_preview = ""
        if task.get('transcript'):
            transcript_preview = task['transcript'][:150]
            if len(task['transcript']) > 150:
                transcript_preview += "..."
        
        # Get the transcript segments for display
        transcript_segments = []
        if transcript_preview and task.get('transcript'):
            # Parse transcript into segments (simplified)
            full_transcript = task['transcript']
            segments = full_transcript.split('. ')
            for i, segment in enumerate(segments[:8]):  # Show first 8 segments
                if segment.strip():
                    start_time = i * 15  # 15 seconds per segment
                    end_time = start_time + 15
                    transcript_segments.append({
                        'start': f"{start_time//60}:{start_time%60:02d}",
                        'end': f"{end_time//60}:{end_time%60:02d}",
                        'text': segment.strip() + ('.' if not segment.endswith('.') else '')
                    })
        
        # Helper functions for formatting
        def format_duration(seconds):
            if not seconds:
                return "Unknown"
            mins = int(seconds // 60)
            secs = int(seconds % 60)
            if mins < 1:
                return f"{secs}s"
            return f"{mins}m {secs}s"
        
        def format_date(date_str):
            if not date_str:
                return "Unknown"
            # Handle YYYYMMDD format
            if isinstance(date_str, str) and len(date_str) == 8 and date_str.isdigit():
                year = date_str[:4]
                month = date_str[4:6]
                day = date_str[6:8]
                from datetime import datetime
                try:
                    return datetime(int(year), int(month), int(day)).strftime("%m/%d/%Y")
                except:
                    return date_str
            # Handle regular date strings
            try:
                from datetime import datetime
                if isinstance(date_str, str):
                    dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                else:
                    dt = date_str
                return dt.strftime("%m/%d/%Y")
            except:
                return str(date_str) if date_str else "Unknown"
        
        # Get video URL for "View Original Video" button
        video_url = task.get('video_url') or task.get('url')
        if not video_url and task.get('video_id'):
            # Construct URL if we have video ID
            if task.get('platform') == 'tiktok':
                if task.get('uploader'):
                    video_url = f"https://www.tiktok.com/@{task['uploader']}/video/{task['video_id']}"
                else:
                    video_url = f"https://www.tiktok.com/video/{task['video_id']}"
            elif task.get('platform') == 'youtube':
                video_url = f"https://www.youtube.com/watch?v={task['video_id']}"
        
        # Prepare template context data
        template_data = {
            "task_id": task_id,
            "task": task,
            "title": title,
            "og_title": og_title,
            "og_description": og_description,
            "og_image": og_image,
            "og_image_square": og_image_square,
            "og_url": og_url,
            "video_url": video_url,
            "transcript_preview": transcript_preview,
            "transcript_segments": transcript_segments,
            "transcript_text": task.get('transcript', ''),
            "quote": task.get('quote'),
            "tldr": task.get('tldr', []),
            "duration": format_duration(task.get('duration')),
            "upload_date": format_date(task.get('upload_date')),
            "like_count": format_number(task.get('like_count', 0)),
            "comment_count": format_number(task.get('comment_count', 0)),
            "repost_count": format_number(task.get('repost_count', 0)),
        }
        
        # Use template rendering instead of inline HTML
        return templates.TemplateResponse("transcript.html", {"request": request, **template_data})
        
    except Exception as e:
        logger.error(f"Error generating rich link preview for {task_id}: {str(e)}", exc_info=True)
        
        # Fallback HTML for errors
        fallback_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta property="og:title" content="ScribeTok - TikTok Transcripts">
    <meta property="og:description" content="Read TikTok video transcripts without sound">
    <meta property="og:site_name" content="ScribeTok">
    <title>ScribeTok - Transcript Not Found</title>
    <script>
        setTimeout(function() {{
            window.location.href = 'https://www.scribetok.com';
        }}, 100);
    </script>
</head>
<body>
    <h1>Transcript not found</h1>
    <p>Redirecting to ScribeTok...</p>
</body>
</html>"""
        return Response(content=fallback_html, media_type="text/html")

# ====================================================================================
# COMMENT EXTRACTION API (PRO FEATURE)
# ====================================================================================

@app.post("/api/pro/comments/fetch", tags=["Pro Features - Comments"])
async def fetch_video_comments(
    payload: FetchCommentsRequest,
    api_key: str = Depends(verify_api_key),
    x_session_token: Optional[str] = Header(None),
):
    """
    Fetch and store comments for a transcribed video (Pro Feature).
    
    Args:
        task_id: Transcription task ID
        count: Number of comments per page (ignored if get_all=True)
        include_replies: Whether to include comment replies
        get_all: If True, fetch ALL comments with pagination (default behavior)
        api_key: Valid API key
    
    Cost: 1 credit per 100 comments (dynamic pricing)
    """
    try:
        # Check if transcription exists
        response = await asyncio.to_thread(
            lambda: supabase.table('transcriptions')
                    .select('task_id, video_id, user_phone, comments_fetched, comment_count')
                    .eq('task_id', payload.task_id)
                    .limit(1)
                    .execute()
        )
        
        if not response.data:
            raise ApiError(404, TASK_NOT_FOUND, "Transcription not found")

        # Handle response.data being a list or dict
        task = response.data[0] if isinstance(response.data, list) else response.data
        video_id = task.get('video_id')
        user_phone = task.get('user_phone')
        already_fetched = task.get('comments_fetched', False)

        # If session token provided, validate it and use session phone for credits
        if x_session_token:
            from .api.auth import verify_session_token as _verify_session
            session = await _verify_session(x_session_token)
            user_phone = session["phone_number"]

        if not video_id:
            raise ApiError(
                400, VALIDATION_ERROR,
                "Video ID not available for this transcription"
            )
        
        # Check if comments already fetched
        if already_fetched and not payload.get_all:
            return {
                "success": True,
                "task_id": payload.task_id,
                "message": "Comments already fetched for this video",
                "comments_fetched": 0,
                "credits_charged": 0,
                "already_fetched": True
            }
        
        # Get preview to estimate credits needed
        from adapters.comments_adapter import TikTokCommentsAdapter
        
        rapidapi_key = os.getenv('RAPIDAPI_KEY')
        if not rapidapi_key:
            raise ApiError(
                503, SERVICE_UNAVAILABLE,
                "Comment extraction not configured"
            )
        
        adapter = TikTokCommentsAdapter([rapidapi_key])
        
        # Get preview for credit estimation
        logger.info(f"Getting preview for credit estimation (task {payload.task_id})")
        preview_result = adapter.fetch_comments(video_id, count=20, get_all=False)
        
        if preview_result.get('error'):
            raise ApiError(
                503, SERVICE_UNAVAILABLE,
                f"Failed to fetch preview: {preview_result['error']}"
            )
        
        preview_comments = preview_result.get('comments', [])
        has_more = preview_result.get('has_more', False)
        
        # Estimate total comments and credits needed
        import math
        if payload.get_all:
            # Estimate using both preview and stored metadata, pick the larger
            est_preview = (len(preview_comments) * 10) if has_more else len(preview_comments)
            try:
                est_meta = int(task.get('comment_count') or 0)
            except Exception:
                est_meta = 0
            estimated_total = max(est_preview, est_meta) if max(est_preview, est_meta) > 0 else est_preview
        else:
            estimated_total = payload.count
        
        credits_needed = math.ceil(estimated_total / 100)
        
        # Check user credits if phone number provided
        if user_phone:
            credits_check = await asyncio.to_thread(
                lambda: supabase.table('sms_users')
                        .select('credits_remaining')
                        .eq('phone_number', user_phone)
                        .limit(1)
                        .execute()
            )
            
            if credits_check.data:
                # Handle both list and dict response formats
                if isinstance(credits_check.data, list):
                    credits = credits_check.data[0].get('credits_remaining', 0) if credits_check.data else 0
                else:
                    credits = credits_check.data.get('credits_remaining', 0)
                if credits < credits_needed:
                    raise ApiError(
                        402, INSUFFICIENT_CREDITS,
                        f"Insufficient credits. Need {credits_needed} credits (estimated {estimated_total} comments). You have {credits} credits."
                    )
        
        # Create progress tracking record
        progress_id = None
        if payload.get_all:
            try:
                progress_response = await asyncio.to_thread(
                    lambda: supabase.table('comments_fetch_progress').upsert({
                        'task_id': payload.task_id,
                        'video_id': video_id,
                        'status': 'in_progress',
                        'current_page': 0,
                        'total_pages_estimate': math.ceil(estimated_total / 50),
                        'comments_fetched': 0,
                        'provider': preview_result.get('provider'),
                        'started_at': datetime.now().isoformat()
                    }, on_conflict='task_id').execute()
                )
                progress_id = progress_response.data[0]['id']
                logger.info(f"Created progress tracking record: {progress_id}")
            except Exception as e:
                logger.warning(f"Failed to create progress record: {e}")
        
        # Fetch comments (all or single page)
        logger.info(f"Fetching comments for video {video_id} (task {payload.task_id}) - get_all={payload.get_all}")
        result = adapter.fetch_comments(video_id, count=payload.count, get_all=payload.get_all)
        
        if result.get('error'):
            # Update progress as failed
            if progress_id:
                await asyncio.to_thread(
                    lambda: supabase.table('comments_fetch_progress').update({
                        'status': 'failed',
                        'error_message': result['error'],
                        'completed_at': datetime.now().isoformat()
                    }).eq('id', progress_id).execute()
                )
            
            raise ApiError(
                503, SERVICE_UNAVAILABLE,
                f"Failed to fetch comments: {result['error']}"
            )
        
        comments = result.get('comments', [])
        pages_fetched = result.get('pages_fetched', 1)
        
        # Store comments in database
        stored_count = 0
        for comment in comments:
            try:
                await asyncio.to_thread(
                    lambda: supabase.table('video_comments').insert({
                        'task_id': payload.task_id,
                        'comment_id': comment.comment_id,
                        'video_id': video_id,
                        'text': comment.text,
                        'author_name': comment.author_name,
                        'author_username': comment.author_username,
                        'author_avatar': comment.author_avatar,
                        'created_at_timestamp': comment.created_at,
                        'likes': comment.likes,
                        'reply_count': comment.reply_count,
                        'parent_comment_id': comment.parent_comment_id,
                        'provider': result.get('provider'),
                        'raw_data': comment.raw_data
                    }).execute()
                )
                stored_count += 1
            except Exception as e:
                logger.warning(f"Failed to store comment {comment.comment_id}: {e}")
                continue
        
        # Calculate actual credits to charge (1 per 100 comments)
        actual_credits = math.ceil(stored_count / 100)
        
        # Update progress as completed
        if progress_id:
            await asyncio.to_thread(
                lambda: supabase.table('comments_fetch_progress').update({
                    'status': 'completed',
                    'current_page': pages_fetched,
                    'comments_fetched': stored_count,
                    'completed_at': datetime.now().isoformat()
                }).eq('id', progress_id).execute()
            )
        
        # Update transcription record
        await asyncio.to_thread(
            lambda: supabase.table('transcriptions').update({
                'comments_fetched': True,
                'comments_count': stored_count,
                'comments_fetched_at': datetime.now().isoformat()
            }).eq('task_id', payload.task_id).execute()
        )
        
        # Deduct credits if user has account
        if user_phone and actual_credits > 0:
            try:
                await asyncio.to_thread(
                    lambda: supabase.rpc('decrement_credits', {
                        'user_phone': user_phone,
                        'amount': actual_credits
                    }).execute()
                )
                logger.info(f"Deducted {actual_credits} credits from {user_phone} for {stored_count} comments")
            except Exception as e:
                logger.warning(f"Failed to deduct credits: {e}")
        
        return {
            "success": True,
            "task_id": payload.task_id,
            "comments_fetched": stored_count,
            "pages_fetched": pages_fetched,
            "credits_charged": actual_credits,
            "provider": result.get('provider'),
            "has_more": result.get('has_more', False),
            "cursor": result.get('cursor'),
            "estimated_total": estimated_total,
            "get_all": payload.get_all
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching comments: {e}", exc_info=True)
        raise ApiError(500, INTERNAL_ERROR, "Failed to fetch comments")


@app.get("/api/public/comments/{task_id}", tags=["Public Transcription"])
async def get_video_comments(
    task_id: str,
    limit: int = 50,
    offset: int = 0,
    sort_by: str = "likes"  # "likes", "recent", or "replies"
):
    """
    Get stored comments for a transcribed video.
    
    Parameters:
    - task_id: Transcription task ID
    - limit: Number of comments to return (max 100)
    - offset: Pagination offset
    - sort_by: Sort order (likes, recent, replies)
    """
    try:
        limit = min(limit, 100)  # Cap at 100
        
        # Build query based on sort order
        query = supabase.table('video_comments').select('*').eq('task_id', task_id)
        
        # Apply sorting
        if sort_by == "likes":
            query = query.order('likes', desc=True)
        elif sort_by == "recent":
            query = query.order('fetched_at', desc=True)
        elif sort_by == "replies":
            query = query.order('reply_count', desc=True)
        else:
            query = query.order('likes', desc=True)
        
        # Apply pagination
        query = query.range(offset, offset + limit - 1)
        
        response = await asyncio.to_thread(query.execute)
        
        return {
            "task_id": task_id,
            "comments": response.data,
            "count": len(response.data),
            "offset": offset,
            "limit": limit
        }
        
    except Exception as e:
        logger.error(f"Error fetching comments: {e}", exc_info=True)
        raise ApiError(500, INTERNAL_ERROR, "Failed to fetch comments")


@app.get("/api/public/comments/{task_id}/top", tags=["Public Transcription"])
async def get_top_comments(
    task_id: str,
    limit: int = 10,
    api_key: str = Depends(verify_api_key)
):
    """Get top N most-liked comments for a video"""
    try:
        response = await asyncio.to_thread(
            supabase.table('video_comments')
                    .select('*')
                    .eq('task_id', task_id)
                    .is_('parent_comment_id', 'null')  # Top-level only
                    .order('likes', desc=True)
                    .limit(limit)
                    .execute()
        )
        
        return {
            "task_id": task_id,
            "top_comments": response.data,
            "count": len(response.data)
        }
        
    except Exception as e:
        logger.error(f"Error fetching top comments: {e}", exc_info=True)
        raise ApiError(500, INTERNAL_ERROR, "Failed to fetch top comments")


@app.get("/api/public/comments/{task_id}/analytics", tags=["Public Transcription"])
async def get_comment_analytics(
    task_id: str,
    api_key: str = Depends(verify_api_key)
):
    """
    Get analytics data for comments (for research dashboard).
    Returns aggregate statistics and top comments.
    """
    try:
        # Fetch all comments for this task
        response = await asyncio.to_thread(
            supabase.table('video_comments')
                    .select('*')
                    .eq('task_id', task_id)
                    .execute()
        )
        
        comments = response.data
        
        if not comments or len(comments) == 0:
            return {
                "task_id": task_id,
                "total_comments": 0,
                "avg_likes": 0,
                "engagement_rate": 0,
                "sentiment": {"positive": 0, "neutral": 0, "negative": 0},
                "top_comments": [],
                "error": "No comments found. Fetch comments first."
            }
        
        # Calculate aggregate statistics
        total_comments = len(comments)
        total_likes = sum(c.get('likes', 0) for c in comments)
        avg_likes = round(total_likes / total_comments) if total_comments > 0 else 0
        total_replies = sum(c.get('reply_count', 0) for c in comments)
        
        # Calculate engagement rate (likes + replies per comment)
        engagement_rate = round(((total_likes + total_replies) / total_comments) / 100, 1) if total_comments > 0 else 0
        
        # Simple sentiment analysis (placeholder - can be enhanced later)
        sentiment = calculate_simple_sentiment(comments)
        
        # Get top 10 comments
        top_comments = sorted(comments, key=lambda x: x.get('likes', 0), reverse=True)[:10]
        
        # Format top comments for table display
        formatted_top_comments = [
            {
                "author": c.get('author_username', 'unknown'),
                "comment": c.get('text', ''),
                "likes": c.get('likes', 0),
                "replies": c.get('reply_count', 0),
                "created_at": c.get('created_at_timestamp', '')
            }
            for c in top_comments
        ]
        
        return {
            "task_id": task_id,
            "total_comments": total_comments,
            "avg_likes": avg_likes,
            "total_likes": total_likes,
            "total_replies": total_replies,
            "engagement_rate": engagement_rate,
            "sentiment": sentiment,
            "top_comments": formatted_top_comments,
            "fetched_at": comments[0].get('fetched_at') if comments else None
        }
        
    except Exception as e:
        logger.error(f"Error fetching comment analytics: {e}", exc_info=True)
        raise ApiError(500, INTERNAL_ERROR, "Failed to fetch comment analytics")


@app.get("/api/public/comments/{task_id}/export/csv", tags=["Public Transcription"])
async def export_comments_csv(
    task_id: str,
    api_key: str = Depends(verify_api_key)
):
    """Export comments as CSV file"""
    try:
        import csv
        from io import StringIO
        
        # Fetch all comments
        response = await asyncio.to_thread(
            supabase.table('video_comments')
                    .select('*')
                    .eq('task_id', task_id)
                    .order('likes', desc=True)
                    .execute()
        )
        
        if not response.data:
            raise ApiError(404, TASK_NOT_FOUND, "No comments found")

        # Create CSV in memory
        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=[
            'author_username', 'author_name', 'text', 'likes', 
            'reply_count', 'created_at_timestamp', 'video_id'
        ])
        
        writer.writeheader()
        for comment in response.data:
            writer.writerow({
                'author_username': comment.get('author_username', ''),
                'author_name': comment.get('author_name', ''),
                'text': comment.get('text', ''),
                'likes': comment.get('likes', 0),
                'reply_count': comment.get('reply_count', 0),
                'created_at_timestamp': comment.get('created_at_timestamp', ''),
                'video_id': comment.get('video_id', '')
            })
        
        # Return as downloadable file
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=comments_{task_id}.csv"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting comments to CSV: {e}", exc_info=True)
        raise ApiError(500, INTERNAL_ERROR, "Failed to export comments to CSV")


@app.get("/api/public/comments/{task_id}/export/json", tags=["Public Transcription"])
async def export_comments_json(
    task_id: str,
    api_key: str = Depends(verify_api_key)
):
    """Export comments as JSON file"""
    try:
        # Fetch all comments
        response = await asyncio.to_thread(
            supabase.table('video_comments')
                    .select('*')
                    .eq('task_id', task_id)
                    .order('likes', desc=True)
                    .execute()
        )
        
        if not response.data:
            raise ApiError(404, TASK_NOT_FOUND, "No comments found")

        # Return as downloadable JSON file
        return Response(
            content=json.dumps(response.data, indent=2),
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename=comments_{task_id}.json"
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting comments to JSON: {e}", exc_info=True)
        raise ApiError(500, INTERNAL_ERROR, "Failed to export comments to JSON")


@app.get("/api/public/comments/preview/{task_id}", tags=["Public Transcription"])
async def preview_comments(
    task_id: str
):
    """
    Get a preview of comments (first 20) to show user before charging.
    This endpoint is FREE and doesn't charge credits.
    
    Returns:
    - preview_comments: First 20 comments
    - estimated_total: Rough estimate of total comments
    - has_more: Whether there are more comments available
    - credits_needed: Estimated credits needed for full fetch
    """
    try:
        # Get task info with comment_count from video metadata
        response = await asyncio.to_thread(
            lambda: supabase.table('transcriptions')
                .select('video_id, video_url, comments_fetched, comment_count')
                .eq('task_id', task_id)
                .single()
                .execute()
        )
        
        if not response.data:
            raise ApiError(404, TASK_NOT_FOUND, "Task not found")

        task = response.data
        video_id = task.get('video_id')
        video_url = task.get('video_url')
        stored_comment_count = task.get('comment_count')

        if not video_id:
            raise ApiError(400, VALIDATION_ERROR, "Video ID not available for this task")
        
        # Check if comments already fetched
        if task.get('comments_fetched'):
            # Return existing comments as preview
            existing_response = await asyncio.to_thread(
                lambda: supabase.table('video_comments')
                    .select('*')
                    .eq('task_id', task_id)
                    .order('likes', desc=True)
                    .limit(20)
                    .execute()
            )
            
            preview_comments = existing_response.data or []
            total_count = len(preview_comments)
            
            return {
                "preview_comments": preview_comments,
                "estimated_total": total_count,
                "has_more": False,
                "credits_needed": 0,
                "already_fetched": True,
                "message": "Comments already fetched"
            }
        
        # Initialize comments adapter
        from adapters.comments_adapter import TikTokCommentsAdapter
        
        rapidapi_key = os.getenv('RAPIDAPI_KEY')
        if not rapidapi_key:
            raise ApiError(
                503, SERVICE_UNAVAILABLE,
                "Comments service not configured"
            )
        
        adapter = TikTokCommentsAdapter([rapidapi_key])
        
        # Fetch preview (first page only)
        logger.info(f"Fetching preview comments for video {video_id} (task {task_id})")
        result = adapter.fetch_comments(video_id, count=20, get_all=False)
        
        if not result.get('comments'):
            return {
                "preview_comments": [],
                "estimated_total": 0,
                "has_more": False,
                "credits_needed": 0,
                "already_fetched": False,
                "message": "No comments available for this video"
            }
        
        preview_comments = result['comments']
        has_more = result.get('has_more', False)
        
        # Estimate total comments
        # Priority: stored video metadata > preview-based estimate
        if stored_comment_count and stored_comment_count > 0:
            estimated_total = stored_comment_count
            logger.info(f"Using stored comment_count from video metadata: {estimated_total}")
        else:
            # If no stored count, estimate based on preview
            estimated_total = len(preview_comments) * 10 if has_more else len(preview_comments)
            logger.info(f"Using preview-based estimate: {estimated_total}")
        
        # Calculate credits needed (1 credit per 100 comments)
        import math
        credits_needed = math.ceil(estimated_total / 100)
        
        # Convert comments to dict format for JSON response
        preview_data = []
        provider_name = result.get('provider')
        for comment in preview_comments:
            preview_data.append({
                "comment_id": getattr(comment, 'comment_id', None),
                "text": getattr(comment, 'text', None),
                "author_name": getattr(comment, 'author_name', None),
                "author_username": getattr(comment, 'author_username', None),
                "author_avatar": getattr(comment, 'author_avatar', None),
                "likes": getattr(comment, 'likes', None),
                "reply_count": getattr(comment, 'reply_count', None),
                "created_at": getattr(comment, 'created_at', None),
                "parent_comment_id": getattr(comment, 'parent_comment_id', None),
                "video_id": getattr(comment, 'video_id', None),
                "provider": provider_name
            })
        
        return {
            "preview_comments": preview_data,
            "estimated_total": estimated_total,
            "has_more": has_more,
            "credits_needed": credits_needed,
            "already_fetched": False,
            "provider": result.get('provider'),
            "message": f"Preview: {len(preview_comments)} comments shown"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching comment preview: {e}", exc_info=True)
        raise ApiError(500, INTERNAL_ERROR, "Failed to fetch comment preview")


@app.get("/api/public/comments/fetch-status/{task_id}", tags=["Public Transcription"])
async def get_fetch_status(
    task_id: str
):
    """
    Check progress of ongoing comment fetch.
    
    Returns:
    - status: 'in_progress', 'completed', 'failed'
    - current_page: Current page being processed
    - comments_fetched: Number of comments fetched so far
    - estimated_total: Estimated total comments
    - progress_percent: Percentage complete
    - eta: Estimated time to completion
    """
    try:
        # Get progress record (avoid maybe_single which can 406 on multiple rows)
        response = await asyncio.to_thread(
            lambda: supabase.table('comments_fetch_progress')
                .select('*')
                .eq('task_id', task_id)
                .limit(1)
                .execute()
        )
        
        if not response.data:
            return {
                "status": "not_started",
                "current_page": 0,
                "comments_fetched": 0,
                "estimated_total": 0,
                "progress_percent": 0,
                "eta": None,
                "message": "No fetch in progress"
            }
        
        progress = response.data[0] if isinstance(response.data, list) and response.data else response.data
        status = progress.get('status', 'unknown')
        current_page = progress.get('current_page', 0)
        comments_fetched = progress.get('comments_fetched', 0)
        total_pages_estimate = progress.get('total_pages_estimate', 1)
        started_at = progress.get('started_at')
        completed_at = progress.get('completed_at')
        
        # Calculate progress percentage
        if total_pages_estimate > 0:
            progress_percent = min(100, (current_page / total_pages_estimate) * 100)
        else:
            progress_percent = 0
        
        # Calculate ETA
        eta = None
        if status == 'in_progress' and started_at and current_page > 0:
            try:
                from datetime import datetime
                start_time = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
                elapsed = datetime.now() - start_time.replace(tzinfo=None)
                
                if current_page > 0:
                    avg_time_per_page = elapsed.total_seconds() / current_page
                    remaining_pages = total_pages_estimate - current_page
                    remaining_seconds = remaining_pages * avg_time_per_page
                    
                    eta_time = datetime.now().timestamp() + remaining_seconds
                    eta = datetime.fromtimestamp(eta_time).strftime("%Y-%m-%d %H:%M:%S")
            except Exception as e:
                logger.warning(f"Error calculating ETA: {e}")
        
        # Estimate total comments
        estimated_total = comments_fetched
        if status == 'in_progress' and total_pages_estimate > 0:
            # Rough estimate based on pages
            estimated_total = int(comments_fetched * (total_pages_estimate / max(1, current_page)))
        
        return {
            "status": status,
            "current_page": current_page,
            "comments_fetched": comments_fetched,
            "estimated_total": estimated_total,
            "progress_percent": round(progress_percent, 1),
            "eta": eta,
            "total_pages_estimate": total_pages_estimate,
            "provider": progress.get('provider'),
            "started_at": started_at,
            "completed_at": completed_at,
            "error_message": progress.get('error_message')
        }
        
    except Exception as e:
        logger.error(f"Error getting fetch status: {e}", exc_info=True)
        raise ApiError(500, INTERNAL_ERROR, "Failed to get fetch status")


def calculate_simple_sentiment(comments):
    """
    Simple sentiment analysis based on keywords.
    Can be enhanced with NLP libraries later.
    """
    positive_keywords = ['love', 'amazing', 'great', 'awesome', 'best', 'perfect', 'helpful', 'thanks', '❤️', '😍', '🔥', '👍', '💯']
    negative_keywords = ['hate', 'bad', 'worst', 'terrible', 'awful', 'disappointed', 'boring', '👎', '😡', '😢']
    
    positive_count = 0
    negative_count = 0
    neutral_count = 0
    
    for comment in comments:
        text = comment.get('text', '').lower()
        
        has_positive = any(word in text for word in positive_keywords)
        has_negative = any(word in text for word in negative_keywords)
        
        if has_positive and not has_negative:
            positive_count += 1
        elif has_negative and not has_positive:
            negative_count += 1
        else:
            neutral_count += 1
    
    total = len(comments)
    if total == 0:
        return {"positive": 0, "neutral": 0, "negative": 0, "dominant": "neutral"}
    
    positive_pct = round((positive_count / total) * 100)
    neutral_pct = round((neutral_count / total) * 100)
    negative_pct = round((negative_count / total) * 100)
    
    # Determine dominant sentiment
    if positive_pct > negative_pct and positive_pct > neutral_pct:
        dominant = "positive"
    elif negative_pct > positive_pct and negative_pct > neutral_pct:
        dominant = "negative"
    else:
        dominant = "neutral"
    
    return {
        "positive": positive_pct,
        "neutral": neutral_pct,
        "negative": negative_pct,
        "dominant": dominant
    }


if __name__ == "__main__":
    # Get port from environment or use default
    port = int(os.environ.get("PORT", 8000))
    
    # Run the app
    uvicorn.run(app, host="0.0.0.0", port=port) 
