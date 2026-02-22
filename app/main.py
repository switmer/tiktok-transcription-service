from .app import app
from .api import public as public_routes
from .api import sms as sms_routes
from .api import chat as chat_routes
from .api import auth as auth_routes

app.include_router(public_routes.router)
app.include_router(sms_routes.router)
app.include_router(chat_routes.router)
app.include_router(auth_routes.router)
