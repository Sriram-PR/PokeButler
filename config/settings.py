import logging
import os
from pathlib import Path

from dotenv import load_dotenv

"""
Configuration settings for the Smogon Bot.

This module loads environment variables, defines constants for the bot's
operation, and validates the configuration to ensure stability. It handles
Discord tokens, API endpoints, gameplay rules, and system limits.
"""

load_dotenv()

logger = logging.getLogger("smogon_bot.config")

# Bot Configuration - Required
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise ValueError(
        "❌ DISCORD_TOKEN not found in environment variables!\n\n"
        "Please create a .env file in the project root with:\n"
        "  DISCORD_TOKEN=your_token_here\n\n"
        "Get your token from: https://discord.com/developers/applications\n"
        "1. Create/select your application\n"
        "2. Go to 'Bot' section\n"
        "3. Click 'Reset Token' to get your token\n"
        "4. Copy it to your .env file"
    )

# Bot Configuration - Optional
COMMAND_PREFIX = os.getenv("COMMAND_PREFIX", ".")
ENVIRONMENT = os.getenv("ENVIRONMENT", "production")

# Owner ID (for admin commands)
# WARNING: This user has full admin access to the bot, including
# sensitive commands like clearing cache and checking uptime.
OWNER_ID = os.getenv("OWNER_ID")
if OWNER_ID:
    try:
        OWNER_ID = int(OWNER_ID)
    except (ValueError, TypeError):
        raise ValueError(
            "❌ OWNER_ID must be a valid integer (your Discord user ID)!\n\n"
            "To find your Discord ID:\n"
            "1. Enable Developer Mode (User Settings > Advanced > Developer Mode)\n"
            "2. Right-click your username\n"
            "3. Click 'Copy User ID'\n"
            "4. Add to .env file: OWNER_ID=your_id_here"
        )
else:
    OWNER_ID = None
    logger.warning(
        "⚠️  OWNER_ID not set - admin commands (/uptime, /cache-stats, etc.) will be unavailable"
    )

# Target User ID (for shiny monitoring)
TARGET_USER_ID = os.getenv("TARGET_USER_ID")
if TARGET_USER_ID:
    try:
        TARGET_USER_ID = int(TARGET_USER_ID)
    except (ValueError, TypeError):
        raise ValueError(
            "❌ TARGET_USER_ID must be a valid integer (Pokemon bot's Discord ID)!\n\n"
            "To find a bot's Discord ID:\n"
            "1. Enable Developer Mode (User Settings > Advanced > Developer Mode)\n"
            "2. Right-click the bot's username\n"
            "3. Click 'Copy User ID'\n"
            "4. Add to .env file: TARGET_USER_ID=bot_id_here"
        )
else:
    TARGET_USER_ID = None
    logger.warning("⚠️  TARGET_USER_ID not set - shiny monitoring will be disabled")

# Shiny Notification Configuration
SHINY_NOTIFICATION_ENABLED = TARGET_USER_ID is not None
SHINY_NOTIFICATION_MESSAGE = os.getenv(
    "SHINY_NOTIFICATION_MESSAGE",
    "🌟 **SHINY POKEMON DETECTED!** 🌟\nA wild shiny has appeared!",
)

# Data Storage
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
SHINY_CONFIG_FILE = DATA_DIR / "shiny_config.json"

# Database Configuration
# Format: scheme://path_or_host
# Defaults to a local SQLite file if not specified in environment
DB_CONNECTION_STRING = os.getenv(
    "DB_CONNECTION_STRING", f"sqlite:///{DATA_DIR / 'bot.db'}"
)

# API Configuration
SMOGON_SETS_URL = "https://data.pkmn.cc/sets"
POKEAPI_URL = "https://pokeapi.co/api/v2"

# Bot Settings
BOT_COLOR = 0xFF7BA9
MAX_EMBED_FIELDS = 25
MAX_GENERATION = 9

# UI Colors
COLOR_ERROR = 0xFF5252  # Red
COLOR_SUCCESS = 0x4CAF50  # Green
COLOR_WARNING = 0xFFC107  # Amber
COLOR_INFO = 0x2196F3  # Blue

# Cache Configuration
CACHE_TIMEOUT = 60  # Cache duration in seconds
MAX_CACHE_SIZE = 200
CACHE_CLEANUP_INTERVAL = 300  # Cleanup interval in seconds
CACHE_PERSIST_TO_DISK = True

