from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.gemini_usage import GeminiUsageDaily


class GeminiDailyLimitExceeded(Exception):
    def __init__(self, limit: int, call_count: int) -> None:
        self.limit = limit
        self.call_count = call_count
        super().__init__(
            f"Gemini daily call limit reached ({call_count}/{limit}). Try again after midnight UTC."
        )


class GeminiUsageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def increment_and_check(self, limit: int) -> int:
        """
        Atomically increments today's call count and raises if the new count
        exceeds limit. A single INSERT...ON CONFLICT...RETURNING takes a row
        lock on today's date, so concurrent requests serialize correctly
        instead of racing on a read-then-write. The increment happens even
        on the call that trips the limit — a rejected call still costs an
        attempt slot, which is correct for a cost-safety counter.
        """
        today = datetime.now(timezone.utc).date()
        stmt = (
            pg_insert(GeminiUsageDaily)
            .values(date=today, call_count=1)
            .on_conflict_do_update(
                index_elements=[GeminiUsageDaily.date],
                set_={"call_count": GeminiUsageDaily.call_count + 1},
            )
            .returning(GeminiUsageDaily.call_count)
        )
        result = await self._session.execute(stmt)
        call_count = result.scalar_one()
        await self._session.commit()

        if call_count > limit:
            raise GeminiDailyLimitExceeded(limit, call_count)
        return call_count
