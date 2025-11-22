"""
Main entry point for the Pokemon Smogon Discord Bot.

This module configures the bot, initializes the database connection, loads extensions
(Cogs), and handles global event listeners. It includes specific logic for:
- Shiny Pokemon detection (scanning messages for patterns).
- Global error handling.
- Graceful startup/shutdown sequences.
- Administrative commands for bot management.
"""

import asyncio
import logging
import re
import sys
import time
from typing import Dict, Optional, Set

import discord
from discord import app_commands
from discord.ext import commands

# Import config
from config.settings import (
    CACHE_TIMEOUT,
    COMMAND_PREFIX,
    DISCORD_TOKEN,
    LOG_LEVEL,
    OWNER_ID,
    SHINY_NOTIFICATION_MESSAGE,
    TARGET_USER_ID,
    validate_settings,
)
from utils.constants import ERROR_MESSAGE_LIFETIME
from utils.database import close_database, get_database

# Helper for embeds
from utils.helpers import (
    create_error_embed,
    create_info_embed,
    create_success_embed,
    create_warning_embed,
)

# Setup logging FIRST
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("smogon_bot")

# Update logging level
logging.getLogger().setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))
logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))

# Validate configuration
try:
    validate_settings()
    logger.info("✅ Configuration validation passed")
except ValueError as e:
    logger.critical(f"❌ Configuration validation failed: {e}")
    sys.exit(1)

# Shiny detection pattern
SHINY_PATTERN = re.compile(
    r"A\s{1,5}wild\s{1,5}\*\*Lv\d{1,3}\s{1,3}★",
    re.UNICODE | re.IGNORECASE,
)

# Pre-built notification message to reduce object creation on hot path
NOTIFICATION_CACHE = SHINY_NOTIFICATION_MESSAGE


class GuildShinyConfig:
    """
    Configuration container for shiny monitoring in a specific guild.

    Attributes:
        guild_id: The ID of the guild.
        channels: Set of channel IDs to monitor for shiny spawns.
        embed_channel_id: Optional channel ID to archive shiny embeds.
    """

    __slots__ = ("guild_id", "channels", "embed_channel_id")

    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        self.channels: Set[int] = set()
        self.embed_channel_id: Optional[int] = None


async def load_shiny_configs() -> Dict[int, GuildShinyConfig]:
    """
    Load per-guild shiny configurations from the database.

    Returns:
        Dictionary mapping guild_id to GuildShinyConfig objects.
    """
    try:
        db = await get_database()
        configs_data = await db.load_all_guild_configs()

        configs = {}
        for guild_id, (channels, archive_id) in configs_data.items():
            config = GuildShinyConfig(guild_id)
            config.channels = channels
            config.embed_channel_id = archive_id
            configs[guild_id] = config

        return configs

    except Exception as e:
        logger.error(f"Error loading shiny configurations: {e}")
        return {}


async def save_shiny_configs(configs: Dict[int, GuildShinyConfig]) -> bool:
    """
    Save per-guild shiny configurations to the database.

    Args:
        configs: Dictionary mapping guild_id to GuildShinyConfig objects.

    Returns:
        True if save successful, False otherwise.
    """
    try:
        db = await get_database()

        for guild_id, config in configs.items():
            await db.save_guild_config(
                guild_id, config.channels, config.embed_channel_id
            )

        logger.debug("Saved shiny configs to database")
        return True

    except Exception as e:
        logger.error(f"Error saving shiny configurations: {e}", exc_info=True)
        return False


