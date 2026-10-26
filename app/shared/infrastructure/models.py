"""Model registry for Alembic autogenerate.

Import every module's SQLAlchemy models here so `Base.metadata` knows all tables.
"""

from app.shared.infrastructure.database import Base

__all__ = ["Base"]
