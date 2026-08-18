"""
Coverage for GeminiUsageRepository.increment_and_check — the boundary
behavior of the in-app Gemini cost-safety net (see DEPLOYMENT_PLAN.md's
"Gemini usage limits" item).

No DB session is actually opened — session.execute is mocked to return
whatever call_count the atomic INSERT...ON CONFLICT...RETURNING would have
produced, since that's the one piece of real logic here (add/commit/refresh
plumbing is exercised end-to-end by the route-level tests instead).
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.repository.gemini_usage_repository import GeminiDailyLimitExceeded, GeminiUsageRepository


def _mock_session(returned_call_count: int) -> MagicMock:
    session = MagicMock()
    execute_result = MagicMock()
    execute_result.scalar_one = MagicMock(return_value=returned_call_count)
    session.execute = AsyncMock(return_value=execute_result)
    session.commit = AsyncMock()
    return session


@pytest.mark.anyio
async def test_allows_the_call_at_exactly_the_limit():
    session = _mock_session(returned_call_count=3)
    repo = GeminiUsageRepository(session)

    call_count = await repo.increment_and_check(limit=3)

    assert call_count == 3
    session.commit.assert_awaited_once()


@pytest.mark.anyio
async def test_blocks_the_call_that_exceeds_the_limit():
    session = _mock_session(returned_call_count=4)
    repo = GeminiUsageRepository(session)

    with pytest.raises(GeminiDailyLimitExceeded) as exc_info:
        await repo.increment_and_check(limit=3)

    assert exc_info.value.limit == 3
    assert exc_info.value.call_count == 4
    # The increment (and its commit) already happened — a rejected call
    # still costs an attempt slot, which is correct for a cost-safety counter.
    session.commit.assert_awaited_once()
