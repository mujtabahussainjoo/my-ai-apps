"""Persistence layer.

Sub-modules are imported lazily by consumers (``from src.database.models import
Order``) so that importing this package never opens a database connection.
"""

from src.database.base import Base, JSONType, new_id, utcnow
from src.database.session import get_db, get_engine, ping, session_scope

__all__ = ["Base", "JSONType", "get_db", "get_engine", "new_id", "ping", "session_scope", "utcnow"]
