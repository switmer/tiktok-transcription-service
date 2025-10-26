# Deploying TikTok Transcriber on Render

Since you already use Render, that's a perfect choice! Render has FFmpeg pre-installed in their environments, making it ideal for our TikTok transcription service. Here's how to set it up:

## Step 1: Prepare Your Project Structure

First, organize your project with these key files:

```
tiktok-transcriber/
├── app.py               # FastAPI/Flask web service
├── transcriber.py       # Core transcription logic
├── requirements.txt     # Dependencies
└── render.yaml          # Render configuration
```

## Step 2: Create the Web Service (app.py)

Let's create a FastAPI service:

```python
# app.py
import os
import json
from datetime import datetime
import uuid
from fastapi import FastAPI, BackgroundTasks, HTTPException, Depends, Header
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any
import uvicorn

# Import your transcription code
from transcriber import download_tiktok, transcribe_audio

app = FastAPI(title="TikTok Transcription API")

# In-memory storage for task results (in production, use a database)
tasks: Dict[str, Dict[str, Any]] = {}

class TranscriptionRequest(BaseModel):
    url: str
    callback_url: Optional[str] = None

class TranscriptionResponse(BaseModel):
    task_id: str
    status: str
    video_id: Optional[str] = None
    title: Optional[str] = None
    created_at: str

# Simple API key auth
def verify_api_key(x_api_key: Optional[str] = Header(None)):
    # In production, use a secure method to store and validate API keys
    valid_api_key = os.environ.get("API_KEY", "test-api-key")
    if not x_api_key or x_api_key != valid_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return x_api_key

@app.post("/api/transcribe", response_model=TranscriptionResponse)
async def transcribe_tiktok(
    request: TranscriptionRequest, 
    background_tasks: BackgroundTasks,
    api_key: str = Depends(verify_api_key)
):
    # Generate unique task ID
    task_id = str(uuid.uuid4())
    
    # Create output directory
    output_dir = f"downloads/{task_id}"
    os.makedirs(output_dir, exist_ok=True)
    
    # Initialize task
    tasks[task_id] = {
        "task_id": task_id,
        "status": "queued",
        "url": request.url,
        "created_at": datetime.now().isoformat()
    }
    
    # Process in background
    background_tasks.add_task(
        process_video, 
        task_id=task_id,
        url=request.url,
        output_dir=output_dir,
        callback_url=request.callback_url
    )
    
    return tasks[task_id]

@app.get("/api/tasks/{task_id}")
async def get_task_status(task_id: str, api_key: str = Depends(verify_api_key)):
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    return tasks[task_id]

@app.get("/api/transcript/{task_id}")
async def get_transcript(task_id: str, api_key: str = Depends(verify_api_key)):
    if task_id not in tasks or tasks[task_id]["status"] != "completed":
        raise HTTPException(status_code=404, detail="Transcript not found or processing incomplete")
    
    transcript_path = tasks[task_id].get("transcript_file")
    if not transcript_path or not os.path.exists(transcript_path):
        raise HTTPException(status_code=404, detail="Transcript file not found")
    
    return FileResponse(transcript_path)

async def process_video(task_id: str, url: str, output_dir: str, callback_url: Optional[str] = None):
    import httpx
    
    try:
        # Update task status
        tasks[task_id]["status"] = "downloading"
        
        # Download video and extract audio
        mp3_file, video_id, title = download_tiktok(url, output_dir)
        
        # Update task info
        tasks[task_id]["video_id"] = video_id
        tasks[task_id]["title"] = title
        
        if not mp3_file:
            tasks[task_id]["status"] = "failed"
            tasks[task_id]["error"] = "Failed to download video"
            return
        
        # Update task status
        tasks[task_id]["status"] = "transcribing"
        
        # Transcribe audio
        transcript, transcript_file = transcribe_audio(mp3_file, output_dir, video_id)
        
        if not transcript:
            tasks[task_id]["status"] = "failed"
            tasks[task_id]["error"] = "Failed to transcribe audio"
            return
        
        # Update task with results
        tasks[task_id]["status"] = "completed"
        tasks[task_id]["transcript"] = transcript
        tasks[task_id]["transcript_file"] = transcript_file
        tasks[task_id]["completed_at"] = datetime.now().isoformat()
        
        # Send callback if provided
        if callback_url:
            async with httpx.AsyncClient() as client:
                await client.post(
                    callback_url, 
                    json={
                        "task_id": task_id,
                        "status": "completed",
                        "transcript_url": f"/api/transcript/{task_id}"
                    }
                )
    
    except Exception as e:
        # Update task with error
        tasks[task_id]["status"] = "failed"
        tasks[task_id]["error"] = str(e)
        
        # Send error callback if provided
        if callback_url:
            async with httpx.AsyncClient() as client:
                await client.post(
                    callback_url, 
                    json={
                        "task_id": task_id,
                        "status": "failed",
                        "error": str(e)
                    }
                )

if __name__ == "__main__":
    # Create downloads directory
    os.makedirs("downloads", exist_ok=True)
    
    # Get port from environment or use default
    port = int(os.environ.get("PORT", 8000))
    
    # Run the app
    uvicorn.run(app, host="0.0.0.0", port=port)
```

