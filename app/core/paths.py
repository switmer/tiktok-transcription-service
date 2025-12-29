import os

from fastapi.templating import Jinja2Templates

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(BASE_DIR)

templates_dir = os.path.join(APP_DIR, "templates")
templates = Jinja2Templates(directory=templates_dir)

static_dir = os.path.join(APP_DIR, "static")
os.makedirs(static_dir, exist_ok=True)

DOWNLOADS_DIR = os.path.join(APP_DIR, "downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)
