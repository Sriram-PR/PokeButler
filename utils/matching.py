"""
Utility for fuzzy string matching.

This module provides asynchronous wrappers for Python's built-in `difflib`
library. Because fuzzy matching on large datasets is CPU-intensive, these
functions offload execution to a separate thread to avoid blocking the main
asyncio event loop.
"""

import asyncio
import difflib
from typing import List


def _get_close_matches_sync(
    word: str, possibilities: List[str], n: int = 3, cutoff: float = 0.6
) -> List[str]:
    """
    Synchronous wrapper for `difflib.get_close_matches`.

    This function performs the actual CPU-intensive string comparison.

    Args:
        word: The string to find matches for.
        possibilities: A list of valid strings to search against.
        n: The maximum number of close matches to return.
        cutoff: A float in [0, 1]. Possibilities that don't score at least
            this similar to word are ignored.

    Returns:
        A list of the best matches, sorted by similarity score.
    """
    return difflib.get_close_matches(word, possibilities, n=n, cutoff=cutoff)


async def get_close_matches_async(
    word: str, possibilities: List[str], n: int = 3, cutoff: float = 0.6
) -> List[str]:
    """
    Asynchronous wrapper for fuzzy matching.

    This function offloads the CPU-bound `difflib` operation to a thread pool
    using `asyncio.to_thread`. This ensures that the bot remains responsive to
    other events (like heartbeats or other commands) while calculating matches
    against large lists of Pokemon names.

    Args:
        word: The word to find matches for.
        possibilities: List of valid words.
        n: Maximum number of matches to return.
        cutoff: Similarity threshold (0.0 to 1.0).

    Returns:
        List of matched strings.
    """
    if not possibilities:
        return []

    return await asyncio.to_thread(
        _get_close_matches_sync, word, possibilities, n, cutoff
    )
