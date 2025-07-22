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
from fastapi import FastAPI, BackgroundTasks, HTTPException, Depends, Header, Request, Query, Form
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse, Response, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
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
from supabase.client import create_client, Client

# Fix imports for deployment
try:
    # Try relative import first (when running as a package)
    from .database import supabase
    from . import discovery
    from . import transcriber
    from . import sms
    from .tiktok_service import tiktok_service
    from . import health_check
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
- 🔐 **Phone-First Auth** - No email required, OTP-based verification  
- 🚀 **Viral Sharing** - Public transcript pages with social features
- 📊 **Rich Metadata** - 20+ fields from TikTok/YouTube videos
- 🔍 **Content Discovery** - Trending, similar, and recent transcriptions

## Phone-First User Flow
1. **Text Video URL** → Instant transcription (no signup required)
2. **Text `/register`** → Create account with full history preserved
3. **Web Login** → Access dashboard with phone + OTP

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
            "name": "System & Health",
            "description": "Service health checks and system maintenance endpoints.",
        },
    ],
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://scribetok.com",
        "https://www.scribetok.com", 
        "https://api.scribetok.com",
        "https://project-waitlist-signup-card-with-animation-586.magicpatterns.app",
        "https://c9218a45-acf5-4cc4-a39d-076b2ba2fab6-render.magicpatterns.app",
        "http://localhost:5173",
        "http://localhost:3000",
        "*"  # Allow all for development
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"]
)

# ---------------------------------------------------------------------------
# Templates & Static setup (paths relative to this file)
# ---------------------------------------------------------------------------

import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Jinja2 templates directory (e.g. app/templates)
templates_dir = os.path.join(BASE_DIR, "templates")
templates = Jinja2Templates(directory=templates_dir)

# Static assets directory (e.g. app/static)
static_dir = os.path.join(BASE_DIR, "static")
# Ensure the directory exists (allows local dev & avoids Render crash)
os.makedirs(static_dir, exist_ok=True)
# Mount at /static so CSS/JS/images are served
app.mount("/static", StaticFiles(directory=static_dir), name="static")

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
    url: str = Field(..., 
        description="TikTok or YouTube video URL to transcribe",
        example="https://www.tiktok.com/@user/video/7526401258786245902"
    )
    callback_url: Optional[str] = Field(None,
        description="Webhook URL to receive completion notification",
        example="https://yourapp.com/webhook"
    )
    format: Optional[str] = Field("bestaudio/best",
        description="Video/audio format preference for download"
    )
    output_template: Optional[str] = Field(None,
        description="Custom output filename template"
    )
    user_phone: Optional[str] = Field(None,
        description="Phone number for SMS notifications (for SMS-initiated requests)"
    )
    extract_audio: bool = Field(True,
        description="Extract audio from video for transcription"
    )
    convert_to_mp3: bool = Field(False,
        description="Convert audio to MP3 format"
    )
    save_thumbnail: bool = Field(True,
        description="Save video thumbnail image"
    )
    extract_metadata: bool = Field(True,
        description="Extract rich metadata (views, likes, creator info, etc.)"
    )
    perform_sentiment_analysis: bool = Field(False,
        description="Analyze transcript sentiment (experimental)"
    )
    create_srt: bool = Field(False,
        description="Generate SRT subtitle file"
    )
    proxy: Optional[str] = Field(None,
        description="Proxy server URL for download",
        example="http://proxy.example.com:8080"
    )
    api_key: Optional[str] = Field(None,
        description="API key for authentication (can also use header)"
    )
    user_phone: Optional[str] = Field(None,
        description="Phone number for SMS notifications and user tracking",
        example="+1234567890"
    )

class TranscriptionResponse(BaseModel):
    """Complete transcription task response with rich metadata"""
    # Core Task Information
    task_id: str = Field(..., example="550e8400-e29b-41d4-a716-446655440000")
    status: str = Field(..., example="completed", pattern="^(pending|processing|completed|failed)$")
    created_at: str = Field(..., example="2025-07-20T12:00:00Z")
    error: Optional[str] = Field(None, example=None)
    # Video Information
    video_id: Optional[str] = Field(None, example="7526401258786245902")
    title: Optional[str] = Field(None, example="Amazing TikTok Video")
    description: Optional[str] = Field(None, example="Check out this amazing tech tutorial! #technology #viral")
    duration: Optional[int] = Field(None, example=122)
    platform: Optional[str] = Field(None, example="tiktok")
    # Creator Information  
    creator: Optional[str] = Field(None, example="Tech Guru")
    uploader_url: Optional[str] = Field(None, example="https://tiktok.com/@techguru")
    # Engagement Metrics
    like_count: Optional[int] = Field(None, example=1500)
    comment_count: Optional[int] = Field(None, example=89)
    repost_count: Optional[int] = Field(None, example=234)
    view_count: Optional[int] = Field(None, example=15)
    # Media Assets
    thumbnail_url: Optional[str] = Field(None, example="https://example.com/thumb.jpg")
    video_url: Optional[str] = Field(None, example="https://cdn.tiktok.com/...")
    thumbnail_local_path: Optional[str] = Field(None, example="d5911018-8ba2-4ca6-bebf-95e9994f3a2d/thumbnail.jpg")
    # Deprecated (kept for compatibility)
    thumbnail: Optional[str] = Field(None, description="Deprecated: Use thumbnail_url instead")
    # Tags and Category
    tags: Optional[list] = Field(None, example=["tech", "viral"])
    category: Optional[str] = Field(None, example="technology")

class TaskListResponse(BaseModel):
    """Response model for task list endpoints"""
    tasks: List[TranscriptionResponse] = Field(..., 
        description="Array of transcription tasks"
    )
    total: Optional[int] = Field(None,
        description="Total number of tasks",
        example=156
    )
    limit: Optional[int] = Field(None,
        description="Maximum results per page",
        example=50
    )
    offset: Optional[int] = Field(None,
        description="Number of results skipped",
        example=0
    )

class HealthCheckResponse(BaseModel):
    """Health check response model"""
    status: str = Field(...,
        description="Service status",
        example="ok"
    )
    version: str = Field(...,
        description="API version",
        example="1.0.0"
    )
    timestamp: float = Field(...,
        description="Server timestamp",
        example=1753026086.24777
    )
    services: Dict[str, str] = Field(...,
        description="Connected service statuses",
        example={
            "openai": "connected",
            "supabase": "connected", 
            "rapidapi": "connected"
        }
    )

