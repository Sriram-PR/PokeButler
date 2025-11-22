"""
API Client module for fetching competitive Pokemon data.

This module handles interactions with the Smogon API (via data.pkmn.cc) and
PokeAPI. It implements robust infrastructure patterns including connection
pooling, circuit breakers, request deduplication, and database-backed caching.
"""

import asyncio
import hashlib
import logging
from collections import defaultdict
from typing import Any, Dict, Optional

import aiohttp

from config.settings import (
    API_REQUEST_TIMEOUT,
    CACHE_CLEANUP_INTERVAL,
    CACHE_TIMEOUT,
    FORMATS_BY_GEN,
    MAX_CACHE_SIZE,
    MAX_CONCURRENT_API_REQUESTS,
    POKEAPI_URL,
    PRIORITY_FORMATS,
    SMOGON_SETS_URL,
)
from utils.api_models import (
    CacheStats,
    DeduplicationStats,
    PokeAPIEVYield,
    PokeAPISprite,
    SmogonSet,
)
from utils.circuit_breaker import CircuitBreaker, CircuitBreakerError
from utils.constants import (
    API_STARTUP_VALIDATION_TIMEOUT,
    CACHE_KEY_HASH_ALGORITHM,
    GLOBAL_API_MAX_CONCURRENT,
)
from utils.database import get_database
from utils.decorators import retry_on_error

logger = logging.getLogger("smogon_bot.api")

# Connection pool settings
CONNECTION_POOL_LIMIT = 100  # Total connections across all hosts
CONNECTION_POOL_LIMIT_PER_HOST = 30  # Max connections per host
CONNECTION_KEEPALIVE_TIMEOUT = 30  # Seconds to keep idle connections


