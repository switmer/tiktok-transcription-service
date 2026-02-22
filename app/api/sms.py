import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from ..core.auth import verify_api_key
from ..core.errors import (
    ApiError,
    INSUFFICIENT_CREDITS,
    INTERNAL_ERROR,
    SERVICE_UNAVAILABLE,
    TASK_NOT_FOUND,
    TRANSCRIPT_NOT_READY,
    VALIDATION_ERROR,
)
from ..database import supabase
from .. import sms
from ..app import init_task, process_transcription_with_sms_notification
from ..models.schemas import (
    AccountLinkResponse,
    SMSResponse,
    SmsChatRequest,
    SmsChatResponse,
    SmsChatResetRequest,
    SmsChatResetResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["SMS Integration"])


@router.post("/api/link-sms-account", response_model=AccountLinkResponse)
async def link_sms_account(request: Request):
    """Create phone-based auth account and link SMS user's transcription history"""
    try:
        body = await request.json()
        phone = body.get('phone')

        if not phone:
            raise ApiError(400, VALIDATION_ERROR, "Phone number is required")

        phone = phone.replace('+', '').replace('-', '').replace(' ', '').replace('(', '').replace(')', '')
        if len(phone) == 10:
            phone = f"+1{phone}"
        elif len(phone) == 11 and phone.startswith('1'):
            phone = f"+{phone}"
        elif not phone.startswith('+'):
            phone = f"+{phone}"

        logger.info(f"Creating phone-based auth account for phone {phone} (phone-only auth)")

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
                content={"success": False, "error": "Phone number already registered"},
            )

        stats_response = await asyncio.to_thread(
            supabase.rpc,
            'get_sms_user_stats',
            {'p_phone_number': phone},
        )

        if not stats_response.data or stats_response.data[0]['total_transcriptions'] == 0:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "No transcription history found for this phone number"},
            )

        transcription_count = stats_response.data[0]['total_transcriptions']

        try:
            auth_response = await asyncio.to_thread(
                supabase.auth.admin.create_user,
                {
                    "phone": phone,
                    "phone_confirm": True,
                    "user_metadata": {
                        "linked_from_sms": True,
                        "transcription_count": transcription_count,
                        "auth_type": "phone_only",
                    },
                },
            )

            if not auth_response.user:
                raise Exception("Failed to create auth user")

            auth_user_id = auth_response.user.id
            logger.info(f"Created phone-based auth user {auth_user_id} for phone {phone}")

        except Exception as e:
            logger.error(f"Failed to create auth user: {str(e)}")
            return JSONResponse(
                status_code=500,
                content={"success": False, "error": f"Failed to create account: {str(e)}"},
            )

        try:
            link_response = await asyncio.to_thread(
                supabase.rpc,
                'link_sms_user_to_auth',
                {
                    'p_phone_number': phone,
                    'p_auth_user_id': auth_user_id,
                },
            )

            linked_count = link_response.data[0]['linked_transcriptions'] if link_response.data else 0

            logger.info(
                f"Successfully linked {linked_count} transcriptions for phone {phone} to user {auth_user_id}"
            )

            return JSONResponse(
                content={
                    "success": True,
                    "linked_transcriptions": linked_count,
                    "auth_user_id": auth_user_id,
                    "phone": phone,
                    "message": f"Successfully created phone-based account and linked {linked_count} transcriptions",
                }
            )

        except Exception as e:
            logger.error(f"Failed to link transcriptions: {str(e)}")
            try:
                await asyncio.to_thread(supabase.auth.admin.delete_user, auth_user_id)
            except Exception:
                pass
            return JSONResponse(
                status_code=500,
                content={"success": False, "error": f"Failed to link transcriptions: {str(e)}"},
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in link_sms_account: {str(e)}", exc_info=True)
        raise ApiError(500, INTERNAL_ERROR, "Failed to link SMS account")


@router.post("/api/sms/inbound")
async def handle_inbound_sms(
    background_tasks: BackgroundTasks,
    From: str = Form(...),
    Body: str = Form(...),
    MessageSid: str = Form(None),
    To: str = Form(None),
):
    """Handle incoming SMS from Twilio webhook"""
    try:
        logger.info(f"Received SMS from {From}: {Body[:50]}...")

        command = None
        if Body.startswith('/'):
            command = Body.split()[0].lower()

        await asyncio.to_thread(
            supabase.table('user_messages')
                    .insert({
                        'from_phone': From,
                        'message_body': Body,
                        'command': command,
                        'response_sent': False,
                    })
                    .execute()
        )

        twiml_response = await sms.SMSHandler.process_inbound_sms(From, Body)

        if sms.SMSHandler.is_video_url(Body):
            video_url = sms.SMSHandler.extract_video_url(Body)
            if video_url:
                job_response = supabase.table('transcript_jobs').insert({
                    'from_phone': From,
                    'video_url': video_url,
                    'status': 'queued',
                    'message_sid': MessageSid,
                }).execute()

                if job_response.data:
                    job_id = job_response.data[0]['id']

                    task = await init_task(video_url, user_id=None, user_phone=From)
                    task_id = task['task_id']

                    result = supabase.table('transcript_jobs').update(
                        {'transcript_id': task_id}
                    ).eq('id', job_id).execute()
                    if result.data:
                        logger.info(f"Linked job {job_id} to task {task_id}")
                    else:
                        logger.warning(f"Failed to link job {job_id} to task {task_id}: {result}")

                    result = supabase.table('transcriptions').update(
                        {'user_phone': From}
                    ).eq('task_id', task_id).execute()
                    if result.data:
                        logger.info(f"Stored user phone for task {task_id}")
                    else:
                        logger.warning(f"Failed to store user phone for task {task_id}: {result}")

                    background_tasks.add_task(
                        process_transcription_with_sms_notification,
                        task_id,
                        video_url,
                        From,
                        job_id,
                    )
                    logger.info(f"Queued transcription task {task_id} for SMS user {From}")

        result = supabase.table('user_messages').update({'response_sent': True}).eq(
            'from_phone', From
        ).eq('message_body', Body).execute()
        if result.data:
            logger.info(f"Marked message as responded for {From}")
        else:
            logger.warning(f"Failed to mark message as responded for {From}: {result}")

        return Response(content=twiml_response, media_type="application/xml")

    except Exception as e:
        logger.error(f"Error handling inbound SMS: {str(e)}", exc_info=True)
        error_response = sms.SMSHandler.create_twiml_response(
            "🚨 Oops! Something went wrong. Please try again or contact support."
        )
        return Response(content=error_response, media_type="application/xml")


@router.post("/api/sms/status")
async def handle_sms_status(
    request: Request,
    MessageSid: str = Form(...),
    MessageStatus: str = Form(...),
    To: str = Form(None),
    From: str = Form(None),
):
    """Handle SMS delivery status updates from Twilio"""
    try:
        logger.info(f"SMS status update - SID: {MessageSid}, Status: {MessageStatus}, To: {To}")
        return {"status": "received"}
    except Exception as e:
        logger.error(f"Error handling SMS status: {str(e)}", exc_info=True)
        return {"error": "Failed to process status update"}


@router.post("/api/sms/send", response_model=SMSResponse)
async def send_sms(
    request: Request,
    api_key: str = Depends(verify_api_key),
):
    """Send SMS message (for testing or manual sends)"""
    try:
        body = await request.json()
        to = body.get("to")
        message = body.get("message")

        if not to or not message:
            raise ApiError(400, VALIDATION_ERROR, "Both 'to' and 'message' are required")

        success = await sms.SMSHandler.send_sms(to, message)

        if success:
            return {"status": "sent", "to": to}
        raise ApiError(500, INTERNAL_ERROR, "Failed to send SMS")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending SMS: {str(e)}", exc_info=True)
        raise ApiError(500, INTERNAL_ERROR, "Failed to send SMS")


@router.post("/api/sms/summary")
async def generate_sms_summary(request: Request):
    """Generate AI summary of user's latest transcript for SMS"""
    try:
        body = await request.json()
        phone = body.get("phone")

        if not phone:
            raise ApiError(400, VALIDATION_ERROR, "Phone number is required")

        summary_result = await sms.SMSHandler.handle_summary_command(phone)
        return {"summary": summary_result}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating SMS summary: {str(e)}", exc_info=True)
        raise ApiError(500, INTERNAL_ERROR, "Failed to generate summary")


@router.post("/api/sms/chat", response_model=SmsChatResponse)
async def sms_chat(request: SmsChatRequest):
    """Answer a user's question about their latest transcript with chat memory."""
    if supabase is None:
        logger.error("Cannot chat: Supabase client not initialized.")
        raise ApiError(503, SERVICE_UNAVAILABLE, "Database connection not available")

    phone = request.phone.strip()
    message = request.message.strip()
    if not phone:
        raise ApiError(400, VALIDATION_ERROR, "Phone number is required")
    if not message:
        raise ApiError(400, VALIDATION_ERROR, "Message is required")

    try:
        thread = None
        thread_id = None
        conversation_summary = ""
        message_history = []
        task_id = None

        try:
            thread_response = supabase.table('conversation_threads') \
                .select('id, task_id, summary, message_count') \
                .eq('user_phone', phone) \
                .eq('status', 'active') \
                .order('last_active', desc=True) \
                .limit(1) \
                .execute()
            thread = thread_response.data[0] if thread_response.data else None
        except Exception as e:
            logger.error(f"Error loading conversation thread: {str(e)}")
            thread = None

        if not thread:
            transcript_lookup = supabase.table('transcriptions') \
                .select('task_id') \
                .eq('user_phone', phone) \
                .eq('status', 'completed') \
                .order('created_at', desc=True) \
                .limit(1) \
                .execute()
            if not transcript_lookup.data:
                raise ApiError(404, TASK_NOT_FOUND, "No completed transcripts found for this number")

            task_id = transcript_lookup.data[0]['task_id']
            try:
                thread_insert = supabase.table('conversation_threads').insert({
                    'user_phone': phone,
                    'task_id': task_id,
                    'summary': None,
                    'message_count': 0,
                    'status': 'active',
                    'last_active': datetime.now(timezone.utc).isoformat(),
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'updated_at': datetime.now(timezone.utc).isoformat(),
                }).execute()
                if thread_insert.data:
                    thread = thread_insert.data[0]
                else:
                    thread_fetch = supabase.table('conversation_threads') \
                        .select('id, task_id, summary, message_count') \
                        .eq('user_phone', phone) \
                        .eq('task_id', task_id) \
                        .eq('status', 'active') \
                        .order('created_at', desc=True) \
                        .limit(1) \
                        .execute()
                    thread = thread_fetch.data[0] if thread_fetch.data else None
            except Exception as e:
                logger.error(f"Error creating conversation thread: {str(e)}")
                thread = None

        if thread:
            task_id = thread.get('task_id')
            thread_id = thread.get('id')
            conversation_summary = thread.get('summary') or ""
        elif not task_id:
            transcript_lookup = supabase.table('transcriptions') \
                .select('task_id') \
                .eq('user_phone', phone) \
                .eq('status', 'completed') \
                .order('created_at', desc=True) \
                .limit(1) \
                .execute()
            if not transcript_lookup.data:
                raise ApiError(404, TASK_NOT_FOUND, "No completed transcripts found for this number")
            task_id = transcript_lookup.data[0]['task_id']
            thread_id = task_id

        task_response = supabase.table('transcriptions').select(
            'status, transcript, title, description, quote, tldr, error, uploader, channel, duration, platform, view_count, like_count, category, auto_tags'
        ).eq('task_id', task_id).maybe_single().execute()

        if not task_response.data:
            raise ApiError(404, TASK_NOT_FOUND, "Transcript not found")

        task = task_response.data
        if task.get('status') == 'failed':
            error_message = task.get('error', 'Unknown error')
            raise ApiError(400, TRANSCRIPT_NOT_READY, f"Transcription failed: {error_message}")
        if task.get('status') != 'completed':
            raise ApiError(
                409, TRANSCRIPT_NOT_READY,
                f"Transcription not completed yet. Current status: {task.get('status')}",
            )

        transcript_text = task.get('transcript') or ''
        if not transcript_text:
            raise ApiError(400, TRANSCRIPT_NOT_READY, "Transcript not ready yet")

        if thread_id:
            try:
                supabase.table('conversation_messages').insert({
                    'thread_id': thread_id,
                    'role': 'user',
                    'content': message,
                }).execute()
            except Exception as e:
                logger.error(f"Error saving user message: {str(e)}")

            try:
                messages_response = supabase.table('conversation_messages') \
                    .select('role, content, created_at') \
                    .eq('thread_id', thread_id) \
                    .order('created_at', desc=True) \
                    .limit(20) \
                    .execute()
                messages = messages_response.data or []
                messages_sorted = list(reversed(messages))
                message_history = [
                    {'role': msg.get('role'), 'content': msg.get('content')}
                    for msg in messages_sorted
                    if msg.get('content')
                ]
            except Exception as e:
                logger.error(f"Error loading message history: {str(e)}")
                message_history = []

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
            question=message,
            transcript_text=transcript_text,
            title=task.get('title') or '',
            description=task.get('description') or '',
            quote=task.get('quote') or '',
            tldr_list=tldr_list,
            max_chars=request.max_chars or 360,
            conversation_summary=conversation_summary,
            message_history=message_history,
            metadata={k: task.get(k) for k in ('uploader', 'channel', 'duration', 'platform', 'view_count', 'like_count', 'category', 'auto_tags') if task.get(k)},
        )
        if not answer:
            answer = sms.SMSHandler._clip_answer("I can't tell from this video.", request.max_chars or 360)

        if thread_id:
            try:
                supabase.table('conversation_messages').insert({
                    'thread_id': thread_id,
                    'role': 'assistant',
                    'content': answer,
                }).execute()
            except Exception as e:
                logger.error(f"Error saving assistant message: {str(e)}")

            if thread:
                summary_messages = message_history + [{'role': 'assistant', 'content': answer}]
                new_summary = await sms.SMSHandler.generate_chat_summary(
                    conversation_summary,
                    summary_messages[-20:],
                    max_chars=600,
                )

                try:
                    supabase.table('conversation_threads').update({
                        'summary': new_summary,
                        'message_count': (thread.get('message_count') or 0) + 2,
                        'last_active': datetime.now(timezone.utc).isoformat(),
                        'updated_at': datetime.now(timezone.utc).isoformat(),
                    }).eq('id', thread_id).execute()
                except Exception as e:
                    logger.error(f"Error updating conversation thread: {str(e)}")

        return SmsChatResponse(
            answer=answer,
            task_id=task_id,
            thread_id=thread_id or task_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating SMS chat response: {str(e)}", exc_info=True)
        raise ApiError(500, INTERNAL_ERROR, "Failed to generate answer")


@router.post("/api/sms/chat/reset", response_model=SmsChatResetResponse)
async def sms_chat_reset(request: SmsChatResetRequest):
    """Reset the active chat thread for a phone number."""
    if supabase is None:
        logger.error("Cannot reset chat: Supabase client not initialized.")
        raise ApiError(503, SERVICE_UNAVAILABLE, "Database connection not available")

    phone = request.phone.strip()
    if not phone:
        raise ApiError(400, VALIDATION_ERROR, "Phone number is required")

    try:
        response = supabase.table('conversation_threads').update({
            'status': 'closed',
            'closed_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }).eq('user_phone', phone).eq('status', 'active').execute()

        closed_threads = len(response.data) if response.data else 0
        return SmsChatResetResponse(success=True, closed_threads=closed_threads)
    except Exception as e:
        logger.error(f"Error resetting SMS chat: {str(e)}", exc_info=True)
        raise ApiError(500, INTERNAL_ERROR, "Failed to reset chat")


@router.get("/api/analytics/sms")
async def sms_analytics(api_key: str = Depends(verify_api_key)):
    """Get SMS usage analytics"""
    try:
        jobs_response = await asyncio.to_thread(
            supabase.table('transcript_jobs')
                    .select("status, created_at, from_phone")
                    .limit(5000)
                    .execute()
        )

        messages_response = await asyncio.to_thread(
            supabase.table('user_messages')
                    .select("command, created_at, from_phone")
                    .limit(5000)
                    .execute()
        )

        jobs_data = jobs_response.data if jobs_response.data else []
        messages_data = messages_response.data if messages_response.data else []

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
                "success_rate": round((completed_jobs / total_jobs * 100) if total_jobs > 0 else 0, 2),
            },
            "users": {
                "unique_users": unique_users,
                "total_messages": len(messages_data),
            },
            "commands": command_stats,
        }

    except Exception as e:
        logger.error(f"Error getting SMS analytics: {str(e)}", exc_info=True)
        raise ApiError(500, INTERNAL_ERROR, "Error retrieving analytics")


@router.get("/api/admin/stats")
async def admin_stats(
    period: str = "month",
    api_key: str = Depends(verify_api_key)
):
    """
    Get comprehensive admin statistics including costs, revenue, and trends.

    Args:
        period: Time period for stats - 'day', 'week', 'month', or 'all'

    Returns:
        Detailed admin stats including financials, users, usage, and cost breakdown
    """
    try:
        from ..cost_tracker import CostTracker

        # Validate period
        if period not in ['day', 'week', 'month', 'all']:
            period = 'month'

        stats = await CostTracker.get_admin_stats(period)

        if not stats:
            # Return empty stats structure if no data
            return {
                "period": period,
                "financials": {
                    "revenue_cents": 0,
                    "costs_cents": 0,
                    "profit_cents": 0,
                    "margin_percent": 0
                },
                "users": {
                    "total": 0,
                    "active": 0,
                    "new": 0,
                    "paid": 0,
                    "conversion_rate": 0
                },
                "usage": {
                    "transcriptions": 0,
                    "success_rate": 0
                },
                "cost_breakdown": [],
                "revenue_breakdown": {}
            }

        return stats

    except ImportError:
        raise ApiError(501, SERVICE_UNAVAILABLE, "Cost tracking module not available")
    except Exception as e:
        logger.error(f"Error getting admin stats: {str(e)}", exc_info=True)
        raise ApiError(500, INTERNAL_ERROR, "Error retrieving admin stats")


@router.get("/api/admin/trends")
async def admin_trends(
    days: int = 30,
    api_key: str = Depends(verify_api_key)
):
    """
    Get daily cost/revenue trends for charting.

    Args:
        days: Number of days to fetch (default 30, max 90)

    Returns:
        List of daily data with costs, revenue, and transcription counts
    """
    try:
        from ..cost_tracker import CostTracker

        # Cap days at 90
        days = min(days, 90)

        trends = await CostTracker.get_cost_trends(days)

        if not trends:
            return []

        return trends

    except ImportError:
        raise ApiError(501, SERVICE_UNAVAILABLE, "Cost tracking module not available")
    except Exception as e:
        logger.error(f"Error getting admin trends: {str(e)}", exc_info=True)
        raise ApiError(500, INTERNAL_ERROR, "Error retrieving trends")
