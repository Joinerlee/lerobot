"""
LeRobot Backend API Routes

All API routers are registered here.
"""

from .health import router as health_router
from .robots import router as robots_router
from .sessions import router as sessions_router
from .upload import router as upload_router
from .websocket import router as websocket_router

__all__ = [
    "health_router",
    "robots_router",
    "sessions_router",
    "upload_router",
    "websocket_router",
]
