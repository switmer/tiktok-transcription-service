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

## Deployment

### Render.com Deployment

This app is configured for deployment on Render.com. The deployment configuration is in `render.yaml`.

**CRITICAL:** Make sure the render.yaml contains:
```yaml
buildCommand: cd app && pip install -r requirements.txt
startCommand: cd app && uvicorn app:app --host 0.0.0.0 --port $PORT
```

**Common deployment issues:**
1. **"Attribute 'app' not found"** - This happens when uvicorn can't find the FastAPI app. Make sure:
   - The working directory is set to the `app` folder 
   - The startCommand includes `cd app &&`
   - The app variable is properly defined in app.py

2. **Environment variables** - Set these in Render dashboard:
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_KEY` 
   - `OPENAI_API_KEY`

### Local Development

Start the FastAPI server:
```bash
cd app
uvicorn app:app --reload
```

## Output Files

The service creates the following directory structure:
```
downloads/
├── {task_id}/     # Task-specific folder
    ├── audio/     # Extracted audio files
    ├── video/     # Downloaded videos
    └── transcript.txt # Generated transcript
``` 