# API Rate Limiting (for external APIs, not user rate limiting)
MAX_CONCURRENT_API_REQUESTS = 5
API_REQUEST_TIMEOUT = 30  # Timeout in seconds

# Retry Configuration
MAX_RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY = 1  # Base delay in seconds for exponential backoff
RETRY_MAX_DELAY = 10  # Maximum delay in seconds between retries

# Command Cooldowns (seconds) - These provide sufficient rate limiting
SMOGON_COMMAND_COOLDOWN = 5  # User can use /smogon once every 5 seconds
EFFORTVALUE_COMMAND_COOLDOWN = 3  # User can use /ev once every 3 seconds
SPRITE_COMMAND_COOLDOWN = 3  # User can use /sprite once every 3 seconds
DEFAULT_COMMAND_COOLDOWN = 5

# Logging Configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Generation Mappings
GENERATION_MAP = {
    "gen1": "gen1",
    "gen2": "gen2",
    "gen3": "gen3",
    "gen4": "gen4",
    "gen5": "gen5",
    "gen6": "gen6",
    "gen7": "gen7",
    "gen8": "gen8",
    "gen9": "gen9",
    "1": "gen1",
    "2": "gen2",
    "3": "gen3",
    "4": "gen4",
    "5": "gen5",
    "6": "gen6",
    "7": "gen7",
    "8": "gen8",
    "9": "gen9",
}

# Tier Mappings
TIER_MAP = {
    "ou": "ou",
    "uu": "uu",
    "ru": "ru",
    "nu": "nu",
    "pu": "pu",
    "zu": "zu",
    "ubers": "ubers",
    "uubers": "uubers",
    "lc": "lc",
    "littlecup": "lc",
    "vgc": "vgc2025regh",
    "vgc2025": "vgc2025regh",
    "doubles": "doublesou",
    "doublesou": "doublesou",
    "dou": "doublesou",
    "1v1": "1v1",
    "monotype": "monotype",
    "ag": "ag",
    "anythinggoes": "ag",
    "cap": "cap",
    "nationaldex": "nationaldex",
    "natdex": "nationaldex",
    "nfe": "nfe",
}

# Formats by generation (ordered by popularity)
FORMATS_BY_GEN = {
    "gen9": [
        "ou",
        "ubers",
        "nationaldex",
        "uu",
        "doublesou",
        "ru",
        "nu",
        "pu",
        "lc",
        "monotype",
        "1v1",
        "vgc2025regh",
        "zu",
        "cap",
        "ag",
    ],
    "gen8": [
        "ou",
        "ubers",
        "uu",
        "doublesou",
        "ru",
        "nu",
        "pu",
        "lc",
        "monotype",
        "1v1",
        "nationaldex",
        "vgc2021",
        "zu",
        "cap",
        "ag",
    ],
    "gen7": [
        "ou",
        "ubers",
        "uu",
        "doublesou",
        "ru",
        "nu",
        "pu",
        "lc",
        "monotype",
        "1v1",
        "vgc2019",
        "zu",
        "ag",
    ],
    "gen6": [
        "ou",
        "ubers",
        "uu",
        "doublesou",
        "ru",
        "nu",
        "pu",
        "lc",
        "monotype",
        "1v1",
        "vgc2016",
        "ag",
    ],
    "gen5": ["ou", "ubers", "uu", "doublesou", "ru", "nu", "lc", "monotype"],
    "gen4": ["ou", "ubers", "uu", "ru", "nu", "lc"],
    "gen3": ["ou", "ubers", "uu", "nu", "lc"],
    "gen2": ["ou", "ubers", "uu", "nu"],
    "gen1": ["ou", "ubers", "uu"],
}

PRIORITY_FORMATS = ["ou", "ubers", "uu", "doublesou"]

# Format display names
FORMAT_NAMES = {
    "ou": "OverUsed",
    "uu": "UnderUsed",
    "ru": "RarelyUsed",
    "nu": "NeverUsed",
    "pu": "PU",
    "zu": "ZeroUsed",
    "lc": "Little Cup",
    "ag": "Anything Goes",
    "ubers": "Ubers",
    "uubers": "UUbers",
    "doublesou": "Doubles OU",
    "1v1": "1v1",
    "monotype": "Monotype",
    "cap": "CAP",
    "nationaldex": "National Dex",
    "vgc2025regh": "VGC 2025 Reg H",
    "vgc2021": "VGC 2021",
    "vgc2019": "VGC 2019",
    "vgc2016": "VGC 2016",
    "nfe": "NFE",
}

