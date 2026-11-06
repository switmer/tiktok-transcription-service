from .app import app, include_api_routers

# Ensure routers are mounted when this module is the ASGI target.
include_api_routers()
