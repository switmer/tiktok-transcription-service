import asyncio
import glob
import json
import logging
import os
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse, Response
from PIL import Image, ImageDraw, ImageFont

from ..app import (
    create_square_thumbnail,
    init_task,
    is_youtube_url,
    process_transcription_task,
)
from ..core.paths import DOWNLOADS_DIR, static_dir
from ..database import supabase
from .. import sms, transcriber
from ..models.schemas import (
    SearchHit,
    SearchResponse,
    TaskListResponse,
    TranscriptionRequest,
    TranscriptionResponse,
    TranscriptChatRequest,
    TranscriptChatResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Public Transcription"])


@router.post("/api/public/transcribe", response_model=TranscriptionResponse)
async def transcribe(
    request: TranscriptionRequest,
    background_tasks: BackgroundTasks,
    user_id: Optional[str] = None,
) -> TranscriptionResponse:
    """Start a new transcription task or return existing one."""
    try:
        logger.info(f"Transcribe request: url={request.url}, user_phone={request.user_phone}")
        task = await init_task(request.url, user_id, request.user_phone)
        task_id = task['task_id']

        response = await asyncio.to_thread(
            lambda: supabase.table('transcriptions')
                            .select("*")
                            .eq('task_id', str(task_id))
                            .single()
                            .execute()
        )

        if not response.data:
            logger.error(f"Failed to retrieve task details immediately after creation for task_id: {task_id}")
            raise HTTPException(status_code=500, detail="Failed to retrieve task details")

        task_data = response.data

        if task_data['status'] != 'completed':
            if is_youtube_url(request.url):
                logger.info(f"Attempting instant YouTube transcription for task {task_id}")

                try:
                    youtube_result = transcriber.download_youtube_rapidapi(request.url)

                    if youtube_result:
                        await asyncio.to_thread(
                            supabase.table('transcriptions')
                                    .update({
                                        'status': 'completed',
                                        'video_id': youtube_result['video_id'],
                                        'title': youtube_result['title'],
                                        'description': youtube_result.get('description'),
                                        'transcript': youtube_result['transcript'],
                                        'platform': 'youtube',
                                        'category': 'youtube-transcription',
                                        'tags': ['sms-inbound', 'youtube'] if request.user_phone else ['youtube'],
                                        'thumbnail_url': youtube_result.get('thumbnail_url'),
                                        'duration': youtube_result.get('duration'),
                                        'uploader': youtube_result.get('uploader'),
                                        'channel': youtube_result.get('channel'),
                                        'raw_metadata': youtube_result.get('metadata'),
                                    })
                                    .eq('task_id', task_id)
                                    .execute()
                        )

                        task_data['status'] = 'completed'
                        task_data['video_id'] = youtube_result['video_id']
                        task_data['title'] = youtube_result['title']
                        task_data['description'] = youtube_result.get('description')
                        task_data['platform'] = 'youtube'

                        logger.info(f"YouTube instant transcription completed for task {task_id}")
                    else:
                        logger.warning(
                            f"YouTube instant transcription failed for {task_id}, falling back to background processing"
                        )
                        background_tasks.add_task(
                            process_transcription_task,
                            task_id,
                            request.url,
                            request.callback_url,
                            request.proxy,
                        )
                        logger.info(f"Task {task_id} queued for background processing (YouTube fallback)")

                except Exception as e:
                    logger.error(f"YouTube instant transcription error for {task_id}: {str(e)}")
                    background_tasks.add_task(
                        process_transcription_task,
                        task_id,
                        request.url,
                        request.callback_url,
                        request.proxy,
                    )
                    logger.info(f"Task {task_id} queued for background processing (YouTube error fallback)")
            else:
                background_tasks.add_task(
                    process_transcription_task,
                    task_id,
                    request.url,
                    request.callback_url,
                    request.proxy,
                )
                logger.info(f"Task {task_id} queued for background processing URL: {request.url}")
        else:
            logger.info(f"Returning existing transcription for URL: {request.url}")

        return TranscriptionResponse(
            task_id=task_id,
            status=task_data['status'],
            video_id=task_data.get('video_id'),
            title=task_data.get('title'),
            description=task_data.get('description'),
            created_at=task_data['created_at'],
            error=task_data.get('error'),
            thumbnail=task_data.get('thumbnail_url'),
            thumbnail_url=task_data.get('thumbnail_url'),
            thumbnail_local_path=task_data.get('thumbnail_local_path'),
        )

    except Exception as e:
        logger.error(f"Error in transcribe endpoint: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to start transcription")


@router.get("/api/public/tasks/{task_id}")
async def public_get_task(task_id: str):
    """Get task status without requiring API key."""
    if supabase is None:
        logger.error(f"Cannot get task {task_id}: Supabase client not initialized.")
        raise HTTPException(status_code=500, detail="Database connection not available")

    try:
        response = await asyncio.to_thread(
            lambda: supabase.table('transcriptions')
                            .select("task_id, status, video_id, title, description, created_at, error, thumbnail_url, thumbnail_local_path, video_url, url, like_count, comment_count, repost_count, view_count, duration, platform, uploader, channel, metadata, raw_metadata")
                            .eq('task_id', task_id)
                            .maybe_single()
                            .execute()
        )

        if hasattr(response, 'error') and response.error:
            logger.error(f"Failed to get task {task_id} from Supabase: {response.error}")
            raise HTTPException(status_code=500, detail="Database error retrieving task")

        if not response.data:
            raise HTTPException(status_code=404, detail="Task not found")

        task_data = response.data

        raw_meta = task_data.get('raw_metadata') if task_data.get('raw_metadata') else {}
        raw_data = raw_meta.get('data', {}) if isinstance(raw_meta, dict) else {}

        original_tiktok_url = raw_meta.get('url') or task_data.get('url') or None

        if not original_tiktok_url:
            video_id = task_data.get('video_id') or raw_data.get('id')
            if video_id:
                uploader = task_data.get('uploader') or raw_data.get('author', {}).get('unique_id')
                if task_data.get('platform') == 'tiktok':
                    original_tiktok_url = (
                        f"https://www.tiktok.com/@{uploader}/video/{video_id}"
                        if uploader else f"https://www.tiktok.com/video/{video_id}"
                    )
                elif task_data.get('platform') == 'youtube':
                    original_tiktok_url = f"https://www.youtube.com/watch?v={video_id}"

        def get_with_fallback(key, raw_key=None):
            if raw_key and raw_data.get(raw_key):
                return raw_data.get(raw_key)
            return task_data.get(key)

        return TranscriptionResponse(
            task_id=task_data['task_id'],
            status=task_data['status'],
            video_id=task_data.get('video_id'),
            title=get_with_fallback('title', 'title'),
            description=task_data.get('description') or raw_data.get('description'),
            created_at=task_data['created_at'],
            error=task_data.get('error'),
            thumbnail=task_data.get('thumbnail_url'),
            thumbnail_url=task_data.get('thumbnail_url'),
            thumbnail_local_path=task_data.get('thumbnail_local_path'),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching task {task_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Server error retrieving task")


@router.get("/api/public/transcript/{task_id}")
async def public_get_transcript(task_id: str, format: Optional[str] = None):
    """Get transcript content for a task (public)"""
    if supabase is None:
        logger.error(f"Cannot get transcript {task_id}: Supabase client not initialized.")
        raise HTTPException(status_code=500, detail="Database connection not available")

    try:
        response = await asyncio.to_thread(
            lambda: supabase.table('transcriptions')
                            .select("task_id, status, transcript, error")
                            .eq('task_id', task_id)
                            .maybe_single()
                            .execute()
        )

        if not response.data:
            raise HTTPException(status_code=404, detail="Task not found")

        task = response.data
        if task.get('status') != 'completed':
            raise HTTPException(status_code=400, detail="Transcript not ready")

        transcript_text = task.get('transcript') or ''
        if format == "plain":
            return Response(content=transcript_text, media_type="text/plain")
        if format == "json":
            return {"task_id": task_id, "transcript": transcript_text}
        return {"task_id": task_id, "transcript": transcript_text}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving transcript {task_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Server error retrieving transcript")


@router.post(
    "/api/public/transcript/{task_id}/chat",
    response_model=TranscriptChatResponse,
)
async def public_chat_transcript(task_id: str, payload: TranscriptChatRequest):
    if supabase is None:
        logger.error("Cannot chat with transcript: Supabase client not initialized.")
        raise HTTPException(status_code=500, detail="Database connection not available")

    try:
        response = await asyncio.to_thread(
            lambda: supabase.table('transcriptions')
                            .select("task_id, status, transcript, title, description, quote, tldr, error")
                            .eq('task_id', task_id)
                            .maybe_single()
                            .execute()
        )

        if not response.data:
            raise HTTPException(status_code=404, detail="Task not found")

        task = response.data
        if task.get('status') != 'completed':
            raise HTTPException(status_code=400, detail="Transcript not ready")

        tldr_list = None
        if task.get('tldr'):
            try:
                if isinstance(task['tldr'], str):
                    tldr_list = json.loads(task['tldr'])
                elif isinstance(task['tldr'], list):
                    tldr_list = task['tldr']
            except (json.JSONDecodeError, TypeError):
                tldr_list = None

        answer = await sms.SMSHandler.generate_answer(
            question=payload.message,
            transcript_text=task.get('transcript') or '',
            title=task.get('title') or '',
            description=task.get('description') or '',
            quote=task.get('quote') or '',
            tldr_list=tldr_list,
            max_chars=payload.max_chars or 360,
        )

        return TranscriptChatResponse(task_id=task_id, answer=answer)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating transcript chat response: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate answer")


@router.get("/api/public/tasks", response_model=TaskListResponse)
async def public_list_tasks():
    """List completed public tasks for discovery/browse."""
    if supabase is None:
        logger.error("Cannot list public tasks: Supabase client not initialized.")
        raise HTTPException(status_code=500, detail="Database connection not available")

    response = await asyncio.to_thread(
        lambda: supabase.table('transcriptions')
                        .select("task_id, status, video_id, title, description, created_at, error, thumbnail_url, thumbnail_local_path")
                        .eq('status', 'completed')
                        .order('created_at', desc=True)
                        .limit(50)
                        .execute()
    )

    tasks_list = []
    if response.data:
        for task_data in response.data:
            tasks_list.append(
                TranscriptionResponse(
                    task_id=task_data['task_id'],
                    status=task_data['status'],
                    video_id=task_data.get('video_id'),
                    title=task_data.get('title'),
                    description=task_data.get('description'),
                    created_at=task_data['created_at'],
                    error=task_data.get('error'),
                    thumbnail=task_data.get('thumbnail_url'),
                    thumbnail_url=task_data.get('thumbnail_url'),
                    thumbnail_local_path=task_data.get('thumbnail_local_path'),
                )
            )

    return TaskListResponse(tasks=tasks_list)


@router.get("/api/public/search", response_model=SearchResponse)
async def public_search_transcriptions(
    q: str = Query(..., min_length=2, max_length=120, description="Search query"),
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    only_public: bool = Query(True),
    only_completed: bool = Query(True),
):
    if supabase is None:
        logger.error("Cannot search transcriptions: Supabase client not initialized.")
        raise HTTPException(status_code=500, detail="Database connection not available")

    query = (q or "").strip()
    if len(query) < 2:
        return SearchResponse(query=query, results=[], limit=max(0, limit), offset=max(0, offset))

    try:
        response = await asyncio.to_thread(
            lambda: supabase.rpc(
                "search_transcriptions",
                {
                    "query": query,
                    "only_public": only_public,
                    "only_completed": only_completed,
                    "limit_results": limit,
                    "offset_results": offset,
                },
            ).execute()
        )

        if hasattr(response, "error") and response.error:
            logger.error(f"Search RPC error: {response.error}")
            raise HTTPException(status_code=500, detail="Search failed")

        results: List[SearchHit] = []
        for row in (response.data or []):
            results.append(
                SearchHit(
                    task_id=str(row.get("task_id")),
                    title=row.get("title"),
                    updated_at=row.get("updated_at"),
                    rank=row.get("rank"),
                    source=row.get("source"),
                )
            )

        return SearchResponse(query=query, results=results, limit=limit, offset=offset)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Search exception: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Server error searching transcriptions")


@router.get("/api/public/thumbnail/{task_id}")
async def public_get_thumbnail(task_id: str):
    """Get the thumbnail image for a task without API key"""
    if supabase is None:
        logger.error(f"Cannot get public thumbnail for {task_id}: Supabase client not initialized.")
        raise HTTPException(status_code=500, detail="Database connection not available")

    try:
        response = await asyncio.to_thread(
            supabase.table('transcriptions')
                    .select("task_id, status, error, thumbnail_url, thumbnail_local_path, supabase_thumbnail_url")
                    .eq('task_id', task_id)
                    .maybe_single()
                    .execute()
        )

        if hasattr(response, 'error') and response.error:
            logger.error(f"Database error fetching public thumbnail for {task_id}: {response.error}")
            raise HTTPException(status_code=500, detail="Database error retrieving task info")

        if not response.data:
            raise HTTPException(status_code=404, detail="Task not found")

        task = response.data

        if task["status"] == "failed":
            error_message = task.get("error", "Unknown error")
            raise HTTPException(status_code=400, detail=f"Transcription failed: {error_message}")

        if task["status"] != "completed":
            raise HTTPException(
                status_code=400,
                detail=f"Transcription not completed yet. Current status: {task['status']}",
            )

        if task.get("supabase_thumbnail_url"):
            logger.info(f"Redirecting to Supabase thumbnail URL: {task['supabase_thumbnail_url']}")
            return RedirectResponse(url=task["supabase_thumbnail_url"])

        if task.get("thumbnail_url"):
            logger.info(f"Redirecting to external thumbnail URL: {task['thumbnail_url']}")
            return RedirectResponse(url=task["thumbnail_url"])

        if task.get("thumbnail_local_path"):
            local_thumbnail_full_path = os.path.join(DOWNLOADS_DIR, task["thumbnail_local_path"])
            if os.path.exists(local_thumbnail_full_path):
                logger.info(f"Serving local thumbnail file: {local_thumbnail_full_path}")
                media_type = 'image/jpeg'
                if local_thumbnail_full_path.lower().endswith('.png'):
                    media_type = 'image/png'
                elif local_thumbnail_full_path.lower().endswith('.webp'):
                    media_type = 'image/webp'
                return FileResponse(local_thumbnail_full_path, media_type=media_type)
            logger.warning(
                f"Local thumbnail path found in task data ({task['thumbnail_local_path']}), but file does not exist."
            )
            try:
                supabase.table('transcriptions').update(
                    {"thumbnail_local_path": None}
                ).eq('task_id', task_id).execute()
                logger.info(f"Cleared invalid thumbnail_local_path for task {task_id}")
            except Exception as e:
                logger.error(f"Failed to clear thumbnail_local_path for {task_id}: {e}")

        output_dir = os.path.join(DOWNLOADS_DIR, task_id)
        thumbnail_path = None
        logger.info(f"(Fallback) Looking for thumbnail images in {output_dir}")
        for ext in ['.jpg', '.png', '.jpeg', '.webp']:
            files = glob.glob(os.path.join(output_dir, f"**/*{ext}"), recursive=True)
            if files:
                thumbnail_path = files[0]
                break

        if thumbnail_path:
            logger.info(f"(Fallback) Found local thumbnail file: {thumbnail_path}")
            media_type = 'image/jpeg'
            if thumbnail_path.lower().endswith('.png'):
                media_type = 'image/png'
            elif thumbnail_path.lower().endswith('.webp'):
                media_type = 'image/webp'
            return FileResponse(thumbnail_path, media_type=media_type)

        logger.warning(f"No thumbnail found for task {task_id}, using default")
        default_thumbnail = os.path.join(static_dir, "default_thumbnail.jpg")

        if not os.path.exists(default_thumbnail):
            try:
                img = Image.new('RGB', (640, 360), color=(53, 59, 72))
                draw = ImageDraw.Draw(img)
                text = "ScribeTok"
                font = ImageFont.load_default()
                text_width, text_height = draw.textsize(text, font=font)
                position = ((640 - text_width) // 2, (360 - text_height) // 2)
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


@router.get("/api/public/thumbnail_square/{task_id}")
async def public_get_square_thumbnail(task_id: str):
    """Get square thumbnail image for a task (optimized for iMessage/WhatsApp previews)"""
    if supabase is None:
        logger.error(f"Cannot get public square thumbnail for {task_id}: Supabase client not initialized.")
        raise HTTPException(status_code=500, detail="Database connection not available")

    try:
        response = await asyncio.to_thread(
            supabase.table('transcriptions')
                    .select("task_id, status, error, thumbnail_url, thumbnail_local_path, supabase_thumbnail_url")
                    .eq('task_id', task_id)
                    .maybe_single()
                    .execute()
        )

        if hasattr(response, 'error') and response.error:
            logger.error(f"Database error fetching public square thumbnail for {task_id}: {response.error}")
            raise HTTPException(status_code=500, detail="Database error retrieving task info")

        if not response.data:
            raise HTTPException(status_code=404, detail="Task not found")

        task = response.data

        if task["status"] == "failed":
            error_message = task.get("error", "Unknown error")
            raise HTTPException(status_code=400, detail=f"Transcription failed: {error_message}")

        if task["status"] != "completed":
            raise HTTPException(
                status_code=400,
                detail=f"Transcription not completed yet. Current status: {task['status']}",
            )

        if task.get("supabase_thumbnail_url"):
            logger.info(f"Redirecting to Supabase square thumbnail URL: {task['supabase_thumbnail_url']}")
            return RedirectResponse(url=task["supabase_thumbnail_url"])

        if task.get("thumbnail_url"):
            logger.info(f"Redirecting to external thumbnail URL: {task['thumbnail_url']}")
            return RedirectResponse(url=task["thumbnail_url"])

        if task.get("thumbnail_local_path"):
            local_thumbnail_full_path = os.path.join(DOWNLOADS_DIR, task["thumbnail_local_path"])
            if os.path.exists(local_thumbnail_full_path):
                square_thumbnail_path = os.path.join(DOWNLOADS_DIR, f"{task_id}_square.jpg")

                if not os.path.exists(square_thumbnail_path):
                    success = create_square_thumbnail(local_thumbnail_full_path, square_thumbnail_path)
                    if not success:
                        raise HTTPException(status_code=500, detail="Failed to create square thumbnail")

                return FileResponse(square_thumbnail_path, media_type="image/jpeg")

        logger.warning(f"No square thumbnail found for task {task_id}, using default")
        default_square_thumbnail = os.path.join(static_dir, "default_square_thumbnail.jpg")

        if not os.path.exists(default_square_thumbnail):
            try:
                img = Image.new('RGB', (1200, 1200), color=(53, 59, 72))
                draw = ImageDraw.Draw(img)
                text = "ScribeTok"
                font = ImageFont.load_default()
                text_width, text_height = draw.textsize(text, font=font)
                position = ((1200 - text_width) // 2, (1200 - text_height) // 2)
                draw.text(position, text, fill=(236, 240, 241), font=font)
                img.save(default_square_thumbnail)
                logger.info(f"Created default square thumbnail at {default_square_thumbnail}")
            except Exception as e:
                logger.error(f"Error creating default square thumbnail: {str(e)}")
                raise HTTPException(
                    status_code=404,
                    detail="Square thumbnail not found and could not create default",
                )

        return FileResponse(default_square_thumbnail, media_type="image/jpeg")

    except Exception as e:
        logger.error(f"Error fetching public square thumbnail for task {task_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Server error fetching square thumbnail")
