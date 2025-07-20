# ScribeTok API Documentation

Complete API reference for the TikTok/YouTube transcription service with SMS integration and phone-first authentication.

## Base URL

- **Production:** `https://tiktok-transcription-service.onrender.com`
- **Local:** `http://localhost:8000`

## Authentication

### Public Endpoints
- **Prefix:** `/api/public/`
- **Authentication:** None required
- **Use Case:** Content discovery, transcription access, SMS integration

### Private Endpoints
- **Authentication:** API Key via `X-API-Key` header
- **Use Case:** Task management, analytics, administrative functions
- **Example:** `X-API-Key: your-api-key-here`

---

## 🎬 Core Transcription Endpoints

### Start Transcription (Public)

**`POST /api/public/transcribe`**

Start transcribing a TikTok or YouTube video. YouTube videos are processed instantly via RapidAPI, while TikTok videos go through full metadata extraction.

**Request:**
```json
{
  "url": "https://youtube.com/watch?v=dQw4w9WgXcQ",
  "callback_url": "https://yourapp.com/webhook",
  "extract_audio": true,
  "save_thumbnail": true,
  "perform_sentiment_analysis": false,
  "create_srt": false,
  "user_phone": "+1234567890"
}
```

**Supported URL Formats:**
- **TikTok**: `https://tiktok.com/@user/video/123`, `https://vm.tiktok.com/abc123`
- **YouTube**: `https://youtube.com/watch?v=abc123`, `https://youtu.be/abc123`, `https://youtube.com/shorts/abc123`

**Response:**

**TikTok Video (Pending Processing):**
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "video_id": "7526401258786245902",
  "title": "Amazing TikTok Video",
  "created_at": "2025-07-20T12:00:00Z",
  "thumbnail_url": "https://p16-sign-sg.tiktokcdn.com/..."
}
```

**YouTube Video (Instantly Completed):**
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440001",
  "status": "completed",
  "video_id": "dQw4w9WgXcQ",
  "title": "Rick Astley - Never Gonna Give You Up",
  "created_at": "2025-07-20T12:00:00Z",
  "platform": "youtube",
  "category": "youtube-transcription",
  "tags": ["sms-inbound", "youtube"]
}
```

### Get Task Status

**`GET /api/public/tasks/{task_id}`**

Check the status of a transcription task.

**Response:**
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "title": "Amazing TikTok Video",
  "video_id": "7526401258786245902",
  "created_at": "2025-07-20T12:00:00Z",
  "thumbnail_url": "https://p16-sign-sg.tiktokcdn.com/...",
  "video_url": "https://v103.tokcdn.com/...",
  "duration": 122,
  "description": "Check out this amazing content!",
  "channel": "@username",
  "like_count": 1500,
  "comment_count": 89,
  "view_count": 12500,
  "platform": "tiktok",
  "category": "entertainment",
  "tags": ["viral", "funny", "trending"],
  "auto_tags": ["#amazing", "#tiktok"],
  "error": null
}
```

### Get Transcript

**`GET /api/public/transcript/{task_id}`**
**`GET /api/public/transcript/{task_id}?format=json`**

Get the timestamped transcript for a completed video.

**Response (Text):**
```
0:00:00
- So supposedly the raw footage was edited in Adobe

0:00:15
- This is the official FBI memo

