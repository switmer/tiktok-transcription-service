# TikTok Transcription Service API Documentation

**📢 UPDATED: For the most comprehensive and current API documentation including SMS integration, account linking, and all new features, see [COMPLETE_API_DOCS.md](../../COMPLETE_API_DOCS.md)**

## Base URL

- **Production:** https://api.scribetok.com
- **Local:** http://localhost:8000

## Authentication

### Public Endpoints
- **Prefix:** `/api/public/`
- **Authentication:** None required
- **Use Case:** Content discovery, basic transcription access

### Private Endpoints
- **Authentication:** API Key via `X-API-Key` header
- **Use Case:** Task management, file operations
- **Example:** `X-API-Key: your-api-key-here`

## Core Endpoints

### 1. Transcription Operations

#### Start Transcription (Public)

`POST /api/public/transcribe`

**Content-Type:** `application/json`

```json
{
  "url": "https://tiktok.com/@user/video/123",
  "callback_url": "https://yourapp.com/webhook",
  "extract_audio": true,
  "save_thumbnail": true,
  "perform_sentiment_analysis": false,
  "create_srt": false
}
```

**Response:**
```json
{
  "task_id": "uuid-here",
  "status": "pending",
  "video_id": "123",
  "title": "Video Title",
  "created_at": "2025-01-16T12:00:00Z",
  "thumbnail_url": "https://example.com/thumb.jpg"
}
```

#### Get Task Status

`GET /api/public/tasks/{task_id}`

**Response:**
```json
{
  "task_id": "uuid-here",
  "status": "completed",
  "title": "Video Title",
  "created_at": "2025-01-16T12:00:00Z",
  "thumbnail_url": "https://example.com/thumb.jpg"
}
```

#### Get Transcript

`GET /api/public/transcript/{task_id}`  
`GET /api/public/transcript/{task_id}?format=json`

**Response:** File download or JSON transcript

#### Get Thumbnail

`GET /api/public/thumbnail/{task_id}`

**Response:** Image file

### 2. Content Discovery (Public)

- `GET /api/public/discover/trending?time_window=week&limit=10`
- `GET /api/public/discover/similar/{task_id}?limit=5`
- `GET /api/public/discover/recent?category=entertainment&limit=10`
- `GET /api/public/discover/categories`

### 3. Task Management (Private)

#### Submit Task

`POST /api/tasks`

**Headers:** `X-API-Key: your-api-key`

**Content-Type:** `application/json`

```json
{
  "url": "https://youtube.com/watch?v=xyz",
  "extract_audio": true,
  "save_thumbnail": true
}
```

#### List Tasks

`GET /api/tasks`

**Headers:** `X-API-Key: your-api-key`

#### Delete Task

`DELETE /api/tasks/{task_id}`

**Headers:** `X-API-Key: your-api-key`

### 4. Health & Testing

- `GET /api/healthcheck`
- `GET /api/test` (Test OpenAI Connection)

## Request/Response Models

### TranscriptionRequest
```typescript
interface TranscriptionRequest {
  url: string;                          // Required: Video URL
  callback_url?: string;                // Optional: Webhook URL
  format?: string;                      // Default: "bestaudio/best"
  extract_audio?: boolean;              // Default: true
  convert_to_mp3?: boolean;             // Default: false
  save_thumbnail?: boolean;             // Default: true
  extract_metadata?: boolean;           // Default: true
  perform_sentiment_analysis?: boolean; // Default: false
  create_srt?: boolean;                 // Default: false
  proxy?: string;                       // Optional: Proxy URL
}
```

### TranscriptionResponse
```typescript
interface TranscriptionResponse {
  task_id: string;
  status: "pending" | "processing" | "completed" | "failed";
  video_id?: string;
  title?: string;
  created_at: string;
  error?: string;
  thumbnail?: string;
  thumbnail_url?: string;
  thumbnail_local_path?: string;
}
```

## Usage Examples

### JavaScript/Node.js
```js
// Start transcription
const response = await fetch('https://api.scribetok.com/api/public/transcribe', {
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

// Check status
const statusResponse = await fetch(`https://api.scribetok.com/api/public/tasks/${task.task_id}`);
const status = await statusResponse.json();
console.log('Status:', status.status);

// Get transcript when completed
if (status.status === 'completed') {
  const transcript = await fetch(`https://api.scribetok.com/api/public/transcript/${task.task_id}`);
  const transcriptText = await transcript.text();
  console.log('Transcript:', transcriptText);
}
```

### Python
```python
import requests
import time

# Start transcription
response = requests.post(
    'https://api.scribetok.com/api/public/transcribe',
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
    status_response = requests.get(f'https://api.scribetok.com/api/public/tasks/{task_id}')
    status = status_response.json()

    if status['status'] == 'completed':
        # Get transcript
        transcript_response = requests.get(f'https://api.scribetok.com/api/public/transcript/{task_id}')
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
curl -X POST "https://api.scribetok.com/api/public/transcribe" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://tiktok.com/@user/video/123", "save_thumbnail": true}'

# Check status
curl "https://api.scribetok.com/api/public/tasks/your-task-id"

# Get transcript
curl "https://api.scribetok.com/api/public/transcript/your-task-id"
```

## Error Handling

### Common Error Codes
- 400: Bad request (invalid URL, transcription failed)
- 401: Unauthorized (invalid API key for private endpoints)
- 404: Not found (task not found, file not found)
- 500: Internal server error

### Error Response Format
```json
{
  "detail": "Error message description"
}
```

## Rate Limits
- Public endpoints: No specific rate limits (subject to server capacity)
- Private endpoints: Depends on API key configuration

## Interactive Documentation
- [Swagger UI](https://api.scribetok.com/docs)
- [ReDoc](https://api.scribetok.com/redoc)

This API provides comprehensive video transcription capabilities with both public access for discovery and private authenticated access for advanced features. 