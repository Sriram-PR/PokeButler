import asyncio
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio  # NEW IMPORT

from utils.api_clients import SmogonAPIClient
from utils.circuit_breaker import CircuitBreakerError


@pytest.mark.asyncio
class TestSmogonAPIClient:
    # CHANGED: @pytest.fixture -> @pytest_asyncio.fixture
    @pytest_asyncio.fixture
    async def client(self, mock_db):
        client = SmogonAPIClient()
        yield client
        await client.close()

    async def test_deduplication(self, client):
        """Test that concurrent requests for same resource only trigger one fetch"""

        # Create a mock fetch function that sleeps slightly
        mock_fetch = AsyncMock(return_value={"some": "data"})

        async def slow_fetch():
            await asyncio.sleep(0.1)
            return await mock_fetch()

        # Launch 5 simultaneous requests
        tasks = [client._deduplicate_request("test_key", slow_fetch) for _ in range(5)]

        results = await asyncio.gather(*tasks)

        # All should return same data
        for res in results:
            assert res == {"some": "data"}

        # The actual fetch should have only been called ONCE
        assert mock_fetch.call_count == 1

    async def test_circuit_breaker_activates(self, client):
        """Test that circuit breaker opens after failures"""

        # Reduce threshold for testing
        client._smogon_breaker.failure_threshold = 2
        client._smogon_breaker.recovery_timeout = 1

        # Mock a function that always fails
        async def failing_func():
            raise asyncio.TimeoutError("Fail")

        # Fail twice to open breaker
        with pytest.raises(asyncio.TimeoutError):
            await client._smogon_breaker.call(failing_func)
        with pytest.raises(asyncio.TimeoutError):
            await client._smogon_breaker.call(failing_func)

        # Third call should raise CircuitBreakerError instantly
        with pytest.raises(CircuitBreakerError):
            await client._smogon_breaker.call(failing_func)