0:00:30
- Down here there's going to be two links to two different videos
```

**Response (JSON format):**
```json
{
  "transcript": "Full timestamped transcript text...",
  "segments": [
    {
      "start": 0.0,
      "end": 15.0,
      "text": "So supposedly the raw footage was edited in Adobe"
    }
  ]
}
```

### Get Thumbnail

**`GET /api/public/thumbnail/{task_id}`**

Get the video thumbnail image.

**Response:** Image file (JPEG/PNG)

### List Public Tasks

**`GET /api/public/tasks`**

Get a list of all public transcription tasks.

**Query Parameters:**
- `limit` (optional): Maximum number of results (default: 50)
- `offset` (optional): Number of results to skip (default: 0)

**Response:**
```json
{
  "tasks": [
    {
      "task_id": "550e8400-e29b-41d4-a716-446655440000",
      "title": "Amazing TikTok Video",
      "status": "completed",
      "created_at": "2025-07-20T12:00:00Z",
      "thumbnail_url": "https://...",
      "view_count": 15,
      "category": "entertainment"
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

---

## 🔍 Content Discovery Endpoints

### Trending Transcriptions

**`GET /api/public/discover/trending`**

Get trending transcribed videos.

**Query Parameters:**
- `time_window`: `week` | `month` | `all` (default: `week`)
- `category`: Filter by category (optional)
- `limit`: Number of results (default: 10, max: 50)

**Response:**
```json
[
  {
    "task_id": "550e8400-e29b-41d4-a716-446655440000",
    "title": "Trending Video Title",
    "video_id": "7526401258786245902",
    "thumbnail_url": "https://...",
    "view_count": 1250,
    "category": "entertainment",
    "tags": ["viral", "trending"],
    "created_at": "2025-07-20T12:00:00Z",
    "platform": "tiktok",
    "like_count": 500,
    "comment_count": 89
  }
]
```

### Similar Content

**`GET /api/public/discover/similar/{task_id}`**

Find transcriptions similar to a given video.

**Query Parameters:**
- `limit`: Number of results (default: 5, max: 20)

**Response:** Array of transcription objects (same format as trending)

### Recent Transcriptions

**`GET /api/public/discover/recent`**

Get recently transcribed videos.

**Query Parameters:**
- `category`: Filter by category (optional)
- `limit`: Number of results (default: 10, max: 50)

**Response:** Array of transcription objects (same format as trending)

### Available Categories

**`GET /api/public/discover/categories`**

Get list of available content categories.

**Response:**
```json
[
  "entertainment",
  "education", 
  "news",
  "comedy",
  "music",
  "sports",
  "technology",
  "lifestyle"
]
```

---

## 📱 SMS Integration Endpoints

### SMS Webhook Handler

**`POST /api/sms/inbound`**

Handle incoming SMS messages from Twilio. Supports both TikTok and YouTube video URLs, plus SMS commands.

**Request Examples (Form Data):**

**TikTok Video:**
```
From=+1234567890
Body=https://tiktok.com/@user/video/123
```

**YouTube Video:**
```
From=+1234567890
Body=https://youtube.com/watch?v=dQw4w9WgXcQ
```

**SMS Commands:**
```
From=+1234567890
Body=/help
```

**Response:** TwiML XML for SMS reply

**SMS Command Support:**
- `/help` - Show available commands
- `/register` - Create account and link history
- `/login` - Get OTP verification code
- `/verify 123456` - Verify with OTP code
- `/profile` - View account stats
- `/vault` - View recent transcripts

**Video Processing:**
- **YouTube**: Instant transcription via RapidAPI with immediate SMS response
- **TikTok**: Full processing with rich metadata via backend service

### SMS Status Updates

**`POST /api/sms/status`**

Handle SMS delivery status updates from Twilio.

**Request:** Twilio status webhook payload

### Send SMS

**`POST /api/sms/send`** (Private)

Send an SMS message programmatically.

**Headers:** `X-API-Key: your-api-key`

**Request:**
```json
{
  "to": "+1234567890",
  "message": "Your transcript is ready!"
}
```

**Response:**
```json
{
  "success": true,
  "message_sid": "SM1234567890abcdef",
  "status": "queued"
}
```

### SMS Analytics

**`GET /api/analytics/sms`** (Private)

Get SMS usage analytics and statistics.

**Headers:** `X-API-Key: your-api-key`

**Response:**
```json
{
  "total_messages": 1250,
  "messages_this_month": 89,
  "unique_users": 456,
  "transcriptions_via_sms": 1100,
  "most_active_users": [
    {
      "phone": "+1234567890",
      "message_count": 25,
      "transcription_count": 23
    }
  ]
}
```

---

## 👤 Account Linking & Authentication

### Link SMS Account

**`POST /api/link-sms-account`** (Private)

Create a phone-based Supabase auth account and link SMS transcription history.

**Headers:** `X-API-Key: your-api-key`

**Request:**
```json
{
  "phone": "+1234567890"
}
```

**Response:**
```json
{
  "success": true,
  "auth_user_id": "550e8400-e29b-41d4-a716-446655440000",
  "linked_transcriptions": 15,
  "phone": "+1234567890",
  "message": "Account created and 15 transcriptions linked"
}
```

**SMS Commands Available:**
- `/help` - Show available commands
- `/register` - Create account and link history
- `/login` - Get OTP verification code
- `/verify 123456` - Verify with OTP code
- `/profile` - View account stats
- `/vault` - View recent transcripts

---

## 🔧 Private Task Management

### Submit Task

**`POST /api/tasks`** (Private)

Submit a new transcription task with full control options.

**Headers:** `X-API-Key: your-api-key`

**Request:**
```json
{
  "url": "https://youtube.com/watch?v=xyz",
  "callback_url": "https://yourapp.com/webhook",
  "extract_audio": true,
  "save_thumbnail": true,
  "perform_sentiment_analysis": false,
  "create_srt": false,
  "proxy": "http://proxy.example.com:8080"
}
```

### List Your Tasks

**`GET /api/tasks`** (Private)

Get all tasks created with your API key.

**Headers:** `X-API-Key: your-api-key`

**Query Parameters:**
- `limit`: Number of results (default: 50)
- `status`: Filter by status (`pending`, `processing`, `completed`, `failed`)

### Get Private Task

**`GET /api/tasks/{task_id}`** (Private)

Get detailed task information including file paths.

**Headers:** `X-API-Key: your-api-key`

### Delete Task

**`DELETE /api/tasks/{task_id}`** (Private)

Delete a task and associated files.

**Headers:** `X-API-Key: your-api-key`

### Get Private Transcript

**`GET /api/transcript/{task_id}`** (Private)

Get transcript with additional metadata and file access.

**Headers:** `X-API-Key: your-api-key`

---

## 🌐 Web Viewer & Public Pages

### Public Transcript Viewer

**`GET /v/{task_id}`**

Public web page for viewing transcripts with social sharing.

**Features:**
- Timestamped transcript display
- Video thumbnail and metadata
- Social sharing buttons
- Viral sharing mechanics
- Mobile-responsive design

### Homepage

**`GET /`**

Service homepage with API information.

---

## 🔗 Webhooks & Integration

### Supabase Webhook Handler

**`POST /api/webhook/supabase`** (Private)

Handle webhooks from Supabase for database events.

**Headers:** `X-API-Key: your-api-key`

**Request:** Supabase webhook payload

---

## 🛠️ System & Maintenance

### Health Check

**`GET /api/healthcheck`**

Check service health and dependencies.

**Response:**
```json
{
  "status": "ok",
  "version": "1.0.0",
  "timestamp": 1753026086.24777,
  "services": {
    "openai": "connected",
    "supabase": "connected",
    "rapidapi": "connected"
  }
}
```

### Test OpenAI Connection

**`GET /api/test`** (Private)

Test OpenAI API connectivity.

**Headers:** `X-API-Key: your-api-key`

### Test Download

**`POST /api/test-download`** (Private)

Test video download functionality.

**Headers:** `X-API-Key: your-api-key`

### Fallback Download

**`POST /api/fallback-download`** (Private)

Use alternative download methods for problematic videos.

**Headers:** `X-API-Key: your-api-key`

### Clean Stuck Tasks

**`POST /api/cleanup-stuck-tasks`** (Private/Public)
**`POST /api/public/cleanup-stuck-tasks`**

Clean up tasks stuck in processing state.

### Reprocess SMS Jobs

**`POST /api/reprocess-sms-jobs`** (Private/Public)
**`POST /api/public/reprocess-sms-jobs`**

Reprocess failed SMS transcription jobs.

---

## 📊 Rich Metadata Fields

All transcription responses include extensive metadata extracted from videos:

### Video Information
- `video_id` - Platform video ID
- `title` - Video title
- `description` - Video description
- `duration` - Video length in seconds
- `upload_date` - When video was uploaded
- `platform` - "tiktok" or "youtube"

### Creator Information
- `channel` - Creator username/channel name
- `channel_id` - Creator's unique ID
- `uploader` - Display name
- `uploader_url` - Link to creator's profile

### Engagement Metrics
- `like_count` - Number of likes
- `comment_count` - Number of comments
- `repost_count` - Number of reposts/shares
- `view_count` - Video view count (service views)

### Technical Details
- `video_url` - Direct CDN link to video file
- `thumbnail_url` - Video thumbnail URL
- `width` / `height` - Video dimensions
- `resolution` - Video quality
- `format` - Video format information

### Content Classification
- `category` - AI-generated category
- `tags` - Manual tags
- `auto_tags` - Auto-extracted hashtags
- `timestamp` - Creation timestamp

---

## 📱 Interactive Documentation

- **Swagger UI:** `https://tiktok-transcription-service.onrender.com/docs`
- **ReDoc:** `https://tiktok-transcription-service.onrender.com/redoc`

---

## 🔗 Usage Examples

### JavaScript/Node.js

**TikTok Transcription:**
```javascript
// Start TikTok transcription (async processing)
const response = await fetch('https://tiktok-transcription-service.onrender.com/api/public/transcribe', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    url: 'https://tiktok.com/@user/video/123',
    save_thumbnail: true,
    extract_audio: true
  })
});

const task = await response.json();
console.log('Task ID:', task.task_id);

// Poll for completion
const checkStatus = async () => {
  const statusResponse = await fetch(`https://tiktok-transcription-service.onrender.com/api/public/tasks/${task.task_id}`);
  const status = await statusResponse.json();
  
  if (status.status === 'completed') {
    // Get transcript
    const transcriptResponse = await fetch(`https://tiktok-transcription-service.onrender.com/api/public/transcript/${task.task_id}`);
    const transcript = await transcriptResponse.text();
    console.log('Transcript:', transcript);
  } else if (status.status === 'failed') {
    console.error('Transcription failed:', status.error);
  } else {
    // Still processing, check again in 5 seconds
    setTimeout(checkStatus, 5000);
  }
};

checkStatus();
```

**YouTube Transcription (Instant):**
```javascript
// Start YouTube transcription (instant processing)
const response = await fetch('https://tiktok-transcription-service.onrender.com/api/public/transcribe', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    url: 'https://youtube.com/watch?v=dQw4w9WgXcQ',
    user_phone: '+1234567890'  // Optional: for SMS notification
  })
});

