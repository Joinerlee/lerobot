"""
LeRobot Backend API Module

API routes and dependencies.
"""

from . import routes
from .dependencies import get_db

__all__ = ["routes", "get_db"]
