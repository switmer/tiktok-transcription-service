#!/bin/bash

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR/.."

# Check if virtual environment exists, if not run setup
if [ ! -d "venv" ]; then
    echo "Virtual environment not found. Running setup first..."
    "$SCRIPT_DIR/setup.sh"
fi

# Activate virtual environment
source venv/bin/activate

# Start the service
echo "Starting TikTok Transcription Service..."
cd "$SCRIPT_DIR"
uvicorn app:app --reload

# To stop the service, press CTRL+C 