async def forward_shiny_to_archive(
    bot: commands.Bot,
    guild_config: GuildShinyConfig,
    first_embed: discord.Embed,
    message: discord.Message,
) -> None:
    """
    Background task to forward a shiny embed to an archive channel.

    Args:
        bot: The bot instance.
        guild_config: Configuration object for the specific guild.
        first_embed: The embed detected containing the shiny.
        message: The original message object (used for jump links).
    """
    try:
        archive_channel = bot.get_channel(guild_config.embed_channel_id)  # type: ignore

        if not archive_channel:
            logger.warning(
                f"Archive channel {guild_config.embed_channel_id} not found "
                f"in {message.guild.name}",  # type: ignore
                extra={"guild_id": message.guild.id},  # type: ignore
            )
            return

        jump_link = (
            f"https://discord.com/channels/{message.guild.id}/"  # type: ignore
            f"{message.channel.id}/{message.id}"
        )

        await archive_channel.send(  # type: ignore
            content=f"Jump to message: {jump_link}", embed=first_embed
        )

        logger.info(
            f"Forwarded shiny embed to archive channel {archive_channel.name}",  # type: ignore
            extra={"guild_id": message.guild.id},  # type: ignore
        )

    except Exception as e:
        logger.error(
            f"Error forwarding to archive: {e}",
            extra={"guild_id": message.guild.id},  # type: ignore
            exc_info=True,
        )


