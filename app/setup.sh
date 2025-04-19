#!/bin/bash

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR/.."

echo "Setting up TikTok Transcription Service..."

# Create virtual environment
echo "Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate

# Install dependencies with specific versions to avoid conflicts
echo "Installing dependencies..."
pip install --upgrade pip
pip install "fastapi<0.100.0" "pydantic<2.0.0" uvicorn python-dotenv python-multipart openai yt-dlp requests

# Create requirements.txt if needed
if [ ! -f "$SCRIPT_DIR/requirements.txt" ]; then
    echo "Creating requirements.txt..."
    echo "fastapi<0.100.0" > "$SCRIPT_DIR/requirements.txt"
    echo "pydantic<2.0.0" >> "$SCRIPT_DIR/requirements.txt"
    echo "uvicorn" >> "$SCRIPT_DIR/requirements.txt"
    echo "python-dotenv" >> "$SCRIPT_DIR/requirements.txt"
    echo "python-multipart" >> "$SCRIPT_DIR/requirements.txt"
    echo "openai" >> "$SCRIPT_DIR/requirements.txt"
    echo "yt-dlp" >> "$SCRIPT_DIR/requirements.txt"
    echo "requests" >> "$SCRIPT_DIR/requirements.txt"
fi

# Check if .env file exists
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo "Creating .env file template..."
    echo "OPENAI_API_KEY=your_openai_api_key" > "$SCRIPT_DIR/.env"
    echo "API_KEY=your_custom_api_key_for_service" >> "$SCRIPT_DIR/.env"
    echo ".env file created. Please update with your actual API keys before running the service."
fi

# Create necessary directories
echo "Creating output directories..."
mkdir -p "$SCRIPT_DIR/downloads"

echo "Setup complete!"
echo "To start the service, run: ./app/start.sh" 