"""Model registry for Alembic autogenerate.

Import every module's SQLAlchemy models here so `Base.metadata` knows all tables.
"""

from app.modules.auth.infrastructure.models import RefreshTokenModel
from app.modules.staff.infrastructure.models import UserModel
from app.modules.tenants.infrastructure.models import TenantModel
from app.shared.infrastructure.database import Base

__all__ = ["Base", "RefreshTokenModel", "TenantModel", "UserModel"]
