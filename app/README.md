# ScribeTok - TikTok/YouTube Transcription Service

A comprehensive FastAPI service that transcribes TikTok and YouTube videos with SMS integration and phone-first authentication.

## 📚 **Complete API Documentation**

**👉 See [COMPLETE_API_DOCS.md](../COMPLETE_API_DOCS.md) for full API reference including all endpoints, SMS integration, and new features.**

## ✨ Features

### Core Transcription
- Download TikTok and YouTube videos
- Extract audio with multiple fallback methods (RapidAPI + yt-dlp)
- Transcribe using OpenAI Whisper with timestamps
- Rich metadata extraction (20+ fields)
- Direct CDN video URLs (no local storage)

### SMS Integration
- Full SMS workflow with Twilio
- Phone-first authentication (no email required)
- SMS commands: `/help`, `/register`, `/login`, `/verify`, `/profile`, `/vault`
- Account linking for SMS users
- SMS analytics and tracking

### Content Discovery
- Trending transcriptions
- Similar content recommendations
- Category-based browsing
- Public transcript viewer with viral sharing

### Advanced Features
- Background task processing
- API key authentication
- File cleanup and resource management
- Error resilience and graceful degradation
- Auto-tagging and content classification

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

## 🚀 Quick API Examples

**📖 See [COMPLETE_API_DOCS.md](../COMPLETE_API_DOCS.md) for full endpoint documentation**

### Start Transcription (Public)
```bash
curl -X POST "https://api.scribetok.com/api/public/transcribe" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://tiktok.com/@user/video/123"}'
```

### Check Status
```bash
curl "https://api.scribetok.com/api/public/tasks/{task_id}"
```

### Get Transcript
```bash
curl "https://api.scribetok.com/api/public/transcript/{task_id}"
```

### SMS Integration
Send TikTok URL via SMS to your Twilio number for instant transcription!

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

## SwiftBar 101 (Menu-bar Transcription Tool)

SwiftBar lets any script become a macOS menu-bar item. We ship a plugin that wraps `app/local_scripts/transcribe_video.py` so you can transcribe any media file from the menu bar.

Quick start:
```bash
brew install swiftbar
mkdir -p "$HOME/Library/Application Support/SwiftBar/Plugins"
# The plugin is created automatically by our setup, but if needed place
# transcribe_anything.sh in that folder and make it executable:
# chmod +x "$HOME/Library/Application Support/SwiftBar/Plugins/transcribe_anything.sh"
```

Usage:
- Click the "Transcribe" menubar item → Pick file(s) → transcripts are saved next to originals as `_transcript.txt` (also `.srt`/`.vtt`).
- Choose model via the plugin menu (persisted).
- View progress live in the menu title; open logs via "Open last log".
- Cancel mid-run from the menu; jobs are killed as a process group.

Progress convention:
- Our Python tool prints lines like `PROGRESS: 0.42` to STDERR.
- The plugin parses these to render percent; keep this if you extend the tool.

Troubleshooting:
- If ffmpeg isn’t found, install with `brew install ffmpeg`.
- Ensure `openai-whisper` or `faster-whisper` is installed in the Python environment used by `/usr/bin/python3`.
- If the menu doesn’t appear, relaunch SwiftBar or verify the Plugins folder path. 