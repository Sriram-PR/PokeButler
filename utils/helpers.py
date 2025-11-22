"""
Helper functions for Discord embed creation and text formatting.

This module contains utility functions to:
- Sanitize text to prevent Discord mention exploits.
- Format Pokemon data (names, moves, stats) for display.
- Create standardized embeds (Error, Success, Info, Warning).
- Truncate text to ensure compliance with Discord API limits.
"""

from typing import Any, Dict, List, Optional

import discord

from config.settings import (
    COLOR_ERROR,
    COLOR_INFO,
    COLOR_SUCCESS,
    COLOR_WARNING,
    FORMAT_NAMES,
    SMOGON_DEX_GENS,
)
from utils.assets import TYPE_EMOJIS
from utils.constants import (
    DISCORD_EMBED_DESCRIPTION_LIMIT,
    DISCORD_EMBED_TITLE_LIMIT,
    DISCORD_EMBED_TOTAL_LIMIT,
)


def sanitize_embed_content(text: str) -> str:
    """
    Sanitize text for safe embedding by escaping mentions and markdown.

    Injects a zero-width space (`\u200b`) into mentions (e.g., `@everyone`
    becomes `@` + `\u200b` + `everyone`) to prevent them from pinging users,
    even if the bot has mention permissions. Also escapes markdown characters
    to prevent formatting exploits.

    Args:
        text: Text to sanitize.

    Returns:
        Sanitized text safe for Discord embeds.
    """
    if not text:
        return ""

    # Prevent @everyone, @here, and user mentions
    text = text.replace("@everyone", "@\u200beveryone")
    text = text.replace("@here", "@\u200bhere")
    text = text.replace("@", "@\u200b")  # Zero-width space prevents mentions

    # Escape Discord markdown to prevent formatting exploits
    text = text.replace("`", "\\`")
    text = text.replace("*", "\\*")
    text = text.replace("_", "\\_")
    text = text.replace("~", "\\~")
    text = text.replace("|", "\\|")

    return text


def capitalize_pokemon_name(name: str) -> str:
    """
    Properly capitalize Pokemon names with special handling for forms.

    Handles hyphens generally (e.g., 'landorus-therian' -> 'Landorus-Therian')
    and maps specific edge cases like 'Ho-Oh' or 'Type: Null' manually.

    Args:
        name: Pokemon name (e.g., 'garchomp', 'landorus-therian').

    Returns:
        Properly formatted display name.
    """
    # Special cases
    special_cases = {
        "nidoran-f": "Nidoran♀",
        "nidoran-m": "Nidoran♂",
        "mr-mime": "Mr. Mime",
        "mime-jr": "Mime Jr.",
        "type-null": "Type: Null",
        "ho-oh": "Ho-Oh",
        "porygon-z": "Porygon-Z",
        "jangmo-o": "Jangmo-o",
        "hakamo-o": "Hakamo-o",
        "kommo-o": "Kommo-o",
    }

    name_lower = name.lower()
    if name_lower in special_cases:
        return special_cases[name_lower]

    # Handle forms (e.g., "landorus-therian" -> "Landorus-Therian")
    parts = name.split("-")
    capitalized = [part.capitalize() for part in parts]

    return "-".join(capitalized)


def format_generation_tier(generation: str, tier: str) -> str:
    """
    Format generation and tier for display.

    Converts internal keys like 'gen9' and 'ou' into readable titles
    like 'Gen 9 OU (OverUsed)'.

    Args:
        generation: Generation string (e.g., 'gen9').
        tier: Tier string (e.g., 'ou').

    Returns:
        Formatted string.
    """
    # Extract generation number
    gen_num = generation.replace("gen", "")
    tier_upper = tier.upper()

    # Get full tier name if available
    tier_full_name = FORMAT_NAMES.get(tier.lower())

    if tier_full_name:
        tier_display = f"{tier_upper} ({tier_full_name})"
    else:
        tier_display = tier_upper

    return f"Gen {gen_num} {tier_display}"


def get_format_display_name(tier: str, set_count: Optional[int] = None) -> str:
    """
    Get a clean display name for a format/tier in UI selectors.

    Args:
        tier: Tier string (e.g., 'ou', 'doublesou').
        set_count: Optional number of sets available for this format.

    Returns:
        Formatted display name (e.g., 'OU - 5 sets').
    """
    tier_upper = tier.upper()
    display = tier_upper

    if set_count is not None:
        display += f" - {set_count} set{'s' if set_count != 1 else ''}"

    return display


