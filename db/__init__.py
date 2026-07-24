"""Persistence layer for the POC (SQLite behind a thin repository).

Only ``repository`` should touch the database. Swapping to Postgres/Supabase
later should touch this package and nothing else.
"""

from db.repository import SessionRepository  # noqa: F401
