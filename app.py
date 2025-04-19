"""
Entry point for the application when running from the root directory.
"""
import os
import sys

# Add the app directory to the path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Import the app from app/app.py
from app.app import app

# This file allows running the app from the root directory using:
# uvicorn app:app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000"))) 