class AdminCommands(commands.Cog):
    """Administrative and Developer commands for bot maintenance."""

    def __init__(self, bot: "SmogonBot"):
        self.bot = bot

    @app_commands.command(
        name="cache-stats", description="View API cache statistics (Developer only)"
    )
    async def cache_stats(self, interaction: discord.Interaction) -> None:
        """
        View cache performance statistics.

        Restricted to the bot owner. Shows hit rates and memory usage.
        """
        if not OWNER_ID or interaction.user.id != OWNER_ID:
            embed = create_error_embed(
                "Access Denied", "This command is only available to the bot owner."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        smogon_cog = self.bot.get_cog("Smogon")
        if not smogon_cog or not hasattr(smogon_cog, "api_client"):
            embed = create_error_embed("System Error", "API client not available.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        api_client = smogon_cog.api_client  # type: ignore
        stats = api_client.get_cache_stats()

        # Get actual size from database
        try:
            db = await get_database()
            db_stats = await db.get_cache_stats()
            actual_size = db_stats["size"]
        except Exception as e:
            logger.error(f"Error getting DB cache stats: {e}")
            actual_size = 0

        embed = discord.Embed(
            title="📊 API Cache Statistics",
            description="Performance metrics for API caching system",
            color=0x00CED1,
            timestamp=interaction.created_at,
        )

        embed.add_field(
            name="💾 Cache Size",
            value=(f"```{actual_size:,} / {stats['max_size']:,} entries```\n"),
            inline=False,
        )

        hit_rate_value = float(stats["hit_rate"].rstrip("%"))
        hit_rate_emoji = (
            "🟢" if hit_rate_value >= 70 else "🟡" if hit_rate_value >= 40 else "🔴"
        )

        embed.add_field(
            name=f"{hit_rate_emoji} Hit Rate",
            value=(
                f"```{stats['hit_rate']}```\n"
                f"Hits: {stats['hits']:,} | Misses: {stats['misses']:,}"
            ),
            inline=True,
        )

        total = stats["hits"] + stats["misses"]
        embed.add_field(
            name="📈 Total Requests", value=f"```{total:,} requests```", inline=True
        )

        embed.set_footer(text=f"Cache timeout: {CACHE_TIMEOUT}s")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="cache-clear", description="Clear the API cache (Developer only)"
    )
    async def cache_clear(self, interaction: discord.Interaction) -> None:
        """
        Manually clear the API cache.

        Restricted to the bot owner. useful if API data is stale or corrupted.
        """
        if not OWNER_ID or interaction.user.id != OWNER_ID:
            embed = create_error_embed(
                "Access Denied", "This command is only available to the bot owner."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        smogon_cog = self.bot.get_cog("Smogon")
        if not smogon_cog or not hasattr(smogon_cog, "api_client"):
            embed = create_error_embed("System Error", "API client not available.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        api_client = smogon_cog.api_client  # type: ignore
        old_stats = api_client.get_cache_stats()

        await api_client.clear_cache()

        embed = create_success_embed(
            "Cache Cleared", "API cache has been manually cleared"
        )
        embed.add_field(
            name="Previous Hit Rate", value=old_stats["hit_rate"], inline=True
        )
        embed.add_field(
            name="Total Requests",
            value=f"{old_stats['hits'] + old_stats['misses']:,}",
            inline=True,
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="shiny-channel",
        description="Manage shiny monitoring channels for this server (Developer only)",
    )
    @app_commands.describe(
        action="Action to perform",
        channel="Channel to add/remove (leave empty for current channel)",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="add", value="add"),
            app_commands.Choice(name="remove", value="remove"),
            app_commands.Choice(name="list", value="list"),
            app_commands.Choice(name="clear", value="clear"),
        ]
    )
    @app_commands.default_permissions(administrator=True)
    async def shiny_channel(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        channel: Optional[discord.TextChannel] = None,
    ) -> None:
        """
        Manage channels to monitor for shiny Pokemon in this server.

        Requires Administrator permissions.
        """
        if not interaction.guild:
            embed = create_error_embed(
                "Error", "This command can only be used in a server."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        is_owner = OWNER_ID and interaction.user.id == OWNER_ID
        is_admin = interaction.user.guild_permissions.administrator  # type: ignore

        if not (is_owner or is_admin):
            embed = create_error_embed(
                "Permission Denied",
                "Requires Administrator permissions or bot owner access!",
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        guild_config = self.bot.get_guild_config(interaction.guild.id)
        action_value = action.value
        target_channel = channel or interaction.channel

        if action_value == "add":
            if target_channel.id in guild_config.channels:  # type: ignore
                embed = create_warning_embed(
                    "Already Monitored",
                    f"{target_channel.mention} is already being monitored.",  # type: ignore
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                guild_config.channels.add(target_channel.id)  # type: ignore
                await save_shiny_configs(self.bot.shiny_configs)
                embed = create_success_embed(
                    "Channel Added",
                    f"Added {target_channel.mention} to shiny monitoring.\nTotal channels: {len(guild_config.channels)}",  # type: ignore
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)

        elif action_value == "remove":
            if target_channel.id not in guild_config.channels:  # type: ignore
                embed = create_warning_embed(
                    "Not Monitored",
                    f"{target_channel.mention} is not being monitored.",  # type: ignore
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                guild_config.channels.remove(target_channel.id)  # type: ignore
                await save_shiny_configs(self.bot.shiny_configs)
                embed = create_success_embed(
                    "Channel Removed",
                    f"Removed {target_channel.mention} from monitoring.\nTotal channels: {len(guild_config.channels)}",  # type: ignore
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)

        elif action_value == "list":
            if not guild_config.channels:
                embed = create_info_embed(
                    "No Channels",
                    "No channels configured for shiny monitoring.\nUse `/shiny-channel add` to add channels.",
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                embed = discord.Embed(
                    title=f"🔍 Shiny Monitoring - {interaction.guild.name}",
                    description=f"Total: {len(guild_config.channels)} channel(s)",
                    color=0xFFD700,
                )

                channel_list = []
                for channel_id in guild_config.channels:
                    channel_obj = self.bot.get_channel(channel_id)
                    if channel_obj:
                        channel_list.append(f"• {channel_obj.mention}")  # type: ignore
                    else:
                        channel_list.append(f"• Unknown Channel (`{channel_id}`)")

                embed.add_field(
                    name="Monitored Channels",
                    value="\n".join(channel_list) if channel_list else "None",
                    inline=False,
                )

                await interaction.response.send_message(embed=embed, ephemeral=True)

        elif action_value == "clear":
            count = len(guild_config.channels)
            guild_config.channels.clear()
            await save_shiny_configs(self.bot.shiny_configs)
            embed = create_success_embed(
                "Cleared", f"Cleared all shiny monitoring channels ({count} removed)."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="shiny-archive",
        description="Manage shiny archive channel for this server (Developer only)",
    )
    @app_commands.describe(
        action="Action to perform",
        channel="Channel to set as archive (leave empty for current channel)",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="set", value="set"),
            app_commands.Choice(name="unset", value="unset"),
            app_commands.Choice(name="show", value="show"),
        ]
    )
    @app_commands.default_permissions(administrator=True)
    async def shiny_archive(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        channel: Optional[discord.TextChannel] = None,
    ) -> None:
        """
        Manage archive channel where shiny embeds are forwarded in this server.

        Requires Administrator permissions.
        """
        if not interaction.guild:
            embed = create_error_embed(
                "Error", "This command can only be used in a server."
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        is_owner = OWNER_ID and interaction.user.id == OWNER_ID
        is_admin = interaction.user.guild_permissions.administrator  # type: ignore

        if not (is_owner or is_admin):
            embed = create_error_embed(
                "Permission Denied",
                "Requires Administrator permissions or bot owner access!",
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        guild_config = self.bot.get_guild_config(interaction.guild.id)
        action_value = action.value

        if action_value == "set":
            target_channel = channel or interaction.channel
            guild_config.embed_channel_id = target_channel.id  # type: ignore
            await save_shiny_configs(self.bot.shiny_configs)

            embed = create_success_embed(
                "Archive Set",
                f"Set {target_channel.mention} as the shiny archive channel for **{interaction.guild.name}**.\n"  # type: ignore
                f"Shiny embeds will be forwarded here with jump links.",
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            logger.info(
                f"Set shiny archive: {target_channel.name} in {interaction.guild.name}"  # type: ignore
            )

        elif action_value == "unset":
            if guild_config.embed_channel_id is None:
                embed = create_warning_embed(
                    "Not Configured",
                    f"No archive channel is currently set for **{interaction.guild.name}**.",
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                old_channel_id = guild_config.embed_channel_id
                guild_config.embed_channel_id = None
                await save_shiny_configs(self.bot.shiny_configs)

                embed = create_success_embed(
                    "Archive Removed",
                    f"Removed archive channel from **{interaction.guild.name}** (was: `{old_channel_id}`).",
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)

        elif action_value == "show":
            if guild_config.embed_channel_id is None:
                embed = create_info_embed(
                    "Not Configured",
                    f"No archive channel is currently configured for **{interaction.guild.name}**.\nUse `/shiny-archive set` to set one.",
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
            else:
                archive_channel = self.bot.get_channel(guild_config.embed_channel_id)

                embed = discord.Embed(
                    title=f"📦 Shiny Archive - {interaction.guild.name}",
                    description="Shiny embeds are forwarded to this channel",
                    color=0xFFD700,
                )

                if archive_channel:
                    embed.add_field(
                        name="Archive Channel",
                        value=f"{archive_channel.mention} (`{guild_config.embed_channel_id}`)",  # type: ignore
                        inline=False,
                    )
                else:
                    embed.add_field(
                        name="Archive Channel",
                        value=f"Unknown Channel (`{guild_config.embed_channel_id}`) - May have been deleted",
                        inline=False,
                    )

                embed.set_footer(
                    text=f"Configuration is specific to {interaction.guild.name}"
                )

                await interaction.response.send_message(embed=embed, ephemeral=True)


class SmogonBot(commands.Bot):
    """
    Custom bot class extending `commands.Bot`.

    Features:
    - Async initialization via `setup_hook`.
    - Database connection lifecycle management.
    - Shiny config loading/saving.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.start_time: Optional[float] = None
        self.shiny_configs: Dict[int, GuildShinyConfig] = {}

    async def setup_hook(self) -> None:
        """
        Async initialization hook called before the bot connects to Discord.

        Performs:
        1. Time recording for uptime.
        2. Database connection initialization.
        3. Loading of guild configurations.
        4. Extension (Cog) loading.
        5. API connectivity validation.
        6. Slash command synchronization.
        """
        logger.info("Bot setup hook called - performing async initialization")
        self.start_time = time.time()

        # Load per-guild shiny configurations from database
        self.shiny_configs = await load_shiny_configs()

        # Load extensions
        await self.load_extensions()

        # Add Admin Commands Cog
        await self.add_cog(AdminCommands(self))
        logger.info("✅ Loaded AdminCommands")

        # Validate API connectivity
        logger.info("Validating API connectivity...")
        smogon_cog = self.get_cog("Smogon")
        if smogon_cog and hasattr(smogon_cog, "api_client"):
            await smogon_cog.api_client.validate_api_connectivity()  # type: ignore

        # Sync slash commands
        try:
            synced = await self.tree.sync()
            logger.info(f"✅ Synced {len(synced)} slash command(s) to Discord")
        except Exception as e:
            logger.error(f"❌ Failed to sync commands: {e}")

        # Register the app command error handler
        self.tree.on_error = self.on_app_command_error

    async def load_extensions(self) -> None:
        """Load all bot cogs (Smogon, Blackjack, Utility)."""
        cogs = ["cogs.smogon", "cogs.blackjack", "cogs.utility"]
        for cog in cogs:
            try:
                await self.load_extension(cog)
                logger.info(f"✅ Loaded {cog}")
            except Exception as e:
                logger.error(f"❌ Failed to load {cog}: {e}", exc_info=e)

    async def close(self) -> None:
        """
        Clean up resources during shutdown.

        Saves configs, closes API clients, and closes database connections
        before shutting down the bot instance.
        """
        logger.info("Bot shutdown initiated - cleaning up resources")
        await save_shiny_configs(self.shiny_configs)

        for cog_name, cog in self.cogs.items():
            if hasattr(cog, "api_client"):
                await cog.api_client.close()  # type: ignore

        await close_database()
        await super().close()

    def get_guild_config(self, guild_id: int) -> GuildShinyConfig:
        """
        Get existing guild config or create a new one if not present.

        Args:
            guild_id: The ID of the guild.

        Returns:
            The GuildShinyConfig object.
        """
        if guild_id not in self.shiny_configs:
            self.shiny_configs[guild_id] = GuildShinyConfig(guild_id)
        return self.shiny_configs[guild_id]

    async def on_ready(self) -> None:
        """Called when the bot has successfully connected to the Gateway."""
        logger.info(f"✅ Bot is ready as {self.user.name}")  # type: ignore
        await self.change_presence(
            activity=discord.Game(name=f"Pokemon Smogon | {COMMAND_PREFIX}smogon")
        )

    async def on_message(self, message: discord.Message) -> None:
        """
        Global message listener.

        Handles:
        1. Shiny Pokemon Detection: Checks messages from `TARGET_USER_ID` for
           specific regex patterns in embeds.
        2. Command Processing: Passes messages to the command handler.
        """
        if message.author.id == self.user.id:  # type: ignore
            return

        if not message.guild:
            await self.process_commands(message)
            return

        # Shiny Detection Logic
        try:
            if TARGET_USER_ID and message.author.id == TARGET_USER_ID:
                if message.embeds:
                    first_embed = message.embeds[0]
                    if first_embed.description and SHINY_PATTERN.search(
                        first_embed.description
                    ):
                        guild_config = self.shiny_configs.get(message.guild.id)
                        if guild_config and message.channel.id in guild_config.channels:
                            await message.channel.send(NOTIFICATION_CACHE)

                            if guild_config.embed_channel_id:
                                asyncio.create_task(
                                    forward_shiny_to_archive(
                                        self, guild_config, first_embed, message
                                    )
                                )
        except Exception as e:
            logger.error(f"Error in shiny detection: {e}")

        await self.process_commands(message)

    async def on_guild_join(self, guild: discord.Guild) -> None:
        """Initialize config when joining a new guild."""
        self.get_guild_config(guild.id)

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        """Cleanup config when removed from a guild."""
        if guild.id in self.shiny_configs:
            del self.shiny_configs[guild.id]
            try:
                db = await get_database()
                await db.delete_guild_config(guild.id)
            except Exception:
                pass

    async def on_command_error(
        self, ctx: commands.Context, error: commands.CommandError
    ) -> None:
        """
        Global error handler for text-based prefix commands.

        Converts raw exceptions into standardized, user-friendly embeds.
        """

        if isinstance(error, commands.CommandNotFound):
            return

        if isinstance(error, commands.MaxConcurrencyReached):
            embed = create_warning_embed(
                "Busy",
                f"The bot is processing too many `{ctx.command.name}` commands. Try again momentarily.",  # type: ignore
            )
            await ctx.send(embed=embed, delete_after=10)
            return

        if isinstance(error, commands.CommandOnCooldown):
            embed = create_warning_embed(
                "Cooldown", f"Try again in **{error.retry_after:.1f}s**"
            )
            await ctx.send(embed=embed, delete_after=ERROR_MESSAGE_LIFETIME)

        elif isinstance(error, commands.MissingRequiredArgument):
            embed = create_error_embed(
                "Missing Argument",
                f"Missing: `{error.param.name}`\nUse `{COMMAND_PREFIX}help` for usage.",
            )
            await ctx.send(embed=embed, delete_after=ERROR_MESSAGE_LIFETIME)

        elif isinstance(error, commands.BadArgument):
            embed = create_error_embed(
                "Invalid Argument",
                f"Invalid input provided!\nUse `{COMMAND_PREFIX}help` for usage.",
            )
            await ctx.send(embed=embed, delete_after=ERROR_MESSAGE_LIFETIME)

        elif isinstance(error, commands.MissingPermissions):
            perms = ", ".join(error.missing_permissions)
            embed = create_error_embed(
                "Permission Denied", f"You are missing: `{perms}`"
            )
            await ctx.send(embed=embed, delete_after=ERROR_MESSAGE_LIFETIME)

        elif isinstance(error, commands.BotMissingPermissions):
            perms = ", ".join(error.missing_permissions)
            embed = create_error_embed(
                "Bot Permission Denied", f"I am missing: `{perms}`"
            )
            await ctx.send(embed=embed, delete_after=ERROR_MESSAGE_LIFETIME)

        elif isinstance(error, commands.CheckFailure):
            embed = create_error_embed(
                "Permission Denied", "You don't have permission to use this command!"
            )
            await ctx.send(embed=embed, delete_after=ERROR_MESSAGE_LIFETIME)

        else:
            logger.error(f"Unexpected error: {error}", exc_info=error)
            embed = create_error_embed(
                "System Error", "An unexpected error occurred. Please try again later."
            )
            await ctx.send(embed=embed, delete_after=ERROR_MESSAGE_LIFETIME)

    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: discord.app_commands.AppCommandError,
    ) -> None:
        """
        Global error handler for application (slash) commands.

        Handles deferral states to ensure the error message is delivered
        via `followup` if the interaction is already acknowledged.
        """

        if interaction.response.is_done():
            send_method = interaction.followup.send
        else:
            send_method = interaction.response.send_message

        if isinstance(error, discord.app_commands.CommandOnCooldown):
            embed = create_warning_embed(
                "Cooldown", f"Try again in **{error.retry_after:.1f}s**"
            )

        elif isinstance(error, discord.app_commands.MissingPermissions):
            perms = ", ".join(error.missing_permissions)
            embed = create_error_embed(
                "Permission Denied", f"You are missing: `{perms}`"
            )

        elif isinstance(error, discord.app_commands.BotMissingPermissions):
            perms = ", ".join(error.missing_permissions)
            embed = create_error_embed(
                "Bot Permission Denied", f"I am missing: `{perms}`"
            )

        else:
            logger.error(f"Unexpected slash error: {error}", exc_info=error)
            embed = create_error_embed(
                "System Error", "An unexpected error occurred. Please try again later."
            )

        try:
            await send_method(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Failed to send error message: {e}")


async def main() -> None:
    """
    Main bot startup function.

    Sets intents, initializes the bot instance, and enters the context manager.
    """
    intents = discord.Intents.default()
    intents.message_content = True
    intents.guilds = True

    bot = SmogonBot(command_prefix=COMMAND_PREFIX, intents=intents, help_command=None)

    async with bot:
        await bot.start(DISCORD_TOKEN)  # type: ignore


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user (Ctrl+C)")
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=e)
        sys.exit(1)
