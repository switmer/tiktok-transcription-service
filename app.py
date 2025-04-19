"""
Entry point for the application.
"""
import os
import sys

# Add the app directory to the path
app_dir = os.path.join(os.path.dirname(__file__), 'app')
sys.path.insert(0, app_dir)

# Import all necessary components from app/app.py
from app.app import (
    app,  # The FastAPI instance
    supabase,  # Supabase client
    discovery,  # Discovery routes
    transcriber,  # Transcription logic
)

# The app variable is now directly available for uvicorn to import

# This file allows running the app from the root directory using:
# uvicorn app:app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000"))) 