const task = await response.json();
console.log('Task ID:', task.task_id);

// YouTube videos are completed immediately
if (task.status === 'completed') {
  const transcriptResponse = await fetch(`https://tiktok-transcription-service.onrender.com/api/public/transcript/${task.task_id}`);
  const transcript = await transcriptResponse.text();
  console.log('YouTube Transcript:', transcript);
}
```

### Python

```python
import requests
import time

# Start transcription
response = requests.post(
    'https://tiktok-transcription-service.onrender.com/api/public/transcribe',
    json={
        'url': 'https://tiktok.com/@user/video/123',
        'save_thumbnail': True,
        'extract_audio': True
    }
)

task = response.json()
task_id = task['task_id']

# Poll for completion
while True:
    status_response = requests.get(
        f'https://tiktok-transcription-service.onrender.com/api/public/tasks/{task_id}'
    )
    status = status_response.json()

    if status['status'] == 'completed':
        # Get transcript
        transcript_response = requests.get(
            f'https://tiktok-transcription-service.onrender.com/api/public/transcript/{task_id}'
        )
        print('Transcript:', transcript_response.text)
        break
    elif status['status'] == 'failed':
        print('Error:', status.get('error'))
        break

    time.sleep(5)  # Wait 5 seconds before checking again
```

### cURL

```bash
# Start transcription
curl -X POST "https://tiktok-transcription-service.onrender.com/api/public/transcribe" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://tiktok.com/@user/video/123", "save_thumbnail": true}'

