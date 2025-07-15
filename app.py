"""
Entry point for the application.
"""
import os
import sys

# Add the app directory to the path
app_dir = os.path.join(os.path.dirname(__file__), 'app')
sys.path.insert(0, app_dir)

# Import the FastAPI app instance from app/app.py
try:
    from app.app import app
except ImportError:
    # Fallback import path
    sys.path.append(os.path.join(os.path.dirname(__file__), 'app'))
    from app import app

# Make sure the app is available at module level
__all__ = ['app']

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000"))) 