class SMSResponse(BaseModel):
    """SMS operation response model"""
    success: bool = Field(...,
        description="Whether SMS operation succeeded",
        example=True
    )
    message_sid: Optional[str] = Field(None,
        description="Twilio message SID",
        example="SM1234567890abcdef"
    )
    status: Optional[str] = Field(None,
        description="Message delivery status",
        example="queued"
    )

class AccountLinkResponse(BaseModel):
    """Account linking response model"""
    success: bool = Field(...,
        description="Whether account linking succeeded",
        example=True
    )
    auth_user_id: str = Field(...,
        description="Supabase auth user ID",
        example="550e8400-e29b-41d4-a716-446655440000"
    )
    linked_transcriptions: int = Field(...,
        description="Number of transcriptions linked to account",
        example=15
    )
    phone: str = Field(...,
        description="Phone number",
        example="+1234567890"
    )
    message: str = Field(...,
        description="Success message",
        example="Account created and 15 transcriptions linked"
    )

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
    """Dependency for API key validation using environment variable fallback"""
    # Handle potential None value from Header
    if x_api_key is None:
         logger.warning("API key validation failed: X-API-Key header missing.")
         raise HTTPException(status_code=401, detail="X-API-Key header required")
    
    # Simple validation against environment variable API_KEYS
    api_keys_env = os.getenv("API_KEYS", "").strip()
    if api_keys_env:
        valid_keys = [key.strip() for key in api_keys_env.split(",") if key.strip()]
        if x_api_key not in valid_keys:
            logger.warning("API key validation failed: Invalid API key provided.")
            raise HTTPException(status_code=403, detail="Invalid API Key")
    else:
        logger.warning("No API_KEYS environment variable set, allowing all keys for development")
    
    return x_api_key

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
    return FileResponse("static/robots.txt", media_type="text/plain")

@app.get("/apple-touch-icon.png", include_in_schema=False)
async def apple_touch_icon():
    """Serve apple-touch-icon.png from static directory"""
    return FileResponse("static/apple-touch-icon.png", media_type="image/png")

@app.get("/favicon.ico", include_in_schema=False)
async def favicon_ico():
    """Serve favicon.ico from static directory"""
    return FileResponse("static/favicon.ico", media_type="image/x-icon")

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
        raise HTTPException(status_code=503, detail=f"Service not alive: {str(e)}")

@app.post("/api/public/transcribe", response_model=TranscriptionResponse, tags=["Public Transcription"])
async def transcribe(
    request: TranscriptionRequest,
    background_tasks: BackgroundTasks,
    user_id: Optional[str] = None  # Made optional to support both authenticated and public requests
) -> TranscriptionResponse:
    """Start a new transcription task or return existing one."""
    try:
        # Initialize task (this will check for existing transcriptions)
        # For SMS users, only use user_phone (not user_id since SMS users aren't in auth.users)
        logger.info(f"Transcribe request: url={request.url}, user_phone={request.user_phone}")
        task = await init_task(request.url, user_id, request.user_phone)
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
            # For YouTube URLs, try instant transcription first
            if is_youtube_url(request.url):
                logger.info(f"Attempting instant YouTube transcription for task {task_id}")
                
                try:
                    youtube_result = transcriber.download_youtube_rapidapi(request.url)
                    
                    if youtube_result:
                        # Update task with completed status and transcript
                        await asyncio.to_thread(
                            supabase.table('transcriptions')
                                    .update({
                                        'status': 'completed',
                                        'video_id': youtube_result['video_id'],
                                        'title': youtube_result['title'],
                                        'transcript': youtube_result['transcript'],
                                        'platform': 'youtube',
                                        'category': 'youtube-transcription',
                                        'tags': ['sms-inbound', 'youtube'] if request.user_phone else ['youtube']
                                    })
                                    .eq('task_id', task_id)
                                    .execute()
                        )
                        
                        # Update task_data for response
                        task_data['status'] = 'completed'
                        task_data['video_id'] = youtube_result['video_id']
                        task_data['title'] = youtube_result['title']
                        task_data['platform'] = 'youtube'
                        
                        logger.info(f"YouTube instant transcription completed for task {task_id}")
                    else:
                        logger.warning(f"YouTube instant transcription failed for {task_id}, falling back to background processing")
                        # Queue the background processing as fallback
                        background_tasks.add_task(
                            process_transcription_task,
                            task_id,
                            request.url,
                            request.callback_url,
                            request.proxy
                        )
                        logger.info(f"Task {task_id} queued for background processing (YouTube fallback)")
                        
                except Exception as e:
                    logger.error(f"YouTube instant transcription error for {task_id}: {str(e)}")
                    # Queue the background processing as fallback
                    background_tasks.add_task(
                        process_transcription_task,
                        task_id,
                        request.url,
                        request.callback_url,
                        request.proxy
                    )
                    logger.info(f"Task {task_id} queued for background processing (YouTube error fallback)")
            else:
                # Non-YouTube URLs: use background processing
                background_tasks.add_task(
                    process_transcription_task,
                    task_id,
                    request.url,
                    request.callback_url,
                    request.proxy
                )
                logger.info(f"Task {task_id} queued for background processing URL: {request.url}")
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

@app.get("/api/tasks", response_model=TaskListResponse, tags=["Private Task Management"])
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