class SmogonAPIClient:
    """
    Client for fetching competitive sets from Smogon and Pokemon data from PokeAPI.

    Key Features:
    - **Connection Pooling**: Uses `aiohttp.TCPConnector` to reuse connections.
    - **Circuit Breakers**: Prevents cascading failures when APIs are down.
    - **Request Deduplication**: Merges simultaneous requests for the same resource
      into a single API call.
    - **Global Rate Limiting**: Protects against IP bans via semaphores.
    - **Database Caching**: Persists data to SQLite with LRU eviction.
    """

    def __init__(self):
        self.base_url = SMOGON_SETS_URL
        self.session: Optional[aiohttp.ClientSession] = None

        # Session creation lock to prevent race conditions during lazy loading
        self._session_lock = asyncio.Lock()

        # Global rate limiter (across all users/requests)
        self._global_rate_limiter = asyncio.Semaphore(GLOBAL_API_MAX_CONCURRENT)

        # Per-session rate limiter (for individual requests)
        self._rate_limiter = asyncio.Semaphore(MAX_CONCURRENT_API_REQUESTS)

        # Cache statistics (in-memory for performance)
        self.cache_hits = 0
        self.cache_misses = 0

        # Circuit breakers
        self._smogon_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=60.0,
            success_threshold=2,
            expected_exceptions=(
                aiohttp.ClientError,
                asyncio.TimeoutError,
            ),
            name="smogon_api",
        )

        self._pokeapi_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=60.0,
            success_threshold=2,
            expected_exceptions=(
                aiohttp.ClientError,
                asyncio.TimeoutError,
            ),
            name="pokeapi",
        )

        # Tracks in-flight requests to prevent duplicate API calls
        self._pending_requests: Dict[str, asyncio.Task] = {}
        self._request_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

        # Background cleanup task
        self._cleanup_task: Optional[asyncio.Task] = None
        self._is_closing = False

    def _hash_cache_key(self, key: str) -> str:
        """
        Generate hashed cache key for improved performance and security.

        Args:
            key: Original cache key string.

        Returns:
            Hashed key string.
        """
        hash_obj = hashlib.new(CACHE_KEY_HASH_ALGORITHM)
        hash_obj.update(key.encode("utf-8"))
        return hash_obj.hexdigest()

    async def _deduplicate_request(
        self, key: str, fetch_func, *args, **kwargs
    ) -> Optional[Any]:
        """
        Deduplicate concurrent requests for the same data.

        This employs a 'Release-then-Await' pattern: the lock is held only
        while creating or retrieving the pending task, never while awaiting
        the network result. This prevents serialization of concurrent requests.

        Args:
            key: Unique key identifying this request resource.
            fetch_func: Async function to call if no request is pending.
            *args: Arguments for fetch_func.
            **kwargs: Keyword arguments for fetch_func.

        Returns:
            Result from fetch_func or shared result from a pending request.
        """
        created = False
        task = None

        # 1. Check or Create Task (Critical Section)
        async with self._request_locks[key]:
            if key in self._pending_requests:
                # Join existing request
                task = self._pending_requests[key]
                logger.debug(
                    "Request deduplication: Joining existing request",
                    extra={"key": key[:50]},
                )
            else:
                # Create new request
                task = asyncio.create_task(fetch_func(*args, **kwargs))
                self._pending_requests[key] = task
                created = True
                logger.debug(
                    "Request deduplication: Starting new request",
                    extra={"key": key[:50]},
                )

        # 2. Await Result (Outside Lock)
        try:
            return await task
        finally:
            # 3. Cleanup (Only creator should clean up to avoid race conditions)
            if created:
                async with self._request_locks[key]:
                    # Verify we are cleaning up the correct task
                    if (
                        key in self._pending_requests
                        and self._pending_requests[key] is task
                    ):
                        del self._pending_requests[key]

                logger.debug(
                    "Request deduplication: Cleaned up request",
                    extra={"key": key[:50]},
                )

    async def get_session(self) -> aiohttp.ClientSession:
        """
        Get or create aiohttp session with connection pooling configuration.

        Uses `TCPConnector` to limit total connections and reuse them via
        keep-alive, which is crucial for performance under high load.

        Returns:
            Active aiohttp ClientSession.
        """
        async with self._session_lock:
            if self.session is None or self.session.closed:
                timeout = aiohttp.ClientTimeout(total=API_REQUEST_TIMEOUT)

                # Create TCPConnector with connection pooling
                connector = aiohttp.TCPConnector(
                    limit=CONNECTION_POOL_LIMIT,  # Total connections
                    limit_per_host=CONNECTION_POOL_LIMIT_PER_HOST,  # Per host
                    ttl_dns_cache=300,  # DNS cache TTL (5 minutes)
                    keepalive_timeout=CONNECTION_KEEPALIVE_TIMEOUT,  # Keep connections alive
                    force_close=False,  # Reuse connections
                    enable_cleanup_closed=True,  # Clean up closed connections
                )

                self.session = aiohttp.ClientSession(
                    timeout=timeout,
                    connector=connector,
                    headers={"User-Agent": "Pokemon-Smogon-Discord-Bot/2.0"},
                )

                logger.info(
                    "Created aiohttp session with connection pooling",
                    extra={
                        "total_limit": CONNECTION_POOL_LIMIT,
                        "per_host_limit": CONNECTION_POOL_LIMIT_PER_HOST,
                        "keepalive": CONNECTION_KEEPALIVE_TIMEOUT,
                    },
                )

                # Cancel old cleanup task before creating new one
                if self._cleanup_task and not self._cleanup_task.done():
                    self._cleanup_task.cancel()
                    try:
                        await self._cleanup_task
                    except asyncio.CancelledError:
                        pass

                # Start new cleanup task
                self._cleanup_task = asyncio.create_task(self._cache_cleanup_loop())
                logger.info("Started cache cleanup background task")

        return self.session

    async def validate_api_connectivity(self) -> Dict[str, bool]:
        """
        Validate connectivity to external APIs on startup.

        Returns:
            Dictionary mapping API names ('smogon', 'pokeapi') to boolean status.
        """
        results = {"smogon": False, "pokeapi": False}

        logger.info(
            "Validating API connectivity", extra={"apis": ["smogon", "pokeapi"]}
        )

        # Test Smogon API
        try:
            session = await self.get_session()
            test_url = f"{SMOGON_SETS_URL}/gen9ou.json"

            async with asyncio.timeout(API_STARTUP_VALIDATION_TIMEOUT):
                async with session.get(test_url) as resp:
                    if resp.status == 200:
                        results["smogon"] = True
                        logger.info(
                            "API reachable",
                            extra={"api": "smogon", "status": "success"},
                        )
                    else:
                        logger.warning(
                            "API returned non-200 status",
                            extra={"api": "smogon", "status_code": resp.status},
                        )
        except asyncio.TimeoutError:
            logger.error(
                "API connection timed out",
                extra={
                    "api": "smogon",
                    "timeout_seconds": API_STARTUP_VALIDATION_TIMEOUT,
                },
            )
        except Exception as e:
            logger.error(
                "API validation failed",
                extra={"api": "smogon", "error": str(e)},
                exc_info=True,
            )

        # Test PokeAPI
        try:
            session = await self.get_session()
            test_url = f"{POKEAPI_URL}/pokemon/1"

            async with asyncio.timeout(API_STARTUP_VALIDATION_TIMEOUT):
                async with session.get(test_url) as resp:
                    if resp.status == 200:
                        results["pokeapi"] = True
                        logger.info("✅ PokeAPI is reachable")
                    else:
                        logger.warning(f"⚠️ PokeAPI returned status {resp.status}")
        except asyncio.TimeoutError:
            logger.error("❌ PokeAPI connection timed out")
        except Exception as e:
            logger.error(f"❌ PokeAPI validation failed: {e}")

        # Summary
        if all(results.values()):
            logger.info("✅ All APIs are operational")
        else:
            failed = [api for api, status in results.items() if not status]
            logger.warning(
                f"⚠️ Some APIs are unreachable: {', '.join(failed)}. "
                f"Bot will continue but may have limited functionality."
            )

        return results

    async def close(self) -> None:
        """Close the aiohttp session and cancel background tasks."""
        self._is_closing = True

        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            logger.info("Cancelled cache cleanup task")

        if self.session and not self.session.closed:
            await self.session.close()
            logger.info(
                f"API client session closed (Cache stats - Hits: {self.cache_hits}, Misses: {self.cache_misses})"
            )

            # Log circuit breaker stats
            logger.info(
                "Smogon circuit breaker stats",
                extra=self._smogon_breaker.get_stats(),
            )
            logger.info(
                "PokeAPI circuit breaker stats",
                extra=self._pokeapi_breaker.get_stats(),
            )

    async def _cache_cleanup_loop(self) -> None:
        """Background task to periodically clean expired cache entries."""
        while not self._is_closing:
            try:
                await asyncio.sleep(CACHE_CLEANUP_INTERVAL)
                await self._cleanup_expired_cache()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cache cleanup task: {e}")

    async def _cleanup_expired_cache(self) -> None:
        """Remove expired entries from database cache."""
        try:
            db = await get_database()
            deleted_count = await db.cleanup_expired_cache(CACHE_TIMEOUT)
            if deleted_count > 0:
                logger.debug(
                    "Cleaned expired cache entries",
                    extra={"count": deleted_count, "timeout_seconds": CACHE_TIMEOUT},
                )
        except Exception as e:
            logger.error(f"Error cleaning cache: {e}", exc_info=True)

    async def _get_cached(self, key: str) -> Optional[Any]:
        """
        Get data from database cache if not expired.

        Args:
            key: Cache key.

        Returns:
            Cached data object or None if missing/expired.
        """
        try:
            hashed_key = self._hash_cache_key(key)
            db = await get_database()
            data = await db.get_cache(hashed_key, CACHE_TIMEOUT)

            if data is not None:
                self.cache_hits += 1
                logger.debug(
                    "Cache hit",
                    extra={
                        "cache_key": key[:50],
                        "access_count": data.access_count
                        if hasattr(data, "access_count")
                        else None,
                    },
                )
                return data
            else:
                self.cache_misses += 1
                return None

        except Exception as e:
            logger.error(f"Error getting cache: {e}", exc_info=True)
            self.cache_misses += 1
            return None

    async def _set_cache(self, key: str, data: Any) -> None:
        """
        Store data in database cache with automatic size management.

        Args:
            key: Cache key.
            data: Serializable data object to store.
        """
        try:
            hashed_key = self._hash_cache_key(key)
            db = await get_database()
            await db.set_cache(hashed_key, data, MAX_CACHE_SIZE)
            logger.debug("Data cached", extra={"cache_key": key[:50]})
        except Exception as e:
            logger.error(f"Error setting cache: {e}", exc_info=True)

    @retry_on_error(max_retries=3)
    async def find_pokemon_in_generation(
        self, pokemon: str, generation: str
    ) -> Dict[str, Dict[str, SmogonSet]]:
        """
        Find a Pokemon across all formats in a generation using batched parallel requests.

        This efficiently checks multiple tier definitions (OU, UU, etc.) concurrently
        to find where a Pokemon has valid movesets.

        Args:
            pokemon: Pokemon name.
            generation: Generation string (e.g., 'gen9').

        Returns:
            Dictionary mapping format_id to sets data.
        """
        # Check if we have cached tier locations for this pokemon
        tier_cache_key = f"tier_location:{generation}:{pokemon}"
        cached_tiers = await self._get_cached(tier_cache_key)

        if cached_tiers:
            logger.info(f"Using cached tier locations for {pokemon} in {generation}")
            result = {}
            for tier in cached_tiers:
                sets = await self.get_sets(pokemon, generation, tier)
                if sets:
                    result[tier] = sets
            return result

        # Get available formats for this generation
        available_formats = FORMATS_BY_GEN.get(generation, PRIORITY_FORMATS)

        logger.info(
            f"Searching for {pokemon} in {generation} across {len(available_formats)} formats"
        )

        # Batch API requests to avoid overwhelming the API
        BATCH_SIZE = 5
        found_formats = {}

        async with self._global_rate_limiter:
            for i in range(0, len(available_formats), BATCH_SIZE):
                batch = available_formats[i : i + BATCH_SIZE]
                tasks = [
                    self._fetch_format(pokemon, generation, tier) for tier in batch
                ]

                # Process batch with rate limiting
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Collect successful results from this batch
                for tier, result in zip(batch, results):
                    if result and not isinstance(result, Exception):
                        found_formats[tier] = result
                        logger.info(f"✓ Found {pokemon} in {generation}{tier}")

                # Small delay between batches to be respectful
                if i + BATCH_SIZE < len(available_formats):
                    await asyncio.sleep(0.1)

        # Cache tier locations if found
        if found_formats:
            await self._set_cache(tier_cache_key, list(found_formats.keys()))

        return found_formats

    async def _fetch_format(
        self, pokemon: str, generation: str, tier: str
    ) -> Optional[Dict[str, SmogonSet]]:
        """Internal method to fetch a specific format and find pokemon."""
        try:
            sets = await self.get_sets(pokemon, generation, tier)
            return sets
        except Exception as e:
            logger.debug(f"Error fetching {generation}{tier}: {e}")
            return None

    @retry_on_error(max_retries=3)
    async def get_sets(
        self, pokemon: str, generation: str = "gen9", tier: str = "ou"
    ) -> Optional[Dict[str, SmogonSet]]:
        """
        Fetch competitive sets from Smogon for a specific format.

        Wrapper method that handles:
        1. Cache lookup
        2. Request deduplication
        3. Circuit breaker protection

        Args:
            pokemon: Pokemon name.
            generation: Generation string (e.g., 'gen9', 'gen8').
            tier: Competitive tier (e.g., 'ou', 'uu', 'ubers').

        Returns:
            Dictionary of sets or None if not found.
        """
        pokemon = pokemon.lower().strip().replace(" ", "-")
        generation = generation.lower().strip()
        tier = tier.lower().strip()

        format_id = f"{generation}{tier}"
        cache_key = f"{format_id}:{pokemon}"

        # Check cache first
        cached = await self._get_cached(cache_key)
        if cached is not None:
            return cached

        # Deduplicate requests
        dedup_key = f"smogon:sets:{cache_key}"

        async def _fetch():
            try:
                return await self._smogon_breaker.call(
                    self._fetch_smogon_sets, pokemon, format_id, cache_key
                )
            except CircuitBreakerError:
                logger.error(
                    f"Smogon API circuit breaker open for {format_id}",
                    extra={"pokemon": pokemon, "format": format_id},
                )
                return None

        return await self._deduplicate_request(dedup_key, _fetch)

    async def _fetch_smogon_sets(
        self, pokemon: str, format_id: str, cache_key: str
    ) -> Optional[Dict[str, SmogonSet]]:
        """Internal method to fetch from Smogon API (wrapped by circuit breaker)."""
        session = await self.get_session()
        url = f"{self.base_url}/{format_id}.json"

        logger.debug(f"Fetching {url}")

        async with self._global_rate_limiter:
            async with self._rate_limiter:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()

                        # Search for Pokemon
                        for poke_name, sets in data.items():
                            if poke_name.lower().replace(" ", "-") == pokemon:
                                await self._set_cache(cache_key, sets)
                                logger.info(
                                    "Found competitive sets",
                                    extra={
                                        "pokemon": pokemon,
                                        "format": format_id,
                                        "set_count": len(data),
                                    },
                                )
                                return sets

                        # Partial match
                        for poke_name, sets in data.items():
                            if pokemon in poke_name.lower().replace(" ", "-"):
                                await self._set_cache(cache_key, sets)
                                logger.info(
                                    f"Found sets for {pokemon} (matched {poke_name}) in {format_id}"
                                )
                                return sets

                        logger.debug(f"Pokemon {pokemon} not found in {format_id}")
                        return None

                    elif resp.status == 404:
                        logger.debug(f"Format {format_id} not found (404)")
                        return None
                    else:
                        logger.warning(f"API error {resp.status} for {url}")
                        # Raise to trigger circuit breaker
                        raise aiohttp.ClientResponseError(
                            request_info=resp.request_info,
                            history=resp.history,
                            status=resp.status,
                        )

    @retry_on_error(max_retries=3)
    async def get_pokemon_ev_yield(self, pokemon: str) -> Optional[PokeAPIEVYield]:
        """
        Fetch EV yield data from PokeAPI.

        Args:
            pokemon: Pokemon name.

        Returns:
            PokeAPIEVYield object or None if not found.
        """
        pokemon = pokemon.lower().strip().replace(" ", "-")
        cache_key = f"ev_yield:{pokemon}"

        # Check cache first
        cached = await self._get_cached(cache_key)
        if cached is not None:
            return cached

        # Deduplicate requests
        dedup_key = f"pokeapi:ev:{cache_key}"

        async def _fetch():
            try:
                return await self._pokeapi_breaker.call(
                    self._fetch_pokemon_ev_yield, pokemon, cache_key
                )
            except CircuitBreakerError:
                logger.error(
                    "PokeAPI circuit breaker open for EV yield",
                    extra={"pokemon": pokemon},
                )
                return None

        return await self._deduplicate_request(dedup_key, _fetch)

    async def _fetch_pokemon_ev_yield(
        self, pokemon: str, cache_key: str
    ) -> Optional[PokeAPIEVYield]:
        """Internal method to fetch EV yield from PokeAPI (wrapped by circuit breaker)."""
        session = await self.get_session()
        url = f"{POKEAPI_URL}/pokemon/{pokemon}"
        logger.debug(f"Fetching EV yield from PokeAPI: {url}")

        async with self._global_rate_limiter:
            async with self._rate_limiter:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        ev_yields = {}
                        total_evs = 0

                        for stat in data.get("stats", []):
                            stat_name = stat["stat"]["name"]
                            effort = stat["effort"]
                            ev_yields[stat_name] = effort
                            total_evs += effort

                        result: PokeAPIEVYield = {
                            "ev_yields": ev_yields,
                            "total": total_evs,
                            "name": data.get("name"),
                            "id": data.get("id"),
                            "sprite": data.get("sprites", {}).get("front_default"),
                            "types": [t["type"]["name"] for t in data.get("types", [])],
                        }

                        await self._set_cache(cache_key, result)
                        logger.info(f"Found EV yield for {pokemon}")
                        return result
                    elif resp.status == 404:
                        logger.debug(f"Pokemon {pokemon} not found in PokeAPI")
                        return None
                    else:
                        logger.warning(f"PokeAPI error {resp.status} for {pokemon}")
                        # Raise to trigger circuit breaker
                        raise aiohttp.ClientResponseError(
                            request_info=resp.request_info,
                            history=resp.history,
                            status=resp.status,
                        )

    @retry_on_error(max_retries=3)
    async def get_pokemon_sprite(
        self, pokemon: str, shiny: bool = False, generation: int = 9
    ) -> Optional[PokeAPISprite]:
        """
        Fetch Pokemon sprite from PokeAPI, with generational fallback support.

        Args:
            pokemon: Pokemon name.
            shiny: Whether to fetch the shiny sprite.
            generation: Targeted generation (affects sprite style).

        Returns:
            PokeAPISprite object containing URL or error details.
        """
        pokemon = pokemon.lower().strip().replace(" ", "-")
        cache_key = f"sprite:{pokemon}:{shiny}:{generation}"

        # Check cache first
        cached = await self._get_cached(cache_key)
        if cached is not None:
            return cached

        # Deduplicate requests
        dedup_key = f"pokeapi:sprite:{cache_key}"

        async def _fetch():
            try:
                return await self._pokeapi_breaker.call(
                    self._fetch_pokemon_sprite, pokemon, shiny, generation, cache_key
                )
            except CircuitBreakerError:
                logger.error(
                    "PokeAPI circuit breaker open for sprite",
                    extra={"pokemon": pokemon, "generation": generation},
                )
                return None

        return await self._deduplicate_request(dedup_key, _fetch)

    async def _fetch_pokemon_sprite(
        self, pokemon: str, shiny: bool, generation: int, cache_key: str
    ) -> Optional[PokeAPISprite]:
        """Internal method to fetch sprite from PokeAPI (wrapped by circuit breaker)."""
        session = await self.get_session()
        species_url = f"{POKEAPI_URL}/pokemon-species/{pokemon}"

        async with self._global_rate_limiter:
            async with self._rate_limiter:
                async with session.get(species_url) as species_resp:
                    if species_resp.status == 200:
                        species_data = await species_resp.json()
                        gen_data = species_data.get("generation", {})
                        gen_url = gen_data.get("url", "")

                        try:
                            introduced_gen = int(gen_url.rstrip("/").split("/")[-1])
                        except (ValueError, IndexError):
                            introduced_gen = 1

                        if generation < introduced_gen:
                            logger.debug(
                                f"{pokemon} was introduced in Gen {introduced_gen}, "
                                f"cannot show Gen {generation} sprite"
                            )
                            return {
                                "error": "pokemon_not_in_generation",
                                "introduced_gen": introduced_gen,
                                "requested_gen": generation,
                                "shiny": shiny,
                                "generation": generation,
                                "sprite_url": None,
                                "name": None,
                                "id": None,
                            }
                    elif species_resp.status == 404:
                        logger.debug(f"Pokemon species {pokemon} not found in PokeAPI")
                        return None
                    else:
                        # Raise to trigger circuit breaker
                        raise aiohttp.ClientResponseError(
                            request_info=species_resp.request_info,
                            history=species_resp.history,
                            status=species_resp.status,
                        )

        url = f"{POKEAPI_URL}/pokemon/{pokemon}"
        logger.debug(f"Fetching sprite from PokeAPI: {url}")

        async with self._global_rate_limiter:
            async with self._rate_limiter:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        sprites = data.get("sprites", {})
                        sprite_url = None

                        gen_map = {
                            1: "generation-i",
                            2: "generation-ii",
                            3: "generation-iii",
                            4: "generation-iv",
                            5: "generation-v",
                            6: "generation-vi",
                            7: "generation-vii",
                            8: "generation-viii",
                            9: None,
                        }

                        if generation == 9:
                            sprite_url = sprites.get(
                                "front_shiny" if shiny else "front_default"
                            )
                        else:
                            gen_key = gen_map.get(generation)
                            if gen_key:
                                versions = sprites.get("versions", {})
                                gen_sprites = versions.get(gen_key, {})
                                game_keys = list(gen_sprites.keys())
                                if game_keys:
                                    for game_key in game_keys:
                                        game_sprite = gen_sprites[game_key]
                                        sprite_url = game_sprite.get(
                                            "front_shiny" if shiny else "front_default"
                                        )
                                        if sprite_url:
                                            break

                        if not sprite_url:
                            logger.debug(
                                f"No sprite found for {pokemon} (shiny={shiny}, gen={generation})"
                            )
                            return None

                        result: PokeAPISprite = {
                            "sprite_url": sprite_url,
                            "name": data.get("name"),
                            "id": data.get("id"),
                            "shiny": shiny,
                            "generation": generation,
                            "error": None,
                            "introduced_gen": None,
                            "requested_gen": None,
                        }

                        await self._set_cache(cache_key, result)
                        logger.info(
                            "Found sprite",
                            extra={
                                "pokemon": pokemon,
                                "shiny": shiny,
                                "generation": generation,
                            },
                        )
                        return result
                    elif resp.status == 404:
                        logger.debug(f"Pokemon {pokemon} not found in PokeAPI")
                        return None
                    else:
                        logger.warning(f"PokeAPI error {resp.status} for {pokemon}")
                        # Raise to trigger circuit breaker
                        raise aiohttp.ClientResponseError(
                            request_info=resp.request_info,
                            history=resp.history,
                            status=resp.status,
                        )

    async def get_all_pokemon_names(self) -> list[str]:
        """
        Fetch list of all Pokemon names for fuzzy matching.

        Cached for 24 hours (longer than standard cache) since the list
        changes infrequently.

        Returns:
            List of Pokemon names.
        """
        cache_key = "all_pokemon_names"
        # Use a longer timeout for this list (24 hours)
        # LONG_CACHE_TIMEOUT = 86400 - hardcoded logic below for now

        cached = await self._get_cached(cache_key)
        if cached is not None:
            return cached

        session = await self.get_session()
        # Fetch a large limit to get all species
        url = f"{POKEAPI_URL}/pokemon-species?limit=2000"

        try:
            async with self._global_rate_limiter:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        results = data.get("results", [])
                        names = [p["name"] for p in results]

                        await self._set_cache(cache_key, names)
                        logger.info(
                            f"Cached {len(names)} Pokemon names for fuzzy matching"
                        )
                        return names
                    else:
                        logger.warning(f"Failed to fetch Pokemon list: {resp.status}")
                        return []
        except Exception as e:
            logger.error(f"Error fetching Pokemon list: {e}")
            return []

    async def clear_cache(self) -> None:
        """Clear all cached data from the database."""
        try:
            db = await get_database()
            await db.clear_cache()
            self.cache_hits = 0
            self.cache_misses = 0
            logger.info("Cache cleared")
        except Exception as e:
            logger.error(f"Error clearing cache: {e}", exc_info=True)

    def get_cache_stats(self) -> CacheStats:
        """
        Get cache statistics.

        Returns:
            CacheStats object containing hit rates and counts.
        """
        total_requests = self.cache_hits + self.cache_misses
        hit_rate = (self.cache_hits / total_requests * 100) if total_requests > 0 else 0

        return {
            "size": "N/A",  # Will be fetched from DB if needed
            "max_size": MAX_CACHE_SIZE,
            "hits": self.cache_hits,
            "misses": self.cache_misses,
            "hit_rate": f"{hit_rate:.1f}%",
        }

    def get_deduplication_stats(self) -> DeduplicationStats:
        """
        Get request deduplication statistics.

        Returns:
            DeduplicationStats object.
        """
        return {
            "pending_requests": len(self._pending_requests),
            "active_locks": len(self._request_locks),
        }

    def get_circuit_breaker_stats(self) -> Dict[str, dict]:
        """
        Get circuit breaker statistics for all APIs.

        Returns:
            Dictionary mapping API names to their breaker stats.
        """
        return {
            "smogon": self._smogon_breaker.get_stats(),
            "pokeapi": self._pokeapi_breaker.get_stats(),
        }