def format_move_list(moves: List[Any]) -> str:
    """
    Format a list of moves for display, handling slash options.

    Smogon API sometimes returns a list of choices for a single move slot.
    These are joined by ' / '.

    Args:
        moves: List of moves (can be strings or lists of strings for choices).

    Returns:
        Formatted string with bullet points.
    """
    if not moves:
        return "No moves specified"

    formatted = []
    for move in moves:
        if isinstance(move, list):
            formatted.append(" / ".join(move))
        else:
            formatted.append(str(move))

    return "\n".join(f"• {move}" for move in formatted)


def format_evs(evs: Dict[str, int]) -> str:
    """
    Format an EV dictionary into standard competitive syntax.

    Args:
        evs: Dictionary mapping stat names to values (e.g., {'hp': 252, 'atk': 252}).

    Returns:
        Formatted string (e.g., '252 HP / 252 Atk / 4 Def').
    """
    if not evs:
        return "No EVs specified"

    ev_order = ["hp", "atk", "def", "spa", "spd", "spe"]
    formatted = []

    for stat in ev_order:
        if stat in evs and evs[stat] > 0:
            formatted.append(f"{evs[stat]} {stat.upper()}")

    return " / ".join(formatted) if formatted else "No EVs specified"


def format_ivs(ivs: Dict[str, int]) -> Optional[str]:
    """
    Format an IV dictionary into standard competitive syntax.

    Only explicitly shows IVs that are NOT 31 (perfect), as 31 is the
    standard assumption in competitive play.

    Args:
        ivs: Dictionary mapping stat names to values.

    Returns:
        Formatted string (e.g., '0 Atk') or None if all IVs are 31.
    """
    if not ivs:
        return None

    iv_order = ["hp", "atk", "def", "spa", "spd", "spe"]
    formatted = []

    for stat in iv_order:
        if stat in ivs and ivs[stat] != 31:
            formatted.append(f"{ivs[stat]} {stat.upper()}")

    return " / ".join(formatted) if formatted else None


def _format_field_generic(
    field: Any, default: str = "—", none_value: str = "None"
) -> str:
    """
    Generic helper for formatting fields that might be strings or lists.

    Args:
        field: Value to format (string, list of strings, or None).
        default: Value to return if a list is empty.
        none_value: Value to return if the field itself is None.

    Returns:
        Formatted string joined by slashes if it was a list.
    """
    if isinstance(field, list):
        filtered = [str(f).strip() for f in field if f]
        return " / ".join(filtered) if filtered else default

    if field:
        return str(field).strip()

    return none_value


def format_ability(ability: Any) -> str:
    """
    Format ability field.

    Args:
        ability: Ability name(s) (string or list).

    Returns:
        Formatted string.
    """
    return _format_field_generic(ability, default="—", none_value="—")


def format_item(item: Any) -> str:
    """
    Format item field.

    Args:
        item: Item name(s) (string or list).

    Returns:
        Formatted string.
    """
    return _format_field_generic(item, default="None", none_value="None")


def format_nature(nature: Any) -> str:
    """
    Format nature field.

    Args:
        nature: Nature name(s) (string or list).

    Returns:
        Formatted string.
    """
    return _format_field_generic(nature, default="Any", none_value="Any")


def format_tera_type(tera: Any) -> Optional[str]:
    """
    Format Tera Type field with corresponding custom emojis.

    Args:
        tera: Tera type name(s) (string or list).

    Returns:
        Formatted string with emojis, or None if input is empty.
    """
    if not tera:
        return None

    if isinstance(tera, list):
        formatted = []
        for t in tera:
            emoji = TYPE_EMOJIS.get(t.lower(), "•")
            formatted.append(f"{emoji} {t}")
        return " / ".join(formatted)
    else:
        emoji = TYPE_EMOJIS.get(tera.lower(), "•")
        return f"{emoji} {tera}"


def truncate_text(text: str, max_length: int = 1024, smart: bool = True) -> str:
    """
    Truncate text to fit within Discord API limits.

    Args:
        text: The text to truncate.
        max_length: The absolute maximum characters allowed.
        smart: If True, attempts to split at the nearest space character
            before the limit to avoid cutting words in half.

    Returns:
        Truncated text, ending with '...' if truncation occurred.
    """
    if len(text) <= max_length:
        return text

    if smart:
        # Try to truncate at last space before max_length
        truncate_point = text.rfind(" ", 0, max_length - 3)
        if truncate_point > max_length // 2:  # Only if we find a space in latter half
            return text[:truncate_point] + "..."

    # Fallback to hard truncate
    return text[: max_length - 3] + "..."


