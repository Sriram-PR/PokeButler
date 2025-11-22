import os
import sys
from unittest.mock import MagicMock

import pytest

# Add project root to python path so we can import modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# REMOVED: event_loop fixture (pytest-asyncio handles this now)


@pytest.fixture
def mock_db(mocker):
    """Mock the database to prevent file creation."""
    mock_db_instance = MagicMock()

    # Mock the get_database function to return our mock
    mocker.patch("utils.database.get_database", return_value=mock_db_instance)

    # Mock basic db methods
    mock_db_instance.get_cache.return_value = None
    mock_db_instance.set_cache.return_value = True

    return mock_db_instance