# Smogon Dex generation codes
SMOGON_DEX_GENS = {
    "gen1": "rb",
    "gen2": "gs",
    "gen3": "rs",
    "gen4": "dp",
    "gen5": "bw",
    "gen6": "xy",
    "gen7": "sm",
    "gen8": "ss",
    "gen9": "sv",
}

# Blackjack Game Rules
BLACKJACK_VALUE = 21  # Winning hand value
BLACKJACK_DEALER_STAND_THRESHOLD = 17  # Dealer must stand at this value or higher
BLACKJACK_DEALER_HIT_THRESHOLD = 16  # Dealer must hit at this value or lower
BLACKJACK_ACE_HIGH_VALUE = 11  # Ace counted as high
BLACKJACK_ACE_LOW_VALUE = 1  # Ace counted as low
BLACKJACK_FACE_CARD_VALUE = 10  # Value of J, Q, K
BLACKJACK_INITIAL_CARDS_COUNT = 2  # Cards dealt initially to each player

# Blackjack Deck Configuration
BLACKJACK_NUM_DECKS_IN_SHOE = 2  # Number of standard decks used
BLACKJACK_TOTAL_CARDS_IN_SHOE = 104  # Total cards (52 * 2 decks)

# Blackjack Player Limits
BLACKJACK_MIN_PLAYERS = 1  # Minimum players to start game
BLACKJACK_MAX_PLAYERS = 3  # Maximum players per game
BLACKJACK_QUICK_START_PLAYERS = 1  # Players for quick-start mode (.bj command)

# Blackjack Timeout Configuration
BLACKJACK_LOBBY_TIMEOUT = 90  # Lobby timeout in seconds
BLACKJACK_TURN_TIMEOUT_DEFAULT = 60  # Default turn timeout in seconds
BLACKJACK_TURN_TIMEOUT_MIN = 30  # Minimum turn timeout
BLACKJACK_TURN_TIMEOUT_MAX = 120  # Maximum turn timeout

BLACKJACK_TURN_TIMER_WARNING_THRESHOLD = 15  # Show countdown when ≤ this many seconds
BLACKJACK_TURN_TIMER_UPDATE_INTERVAL = 5  # Update countdown every N seconds


def validate_settings():
    """
    Validate all configuration settings to catch errors at startup.

    Raises:
        ValueError: If any configuration value is invalid (e.g., negative
            timeouts, invalid generation numbers).
    """
    # Validate cache settings
    if CACHE_TIMEOUT <= 0:
        raise ValueError("CACHE_TIMEOUT must be positive")

    if MAX_CACHE_SIZE < 1:
        raise ValueError("MAX_CACHE_SIZE must be at least 1")

    if CACHE_CLEANUP_INTERVAL <= 0:
        raise ValueError("CACHE_CLEANUP_INTERVAL must be positive")

    # Validate API settings
    if MAX_CONCURRENT_API_REQUESTS < 1:
        raise ValueError("MAX_CONCURRENT_API_REQUESTS must be at least 1")

    if API_REQUEST_TIMEOUT <= 0:
        raise ValueError("API_REQUEST_TIMEOUT must be positive")

    # Validate retry settings
    if MAX_RETRY_ATTEMPTS < 0:
        raise ValueError("MAX_RETRY_ATTEMPTS must be non-negative")

    if RETRY_BASE_DELAY < 0:
        raise ValueError("RETRY_BASE_DELAY must be non-negative")

    if RETRY_MAX_DELAY < RETRY_BASE_DELAY:
        raise ValueError("RETRY_MAX_DELAY must be >= RETRY_BASE_DELAY")

    # Validate cooldowns
    if SMOGON_COMMAND_COOLDOWN < 0:
        raise ValueError("SMOGON_COMMAND_COOLDOWN must be non-negative")

    if EFFORTVALUE_COMMAND_COOLDOWN < 0:
        raise ValueError("EFFORTVALUE_COMMAND_COOLDOWN must be non-negative")

    if SPRITE_COMMAND_COOLDOWN < 0:
        raise ValueError("SPRITE_COMMAND_COOLDOWN must be non-negative")

    # Validate generation settings
    if MAX_GENERATION < 1 or MAX_GENERATION > 9:
        raise ValueError("MAX_GENERATION must be between 1 and 9")

    logger.info("✅ Configuration validation completed successfully")
