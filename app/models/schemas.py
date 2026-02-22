from typing import Optional, Dict, Any, List

from pydantic import BaseModel, Field


class TranscriptionRequest(BaseModel):
    """Request model for video transcription"""
    url: str = Field(
        ...,
        description="TikTok or YouTube video URL to transcribe",
        example="https://www.tiktok.com/@user/video/7526401258786245902",
    )
    callback_url: Optional[str] = Field(
        None,
        description="Webhook URL to receive completion notification",
        example="https://yourapp.com/webhook",
    )
    format: Optional[str] = Field(
        "bestaudio/best",
        description="Video/audio format preference for download",
    )
    output_template: Optional[str] = Field(
        None,
        description="Custom output filename template",
    )
    extract_audio: bool = Field(
        True,
        description="Extract audio from video for transcription",
    )
    convert_to_mp3: bool = Field(
        False,
        description="Convert audio to MP3 format",
    )
    save_thumbnail: bool = Field(
        True,
        description="Save video thumbnail image",
    )
    extract_metadata: bool = Field(
        True,
        description="Extract rich metadata (views, likes, creator info, etc.)",
    )
    perform_sentiment_analysis: bool = Field(
        False,
        description="Analyze transcript sentiment (experimental)",
    )
    create_srt: bool = Field(
        False,
        description="Generate SRT subtitle file",
    )
    proxy: Optional[str] = Field(
        None,
        description="Proxy server URL for download",
        example="http://proxy.example.com:8080",
    )
    api_key: Optional[str] = Field(
        None,
        description="API key for authentication (can also use header)",
    )
    user_phone: Optional[str] = Field(
        None,
        description="Phone number for SMS notifications and user tracking",
        example="+1234567890",
    )


class TranscriptionResponse(BaseModel):
    """Complete transcription task response with rich metadata"""
    task_id: str = Field(..., example="550e8400-e29b-41d4-a716-446655440000")
    status: str = Field(..., example="completed", pattern="^(pending|processing|completed|failed)$")
    created_at: str = Field(..., example="2025-07-20T12:00:00Z")
    error: Optional[str] = Field(None, example=None)
    video_id: Optional[str] = Field(None, example="7526401258786245902")
    title: Optional[str] = Field(None, example="Amazing TikTok Video")
    description: Optional[str] = Field(
        None,
        example="Check out this amazing tech tutorial! #technology #viral",
    )
    duration: Optional[int] = Field(None, example=122)
    platform: Optional[str] = Field(None, example="tiktok")
    creator: Optional[str] = Field(None, example="Tech Guru")
    uploader_url: Optional[str] = Field(None, example="https://tiktok.com/@techguru")
    like_count: Optional[int] = Field(None, example=1500)
    comment_count: Optional[int] = Field(None, example=89)
    repost_count: Optional[int] = Field(None, example=234)
    view_count: Optional[int] = Field(None, example=15)
    thumbnail_url: Optional[str] = Field(None, example="https://example.com/thumb.jpg")
    video_url: Optional[str] = Field(None, example="https://cdn.tiktok.com/...")
    thumbnail_local_path: Optional[str] = Field(
        None,
        example="d5911018-8ba2-4ca6-bebf-95e9994f3a2d/thumbnail.jpg",
    )
    thumbnail: Optional[str] = Field(None, description="Deprecated: Use thumbnail_url instead")
    tags: Optional[list] = Field(None, example=["tech", "viral"])
    category: Optional[str] = Field(None, example="technology")


class TaskListResponse(BaseModel):
    """Response model for task list endpoints"""
    tasks: List[TranscriptionResponse] = Field(
        ...,
        description="Array of transcription tasks",
    )
    total: Optional[int] = Field(
        None,
        description="Total number of tasks",
        example=156,
    )
    limit: Optional[int] = Field(
        None,
        description="Maximum results per page",
        example=50,
    )
    offset: Optional[int] = Field(
        None,
        description="Number of results skipped",
        example=0,
    )


class SearchHit(BaseModel):
    """Search hit result for public transcription search."""
    task_id: str = Field(..., description="Transcription task id (UUID)")
    title: Optional[str] = Field(None, description="Video title")
    updated_at: Optional[str] = Field(None, description="Last updated timestamp")
    rank: Optional[float] = Field(None, description="Relevance rank (higher is better)")
    source: Optional[str] = Field(None, description="Which field matched: title|transcript")


class SearchResponse(BaseModel):
    """Response model for search endpoint."""
    query: str = Field(..., description="Original query")
    results: List[SearchHit] = Field(default_factory=list)
    limit: int = Field(..., example=50)
    offset: int = Field(..., example=0)


class TranscriptChatRequest(BaseModel):
    """Request model for transcript chat."""
    message: str = Field(..., min_length=1, max_length=1000, description="User question about the transcript")
    max_chars: Optional[int] = Field(800, ge=120, le=1200, description="Maximum characters for the answer")


