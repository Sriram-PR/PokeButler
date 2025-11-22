"""
Utility commands cog for general bot functionality.

This module contains system-level commands including:
- Help system with category filtering.
- Diagnostic tools (ping, uptime, status).
- Debugging tools for the bot owner.
"""

import logging
import time

import discord
from discord import app_commands
from discord.ext import commands

from config.settings import (
    BOT_COLOR,
    OWNER_ID,
    TARGET_USER_ID,
)
from utils.constants import (
    HEALTHY_LATENCY_MS,
    MAX_MESSAGE_HISTORY_FOR_DEBUG,
    WARNING_LATENCY_MS,
)
from utils.database import get_database
from utils.helpers import create_error_embed

logger = logging.getLogger("smogon_bot.utility")


class Utility(commands.Cog):
    """Utility commands for bot information, diagnostics, and help."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def cog_unload(self) -> None:
        """Cleanup when cog is unloaded."""
        logger.info("Cog unloaded", extra={"cog": "utility"})

    @commands.hybrid_command(
        name="help",
        description="Show bot commands and usage (optionally filtered by category)",
    )
    @app_commands.describe(category="Filter commands by category (optional)")
    @app_commands.choices(
        category=[
            app_commands.Choice(name="All Commands", value="all"),
            app_commands.Choice(name="Pokemon Commands", value="pokemon"),
            app_commands.Choice(name="Blackjack Commands", value="blackjack"),
            app_commands.Choice(name="System Commands", value="system"),
            app_commands.Choice(name="Owner Commands", value="owner"),
        ]
    )
    @commands.max_concurrency(10, commands.BucketType.default, wait=False)
    async def help_command(self, ctx: commands.Context, category: str = "all") -> None:
        """
        Display help information.

        Allows filtering commands by specific categories to avoid cluttering the chat.

        Args:
            ctx: The command context.
            category: The category to filter by ('all', 'pokemon', 'blackjack',
                'system', 'owner'). Default is 'all'.
        """
        if category == "all":
            embed = self._create_full_help_embed()
        elif category == "pokemon":
            embed = self._create_pokemon_help_embed()
        elif category == "blackjack":
            embed = self._create_blackjack_help_embed()
        elif category == "system":
            embed = self._create_system_help_embed()
        elif category == "owner":
            if OWNER_ID:
                embed = self._create_owner_help_embed()
            else:
                embed = create_error_embed(
                    "Access Denied",
                    "Owner commands are not available (OWNER_ID not configured).",
                )
                await ctx.send(embed=embed, ephemeral=True)
                return
        else:
            embed = self._create_full_help_embed()

        await ctx.send(embed=embed)

    def _create_full_help_embed(self) -> discord.Embed:
        """Create help embed with all commands."""
        embed = discord.Embed(
            title="🎮 Pokemon Smogon Bot - Help",
            description="Get competitive Pokemon movesets from Smogon University",
            color=BOT_COLOR,
        )

        embed.add_field(
            name="📖 Pokemon Commands",
            value=(
                "`/smogon <pokemon> [generation] [tier]`\n"
                "`/effortvalue <pokemon>`\n"
                "`/sprite <pokemon> [shiny] [generation]`\n"
                "`/dmgcalc` - Damage calculator link\n"
            ),
            inline=False,
        )

        embed.add_field(
            name="🎴 Blackjack Commands",
            value=(
                "`.bj @user` - Quick 1v1 game\n"
                "`/blackjack quick-start @player` - Quick 1v1 (slash)\n"
                "`/blackjack start` - Full game setup\n"
                "`/blackjack showhand` - View your hand (dealer)\n"
            ),
            inline=False,
        )

        embed.add_field(
            name="🔧 System Commands",
            value=(
                "`/ping` - Check bot latency\n"
                "`/status` - Check bot health\n"
                "`/help [category]` - Show this message\n"
            ),
            inline=False,
        )

        if OWNER_ID:
            embed.add_field(
                name="👑 Owner Commands",
                value=(
                    "`/cache-stats` - View cache statistics\n"
                    "`/cache-clear` - Clear API cache\n"
                    "`/uptime` - Check bot uptime\n"
                    "`/debug-message` - Debug shiny detection\n"
                    "`/shiny-channel` - Manage monitoring\n"
                    "`/shiny-archive` - Manage archive\n"
                ),
                inline=False,
            )

        embed.set_footer(
            text="💡 Use /help <category> to filter commands • Data from Smogon University"
        )

        return embed

    def _create_pokemon_help_embed(self) -> discord.Embed:
        """Create help embed for Pokemon commands only."""
        embed = discord.Embed(
            title="📖 Pokemon Commands",
            description="Commands for fetching Pokemon competitive data",
            color=BOT_COLOR,
        )

        embed.add_field(
            name="/smogon <pokemon> [generation] [tier]",
            value=(
                "Get competitive movesets from Smogon University\n"
                "**Examples:**\n"
                "• `/smogon garchomp` - Latest Garchomp sets\n"
                "• `/smogon landorus-therian gen9 ou` - Specific gen/tier\n"
            ),
            inline=False,
        )

        embed.add_field(
            name="/effortvalue <pokemon>",
            value=(
                "Get EV yield when defeating a Pokemon\n"
                "**Aliases:** `/ev`, `/evyield`, `/yield`\n"
                "**Example:** `/ev garchomp`\n"
            ),
            inline=False,
        )

        embed.add_field(
            name="/sprite <pokemon> [shiny] [generation]",
            value=(
                "Get a Pokemon sprite image\n"
                "**Aliases:** `/img`, `/image`, `/pic`\n"
                "**Examples:**\n"
                "• `/sprite garchomp` - Default sprite\n"
                "• `/sprite garchomp shiny:yes` - Shiny sprite\n"
                "• `/sprite garchomp generation:8` - Gen 8 sprite\n"
            ),
            inline=False,
        )

        embed.add_field(
            name="/dmgcalc",
            value=(
                "Get link to Pokemon Showdown damage calculator\n"
                "**Aliases:** `/calc`, `/damagecalc`, `/calculator`\n"
            ),
            inline=False,
        )

        embed.set_footer(text="Use /help all to see all commands")

        return embed

    def _create_blackjack_help_embed(self) -> discord.Embed:
        """Create help embed for Blackjack commands only."""
        embed = discord.Embed(
            title="🎴 Blackjack Commands",
            description="Commands for playing Blackjack with friends",
            color=BOT_COLOR,
        )

        embed.add_field(
            name="Quick Start (1v1)",
            value=(
                "**Prefix:** `.bj @player`\n"
                "**Slash:** `/blackjack quick-start @player`\n\n"
                "Start an instant 1v1 game with another player.\n"
                "You become the dealer, they become the player.\n"
            ),
            inline=False,
        )

        embed.add_field(
            name="/blackjack start [max_players] [timeout]",
            value=(
                "Start a multiplayer blackjack game with lobby\n"
                "**Parameters:**\n"
                "• `max_players` - Max players (1-3, default: 3)\n"
                "• `timeout` - Turn timeout (30-120s, default: 60s)\n"
            ),
            inline=False,
        )

        embed.add_field(
            name="In-Game Commands",
            value=(
                "`/blackjack showhand` - View your full hand (dealer only)\n"
                "`/blackjack leave` - Leave the lobby before game starts\n"
                "`/blackjack end` - Force end game (owner only)\n"
            ),
            inline=False,
        )

        embed.add_field(
            name="Game Rules",
            value=(
                "• Dealer must stand on 17 or higher\n"
                "• Dealer must hit on 16 or lower\n"
                "• Players can hit, stand, double down, or split\n"
                "• Split aces receive one card each and auto-stand\n"
                "• Turn timeout: player auto-stands if time expires\n"
            ),
            inline=False,
        )

        embed.add_field(
            name="🎨 Visual Styles",
            value=(
                "**New:** The Dealer can toggle between **Custom Emojis** and **Classic Text** styles in the lobby.\n"
                "Default is Custom Emojis."
            ),
            inline=False,
        )

        embed.set_footer(text="Use /help all to see all commands")

        return embed

    def _create_system_help_embed(self) -> discord.Embed:
        """Create help embed for System commands only."""
        embed = discord.Embed(
            title="🔧 System Commands",
            description="Commands for bot information and diagnostics",
            color=BOT_COLOR,
        )

        embed.add_field(
            name="/ping",
            value=(
                "Check bot's latency and response time\n"
                "Shows WebSocket latency and API response time\n"
            ),
            inline=False,
        )

        embed.add_field(
            name="/status",
            value=(
                "Check bot's health and system status\n"
                "Shows latency, server count, uptime, and cache stats\n"
            ),
            inline=False,
        )

        embed.add_field(
            name="/help [category]",
            value=(
                "Show bot commands and usage\n"
                "**Categories:** `all`, `pokemon`, `blackjack`, `system`, `owner`\n"
            ),
            inline=False,
        )

        embed.set_footer(text="Use /help all to see all commands")

        return embed

    def _create_owner_help_embed(self) -> discord.Embed:
        """Create help embed for Owner commands only."""
        embed = discord.Embed(
            title="👑 Owner Commands",
            description="Admin commands for bot management (Owner only)",
            color=BOT_COLOR,
        )

        embed.add_field(
            name="Cache Management",
            value=(
                "`/cache-stats` - View API cache statistics\n"
                "`/cache-clear` - Clear the API cache\n"
            ),
            inline=False,
        )

        embed.add_field(
            name="Bot Management",
            value=(
                "`/uptime` - Check how long the bot has been online\n"
                "`/blackjack end` - Force end a blackjack game\n"
                "`/blackjack debug` - View full game state\n"
            ),
            inline=False,
        )

        if TARGET_USER_ID:
            embed.add_field(
                name="Shiny Monitoring",
                value=(
                    "`/shiny-channel` - Manage shiny monitoring channels (Admin)\n"
                    "`/shiny-archive` - Manage shiny archive channel (Admin)\n"
                    "`/debug-shiny` - Debug shiny detection\n"
                ),
                inline=False,
            )

        embed.set_footer(text="Owner commands require OWNER_ID to be configured")

        return embed

    @commands.hybrid_command(
        name="ping", description="Check bot latency and response time"
    )
    @commands.max_concurrency(10, commands.BucketType.default, wait=False)
    async def ping(self, ctx: commands.Context) -> None:
        """
        Check the bot's latency.

        Displays two metrics:
        1. WebSocket Latency: Time for the gateway to acknowledge a heartbeat.
        2. API Response Time: Round-trip time to send and edit a message.
        """
        ws_latency = round(self.bot.latency * 1000, 2)

        if ctx.interaction:
            # Slash command - ephemeral
            start_time = time.perf_counter()
            await ctx.defer(ephemeral=True)
            api_latency = round((time.perf_counter() - start_time) * 1000, 2)

            embed = discord.Embed(color=0x2B2D31)
            embed.add_field(
                name="WebSocket Latency", value=f"```{ws_latency} ms```", inline=True
            )
            embed.add_field(
                name="API Response Time", value=f"```{api_latency} ms```", inline=True
            )

            await ctx.send(embed=embed)
        else:
            # Prefix command - normal message
            start_time = time.perf_counter()

            embed = discord.Embed(color=0x2B2D31)
            embed.add_field(
                name="WebSocket Latency", value=f"```{ws_latency} ms```", inline=True
            )
            embed.add_field(name="API Response Time", value="```...```", inline=True)

            msg = await ctx.send(embed=embed)
            api_latency = round((time.perf_counter() - start_time) * 1000, 2)

            # Update with actual API latency
            embed.set_field_at(
                1,
                name="API Response Time",
                value=f"```{api_latency} ms```",
                inline=True,
            )
            await msg.edit(embed=embed)

    @commands.hybrid_command(name="uptime", description="Check bot uptime (Owner only)")
    @commands.max_concurrency(5, commands.BucketType.default, wait=False)
    async def uptime(self, ctx: commands.Context) -> None:
        """
        Check how long the bot has been online.

        Restricted to the bot owner.
        """

        # Check if slash command or prefix command for permissions
        if ctx.interaction:
            user_id = ctx.interaction.user.id
        else:
            user_id = ctx.author.id

        if not OWNER_ID or user_id != OWNER_ID:
            embed = create_error_embed(
                "Access Denied", "This command is only available to the bot owner."
            )
            await ctx.send(embed=embed, ephemeral=True)
            return

        if hasattr(self.bot, "start_time") and self.bot.start_time:  # type: ignore
            uptime_seconds = int(time.time() - self.bot.start_time)  # type: ignore

            days, remainder = divmod(uptime_seconds, 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes, seconds = divmod(remainder, 60)

            uptime_parts = []
            if days > 0:
                uptime_parts.append(f"{days}d")
            if hours > 0:
                uptime_parts.append(f"{hours}h")
            if minutes > 0:
                uptime_parts.append(f"{minutes}m")
            uptime_parts.append(f"{seconds}s")

            uptime_str = " ".join(uptime_parts)

            embed = discord.Embed(
                title="⏰ Bot Uptime",
                description=f"```{uptime_str}```",
                color=0x00FF00,
            )

            embed.set_footer(text="Time since last restart")

            # Handle both slash and prefix
            if ctx.interaction:
                await ctx.send(embed=embed, ephemeral=True)
            else:
                await ctx.send(embed=embed)
        else:
            embed = create_error_embed(
                "Data Unavailable", "Uptime tracking not available."
            )
            await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(
        name="status", description="Check bot health and system status"
    )
    @commands.max_concurrency(10, commands.BucketType.default, wait=False)
    async def status(self, ctx: commands.Context) -> None:
        """
        Check the bot's current health and system status.

        Displays:
        - Health Status (Healthy, Warning, Critical based on latency).
        - Server/User counts.
        - Uptime.
        - Cache Hit Rate (if available).
        - Shiny Monitoring stats (if enabled).
        """

        # Get latency
        ws_latency_ms = round(self.bot.latency * 1000, 2)

        # Determine health status based on latency
        if ws_latency_ms < HEALTHY_LATENCY_MS:
            status_emoji = "🟢"
            status_text = "Healthy"
            color = 0x00FF00
        elif ws_latency_ms < WARNING_LATENCY_MS:
            status_emoji = "🟡"
            status_text = "Warning"
            color = 0xFFFF00
        else:
            status_emoji = "🔴"
            status_text = "Critical"
            color = 0xFF0000

        embed = discord.Embed(
            title=f"{status_emoji} Bot Status",
            description=f"**System Health:** {status_text}",
            color=color,
        )

        # Latency
        embed.add_field(
            name="⚡ Latency",
            value=f"```{ws_latency_ms} ms```",
            inline=True,
        )

        # Guild/User count
        guild_count = len(self.bot.guilds)
        user_count = sum(g.member_count for g in self.bot.guilds if g.member_count)
        embed.add_field(
            name="🌐 Reach",
            value=f"```{guild_count} servers\n{user_count:,} users```",
            inline=True,
        )

        # Uptime
        if hasattr(self.bot, "start_time") and self.bot.start_time:  # type: ignore
            uptime_seconds = int(time.time() - self.bot.start_time)  # type: ignore
            days, remainder = divmod(uptime_seconds, 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes, _ = divmod(remainder, 60)

            uptime_str = f"{days}d {hours}h {minutes}m"
            embed.add_field(
                name="⏰ Uptime",
                value=f"```{uptime_str}```",
                inline=True,
            )

        # Cache stats (if available)
        smogon_cog = self.bot.get_cog("Smogon")
        if smogon_cog and hasattr(smogon_cog, "api_client"):
            try:
                stats = smogon_cog.api_client.get_cache_stats()  # type: ignore
                db = await get_database()
                db_stats = await db.get_cache_stats()

                embed.add_field(
                    name="💾 Cache",
                    value=f"```{db_stats['size']}/{stats['max_size']} entries\nHit rate: {stats['hit_rate']}```",
                    inline=True,
                )
            except Exception as e:
                logger.error(f"Error getting cache stats for status: {e}")

        # Shiny monitoring (if enabled)
        if TARGET_USER_ID and hasattr(self.bot, "shiny_configs"):
            total_monitored = sum(
                len(config.channels)
                for config in self.bot.shiny_configs.values()  # type: ignore
            )
            embed.add_field(
                name="🌟 Shiny Watch",
                value=f"```{total_monitored} channels\n{len(self.bot.shiny_configs)} servers```",  # type: ignore
                inline=True,
            )

        embed.set_footer(
            text="All systems operational"
            if status_text == "Healthy"
            else "Performance degraded"
        )

        await ctx.send(embed=embed, ephemeral=True if ctx.interaction else False)

    @commands.command(name="debug-message", aliases=["debug", "debugmsg"])
    async def debug_message_prefix(self, ctx: commands.Context) -> None:
        """
        Debug the last message from the target user (prefix version).

        Checks if the shiny detection regex matches the last message content/embeds.
        Restricted to the bot owner.
        """
        await self._debug_message_impl(ctx, ctx.channel)  # type: ignore

    @commands.hybrid_command(
        name="debug-shiny", description="Debug shiny detection (Owner only)"
    )
    @commands.max_concurrency(3, commands.BucketType.default, wait=False)
    async def debug_shiny(self, ctx: commands.Context) -> None:
        """
        Debug the last message from the target user in this channel.

        Restricted to the bot owner.
        """
        await self._debug_message_impl(ctx, ctx.channel)  # type: ignore

    async def _debug_message_impl(
        self, ctx: commands.Context, channel: discord.TextChannel
    ) -> None:
        """
        Implementation for debug message command.

        Scans recent history for messages from the configured `TARGET_USER_ID`
        and analyzes them against the shiny regex pattern.
        """

        # Check permissions
        if ctx.interaction:
            user_id = ctx.interaction.user.id
        else:
            user_id = ctx.author.id

        if not OWNER_ID or user_id != OWNER_ID:
            embed = create_error_embed("Access Denied", "Owner only!")
            await ctx.send(embed=embed, ephemeral=True)
            return

        if not TARGET_USER_ID:
            embed = create_error_embed(
                "Configuration Error",
                "TARGET_USER_ID not configured! Cannot debug shiny detection.",
            )
            await ctx.send(embed=embed, ephemeral=True)
            return

        # Defer if slash command
        if ctx.interaction:
            await ctx.defer(ephemeral=True)

        # Search for messages from target user
        messages = []
        async for msg in channel.history(limit=MAX_MESSAGE_HISTORY_FOR_DEBUG):
            if msg.author.id == TARGET_USER_ID:
                messages.append(msg)

        if not messages:
            embed = create_error_embed(
                "No Messages Found",
                "No messages from target user found in recent history!",
            )
            await ctx.send(embed=embed, ephemeral=True)
            return

        last_msg = messages[0]

        # Import pattern from bot
        from bot import SHINY_PATTERN

        debug_info = [
            "**Last Message from Target User**",
            f"Author: {last_msg.author.name} (ID: {last_msg.author.id})",
            f"Message ID: {last_msg.id}",
            f"Channel: #{last_msg.channel.name}",
            "",
            f"**Embeds:** {len(last_msg.embeds)}",
        ]

        if last_msg.embeds:
            for idx, embed in enumerate(last_msg.embeds):
                debug_info.append("")
                debug_info.append(f"**╔══ Embed {idx + 1} ══╗**")

                if embed.title:
                    debug_info.append(f"**Title:** `{embed.title}`")

                if embed.author:
                    debug_info.append(f"**Author Name:** `{embed.author.name}`")
                    debug_info.append(
                        f"**Author Icon:** {embed.author.icon_url or 'None'}"
                    )

                if embed.description:
                    desc_preview = embed.description[:200]
                    debug_info.append(f"**Description:**\n```{desc_preview}```")

                if embed.footer:
                    debug_info.append(f"**Footer Text:** `{embed.footer.text}`")

                if embed.image:
                    debug_info.append(f"**Image URL:** {embed.image.url[:50]}...")

                debug_info.append("")
                debug_info.append("**🔍 PATTERN TESTS:**")

                # Test description (PRIMARY CHECK)
                if embed.description:
                    match = SHINY_PATTERN.search(embed.description)
                    debug_info.append(f"**Description match: `{match is not None}`**")
                    if match:
                        debug_info.append(f"**✅ SHINY FOUND: `{match.group()}`**")
                    else:
                        debug_info.append("❌ No shiny pattern in description")

                # Test title
                if embed.title:
                    match = SHINY_PATTERN.search(embed.title)
                    debug_info.append(f"Title match: `{match is not None}`")

                # Test author name
                if embed.author and embed.author.name:
                    match = SHINY_PATTERN.search(embed.author.name)
                    debug_info.append(f"Author.name match: `{match is not None}`")
        else:
            debug_info.append("No embeds!")

        full_text = "\n".join(debug_info)

        # Split into chunks if too long
        if len(full_text) > 2000:
            chunks = [full_text[i : i + 2000] for i in range(0, len(full_text), 2000)]
            for chunk in chunks:
                if ctx.interaction:
                    await ctx.send(chunk, ephemeral=True)
                else:
                    await ctx.send(chunk)
        else:
            if ctx.interaction:
                await ctx.send(full_text, ephemeral=True)
            else:
                await ctx.send(full_text)


async def setup(bot: commands.Bot) -> None:
    """Load the Utility cog."""
    await bot.add_cog(Utility(bot))
    logger.info("Utility cog loaded successfully")
