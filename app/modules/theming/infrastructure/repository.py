import uuid

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.theming.domain.repository import ThemeRecord
from app.modules.theming.domain.theme import Theme, parse_theme
from app.modules.theming.infrastructure.models import ThemeModel


def _to_record(model: ThemeModel) -> ThemeRecord:
    return ThemeRecord(
        id=model.id,
        tenant_id=model.tenant_id,
        draft=parse_theme(model.draft, model.tenant_id),
        published=parse_theme(model.published, model.tenant_id) if model.published is not None else None,
        published_at=model.published_at,
    )


class SqlAlchemyThemeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, tenant_id: uuid.UUID) -> ThemeRecord | None:
        model = await self._session.scalar(select(ThemeModel).where(ThemeModel.tenant_id == tenant_id))
        return _to_record(model) if model is not None else None

    async def lock(self, tenant_id: uuid.UUID, initial: Theme) -> ThemeRecord:
        # The unique tenant_id decides who creates the record; everyone then waits on its row lock.
        await self._session.execute(
            insert(ThemeModel)
            .values(id=uuid.uuid4(), tenant_id=tenant_id, draft=initial.to_dict())
            .on_conflict_do_nothing(index_elements=[ThemeModel.tenant_id])
        )
        model = await self._session.scalar(
            select(ThemeModel)
            .where(ThemeModel.tenant_id == tenant_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        assert model is not None
        return _to_record(model)

    async def update(self, record: ThemeRecord) -> None:
        await self._session.execute(
            update(ThemeModel)
            .where(ThemeModel.id == record.id, ThemeModel.tenant_id == record.tenant_id)
            .values(
                draft=record.draft.to_dict(),
                published=record.published.to_dict() if record.published is not None else None,
                published_at=record.published_at,
            )
        )