class TranscriptChatResponse(BaseModel):
    """Response model for transcript chat."""
    task_id: str = Field(..., description="Transcription task id (UUID)")
    answer: str = Field(..., description="Short answer based on transcript content")


class HealthCheckResponse(BaseModel):
    """Health check response model"""
    status: str = Field(..., description="Service status", example="ok")
    version: str = Field(..., description="API version", example="1.0.0")
    timestamp: float = Field(..., description="Server timestamp", example=1753026086.24777)
    services: Dict[str, str] = Field(
        ...,
        description="Connected service statuses",
        example={
            "openai": "connected",
            "supabase": "connected",
            "rapidapi": "connected",
        },
    )


class SMSResponse(BaseModel):
    """SMS operation response model"""
    success: bool = Field(..., description="Whether SMS operation succeeded", example=True)
    message_sid: Optional[str] = Field(None, description="Twilio message SID", example="SM1234567890abcdef")
    status: Optional[str] = Field(None, description="Message delivery status", example="queued")


class AccountLinkResponse(BaseModel):
    """Account linking response model"""
    success: bool = Field(..., description="Whether account linking succeeded", example=True)
    auth_user_id: str = Field(
        ...,
        description="Supabase auth user ID",
        example="550e8400-e29b-41d4-a716-446655440000",
    )
    linked_transcriptions: int = Field(
        ...,
        description="Number of transcriptions linked to account",
        example=15,
    )
    phone: str = Field(..., description="Phone number", example="+1234567890")
    message: str = Field(
        ...,
        description="Success message",
        example="Account created and 15 transcriptions linked",
    )


class SmsChatRequest(BaseModel):
    """SMS chat request model"""
    phone: str = Field(..., description="E.164 phone number")
    message: str = Field(..., min_length=1, max_length=1000, description="User question")
    max_chars: Optional[int] = Field(800, ge=120, le=1200, description="Maximum characters for the answer")


class SmsChatResponse(BaseModel):
    """SMS chat response model"""
    answer: str = Field(..., description="Short answer based on transcript content")
    task_id: str = Field(..., description="Transcript task id used for context")
    thread_id: str = Field(..., description="Conversation thread id")


class SmsChatResetResponse(BaseModel):
    """SMS chat reset response model"""
    success: bool = Field(..., description="Whether reset succeeded")
    closed_threads: int = Field(..., description="Number of threads closed")


class SmsChatResetRequest(BaseModel):
    """SMS chat reset request model"""
    phone: str = Field(..., description="E.164 phone number")


class FetchCommentsRequest(BaseModel):
    """Request model for fetching comments"""
    task_id: str = Field(..., description="Transcription task id")
    count: int = Field(30, description="Number of comments per page (ignored if get_all=True)")
    include_replies: bool = Field(False, description="Whether to include comment replies")
    get_all: bool = Field(True, description="Fetch all comments with pagination")


# =============================================================================
# Web Chat API Models
# =============================================================================

class ChatMessage(BaseModel):
    """Individual chat message"""
    id: str = Field(..., description="Message UUID")
    role: str = Field(..., description="Message role: 'user' or 'assistant'")
    content: str = Field(..., description="Message content")
    created_at: str = Field(..., description="ISO timestamp when message was created")


class ChatThreadResponse(BaseModel):
    """Response for GET /api/chat/thread/{thread_id}"""
    thread_id: str = Field(..., description="Thread UUID")
    task_id: str = Field(..., description="Associated transcript task UUID")
    user_phone: Optional[str] = Field(None, description="User phone (masked for privacy)")
    status: str = Field(..., description="Thread status: 'active' or 'closed'")
    message_count: int = Field(..., description="Total messages in thread")
    summary: Optional[str] = Field(None, description="AI-generated conversation summary")
    messages: List[ChatMessage] = Field(default_factory=list, description="Chat messages")
    transcript_title: Optional[str] = Field(None, description="Title of the associated transcript")
    transcript_quote: Optional[str] = Field(None, description="Key quote from transcript")
    created_at: str = Field(..., description="Thread creation timestamp")
    last_active: str = Field(..., description="Last activity timestamp")


class WebChatRequest(BaseModel):
    """Request for POST /api/chat/thread/{thread_id}/message"""
    message: str = Field(..., min_length=1, max_length=1000, description="User's question or message")
    max_chars: Optional[int] = Field(600, ge=120, le=1500, description="Maximum characters for response (web allows longer)")


class WebChatResponse(BaseModel):
    """Response for POST /api/chat/thread/{thread_id}/message"""
    thread_id: str = Field(..., description="Thread UUID")
    task_id: str = Field(..., description="Associated transcript task UUID")
    user_message: ChatMessage = Field(..., description="The user's message that was sent")
    assistant_message: ChatMessage = Field(..., description="The assistant's response")


class ChatThreadListResponse(BaseModel):
    """Response for listing user's chat threads"""
    threads: List[ChatThreadResponse] = Field(default_factory=list, description="User's chat threads")
    total: int = Field(..., description="Total number of threads")
