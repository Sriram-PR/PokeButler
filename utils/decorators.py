"""
Reusable decorators for the bot.

This module contains decorators for common functionality such as:
- Automatic retries with exponential backoff.
- Command usage logging.
- Unified deferral logic for hybrid commands (handling both slash and text context).
"""

import asyncio
import logging
from functools import wraps
from typing import Callable, Type, Union

import aiohttp
from discord.ext import commands

from utils.constants import (
    DEFAULT_RETRY_ATTEMPTS,
    RETRY_BASE_DELAY,
    RETRY_MAX_DELAY,
)

logger = logging.getLogger("smogon_bot.decorators")


def retry_on_error(
    max_retries: int = DEFAULT_RETRY_ATTEMPTS,
    exceptions: Union[Type[Exception], tuple] = (
        aiohttp.ClientError,
        asyncio.TimeoutError,
    ),
    base_delay: float = RETRY_BASE_DELAY,
    max_delay: float = RETRY_MAX_DELAY,
):
    """
    Decorator to retry async functions on specific exceptions with exponential backoff.

    The delay formula is: `delay = min(base_delay * (2^attempt), max_delay)`.

    Args:
        max_retries: Maximum number of retry attempts before giving up.
        exceptions: Exception type or tuple of exceptions to catch and retry.
        base_delay: Initial delay in seconds.
        max_delay: Maximum delay in seconds between retries (caps the backoff).

    Returns:
        Decorated function wrapper.

    Raises:
        Exception: The last exception encountered if all retries fail.
    """

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e

                    if attempt == max_retries - 1:
                        logger.error(
                            f"{func.__name__} failed after {max_retries} attempts: {e}"
                        )
                        raise

                    # Calculate delay with exponential backoff
                    delay = min(base_delay * (2**attempt), max_delay)

                    logger.warning(
                        f"{func.__name__} attempt {attempt + 1}/{max_retries} failed: {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )

                    await asyncio.sleep(delay)

            # This should never be reached due to the raise above, but satisfies static analysis
            if last_exception:
                raise last_exception

        return wrapper

    return decorator


def log_command_usage(func: Callable):
    """
    Decorator to log command usage details.

    Logs the command name, user, and guild context.

    Args:
        func: The command function to decorate.

    Returns:
        Decorated function wrapper.
    """

    @wraps(func)
    async def wrapper(*args, **kwargs):
        # Get context from args (usually the second argument for cog commands)
        ctx = args[1] if len(args) > 1 else kwargs.get("ctx")

        if ctx:
            logger.info(
                f"Command '{func.__name__}' used by {ctx.author} (ID: {ctx.author.id}) "
                f"in guild: {ctx.guild.name if ctx.guild else 'DM'}"
            )

        return await func(*args, **kwargs)

    return wrapper


def hybrid_defer(func: Callable):
    """
    Decorator to handle defer/typing logic for hybrid commands.

    This eliminates code duplication by centralizing the defer pattern.
    It abstracts away the difference between:
    1. Slash commands: `await ctx.defer()` (shows "thinking...")
    2. Prefix commands: `async with ctx.typing():` (shows typing indicator)

    Args:
        func: The command function to decorate.

    Returns:
        Decorated function wrapper.
    """

    @wraps(func)
    async def wrapper(self, ctx: commands.Context, *args, **kwargs):
        # Check if this is a slash command or prefix command
        if ctx.interaction:
            # Slash command - defer the response
            await ctx.defer()
            # Execute the actual command logic
            return await func(self, ctx, *args, **kwargs)
        else:
            # Prefix command - show typing indicator
            async with ctx.typing():
                return await func(self, ctx, *args, **kwargs)

    return wrapper
