# TikTok Transcription Service

A FastAPI web service that downloads TikTok videos and transcribes them using OpenAI's Whisper API.

## Features

- Download TikTok videos
- Extract audio from videos
- Transcribe audio using OpenAI's Whisper API
- RESTful API for submitting, checking, and retrieving transcription tasks
- Background task processing
- API key authentication

## Setup

1. Clone the repository
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Create a `.env` file in the app directory with the following:
   ```
   OPENAI_API_KEY=your_openai_api_key
   API_KEY=your_custom_api_key_for_service
   ```

## Running the Service

Start the FastAPI server:

```
uvicorn app:app --reload
```

The service will be available at http://localhost:8000

## API Endpoints

### Submit a transcription task
```
POST /api/transcribe
```

Request body:
```json
{
  "url": "https://www.tiktok.com/@username/video/1234567890"
}
```

Headers:
```
X-API-Key: your_api_key
```

### List all tasks
```
GET /api/tasks
```

### Check task status
```
GET /api/tasks/{task_id}
```

### Get transcript
```
GET /api/transcript/{task_id}
```

### Delete task
```
DELETE /api/tasks/{task_id}
```

### Health check
```
GET /api/healthcheck
```

## Output Files

The service creates the following directory structure:
```
output/
├── videos/        # Downloaded TikTok videos
├── audio/         # Extracted audio files
└── transcripts/   # Generated transcripts
``` 