@app.get(
    "/api/public/tasks/{task_id}",
    response_model=TranscriptionResponse,
    tags=["Core Transcription"],
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
        raise HTTPException(status_code=500, detail="Database connection not available")
    try:
        response = await asyncio.to_thread(
            supabase.table('transcriptions')
                    .select("task_id, status, video_id, title, created_at, error, thumbnail_url, thumbnail_local_path, video_url, duration, like_count, comment_count, repost_count, view_count, platform, tags, category")
                    .eq('task_id', task_id)
                    .maybe_single()
                    .execute
        )
        if hasattr(response, 'error') and response.error:
             logger.error(f"Failed to get task {task_id} from Supabase: {response.error}")
             raise HTTPException(status_code=500, detail="Database error retrieving task")
        if not response.data:
            raise HTTPException(status_code=404, detail="Task not found")
        task_data = response.data
        return TranscriptionResponse(**task_data)
    except HTTPException:
         raise
    except Exception as e:
        logger.error(f"Exception getting task {task_id} from Supabase: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Server error retrieving task")

@app.delete("/api/tasks/{task_id}", tags=["Private Task Management"])
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

@app.get("/api/transcript/{task_id}", tags=["Private Task Management"])
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

@app.post("/api/test-download", response_model=str, tags=["System & Health"])
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
            
            # Generate quote and TLDR
            logger.info(f"Generating quote and TLDR for task {task_id}")
            quote_tldr_result = {}
            try:
                quote_tldr_result = transcriber.generate_quote_and_tldr(transcript_text)
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
                import json
                update_data["tldr"] = json.dumps(quote_tldr_result["tldr"])  # Store as JSON
                logger.info(f"Generated TLDR: {quote_tldr_result['tldr']}")
            
            await asyncio.to_thread(
                supabase.table('transcriptions')
                        .update(update_data)
                        .eq('task_id', task_id)
                        .execute()
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

def is_youtube_url(url: str) -> bool:
    """Check if URL is a YouTube video."""
    import re
    youtube_patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)([^&\n?#]+)',
        r'(?:www\.)?youtube\.com/watch\?v=[\w-]+',
        r'(?:www\.)?youtu\.be/[\w-]+',
        r'(?:www\.)?youtube\.com/shorts/[\w-]+'
    ]
    return any(re.search(pattern, url, re.IGNORECASE) for pattern in youtube_patterns)


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
            supabase.table('transcriptions')
                    .select("url, user_phone") # Fetch URL and user_phone for SMS notifications
                    .eq('task_id', task_id)
                    .single() # Expect exactly one result
                    .execute
        )
        
        if not task_response.data or 'url' not in task_response.data:
             logger.error(f"Could not retrieve original URL for task {task_id} from database.")
             await update_task_status(task_id, "failed", "Failed to retrieve task URL from database")
             return
             
        original_video_url = task_response.data['url']
        user_phone = task_response.data.get('user_phone')  # Get user phone for SMS notifications
        logger.info(f"Processing task {task_id} with original URL from DB: {original_video_url}, SMS phone: {user_phone or 'none'}")
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
                
                # Generate quote and TLDR for YouTube too
                quote_tldr_result = {}
                try:
                    quote_tldr_result = transcriber.generate_quote_and_tldr(transcript_text)
                    logger.info(f"Generated quote/TLDR for YouTube video {video_id}")
                except Exception as e:
                    logger.warning(f"Failed to generate quote/TLDR for YouTube video: {str(e)}")
                
                # Prepare complete update data for YouTube
                update_data = {
                    'status': 'completed',
                    'video_id': video_id,
                    'title': title,
                    'transcript': transcript_text,
                    'platform': platform,
                    'category': 'youtube-transcription',
                    'tags': ['sms-inbound', 'youtube'] if user_phone else ['youtube'],
                    'error': None,
                    'view_count': 1,  # Initialize view count
                    'visibility': 'public'
                }
                
                # Add quote and TLDR if generated successfully
                if quote_tldr_result.get("quote"):
                    update_data["quote"] = quote_tldr_result["quote"]
                    logger.info(f"Generated quote: {quote_tldr_result['quote']}")
                if quote_tldr_result.get("tldr"):
                    import json
                    update_data["tldr"] = json.dumps(quote_tldr_result["tldr"])
                    logger.info(f"Generated TLDR: {quote_tldr_result['tldr']}")
                
                # Add user_phone if available (SMS context)
                if user_phone:
                    update_data['user_phone'] = user_phone
                
                await asyncio.to_thread(
                    supabase.table('transcriptions')
                            .update(update_data)
                            .eq('task_id', task_id)
                            .execute()
                )
                
                # Send SMS notification if user_phone is provided
                if user_phone:
                    try:
                        await sms.send_completion_sms(user_phone, task_id, youtube_result['title'])
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
                logger.warning(f"YouTube instant transcription failed, falling back to standard processing for task {task_id}")
        
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
        
        # Extract rich metadata from .info.json files
        thumbnail_url = None
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
                    # Handle both RapidAPI and yt-dlp metadata formats
                    if 'data' in metadata:  # RapidAPI format
                        data = metadata['data']
                        author = data.get('author', {})
                        rich_metadata = {
                            'description': data.get('title'),  # RapidAPI puts description in title
                            'duration': data.get('duration'),
                            'upload_date': None,  # Not available in RapidAPI
                            'timestamp': data.get('create_time'),
                            'channel': author.get('nickname'),
                            'channel_id': author.get('unique_id'),
                            'uploader': author.get('nickname'),
                            'uploader_url': f"https://tiktok.com/@{author.get('unique_id')}" if author.get('unique_id') else None,
                            'like_count': data.get('digg_count', 0),
                            'comment_count': data.get('comment_count', 0),
                            'repost_count': data.get('share_count', 0),
                            'resolution': None,  # Not directly available
                            'width': None,
                            'height': None,
                            'aspect_ratio': None,
                            'filesize': data.get('hd_size'),
                            'format_id': 'rapidapi_hd',
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
                            'platform': 'tiktok' if 'tiktok' in (metadata.get('webpage_url', '') or original_video_url) else 'youtube'
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
            
            # Generate quote and TLDR
            logger.info(f"Generating quote and TLDR for task {task_id}")
            quote_tldr_result = {}
            try:
                quote_tldr_result = transcriber.generate_quote_and_tldr(transcript_text)
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
                'platform': 'tiktok',  # Default platform for this path
                'language': 'english'  # Default language
            }
            
            # Add quote and TLDR if generated successfully
            if quote_tldr_result.get("quote"):
                update_data["quote"] = quote_tldr_result["quote"]
                logger.info(f"Generated quote: {quote_tldr_result['quote']}")
            
            if quote_tldr_result.get("tldr"):
                import json
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
                
            # Add auto-extracted tags array (combine with existing tags)
            if rich_metadata.get('description'):
                # Extract hashtags from description
                import re
                hashtags = re.findall(r'#(\w+)', rich_metadata['description'])
                if hashtags:
                    all_tags = list(set(tags + hashtags))  # Combine and deduplicate
                    update_data['auto_tags'] = all_tags
                    
            logger.info(f"Updating task {task_id} with {len(update_data)} metadata fields")
                
            await asyncio.to_thread(
                supabase.table('transcriptions')
                        .update(update_data)
                        .eq('task_id', task_id)
                        .execute()
            )
            logger.info(f"Task {task_id} completed with {len(tags)} tags in category: {category}, thumbnail: {thumbnail_local_path or 'none'}")
            
            # Send SMS notification if this was an SMS request
            if update_data.get('user_phone'):
                logger.info(f"Sending SMS completion notification to {update_data['user_phone']} for task {task_id}")
                # Get the generated quote and TLDR for SMS
                quote = quote_tldr_result.get("quote", "")
                tldr_list = quote_tldr_result.get("tldr", [])
                await send_completion_sms(task_id, update_data['user_phone'], title or 'Video', transcript_text, quote, tldr_list)
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
        if not all([os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN')]):
            logger.warning("Twilio credentials not available, skipping SMS notification")
            return
            
        from twilio.rest import Client
        
        # Get user's current credits from SMS users table
        normalized_phone = phone_number.replace('+1', '').replace('+', '') if phone_number.startswith('+1') else phone_number.replace('+', '')
        if len(normalized_phone) == 10:
            normalized_phone = f"+1{normalized_phone}"
        elif len(normalized_phone) == 11 and normalized_phone.startswith('1'):
            normalized_phone = f"+{normalized_phone}"
        
        credits_remaining = 0
        try:
            response = await asyncio.to_thread(
                supabase.table('sms_users')
                .select('credits_remaining')
                .eq('phone_number', normalized_phone)
                .single()
                .execute
            )
            credits_remaining = response.data.get('credits_remaining', 0) if response.data else 0
        except Exception as e:
            logger.warning(f"Could not fetch credits for {phone_number}: {e}")
        
        # Use Quote + TLDR format if available, fallback to preview
        if quote and tldr_list:
            # Show 3-4 TLDR items for richer content (we'll manage length differently)
            short_tldr = tldr_list[:4]  # Allow up to 4 bullet points
            tldr_bullets = '\n'.join([f"• {item[:100]}..." if len(item) > 100 else f"• {item}" for item in short_tldr])
            
            # Allow longer quotes for more impact
            short_quote = quote[:120] + "..." if len(quote) > 120 else quote
            
            message = f"""🧠 "{short_quote}"

📝 TLDR:
{tldr_bullets}

💬 /full for more • /tldr to regenerate
🔗 share.scribetok.com/v/{task_id}
💳 {credits_remaining} left"""
        else:
            # Fallback to old format if quote+TLDR generation failed
            words = transcript.split(' ')[:50] 
            preview = ' '.join(words) + ('...' if len(transcript.split(' ')) > 50 else '')
            
            message = f"""🧠 Here's what's worth remembering: "{title}"

{preview}

📖 Full transcript: https://share.scribetok.com/v/{task_id}
💳 Credits remaining: {credits_remaining}"""

        # Add short upsell messages 
        if credits_remaining == 0:
            message += "\n\n💳 All free credits used! 5 more for $1.99:\nstripe.com/4gMcN42NS • /referral for free"
        elif credits_remaining == 1:
            message += "\n\n⚠️ Last free credit! 5 for $1.99: stripe.com/4gMcN42NS"
        elif credits_remaining == 2:
            message += "\n\n💡 2 credits left! More: stripe.com/4gMcN42NS"

        # Allow longer messages for richer content (up to ~12-14 segments)
        if len(message) > 900:
            logger.warning(f"SMS message too long ({len(message)} chars), truncating")
            # Intelligently truncate by removing last TLDR points instead of cutting mid-sentence
            if "📝 TLDR:" in message and len(short_tldr) > 2:
                # Fallback to 2 TLDR points if message too long
                fallback_tldr = tldr_list[:2]
                fallback_bullets = '\n'.join([f"• {item[:100]}..." if len(item) > 100 else f"• {item}" for item in fallback_tldr])
                message = f"""🧠 "{short_quote}"

📝 TLDR:
{fallback_bullets}

💬 /full for more • /tldr to regenerate
🔗 share.scribetok.com/v/{task_id}
💳 {credits_remaining} left"""
            else:
                message = message[:850] + "..."
        
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
                supabase.table('user_messages').insert({
                    'from_phone': os.getenv('TWILIO_PHONE_NUMBER', '+17744727423'),
                    'to_phone': normalize_phone(phone_number),
                    'message_body': message,
                    'direction': 'outbound',
                    'message_sid': sms.sid,
                    'delivery_status': sms.status or 'queued'
                }).execute
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

async def init_task(video_url: str, user_id: str = None, user_phone: str = None) -> Dict[str, Any]:
    """Initialize a new task entry in the Supabase database."""
    if supabase is None:
        logger.error("Cannot initialize task: Supabase client not initialized")
        raise HTTPException(status_code=500, detail="Database error during task initialization")

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

@app.get("/api/public/tasks/{task_id}", tags=["Public Transcription"])
async def public_get_task(task_id: str):
    """Get task status without requiring API key."""
    if supabase is None:
        logger.error(f"Cannot get task {task_id}: Supabase client not initialized.")
        raise HTTPException(status_code=500, detail="Database connection not available")
        
    try:
        # Fetch task from Supabase
        response = await asyncio.to_thread(
            supabase.table('public_transcriptions')
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

@app.get("/api/public/transcript/{task_id}", tags=["Public Transcription"])
async def public_get_transcript(task_id: str, format: Optional[str] = None):
    """Get transcript for a task without API key"""
    try:
        # Fetch task from database
        result = supabase.table("public_transcriptions").select("*").eq("task_id", task_id).single().execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Task not found")
        
        task = result.data
        
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
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching task {task_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Error retrieving task")
        
    # First check if transcript is stored in database
    if task.get("transcript"):
        transcript_text = task["transcript"]
        
        # Clean the transcript if it contains raw TranscriptionVerbose data
        if transcript_text.startswith('TranscriptionVerbose('):
            import re
            import ast
            
            # Try to extract and format the segments with timestamps
            try:
                # Extract segments data
                segments_match = re.search(r'segments=\[(.*?)\], usage=', transcript_text, re.DOTALL)
                if segments_match:
                    # Format transcript with timestamps
                    formatted_transcript = ""
                    current_minute = -1
                    
                    # Parse individual segments from the raw data
                    segment_pattern = r'TranscriptionSegment\([^)]*start=([0-9.]+)[^)]*text=\'([^\']*)\''
                    segments = re.findall(segment_pattern, transcript_text)
                    
                    for start_time_str, text in segments:
                        start_time = float(start_time_str)
                        minute = int(start_time // 60)
                        second = int(start_time % 60)
                        
                        # Add timestamp header for new minutes
                        if minute != current_minute:
                            if formatted_transcript:  # Add newline if not first
                                formatted_transcript += "\n\n"
                            formatted_transcript += f"{minute}:{second:02d} - {minute}:{second+5:02d}\n"
                            current_minute = minute
                        
                        formatted_transcript += text.strip()
                    
                    if formatted_transcript:
                        transcript_text = formatted_transcript
                    else:
                        # Fallback to plain text if parsing fails
                        text_match = re.search(r'text="([^"]+)"', transcript_text)
                        if text_match:
                            transcript_text = text_match.group(1)
                else:
                    # Fallback to plain text extraction
                    text_match = re.search(r'text="([^"]+)"', transcript_text)
                    if text_match:
                        transcript_text = text_match.group(1)
                        
            except Exception as e:
                logger.warning(f"Error parsing transcript segments, using plain text: {e}")
                # Fallback to simple text extraction
                text_match = re.search(r'text="([^"]+)"', transcript_text)
                if text_match:
                    transcript_text = text_match.group(1)
            
            # Update the database with clean text for future requests
            try:
                supabase.table('transcriptions').update({
                    'transcript': transcript_text
                }).eq('task_id', task_id).execute()
            except Exception as e:
                logger.warning(f"Could not update clean transcript in database: {e}")
        
        if format and format.lower() == 'json':
            return {"transcript": transcript_text, "task_id": task_id}
        return transcript_text
        
    # Look for transcript file as fallback
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

@app.get("/api/public/tasks", response_model=TaskListResponse, tags=["Public Transcription"])
async def public_list_tasks():
    """List the last 50 transcription tasks without API key"""
    if supabase is None:
        logger.error(f"Cannot list public tasks: Supabase client not initialized.")
        raise HTTPException(status_code=500, detail="Database connection not available")

    try:
        # Fetch the last 50 tasks from Supabase, similar to the authenticated endpoint
        response = await asyncio.to_thread(
            supabase.table('public_transcriptions')
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

@app.get("/api/public/thumbnail/{task_id}", tags=["Public Transcription"])
async def public_get_thumbnail(task_id: str):
    """Get the thumbnail image for a task without API key"""
    if supabase is None:
        logger.error(f"Cannot get public thumbnail for {task_id}: Supabase client not initialized.")
        raise HTTPException(status_code=500, detail="Database connection not available")

    try:
        # Fetch task details from Supabase
        response = await asyncio.to_thread(
            supabase.table('transcriptions')
                    .select("task_id, status, error, thumbnail_url, thumbnail_local_path, supabase_thumbnail_url") # Select thumbnail fields
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
        
        # Priority 1: Redirect to Supabase Storage URL if available (persistent, CDN-backed)
        if task.get("supabase_thumbnail_url"):
            logger.info(f"Redirecting to Supabase thumbnail URL: {task['supabase_thumbnail_url']}")
            return RedirectResponse(url=task["supabase_thumbnail_url"])
            
        # Priority 2: Redirect to external thumbnail URL if available (TikTok CDN)
        if task.get("thumbnail_url"):
            logger.info(f"Redirecting to external thumbnail URL: {task['thumbnail_url']}")
            return RedirectResponse(url=task["thumbnail_url"])

        # Priority 3: Serve locally stored thumbnail file if path exists (fallback for persistent storage)
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
                 # Clear the local path from database since file is missing (ephemeral storage)
                 try:
                     await asyncio.to_thread(
                         supabase.table('transcriptions')
                                .update({"thumbnail_local_path": None})
                                .eq('task_id', task_id)
                                .execute()
                     )
                     logger.info(f"Cleared invalid thumbnail_local_path for task {task_id}")
                 except Exception as e:
                     logger.error(f"Failed to clear thumbnail_local_path for {task_id}: {e}")
        
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

@app.get("/api/public/thumbnail_square/{task_id}", tags=["Public Transcription"])
async def public_get_square_thumbnail(task_id: str):
    """Get the square (1:1) thumbnail image for a task without API key - optimized for iMessage/WhatsApp"""
    if supabase is None:
        logger.error(f"Cannot get public square thumbnail for {task_id}: Supabase client not initialized.")
        raise HTTPException(status_code=500, detail="Database connection not available")

    try:
        # Fetch task details from Supabase
        response = await asyncio.to_thread(
            supabase.table('transcriptions')
                    .select("task_id, status, error, thumbnail_url, thumbnail_local_path, supabase_thumbnail_url, square_thumbnail_url")
                    .eq('task_id', task_id)
                    .maybe_single()
                    .execute
        )

        if hasattr(response, 'error') and response.error:
             logger.error(f"Database error fetching public square thumbnail for {task_id}: {response.error}")
             raise HTTPException(status_code=500, detail="Database error retrieving task info")

        if not response.data:
            raise HTTPException(status_code=404, detail="Task not found")

        task = response.data

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
        
        # Priority 1: Serve square thumbnail if it exists
        output_dir = os.path.join(DOWNLOADS_DIR, task_id)
        square_thumbnail_path = os.path.join(output_dir, "thumbnail_square.jpg")
        
        if os.path.exists(square_thumbnail_path):
            logger.info(f"Serving square thumbnail file: {square_thumbnail_path}")
            return FileResponse(square_thumbnail_path, media_type="image/jpeg")
        
        # Priority 2: Create square thumbnail on-the-fly from existing thumbnail
        if task.get("thumbnail_local_path"):
            local_thumbnail_full_path = os.path.join(DOWNLOADS_DIR, task["thumbnail_local_path"])
            if os.path.exists(local_thumbnail_full_path):
                # Create square thumbnail on-demand
                if create_square_thumbnail(local_thumbnail_full_path, square_thumbnail_path):
                    logger.info(f"Created square thumbnail on-demand: {square_thumbnail_path}")
                    return FileResponse(square_thumbnail_path, media_type="image/jpeg")
            else:
                # Clear the local path from database since file is missing (ephemeral storage)
                try:
                    await asyncio.to_thread(
                        supabase.table('transcriptions')
                               .update({"thumbnail_local_path": None})
                               .eq('task_id', task_id)
                               .execute()
                    )
                    logger.info(f"Cleared invalid thumbnail_local_path for task {task_id} (square endpoint)")
                except Exception as e:
                    logger.error(f"Failed to clear thumbnail_local_path for {task_id}: {e}")
        
        # Priority 3: Use Supabase square thumbnail if available
        if task.get("square_thumbnail_url"):
            logger.info(f"Redirecting to Supabase square thumbnail URL: {task['square_thumbnail_url']}")
            return RedirectResponse(url=task["square_thumbnail_url"])
            
        # Priority 4: Use Supabase regular thumbnail if available
        if task.get("supabase_thumbnail_url"):
            logger.info(f"Redirecting to Supabase thumbnail URL (fallback for square): {task['supabase_thumbnail_url']}")
            return RedirectResponse(url=task["supabase_thumbnail_url"])
            
        # Priority 5: Use external thumbnail URL if available (TikTok CDN)
        if task.get("thumbnail_url"):
            logger.info(f"No local square thumbnail, redirecting to external URL: {task['thumbnail_url']}")
            return RedirectResponse(url=task["thumbnail_url"])
        
        # Priority 6: Look for any existing thumbnail and convert it
        for ext in ['.jpg', '.png', '.jpeg', '.webp']:
            files = glob.glob(os.path.join(output_dir, f"**/*{ext}"), recursive=True)
            # Exclude the square thumbnail we're trying to create
            files = [f for f in files if not f.endswith('thumbnail_square.jpg')]
            if files:
                original_thumbnail = files[0]
                if create_square_thumbnail(original_thumbnail, square_thumbnail_path):
                    logger.info(f"Created square thumbnail from fallback image: {square_thumbnail_path}")
                    return FileResponse(square_thumbnail_path, media_type="image/jpeg")
                break
        
        # Final Fallback: Create default square thumbnail
        logger.warning(f"No thumbnail found for task {task_id}, creating default square thumbnail")
        static_dir = os.path.join(os.path.dirname(__file__), "static")
        os.makedirs(static_dir, exist_ok=True)
        default_square_thumbnail = os.path.join(static_dir, "default_square_thumbnail.jpg")
        
        if not os.path.exists(default_square_thumbnail):
            try:
                # Create a square default image
                img = Image.new('RGB', (1200, 1200), color=(53, 59, 72))
                draw = ImageDraw.Draw(img)
                text = "ScribeTok"
                try: font = ImageFont.truetype("Arial", 120)
                except: font = ImageFont.load_default()
                text_width, text_height = draw.textsize(text, font=font) if hasattr(draw, 'textsize') else (400, 80)
                position = ((1200-text_width)//2, (1200-text_height)//2)
                draw.text(position, text, fill=(236, 240, 241), font=font)
                img.save(default_square_thumbnail)
                logger.info(f"Created default square thumbnail at {default_square_thumbnail}")
            except Exception as e:
                logger.error(f"Error creating default square thumbnail: {str(e)}")
                raise HTTPException(status_code=404, detail="Square thumbnail not found and could not create default")
        
        return FileResponse(default_square_thumbnail, media_type="image/jpeg")

    except Exception as e:
        logger.error(f"Error fetching public square thumbnail for task {task_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Server error fetching square thumbnail")

@app.post("/api/tasks", tags=["Private Task Management"])
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

@app.post("/api/cleanup-stuck-tasks", tags=["System & Health"])
async def cleanup_stuck_tasks(api_key: str = Depends(verify_api_key)):
    """Mark long-pending tasks as failed (requires API key)"""
    return await _cleanup_stuck_tasks_logic()

@app.post("/api/public/cleanup-stuck-tasks", tags=["System & Health"])
async def public_cleanup_stuck_tasks():
    """Mark long-pending tasks as failed (public endpoint)"""
    return await _cleanup_stuck_tasks_logic()

@app.post("/api/reprocess-sms-jobs", tags=["System & Health"])
async def reprocess_sms_jobs(background_tasks: BackgroundTasks, api_key: str = Depends(verify_api_key)):
    """Reprocess stuck SMS transcription jobs (requires API key)"""
    return await _reprocess_sms_jobs_logic(background_tasks)

@app.post("/api/public/reprocess-sms-jobs", tags=["System & Health"])
async def public_reprocess_sms_jobs(background_tasks: BackgroundTasks):
    """Reprocess stuck SMS transcription jobs (public endpoint)"""
    return await _reprocess_sms_jobs_logic(background_tasks)

async def _reprocess_sms_jobs_logic(background_tasks: BackgroundTasks):
    """Find and reprocess stuck SMS jobs"""
    if supabase is None:
        logger.error("Cannot reprocess SMS jobs: Supabase client not initialized")
        raise HTTPException(status_code=500, detail="Database connection not available")
    
    try:
        # Find pending SMS jobs
        response = await asyncio.to_thread(
            supabase.table('transcriptions')
            .select("task_id, url, tags")
            .eq('status', 'pending')
            .execute
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
        raise HTTPException(status_code=500, detail=f"Failed to reprocess SMS jobs: {str(e)}")

async def _cleanup_stuck_tasks_logic():
    """Shared cleanup logic"""
    if supabase is None:
        logger.error("Cannot cleanup stuck tasks: Supabase client not initialized")
        raise HTTPException(status_code=500, detail="Database connection not available")
    
    try:
        # Find tasks pending for more than 30 minutes
        cutoff_time = (datetime.now() - timedelta(minutes=30)).isoformat()
        
        response = await asyncio.to_thread(
            supabase.table('transcriptions')
            .select("task_id")
            .eq('status', 'pending')
            .lt('created_at', cutoff_time)
            .execute
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
        raise HTTPException(status_code=500, detail="Failed to cleanup stuck tasks")

# ===============================
# ACCOUNT LINKING ENDPOINTS

@app.post("/api/link-sms-account", response_model=AccountLinkResponse, tags=["SMS Integration"])
async def link_sms_account(request: Request):
    """Create phone-based auth account and link SMS user's transcription history"""
    try:
        body = await request.json()
        phone = body.get('phone')
        
        if not phone:
            raise HTTPException(status_code=400, detail="Phone number is required")
            
        # Normalize phone number
        phone = phone.replace('+', '').replace('-', '').replace(' ', '').replace('(', '').replace(')', '')
        if len(phone) == 10:
            phone = f"+1{phone}"
        elif len(phone) == 11 and phone.startswith('1'):
            phone = f"+{phone}"
        elif not phone.startswith('+'):
            phone = f"+{phone}"
            
        logger.info(f"Creating phone-based auth account for phone {phone} (phone-only auth)")
        
        # Check if phone already has auth account via SMS users table
        sms_user_response = await asyncio.to_thread(
            supabase.table('sms_users')
                    .select('auth_user_id')
                    .eq('phone_number', phone)
                    .single,
        )
        
        if sms_user_response.data and sms_user_response.data.get('auth_user_id'):
            logger.warning(f"Phone {phone} already has auth account")
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "Phone number already registered"}
            )
        
        # Check if phone has transcriptions to link
        stats_response = await asyncio.to_thread(
            supabase.rpc,
            'get_sms_user_stats',
            {'p_phone_number': phone}
        )
        
        if not stats_response.data or stats_response.data[0]['total_transcriptions'] == 0:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "No transcription history found for this phone number"}
            )
        
        transcription_count = stats_response.data[0]['total_transcriptions']
        
        # Create Supabase auth user with phone only
        try:
            auth_response = await asyncio.to_thread(
                supabase.auth.admin.create_user,
                {
                    "phone": phone,
                    "phone_confirm": True,
                    "user_metadata": {
                        "linked_from_sms": True,
                        "transcription_count": transcription_count,
                        "auth_type": "phone_only"
                    }
                }
            )
            
            if not auth_response.user:
                raise Exception("Failed to create auth user")
                
            auth_user_id = auth_response.user.id
            logger.info(f"Created phone-based auth user {auth_user_id} for phone {phone}")
            
        except Exception as e:
            logger.error(f"Failed to create auth user: {str(e)}")
            return JSONResponse(
                status_code=500,
                content={"success": False, "error": f"Failed to create account: {str(e)}"}
            )
        
        # Link transcriptions using database function
        try:
            link_response = await asyncio.to_thread(
                supabase.rpc,
                'link_sms_user_to_auth',
                {
                    'p_phone_number': phone,
                    'p_auth_user_id': auth_user_id
                }
            )
            
            linked_count = link_response.data[0]['linked_transcriptions'] if link_response.data else 0
            
            logger.info(f"Successfully linked {linked_count} transcriptions for phone {phone} to user {auth_user_id}")
            
            return JSONResponse(
                content={
                    "success": True,
                    "linked_transcriptions": linked_count,
                    "auth_user_id": auth_user_id,
                    "phone": phone,
                    "message": f"Successfully created phone-based account and linked {linked_count} transcriptions"
                }
            )
            
        except Exception as e:
            logger.error(f"Failed to link transcriptions: {str(e)}")
            # Clean up created auth user if linking failed
            try:
                await asyncio.to_thread(supabase.auth.admin.delete_user, auth_user_id)
            except:
                pass
            return JSONResponse(
                status_code=500,
                content={"success": False, "error": f"Failed to link transcriptions: {str(e)}"}
            )
        
    except Exception as e:
        logger.error(f"Error in link_sms_account: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# ===============================
# SMS ENDPOINTS
# ===============================

@app.post("/api/sms/inbound", tags=["SMS Integration"])
async def handle_inbound_sms(
    background_tasks: BackgroundTasks,
    From: str = Form(...),
    Body: str = Form(...),
    MessageSid: str = Form(None),
    To: str = Form(None)
):
    """Handle incoming SMS from Twilio webhook"""
    try:
        logger.info(f"Received SMS from {From}: {Body[:50]}...")
        
        # Log the message to user_messages table
        command = None
        if Body.startswith('/'):
            command = Body.split()[0].lower()
        
        await asyncio.to_thread(
            supabase.table('user_messages')
                    .insert({
                        'from_phone': From,
                        'message_body': Body,
                        'command': command,
                        'response_sent': False
                    })
                    .execute
        )
        
        # Process the SMS and get TwiML response
        twiml_response = await sms.SMSHandler.process_inbound_sms(From, Body)
        
        # If this is a video URL, create transcript job and queue processing
        if sms.SMSHandler.is_video_url(Body):
            video_url = sms.SMSHandler.extract_video_url(Body)
            if video_url:
                # Create transcript job entry
                job_response = await asyncio.to_thread(
                    supabase.table('transcript_jobs')
                            .insert({
                                'from_phone': From,
                                'video_url': video_url,
                                'status': 'queued',
                                'message_sid': MessageSid
                            })
                            .execute()
                )
                
                if job_response.data:
                    job_id = job_response.data[0]['id']
                    
                    # Create transcription task
                    task = await init_task(video_url, user_id=None, user_phone=From)
                    task_id = task['task_id']
                    
                    # Link the job to the transcription
                    await asyncio.to_thread(
                        supabase.table('transcript_jobs')
                                .update({'transcript_id': task_id})
                                .eq('id', job_id)
                                .execute()
                    )
                    
                    # Store user phone number for notifications
                    await asyncio.to_thread(
                        supabase.table('transcriptions')
                                .update({'user_phone': From})
                                .eq('task_id', task_id)
                                .execute()
                    )
                    
                    # Queue background processing
                    background_tasks.add_task(
                        process_transcription_with_sms_notification,
                        task_id,
                        video_url,
                        From,
                        job_id
                    )
                    logger.info(f"Queued transcription task {task_id} for SMS user {From}")
        
        # Mark message as responded
        await asyncio.to_thread(
            supabase.table('user_messages')
                    .update({'response_sent': True})
                    .eq('from_phone', From)
                    .eq('message_body', Body)
                    .execute
        )
        
        # Return TwiML response
        return Response(content=twiml_response, media_type="application/xml")
        
    except Exception as e:
        logger.error(f"Error handling inbound SMS: {str(e)}", exc_info=True)
        # Return error TwiML
        error_response = sms.SMSHandler.create_twiml_response(
            "🚨 Oops! Something went wrong. Please try again or contact support."
        )
        return Response(content=error_response, media_type="application/xml")

@app.post("/api/sms/status", tags=["SMS Integration"])
async def handle_sms_status(
    request: Request,
    MessageSid: str = Form(...),
    MessageStatus: str = Form(...),
    To: str = Form(None),
    From: str = Form(None)
):
    """Handle SMS delivery status updates from Twilio"""
    try:
        logger.info(f"SMS status update - SID: {MessageSid}, Status: {MessageStatus}, To: {To}")
        
        # You can store these status updates in your database for analytics
        # For now, just log them
        
        return {"status": "received"}
        
    except Exception as e:
        logger.error(f"Error handling SMS status: {str(e)}", exc_info=True)
        return {"error": "Failed to process status update"}

@app.post("/api/sms/send", response_model=SMSResponse, tags=["SMS Integration"])
async def send_sms(
    request: Request,
    api_key: str = Depends(verify_api_key)
):
    """Send SMS message (for testing or manual sends)"""
    try:
        body = await request.json()
        to = body.get("to")
        message = body.get("message")
        
        if not to or not message:
            raise HTTPException(status_code=400, detail="Both 'to' and 'message' are required")
        
        success = await sms.SMSHandler.send_sms(to, message)
        
        if success:
            return {"status": "sent", "to": to}
        else:
            raise HTTPException(status_code=500, detail="Failed to send SMS")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending SMS: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to send SMS")

@app.post("/api/sms/summary", tags=["SMS Integration"])
async def generate_sms_summary(request: Request):
    """Generate AI summary of user's latest transcript for SMS"""
    try:
        body = await request.json()
        phone = body.get("phone")
        
        if not phone:
            raise HTTPException(status_code=400, detail="Phone number is required")
        
        # Use the SMS handler to generate summary
        summary_result = await sms.SMSHandler.handle_summary_command(phone)
        
        return {"summary": summary_result}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating SMS summary: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate summary")

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
                    .execute
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
                
                success_message = f"✅ Transcript ready!\n\n📄 {title}\n\n{preview}\n\n🔗 View full: {public_link}\n\n💬 Reply /summary for AI summary or /vault for history!"
                
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
            }).execute
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
                    .execute
        )
        
        view_count = len(response.data) if response.data else 1
        
        # Simple trending score (lower = more trending)
        # Based on views in last 24 hours
        recent_response = await asyncio.to_thread(
            supabase.table('referral_events')
                    .select('id')
                    .eq('task_id', task_id)
                    .gte('created_at', (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat())
                    .execute
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

@app.get("/api/analytics/sms", tags=["SMS Integration"])
async def sms_analytics(api_key: str = Depends(verify_api_key)):
    """Get SMS usage analytics"""
    try:
        # Get transcript jobs stats
        jobs_response = await asyncio.to_thread(
            supabase.table('transcript_jobs')
                    .select("status, created_at, from_phone")
                    .execute
        )
        
        # Get user messages stats
        messages_response = await asyncio.to_thread(
            supabase.table('user_messages')
                    .select("command, created_at, from_phone")
                    .execute
        )
        
        jobs_data = jobs_response.data if jobs_response.data else []
        messages_data = messages_response.data if messages_response.data else []
        
        # Calculate stats
        total_jobs = len(jobs_data)
        completed_jobs = len([j for j in jobs_data if j['status'] == 'completed'])
        failed_jobs = len([j for j in jobs_data if j['status'] == 'failed'])
        unique_users = len(set([j['from_phone'] for j in jobs_data]))
        
        command_stats = {}
        for msg in messages_data:
            cmd = msg.get('command', 'unknown')
            command_stats[cmd] = command_stats.get(cmd, 0) + 1
        
        return {
            "jobs": {
                "total": total_jobs,
                "completed": completed_jobs,
                "failed": failed_jobs,
                "success_rate": round((completed_jobs / total_jobs * 100) if total_jobs > 0 else 0, 2)
            },
            "users": {
                "unique_users": unique_users,
                "total_messages": len(messages_data)
            },
            "commands": command_stats
        }
        
    except Exception as e:
        logger.error(f"Error getting SMS analytics: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error retrieving analytics")

# TikTok API Adapter Endpoints
@app.get("/api/public/tiktok/video-info", tags=["TikTok API"])
async def get_tiktok_video_info(video_url: str = Query(..., description="TikTok video URL")):
    """
    Get TikTok video information using multiple API adapters with automatic failover.
    
    This endpoint demonstrates the API adapter pattern for handling rate limits
    and API failures by automatically switching between different TikTok APIs.
    """
    if not video_url:
        raise HTTPException(status_code=400, detail="video_url parameter is required")
    
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
        raise HTTPException(status_code=500, detail=str(e))

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
        raise HTTPException(status_code=500, detail=str(e))

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
        raise HTTPException(status_code=500, detail=str(e))

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
        raise HTTPException(status_code=500, detail=f"Webhook processing failed: {str(e)}")

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
                supabase.table('transcript_jobs')
                        .update({'transcript_id': task_id})
                        .eq('id', job_id)
                        .execute()
            )
            
            # Store user phone number for notifications
            await asyncio.to_thread(
                supabase.table('transcriptions')
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
            supabase.table('public_transcriptions')
                    .select("*")
                    .eq('task_id', task_id)
                    .maybe_single()
                    .execute
        )
        
        if not response.data:
            raise HTTPException(status_code=404, detail="Transcript not found")
        
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
        title = task.get('title', 'TikTok Transcript')
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

if __name__ == "__main__":
    # Get port from environment or use default
    port = int(os.environ.get("PORT", 8000))
    
    # Run the app
    uvicorn.run(app, host="0.0.0.0", port=port) 