def get_smogon_url(pokemon: str, generation: str, tier: str) -> str:
    """
    Generate the official Smogon Dex URL for a specific analysis.

    Maps internal generation codes (gen9) to Smogon codes (sv).

    Args:
        pokemon: Pokemon name.
        generation: Generation string.
        tier: Tier string.

    Returns:
        URL string.
    """
    # Get Smogon generation code
    gen_code = SMOGON_DEX_GENS.get(generation.lower(), "sv")  # Default to SV

    # Format pokemon name (lowercase, keep hyphens)
    pokemon_formatted = pokemon.lower().strip().replace(" ", "-")

    # Format tier (lowercase)
    tier_formatted = tier.lower().strip()

    # Build URL
    url = f"https://www.smogon.com/dex/{gen_code}/pokemon/{pokemon_formatted}/{tier_formatted}/"

    return url


def create_error_embed(title: str, description: str) -> discord.Embed:
    """
    Create a standardized error embed (Red).

    Applies content sanitization to inputs.

    Args:
        title: Title of the error.
        description: Detailed error message.

    Returns:
        Discord Embed object.
    """
    # Sanitize content to prevent exploits
    safe_title = sanitize_embed_content(title)
    safe_description = sanitize_embed_content(description)

    embed = discord.Embed(
        title=f"❌ {safe_title}",
        description=truncate_text(safe_description, DISCORD_EMBED_DESCRIPTION_LIMIT),
        color=COLOR_ERROR,
    )
    return embed


def create_success_embed(title: str, description: str) -> discord.Embed:
    """
    Create a standardized success embed (Green).

    Applies content sanitization to inputs.

    Args:
        title: Title of the success message.
        description: Detailed success message.

    Returns:
        Discord Embed object.
    """
    # Sanitize content to prevent exploits
    safe_title = sanitize_embed_content(title)
    safe_description = sanitize_embed_content(description)

    embed = discord.Embed(
        title=f"✅ {safe_title}",
        description=truncate_text(safe_description, DISCORD_EMBED_DESCRIPTION_LIMIT),
        color=COLOR_SUCCESS,
    )
    return embed


def create_warning_embed(title: str, description: str) -> discord.Embed:
    """
    Create a standardized warning embed (Amber).

    Applies content sanitization to inputs.

    Args:
        title: Title of the warning.
        description: Detailed warning message.

    Returns:
        Discord Embed object.
    """
    # Sanitize content to prevent exploits
    safe_title = sanitize_embed_content(title)
    safe_description = sanitize_embed_content(description)

    embed = discord.Embed(
        title=f"⚠️ {safe_title}",
        description=truncate_text(safe_description, DISCORD_EMBED_DESCRIPTION_LIMIT),
        color=COLOR_WARNING,
    )
    return embed


def create_info_embed(title: str, description: str) -> discord.Embed:
    """
    Create a standardized info embed (Blue).

    Applies content sanitization to inputs.

    Args:
        title: Title of the info message.
        description: Detailed info message.

    Returns:
        Discord Embed object.
    """
    # Sanitize content to prevent exploits
    safe_title = sanitize_embed_content(title)
    safe_description = sanitize_embed_content(description)

    embed = discord.Embed(
        title=f"ℹ️ {safe_title}",
        description=truncate_text(safe_description, DISCORD_EMBED_DESCRIPTION_LIMIT),
        color=COLOR_INFO,
    )
    return embed


def validate_and_truncate_embed(embed: discord.Embed) -> discord.Embed:
    """
    Validate and truncate an embed to ensure it fits within Discord API limits.

    Checks total character counts and truncates fields dynamically if limits
    are exceeded.

    Args:
        embed: The Discord embed to validate.

    Returns:
        The modified (truncated) embed.
    """
    # Truncate title if needed
    if embed.title and len(embed.title) > DISCORD_EMBED_TITLE_LIMIT:
        embed.title = embed.title[: DISCORD_EMBED_TITLE_LIMIT - 3] + "..."

    # Truncate description if needed
    if embed.description and len(embed.description) > DISCORD_EMBED_DESCRIPTION_LIMIT:
        embed.description = truncate_text(
            embed.description, DISCORD_EMBED_DESCRIPTION_LIMIT
        )

    # Check total character count
    total_chars = 0
    if embed.title:
        total_chars += len(embed.title)
    if embed.description:
        total_chars += len(embed.description)
    if embed.footer.text:
        total_chars += len(embed.footer.text)
    if embed.author.name:
        total_chars += len(embed.author.name)

    for field in embed.fields:
        total_chars += len(field.name) + len(field.value)  # type: ignore

    # If over limit, we need to remove some fields
    if total_chars > DISCORD_EMBED_TOTAL_LIMIT:
        # Calculate how much we need to remove
        excess = total_chars - DISCORD_EMBED_TOTAL_LIMIT

        # Try to truncate the description first
        if embed.description and len(embed.description) > excess:
            new_desc_length = max(100, len(embed.description) - excess - 50)
            embed.description = truncate_text(embed.description, new_desc_length)

    return embed