## Step 3: Create the Transcriber Module (transcriber.py)

Let's extract the core functionality from your existing script:

```python
# transcriber.py
import os
import re
from datetime import datetime
import yt_dlp
from openai import OpenAI

# Initialize OpenAI client
client = OpenAI()  # Uses OPENAI_API_KEY from environment

def download_tiktok(url: str, output_dir: str):
    """Download TikTok video and extract audio"""
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'outtmpl': os.path.join(output_dir, '%(id)s.%(ext)s'),
        'writeinfojson': True,
        'writethumbnail': True,
        'quiet': False,
    }
    
    try:
        # Extract info without downloading
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            video_id = info.get('id')
            title = info.get('title')
            
            print(f"Video ID: {video_id}")
            print(f"Title: {title}")
        
        # Download the video
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        # Find the downloaded mp3 file
        mp3_file = None
        for file in os.listdir(output_dir):
            if file.endswith('.mp3'):
                mp3_file = os.path.join(output_dir, file)
                break
        
        return mp3_file, video_id, title
    
    except Exception as e:
        print(f"Error downloading video: {str(e)}")
        return None, None, None

def transcribe_audio(audio_file: str, output_dir: str, video_id: str):
    """Transcribe audio file using OpenAI's Whisper API"""
    try:
        print(f"Transcribing audio file: {audio_file}")
        
        with open(audio_file, "rb") as audio:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio,
                response_format="text"
            )
        
        # Save transcript to file
        transcript_file = os.path.join(output_dir, f"{video_id}_transcript.txt")
        with open(transcript_file, "w", encoding="utf-8") as f:
            f.write(transcript)
        
        print(f"Transcript saved to: {transcript_file}")
        return transcript, transcript_file
    
    except Exception as e:
        print(f"Error transcribing audio: {str(e)}")
        return None, None
```

## Step 4: Create requirements.txt

```
fastapi==0.109.0
uvicorn==0.27.0
yt-dlp==2025.3.31
openai==1.73.0
httpx==0.28.1
python-multipart==0.0.9
pydantic==2.11.3
```

## Step 5: Create render.yaml

```yaml
services:
  - type: web
    name: tiktok-transcriber
    env: python
    plan: starter
    buildCommand: pip install -r requirements.txt
    startCommand: python app.py
    envVars:
      - key: OPENAI_API_KEY
        sync: false  # Will be set manually
      - key: API_KEY
        sync: false  # Will be set manually
      - key: PORT
        value: 10000
    disk:
      name: downloads
      mountPath: /opt/render/project/src/downloads
      sizeGB: 10
```

## Step 6: Deploy to Render

1. **Push your code to GitHub or GitLab**

2. **Create a new Web Service on Render**:
   - Connect your repository
   - Select "Use render.yaml" 
   - Set your environment variables:
     - `OPENAI_API_KEY`: Your OpenAI API key
     - `API_KEY`: A secure API key for your service

3. **Deploy your service**:
   - Render will automatically detect your render.yaml and deploy accordingly

## Step 7: Using Your API

### Example API Usage with curl:

```bash
# Submit a transcription request
curl -X POST "https://your-render-service.onrender.com/api/transcribe" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{"url": "https://www.tiktok.com/@username/video/1234567890"}'

# Check task status
curl "https://your-render-service.onrender.com/api/tasks/your-task-id" \
  -H "X-API-Key: your-api-key"

# Get transcript
curl "https://your-render-service.onrender.com/api/transcript/your-task-id" \
  -H "X-API-Key: your-api-key"
```

### Example API Usage with JavaScript:

```javascript
// Submit a transcription request
async function transcribeTikTok(url) {
  const response = await fetch('https://your-render-service.onrender.com/api/transcribe', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-API-Key': 'your-api-key'
    },
    body: JSON.stringify({ url })
  });
  
  return response.json();
}

// Check task status
async function checkTaskStatus(taskId) {
  const response = await fetch(`https://your-render-service.onrender.com/api/tasks/${taskId}`, {
    headers: {
      'X-API-Key': 'your-api-key'
    }
  });
  
  return response.json();
}

// Usage
const { task_id } = await transcribeTikTok('https://www.tiktok.com/@username/video/1234567890');
console.log(`Task ID: ${task_id}`);

