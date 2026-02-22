"""
Web Chat API endpoints for continuing SMS conversations in the browser.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Path, Query

from ..core.errors import (
    ApiError,
    INTERNAL_ERROR,
    SERVICE_UNAVAILABLE,
    TASK_NOT_FOUND,
    TRANSCRIPT_NOT_READY,
    VALIDATION_ERROR,
)
from ..database import supabase
from .. import sms
from ..models.schemas import (
    ChatMessage,
    ChatThreadResponse,
    ChatThreadListResponse,
    WebChatRequest,
    WebChatResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Web Chat"])


def mask_phone(phone: str) -> str:
    """Mask phone number for privacy, showing only last 4 digits."""
    if not phone or len(phone) < 4:
        return "****"
    return f"***{phone[-4:]}"


@router.get("/api/chat/thread/{thread_id}", response_model=ChatThreadResponse)
async def get_chat_thread(
    thread_id: str = Path(..., description="Thread UUID"),
    include_messages: bool = Query(True, description="Include message history"),
    limit: int = Query(50, ge=1, le=200, description="Max messages to return"),
):
    """
    Fetch a chat thread with its message history.

    This endpoint allows web users to view their SMS conversation
    and continue it in the browser.
    """
    if supabase is None:
        raise ApiError(503, SERVICE_UNAVAILABLE, "Database connection not available")

    try:
        # Fetch thread
        thread_response = supabase.table('conversation_threads') \
            .select('id, task_id, user_phone, status, message_count, summary, created_at, last_active') \
            .eq('id', thread_id) \
            .maybe_single() \
            .execute()

        if not thread_response.data:
            raise ApiError(404, TASK_NOT_FOUND, "Thread not found")

        thread = thread_response.data

        # Fetch associated transcript info
        transcript_title = None
        transcript_quote = None
        if thread.get('task_id'):
            transcript_response = supabase.table('transcriptions') \
                .select('title, quote') \
                .eq('task_id', thread['task_id']) \
                .maybe_single() \
                .execute()
            if transcript_response.data:
                transcript_title = transcript_response.data.get('title')
                transcript_quote = transcript_response.data.get('quote')

        # Fetch messages if requested
        messages = []
        if include_messages:
            messages_response = supabase.table('conversation_messages') \
                .select('id, role, content, created_at') \
                .eq('thread_id', thread_id) \
                .order('created_at', desc=False) \
                .limit(limit) \
                .execute()

            if messages_response.data:
                messages = [
                    ChatMessage(
                        id=msg['id'],
                        role=msg['role'],
                        content=msg['content'],
                        created_at=msg['created_at'],
                    )
                    for msg in messages_response.data
                ]

        return ChatThreadResponse(
            thread_id=thread['id'],
            task_id=thread['task_id'],
            user_phone=mask_phone(thread.get('user_phone', '')),
            status=thread.get('status', 'active'),
            message_count=thread.get('message_count', 0),
            summary=thread.get('summary'),
            messages=messages,
            transcript_title=transcript_title,
            transcript_quote=transcript_quote,
            created_at=thread['created_at'],
            last_active=thread['last_active'],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching chat thread {thread_id}: {str(e)}", exc_info=True)
        raise ApiError(500, INTERNAL_ERROR, "Failed to fetch thread")


@router.post("/api/chat/thread/{thread_id}/message", response_model=WebChatResponse)
async def post_chat_message(
    request: WebChatRequest,
    thread_id: str = Path(..., description="Thread UUID"),
):
    """
    Continue a conversation by posting a new message.

    This endpoint allows web users to send follow-up questions
    about a transcript, continuing where SMS left off.
    """
    if supabase is None:
        raise ApiError(503, SERVICE_UNAVAILABLE, "Database connection not available")

    message = request.message.strip()
    if not message:
        raise ApiError(400, VALIDATION_ERROR, "Message is required")

    try:
        # Fetch thread
        thread_response = supabase.table('conversation_threads') \
            .select('id, task_id, user_phone, status, summary, message_count') \
            .eq('id', thread_id) \
            .maybe_single() \
            .execute()

        if not thread_response.data:
            raise ApiError(404, TASK_NOT_FOUND, "Thread not found")

        thread = thread_response.data

        if thread.get('status') == 'closed':
            raise ApiError(400, VALIDATION_ERROR, "This conversation has been closed. Start a new one via SMS.")

        task_id = thread['task_id']
        conversation_summary = thread.get('summary') or ""

        # Fetch transcript
        task_response = supabase.table('transcriptions').select(
            'status, transcript, title, description, quote, tldr, error, uploader, channel, duration, platform, view_count, like_count, category, auto_tags'
        ).eq('task_id', task_id).maybe_single().execute()

        if not task_response.data:
            raise ApiError(404, TASK_NOT_FOUND, "Associated transcript not found")

        task = task_response.data
        if task.get('status') != 'completed':
            raise ApiError(400, TRANSCRIPT_NOT_READY, f"Transcript not ready. Status: {task.get('status')}")

        transcript_text = task.get('transcript') or ''
        if not transcript_text:
            raise ApiError(400, TRANSCRIPT_NOT_READY, "Transcript content not available")

        # Save user message
        now = datetime.now(timezone.utc).isoformat()
        user_msg_response = supabase.table('conversation_messages').insert({
            'thread_id': thread_id,
            'role': 'user',
            'content': message,
            'created_at': now,
        }).execute()

        user_msg_id = user_msg_response.data[0]['id'] if user_msg_response.data else None

        # Load recent message history for context
        messages_response = supabase.table('conversation_messages') \
            .select('role, content') \
            .eq('thread_id', thread_id) \
            .order('created_at', desc=True) \
            .limit(20) \
            .execute()

        message_history = []
        if messages_response.data:
            messages_sorted = list(reversed(messages_response.data))
            message_history = [
                {'role': msg.get('role'), 'content': msg.get('content')}
                for msg in messages_sorted
                if msg.get('content')
            ]

        # Parse TLDR
        tldr_list = None
        if task.get('tldr'):
            try:
                if isinstance(task['tldr'], str):
                    tldr_list = json.loads(task['tldr'])
                elif isinstance(task['tldr'], list):
                    tldr_list = task['tldr']
            except (json.JSONDecodeError, TypeError):
                tldr_list = None

        # Generate answer (web allows longer responses)
        max_chars = request.max_chars or 600
        answer = await sms.SMSHandler.generate_answer(
            question=message,
            transcript_text=transcript_text,
            title=task.get('title') or '',
            description=task.get('description') or '',
            quote=task.get('quote') or '',
            tldr_list=tldr_list,
            max_chars=max_chars,
            conversation_summary=conversation_summary,
            message_history=message_history,
            metadata={k: task.get(k) for k in ('uploader', 'channel', 'duration', 'platform', 'view_count', 'like_count', 'category', 'auto_tags') if task.get(k)},
        )

        if not answer:
            answer = "I couldn't find an answer to that in this transcript."

        # Save assistant message
        assistant_now = datetime.now(timezone.utc).isoformat()
        assistant_msg_response = supabase.table('conversation_messages').insert({
            'thread_id': thread_id,
            'role': 'assistant',
            'content': answer,
            'created_at': assistant_now,
        }).execute()

        assistant_msg_id = assistant_msg_response.data[0]['id'] if assistant_msg_response.data else None

        # Update thread summary
        summary_messages = message_history + [{'role': 'assistant', 'content': answer}]
        new_summary = await sms.SMSHandler.generate_chat_summary(
            conversation_summary,
            summary_messages[-20:],
            max_chars=600,
        )

        supabase.table('conversation_threads').update({
            'summary': new_summary,
            'message_count': (thread.get('message_count') or 0) + 2,
            'last_active': assistant_now,
            'updated_at': assistant_now,
        }).eq('id', thread_id).execute()

        return WebChatResponse(
            thread_id=thread_id,
            task_id=task_id,
            user_message=ChatMessage(
                id=user_msg_id or "unknown",
                role="user",
                content=message,
                created_at=now,
            ),
            assistant_message=ChatMessage(
                id=assistant_msg_id or "unknown",
                role="assistant",
                content=answer,
                created_at=assistant_now,
            ),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error posting message to thread {thread_id}: {str(e)}", exc_info=True)
        raise ApiError(500, INTERNAL_ERROR, "Failed to send message")


@router.get("/api/chat/task/{task_id}", response_model=ChatThreadResponse)
async def get_or_create_thread_by_task(
    task_id: str = Path(..., description="Transcript task UUID"),
    include_messages: bool = Query(True, description="Include message history"),
    limit: int = Query(50, ge=1, le=200, description="Max messages to return"),
):
    """
    Get or create a chat thread for a specific transcript.

    This endpoint allows web users to start/continue a conversation
    about a transcript using just the task_id from the SMS share link.
    If no thread exists, one will be created.
    """
    if supabase is None:
        raise ApiError(503, SERVICE_UNAVAILABLE, "Database connection not available")

    try:
        # First verify the transcript exists
        transcript_response = supabase.table('transcriptions') \
            .select('task_id, title, quote, user_phone, status') \
            .eq('task_id', task_id) \
            .maybe_single() \
            .execute()

        if not transcript_response.data:
            raise ApiError(404, TASK_NOT_FOUND, "Transcript not found")

        transcript = transcript_response.data
        if transcript.get('status') != 'completed':
            raise ApiError(400, TRANSCRIPT_NOT_READY, f"Transcript not ready. Status: {transcript.get('status')}")

        user_phone = transcript.get('user_phone')
        transcript_title = transcript.get('title')
        transcript_quote = transcript.get('quote')

        # Look for existing active thread for this task
        thread_response = supabase.table('conversation_threads') \
            .select('id, task_id, user_phone, status, message_count, summary, created_at, last_active') \
            .eq('task_id', task_id) \
            .eq('status', 'active') \
            .order('last_active', desc=True) \
            .limit(1) \
            .execute()

        thread = thread_response.data[0] if thread_response.data else None

        # Create new thread if none exists
        if not thread:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).isoformat()

            thread_insert = supabase.table('conversation_threads').insert({
                'task_id': task_id,
                'user_phone': user_phone or 'web_user',
                'summary': None,
                'message_count': 0,
                'status': 'active',
                'last_active': now,
                'created_at': now,
                'updated_at': now,
            }).execute()

            if thread_insert.data:
                thread = thread_insert.data[0]
            else:
                raise ApiError(500, INTERNAL_ERROR, "Failed to create conversation thread")

        # Fetch messages if requested
        messages = []
        if include_messages and thread:
            messages_response = supabase.table('conversation_messages') \
                .select('id, role, content, created_at') \
                .eq('thread_id', thread['id']) \
                .order('created_at', desc=False) \
                .limit(limit) \
                .execute()

            if messages_response.data:
                messages = [
                    ChatMessage(
                        id=msg['id'],
                        role=msg['role'],
                        content=msg['content'],
                        created_at=msg['created_at'],
                    )
                    for msg in messages_response.data
                ]

        return ChatThreadResponse(
            thread_id=thread['id'],
            task_id=thread['task_id'],
            user_phone=mask_phone(thread.get('user_phone', '')),
            status=thread.get('status', 'active'),
            message_count=thread.get('message_count', 0),
            summary=thread.get('summary'),
            messages=messages,
            transcript_title=transcript_title,
            transcript_quote=transcript_quote,
            created_at=thread['created_at'],
            last_active=thread['last_active'],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting/creating thread for task {task_id}: {str(e)}", exc_info=True)
        raise ApiError(500, INTERNAL_ERROR, "Failed to get or create thread")


@router.get("/api/chat/threads", response_model=ChatThreadListResponse)
async def list_chat_threads(
    phone: Optional[str] = Query(None, description="Filter by phone number"),
    task_id: Optional[str] = Query(None, description="Filter by transcript task_id"),
    status: Optional[str] = Query(None, description="Filter by status: 'active' or 'closed'"),
    limit: int = Query(20, ge=1, le=100, description="Max threads to return"),
):
    """
    List chat threads, optionally filtered by phone or task_id.

    This can be used to find a user's conversation threads
    or get all threads for a specific transcript.
    """
    if supabase is None:
        raise ApiError(503, SERVICE_UNAVAILABLE, "Database connection not available")

    try:
        query = supabase.table('conversation_threads') \
            .select('id, task_id, user_phone, status, message_count, summary, created_at, last_active')

        if phone:
            query = query.eq('user_phone', phone)
        if task_id:
            query = query.eq('task_id', task_id)
        if status:
            query = query.eq('status', status)

        query = query.order('last_active', desc=True).limit(limit)

        response = query.execute()
        threads_data = response.data or []

        threads = []
        for t in threads_data:
            threads.append(ChatThreadResponse(
                thread_id=t['id'],
                task_id=t['task_id'],
                user_phone=mask_phone(t.get('user_phone', '')),
                status=t.get('status', 'active'),
                message_count=t.get('message_count', 0),
                summary=t.get('summary'),
                messages=[],  # Don't include messages in list view
                transcript_title=None,
                transcript_quote=None,
                created_at=t['created_at'],
                last_active=t['last_active'],
            ))

        return ChatThreadListResponse(
            threads=threads,
            total=len(threads),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing chat threads: {str(e)}", exc_info=True)
        raise ApiError(500, INTERNAL_ERROR, "Failed to list threads")