# Check status
curl "https://tiktok-transcription-service.onrender.com/api/public/tasks/your-task-id"

# Get transcript
curl "https://tiktok-transcription-service.onrender.com/api/public/transcript/your-task-id"

# Private API example
curl -X GET "https://tiktok-transcription-service.onrender.com/api/tasks" \
  -H "X-API-Key: your-api-key-here"
```

---

## ⚠️ Error Handling

### HTTP Status Codes
- `200` - Success
- `400` - Bad request (invalid URL, missing parameters)
- `401` - Unauthorized (invalid/missing API key)
- `404` - Not found (task not found, file not found)
- `422` - Validation error (invalid request format)
- `500` - Internal server error

### Error Response Format
```json
{
  "detail": "Error message description"
}
```

### Common Errors
- `"Invalid video URL"` - URL format not supported (must be TikTok or YouTube)
- `"Task not found"` - Task ID doesn't exist
- `"Transcription failed"` - Video processing error
- `"Invalid API key"` - Authentication failed
- `"YouTube RapidAPI error"` - YouTube transcription service unavailable
- `"Failed to transcribe YouTube video"` - YouTube processing failed

---

## 🔄 Rate Limits & Quotas

- **Public endpoints:** No specific rate limits (subject to server capacity)
- **Private endpoints:** Depends on API key configuration
- **SMS integration:** Limited by Twilio quotas
- **File storage:** Temporary files cleaned up automatically

---

## 📈 Recent Updates (July 2025)

### New Features
- ✅ **Dual Platform Support** - TikTok AND YouTube transcription
- ✅ **YouTube Instant Processing** - Real-time transcription via RapidAPI
- ✅ **SMS Integration** - Full SMS workflow with Twilio
- ✅ **Phone-First Authentication** - No email required
- ✅ **Account Linking** - Connect SMS users to Supabase auth
- ✅ **Rich Metadata** - 20+ fields from TikTok/YouTube
- ✅ **Direct Video URLs** - CDN links instead of local storage
- ✅ **Analytics Dashboard** - SMS usage tracking
- ✅ **Viral Sharing** - Public transcript pages
- ✅ **Auto-tagging** - Hashtag extraction
- ✅ **Content Discovery** - Trending/similar/recent endpoints

### Architecture Improvements
- ✅ **File Cleanup** - Automatic cleanup prevents disk issues
- ✅ **Error Resilience** - Graceful handling of edge cases
- ✅ **Multiple Download Methods** - RapidAPI + yt-dlp fallback
- ✅ **Timestamped Transcripts** - Proper segment formatting
- ✅ **Database Optimization** - Removed unused tables

---

This API provides comprehensive **dual-platform video transcription** capabilities (TikTok + YouTube) with SMS integration, phone-first authentication, and extensive content discovery features. Features instant YouTube processing via RapidAPI and rich TikTok metadata extraction. Perfect for building viral social media tools and content analysis applications.