// Poll for completion
const checkInterval = setInterval(async () => {
  const task = await checkTaskStatus(task_id);
  console.log(`Status: ${task.status}`);
  
  if (task.status === 'completed' || task.status === 'failed') {
    clearInterval(checkInterval);
    console.log('Task completed!');
    console.log(task);
  }
}, 5000);
```

## Additional Considerations for Production

1. **Database**: Replace the in-memory task storage with a database
   - Add `sqlalchemy` and `databases` to your requirements.txt
   - Use PostgreSQL (Render provides managed databases)

2. **Rate Limiting**: Add API rate limiting
   - Add `slowapi` to your requirements.txt
   
3. **Authentication**: Implement proper authentication
   - Consider using JWT tokens instead of API keys

4. **Monitoring**: Set up monitoring and logging
   - Add `sentry-sdk` to capture errors
   - Implement structured logging

5. **Scaling**: Consider background worker architecture
   - Use Redis for task queuing (available as Render add-on)
   - Separate download and transcription logic

This setup gives you a production-ready TikTok transcription service on Render that leverages the platform's strengths while avoiding Docker complexity!


---
You're right to focus on the actual dependencies of our `downloader.py` script. Let's analyze what components are essential for our TikTok transcription service to work:

## Core Dependencies of `downloader.py`

1. **yt-dlp**: Essential for downloading TikTok videos
2. **FFmpeg**: Required by yt-dlp for audio extraction
3. **OpenAI API**: For transcription with Whisper
4. **Python libraries**: Several standard and third-party libraries

Here's a breakdown of all dependencies:

```
# External Binaries
- FFmpeg (system dependency)

# Python Packages
- yt-dlp (for downloading videos)
- openai (for transcription API)
- pydub (for audio processing)
- datetime, os, sys, json, re (standard libraries)
```

## Deployment Challenges

The main challenge with deploying this service is **FFmpeg**. It's a system-level dependency that:

1. Cannot be installed via pip
2. Requires proper system libraries
3. Makes deployment more complex on serverless platforms

This is why Docker is often used - it bundles all these dependencies neatly. However, if you want to avoid Docker, you have a few options:

## Non-Docker Deployment Options (Considering Dependencies)

### 1. Managed VPS (Virtual Private Server)

**Example: DigitalOcean Droplet or Linode**

```bash
# Install system dependencies
sudo apt update
sudo apt install -y ffmpeg python3-pip

# Clone your repo
git clone https://github.com/yourusername/tiktok-transcriber.git
cd tiktok-transcriber

# Install Python dependencies
pip install -r requirements.txt

# Run the service
python3 app.py
```

**Pros**: Simple, full control, can install system packages
**Cons**: Manual scaling, requires server management

### 2. Google Cloud Run (without Dockerfile)

Cloud Run can use buildpacks instead of Docker:

```bash
# Create a requirements.txt
echo "yt-dlp==2025.3.31
openai==1.73.0
pydub==0.25.1" > requirements.txt

# Create an app.yaml (includes FFmpeg installation)
cat > app.yaml << EOF
runtime: python39
instance_class: F2

entrypoint: gunicorn -b :$PORT main:app

build_env_variables:
  GOOGLE_ENTRYPOINT: "apt-get update && apt-get install -y ffmpeg && exec gunicorn -b :$PORT main:app"
EOF

# Deploy
gcloud app deploy
```

### 3. Render.com (Simpler than Docker, has FFmpeg pre-installed)

Just connect your GitHub repo and Render will detect Python and automatically build it.

### 4. Railway (Supports FFmpeg out of the box)

```bash
# Install Railway CLI
npm i -g @railway/cli

# Initialize project
railway init

# Deploy (Railway auto-detects Python)
railway up
```

### 5. Fly.io (Simplifies Docker)

Fly.io uses Docker under the hood but makes it incredibly simple:

```bash
# Install flyctl
curl -L https://fly.io/install.sh | sh

# Generate a fly.toml file
fly launch

# This creates a Dockerfile for you with appropriate dependencies
fly deploy
```

## Most Pragmatic Approach: PythonAnywhere

For the specific case of a TikTok transcriber, PythonAnywhere is ideal because:

1. FFmpeg is pre-installed
2. It's designed for Python hosting
3. Super simple setup
4. Reasonable pricing
5. No Docker or complex deployment needed

```bash
# On PythonAnywhere console:
pip install --user yt-dlp openai pydub

# Then upload your script or git clone it
git clone https://github.com/yourusername/tiktok-transcriber.git

# Set up a web app through their interface pointing to your application
```

## If You Absolutely Need Serverless

For a truly serverless approach that handles FFmpeg:

### AWS Lambda with Lambda Layers

1. Create a Lambda Layer containing FFmpeg binaries
2. Upload your function code separately
3. Attach the FFmpeg layer to your function

```bash
# Download pre-compiled FFmpeg for Lambda
curl -O https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz
tar xf ffmpeg-release-amd64-static.tar.xz

# Create layer structure
mkdir -p ffmpeg-layer/bin
cp ffmpeg-4.4-amd64-static/ffmpeg ffmpeg-layer/bin/

# Package layer
cd ffmpeg-layer
zip -r ../ffmpeg-layer.zip .

# Upload to AWS
aws lambda publish-layer-version \
    --layer-name ffmpeg \
    --zip-file fileb://ffmpeg-layer.zip
```

Then create your Lambda function and attach this layer.

## Conclusion

Given the dependency on FFmpeg, your most straightforward non-Docker options are:

1. **PythonAnywhere**: Simplest solution with FFmpeg pre-installed
2. **Railway/Render**: Platform-as-a-Service with FFmpeg support
3. **Fly.io**: Simplifies Docker without you having to write Dockerfiles
4. **Standard VPS**: Complete control, easy FFmpeg installation

The fastest path to getting your service up and running would be PythonAnywhere or Railway, as they require minimal configuration while supporting all your dependencies.
