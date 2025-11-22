"""
Type definitions for API responses to ensure strict typing and reduce runtime errors.
"""

from typing import Dict, List, Optional, TypedDict, Union


class SmogonSet(TypedDict, total=False):
    """
    Represents a competitive moveset from the Smogon API.

    This matches the JSON structure returned by data.pkmn.cc.
    All fields are optional (total=False) because the API does not guarantee
    every field exists for every Pokemon set (e.g., some sets might lack
    items or specific IVs).

    Attributes:
        moves: List of move names or list of choices for a slot.
        nature: Nature name(s).
        item: Item name(s).
        ability: Ability name(s).
        evs: Dictionary mapping stat names to EV values.
        ivs: Dictionary mapping stat names to IV values (default 31 if missing).
        teratypes: Tera type(s) (Gen 9 specific).
        teratype: Legacy field for tera type (handling API inconsistency).
        level: Pokemon level for the format (usually 100 or 50).
    """

    moves: List[Union[str, List[str]]]
    nature: Union[str, List[str]]
    item: Union[str, List[str]]
    ability: Union[str, List[str]]
    evs: Dict[str, int]
    ivs: Optional[Dict[str, int]]
    teratypes: Optional[Union[str, List[str]]]
    teratype: Optional[Union[str, List[str]]]
    level: int


class PokeAPIEVYield(TypedDict):
    """
    Represents EV yield data derived from PokeAPI.
    """

    ev_yields: Dict[str, int]
    total: int
    name: str
    id: int
    sprite: Optional[str]
    types: List[str]


class PokeAPISprite(TypedDict, total=False):
    """
    Represents sprite data derived from PokeAPI.

    This model handles both successful sprite retrieval and specific error
    states (e.g., requesting a Gen 1 sprite for a Gen 9 Pokemon).
    Using total=False allows optional error fields without wrapping everything
    in generic Optionals.

    Attributes:
        sprite_url: The URL of the image, or None if not found/error.
        error: Error code string (e.g., 'pokemon_not_in_generation') if applicable.
        introduced_gen: The generation the Pokemon debuted in (for error messaging).
        requested_gen: The generation requested by the user (for error messaging).
    """

    sprite_url: Optional[str]
    name: Optional[str]
    id: Optional[int]
    shiny: bool
    generation: int
    # Error handling fields
    error: Optional[str]
    introduced_gen: Optional[int]
    requested_gen: Optional[int]


class CacheStats(TypedDict):
    """
    Represents cache statistics.

    Attributes:
        size: Current number of entries in the cache (not file size in bytes).
        max_size: Maximum allowed entries before eviction triggers.
        hits: Number of successful cache lookups.
        misses: Number of failed lookups that resulted in API calls.
        hit_rate: Percentage string (e.g., '85.5%').
    """

    size: Union[int, str]
    max_size: int
    hits: int
    misses: int
    hit_rate: str


class DeduplicationStats(TypedDict):
    """
    Represents request deduplication statistics.

    Attributes:
        pending_requests: Number of API requests currently in flight (deduplicated).
        active_locks: Number of locks currently held for request coordination.
    """

    pending_requests: int
    active_locks: int
