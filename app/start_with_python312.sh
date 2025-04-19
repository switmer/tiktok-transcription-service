#!/bin/bash

# Exit on error
set -e

# Check if Python 3.12 is installed
if ! command -v python3.12 &> /dev/null
then
    echo "Python 3.12 is required but not found. Please install it."
    exit 1
fi

# Get the project root directory
PROJECT_ROOT=$(cd .. && pwd)

# Create a Python 3.12 virtual environment if it doesn't exist
if [ ! -d "$PROJECT_ROOT/venv-py312" ]; then
    echo "Creating Python 3.12 virtual environment..."
    cd "$PROJECT_ROOT" && python3.12 -m venv venv-py312
fi

# Activate the virtual environment
source "$PROJECT_ROOT/venv-py312/bin/activate"

# Install requirements
echo "Installing dependencies..."
cd "$PROJECT_ROOT" && pip install -r requirements.txt

# Start the service
echo "Starting TikTok Transcription Service with Python 3.12..."
cd "$PROJECT_ROOT/app" && uvicorn app:app --reload

# To stop the service, press CTRL+C 