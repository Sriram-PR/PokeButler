"""
Database module for persistent storage using SQLite.

Handles guild configurations, cache, and game state persistence.
"""

import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional, Set, Tuple
from urllib.parse import urlparse

import aiosqlite

from config.settings import DB_CONNECTION_STRING

logger = logging.getLogger("smogon_bot.database")


class Database:
    """
    Async Database interface for bot persistence.
    Currently supports SQLite via aiosqlite.

    Schema:
    - **guild_configs**: Stores shiny monitoring settings per guild.
      Columns: guild_id (PK), channels (JSON List), archive_channel_id, updated_at.
    - **api_cache**: Stores API responses with expiration and access tracking.
      Columns: cache_key (PK), data (JSON), created_at, last_accessed, access_count.

    WARNING:
        Automated use of the `VACUUM` command is strongly discouraged. It requires
        an EXCLUSIVE lock on the database file, which effectively freezes the
        bot's persistence layer for the duration of the operation. Only run
        vacuum operations during maintenance windows or startup.
    """

    def __init__(self, connection_string: str = DB_CONNECTION_STRING):
        """
        Initialize the database instance.

        Args:
            connection_string: The connection URI (e.g., 'sqlite:///data/bot.db').
        """
        self.connection_string = connection_string
        self._conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

        # Parse connection details
        self.db_type, self.db_path = self._parse_connection_string(connection_string)

    def _parse_connection_string(self, conn_str: str) -> Tuple[str, str]:
        """
        Parse connection string to determine database type and path/host.

        Args:
            conn_str: Connection string in format 'scheme:///path' or
                'scheme://user:pass@host:port/db'.

        Returns:
            Tuple containing (scheme, path).
        """
        try:
            # Handle simple sqlite paths manually to avoid os-specific parsing issues
            if conn_str.startswith("sqlite:///"):
                return "sqlite", conn_str.replace("sqlite:///", "")

            parsed = urlparse(conn_str)
            return parsed.scheme, parsed.path
        except Exception as e:
            logger.error(f"Invalid connection string format: {e}")
            # Fallback safe default
            return "sqlite", "data/bot.db"

    async def connect(self) -> None:
        """
        Initialize database connection and create tables.

        Raises:
            ValueError: If the database type is not supported (currently only 'sqlite').
        """
        if self.db_type == "sqlite":
            await self._connect_sqlite()
        else:
            raise ValueError(
                f"Unsupported database type: {self.db_type}. Only 'sqlite' is currently supported."
            )

    async def _connect_sqlite(self) -> None:
        """Internal method to establish connection to SQLite file."""
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._create_tables()
        logger.info(f"Database connected ({self.db_type}): {self.db_path}")

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            await self._conn.close()
            logger.info("Database connection closed")

    async def _create_tables(self) -> None:
        """Create database tables and indexes if they don't exist."""
        async with self._lock:
            # Guild configurations
            await self._conn.execute(  # type: ignore
                """
                CREATE TABLE IF NOT EXISTS guild_configs (
                    guild_id INTEGER PRIMARY KEY,
                    channels TEXT NOT NULL,
                    archive_channel_id INTEGER,
                    updated_at REAL NOT NULL
                )
            """
            )

            # API cache with size management
            await self._conn.execute(  # type: ignore
                """
                CREATE TABLE IF NOT EXISTS api_cache (
                    cache_key TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    last_accessed REAL NOT NULL,
                    access_count INTEGER DEFAULT 1
                )
            """
            )

            # Index for cache cleanup
            await self._conn.execute(  # type: ignore
                """
                CREATE INDEX IF NOT EXISTS idx_cache_access 
                ON api_cache(last_accessed)
            """
            )

            await self._conn.commit()  # type: ignore
            logger.info("Database tables initialized")

    # ==================== GUILD CONFIGURATIONS ====================

    async def save_guild_config(
        self, guild_id: int, channels: Set[int], archive_channel_id: Optional[int]
    ) -> bool:
        """
        Save guild shiny monitoring configuration.

        Args:
            guild_id: Discord guild ID.
            channels: Set of channel IDs to monitor.
            archive_channel_id: Optional channel ID for archiving shiny embeds.

        Returns:
            True if the save was successful, False otherwise.
        """
        try:
            async with self._lock:
                channels_json = json.dumps(list(channels))
                current_time = time.time()

                await self._conn.execute(  # type: ignore
                    """
                    INSERT INTO guild_configs (guild_id, channels, archive_channel_id, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(guild_id) DO UPDATE SET
                        channels = excluded.channels,
                        archive_channel_id = excluded.archive_channel_id,
                        updated_at = excluded.updated_at
                    """,
                    (guild_id, channels_json, archive_channel_id, current_time),
                )
                await self._conn.commit()  # type: ignore

                logger.debug(f"Saved guild config for {guild_id}")
                return True

        except Exception as e:
            logger.error(f"Error saving guild config: {e}", exc_info=True)
            return False

    async def load_guild_config(
        self, guild_id: int
    ) -> Optional[Tuple[Set[int], Optional[int]]]:
        """
        Load shiny monitoring configuration for a specific guild.

        Args:
            guild_id: Discord guild ID.

        Returns:
            Tuple containing (set of monitored channel IDs, archive channel ID),
            or None if no configuration exists.
        """
        try:
            async with self._lock:
                cursor = await self._conn.execute(  # type: ignore
                    "SELECT channels, archive_channel_id FROM guild_configs WHERE guild_id = ?",
                    (guild_id,),
                )
                row = await cursor.fetchone()

                if row:
                    channels = set(json.loads(row["channels"]))
                    archive_id = row["archive_channel_id"]
                    return channels, archive_id

                return None

        except Exception as e:
            logger.error(f"Error loading guild config: {e}", exc_info=True)
            return None

    async def load_all_guild_configs(self) -> Dict[int, Tuple[Set[int], Optional[int]]]:
        """
        Load configurations for all guilds.

        Returns:
            Dictionary mapping guild_id to (monitored_channels, archive_channel_id).
        """
        try:
            async with self._lock:
                cursor = await self._conn.execute(  # type: ignore
                    "SELECT guild_id, channels, archive_channel_id FROM guild_configs"
                )
                rows = await cursor.fetchall()

                configs = {}
                for row in rows:
                    guild_id = row["guild_id"]
                    channels = set(json.loads(row["channels"]))
                    archive_id = row["archive_channel_id"]
                    configs[guild_id] = (channels, archive_id)

                logger.info(f"Loaded {len(configs)} guild configurations")
                return configs

        except Exception as e:
            logger.error(f"Error loading guild configs: {e}", exc_info=True)
            return {}

    async def delete_guild_config(self, guild_id: int) -> bool:
        """
        Delete configuration for a specific guild.

        Args:
            guild_id: Discord guild ID.

        Returns:
            True if successful, False otherwise.
        """
        try:
            async with self._lock:
                await self._conn.execute(  # type: ignore
                    "DELETE FROM guild_configs WHERE guild_id = ?", (guild_id,)
                )
                await self._conn.commit()  # type: ignore
                logger.info(f"Deleted guild config for {guild_id}")
                return True

        except Exception as e:
            logger.error(f"Error deleting guild config: {e}", exc_info=True)
            return False

    # ==================== API CACHE ====================

    async def get_cache(self, cache_key: str, max_age: float) -> Optional[Any]:
        """
        Retrieve cached data if it hasn't expired.

        Updates the `last_accessed` timestamp and `access_count` on a hit.
        Automatically deletes the entry if found but expired.

        Args:
            cache_key: The unique cache identifier.
            max_age: Maximum allowed age of the cache entry in seconds.

        Returns:
            The cached data (deserialized from JSON) or None if missing/expired.
        """
        try:
            async with self._lock:
                current_time = time.time()

                cursor = await self._conn.execute(  # type: ignore
                    "SELECT data, created_at FROM api_cache WHERE cache_key = ?",
                    (cache_key,),
                )
                row = await cursor.fetchone()

                if row:
                    created_at = row["created_at"]
                    age = current_time - created_at

                    if age < max_age:
                        # Update last accessed time and access count
                        await self._conn.execute(  # type: ignore
                            """
                            UPDATE api_cache 
                            SET last_accessed = ?, access_count = access_count + 1
                            WHERE cache_key = ?
                            """,
                            (current_time, cache_key),
                        )
                        await self._conn.commit()  # type: ignore

                        data = json.loads(row["data"])
                        logger.debug(f"Cache hit: {cache_key[:50]}...")
                        return data
                    else:
                        # Expired - delete it
                        await self._conn.execute(  # type: ignore
                            "DELETE FROM api_cache WHERE cache_key = ?", (cache_key,)
                        )
                        await self._conn.commit()  # type: ignore
                        logger.debug(f"Cache expired: {cache_key[:50]}...")

                return None

        except Exception as e:
            logger.error(f"Error getting cache: {e}", exc_info=True)
            return None

    async def set_cache(self, cache_key: str, data: Any, max_size: int) -> bool:
        """
        Store data in cache with automatic size management (LRU).

        If the cache exceeds `max_size`, this method triggers an eviction of the
        least recently accessed entries (roughly 10% of max size) before insertion.

        Args:
            cache_key: The unique cache identifier.
            data: Data to cache (must be JSON serializable).
            max_size: Maximum number of entries allowed in the cache table.

        Returns:
            True if insertion/update was successful, False otherwise.
        """
        try:
            async with self._lock:
                current_time = time.time()

                # Check current cache size
                cursor = await self._conn.execute(  # type: ignore
                    "SELECT COUNT(*) as count FROM api_cache"
                )
                row = await cursor.fetchone()
                cache_size = row["count"]  # type: ignore

                # If at max size, remove least recently accessed entries
                if cache_size >= max_size:
                    # Remove 10% of oldest entries to avoid constant deletions
                    remove_count = max(1, max_size // 10)
                    await self._conn.execute(  # type: ignore
                        """
                        DELETE FROM api_cache WHERE cache_key IN (
                            SELECT cache_key FROM api_cache 
                            ORDER BY last_accessed ASC 
                            LIMIT ?
                        )
                        """,
                        (remove_count,),
                    )
                    logger.debug(f"Evicted {remove_count} old cache entries")

                # Insert or replace cache entry
                data_json = json.dumps(data)
                await self._conn.execute(  # type: ignore
                    """
                    INSERT INTO api_cache (cache_key, data, created_at, last_accessed)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(cache_key) DO UPDATE SET
                        data = excluded.data,
                        created_at = excluded.created_at,
                        last_accessed = excluded.last_accessed
                    """,
                    (cache_key, data_json, current_time, current_time),
                )
                await self._conn.commit()  # type: ignore

                logger.debug(f"Cached: {cache_key[:50]}...")
                return True

        except Exception as e:
            logger.error(f"Error setting cache: {e}", exc_info=True)
            return False

    async def clear_cache(self) -> bool:
        """
        Clear all cached data from the database.

        Returns:
            True if successful, False otherwise.
        """
        try:
            async with self._lock:
                await self._conn.execute("DELETE FROM api_cache")  # type: ignore
                await self._conn.commit()  # type: ignore
                logger.info("Cache cleared")
                return True

        except Exception as e:
            logger.error(f"Error clearing cache: {e}", exc_info=True)
            return False

    async def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the cache usage.

        Returns:
            Dictionary containing 'size' (count), 'total_accesses', and 'avg_accesses'.
        """
        try:
            async with self._lock:
                cursor = await self._conn.execute(  # type: ignore
                    """
                    SELECT 
                        COUNT(*) as size,
                        SUM(access_count) as total_accesses,
                        AVG(access_count) as avg_accesses
                    FROM api_cache
                """
                )
                row = await cursor.fetchone()

                return {
                    "size": row["size"],  # type: ignore
                    "total_accesses": row["total_accesses"] or 0,  # type: ignore
                    "avg_accesses": round(row["avg_accesses"] or 0, 1),  # type: ignore
                }

        except Exception as e:
            logger.error(f"Error getting cache stats: {e}", exc_info=True)
            return {"size": 0, "total_accesses": 0, "avg_accesses": 0}

    async def cleanup_expired_cache(self, max_age: float) -> int:
        """
        Remove expired cache entries based on creation time.

        Args:
            max_age: Maximum allowed age in seconds.

        Returns:
            Number of entries removed.
        """
        try:
            async with self._lock:
                current_time = time.time()
                cutoff_time = current_time - max_age

                cursor = await self._conn.execute(  # type: ignore
                    "DELETE FROM api_cache WHERE created_at < ? RETURNING cache_key",
                    (cutoff_time,),
                )
                deleted_rows = await cursor.fetchall()
                deleted_count = len(deleted_rows)  # type: ignore

                await self._conn.commit()  # type: ignore

                if deleted_count > 0:
                    logger.debug(f"Cleaned {deleted_count} expired cache entries")

                return deleted_count

        except Exception as e:
            logger.error(f"Error cleaning cache: {e}", exc_info=True)
            return 0

    # ==================== UTILITY ====================

    async def vacuum(self) -> None:
        """
        Optimize database by reclaiming unused space and rebuilding indexes.

        WARNING:
            This operation locks the database file. Do not run during peak usage.
        """
        try:
            async with self._lock:
                await self._conn.execute("VACUUM")  # type: ignore
                logger.info("Database vacuumed")
        except Exception as e:
            logger.error(f"Error vacuuming database: {e}", exc_info=True)


# Global database instance
_db_instance: Optional[Database] = None
# Lock for thread-safe initialization
_db_init_lock = asyncio.Lock()


async def get_database() -> Database:
    """
    Get global database instance (Singleton pattern).

    Initializes and connects if not already connected.
    Uses double-checked locking to prevent race conditions during startup.

    Returns:
        The connected Database instance.
    """
    global _db_instance

    if _db_instance is None:
        async with _db_init_lock:
            # Check again inside lock to ensure another task didn't init while we waited
            if _db_instance is None:
                instance = Database()
                await instance.connect()
                # Only assign to global variable AFTER connection is fully established
                _db_instance = instance

    return _db_instance


async def close_database() -> None:
    """
    Close global database instance and cleanup resources.
    """
    global _db_instance
    if _db_instance is not None:
        await _db_instance.close()
        _db_instance = None
