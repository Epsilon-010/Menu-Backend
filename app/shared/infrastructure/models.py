"""Model registry for Alembic autogenerate.

Import every module's SQLAlchemy models here so `Base.metadata` knows all tables.
"""

from app.modules.auth.infrastructure.models import RefreshTokenModel
from app.modules.catalog.infrastructure.models import CategoryModel, ItemModel
from app.modules.media.infrastructure.models import ImageUploadModel
from app.modules.orders.infrastructure.models import (
    BillModel,
    CartLineModel,
    CartModel,
    GuestModel,
    OrderCounterModel,
    OrderItemModel,
    OrderModel,
)
from app.modules.staff.infrastructure.models import UserModel
from app.modules.tables.infrastructure.models import TableModel
from app.modules.tenants.infrastructure.models import TenantModel
from app.shared.infrastructure.database import Base

__all__ = [
    "Base",
    "BillModel",
    "CartLineModel",
    "CartModel",
    "CategoryModel",
    "GuestModel",
    "ImageUploadModel",
    "ItemModel",
    "OrderCounterModel",
    "OrderItemModel",
    "OrderModel",
    "RefreshTokenModel",
    "TableModel",
    "TenantModel",
    "UserModel",
]
