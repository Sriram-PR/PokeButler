"""
Blackjack game cog for Discord bot.

This module implements the Discord command interface for the Blackjack game.
It handles:
- Slash commands for starting, managing, and playing games.
- Prefix commands for quick-start functionality.
- Game lifecycle management (creation, active tracking, cleanup).
- integration with the game engine and UI views.
"""

import asyncio
import logging
from typing import Dict, Optional

import discord
from discord import app_commands
from discord.ext import commands

from config.settings import (
    BLACKJACK_LOBBY_TIMEOUT,
    BLACKJACK_MAX_PLAYERS,
    BLACKJACK_MIN_PLAYERS,
    BLACKJACK_QUICK_START_PLAYERS,
    BLACKJACK_TURN_TIMEOUT_DEFAULT,
    BLACKJACK_TURN_TIMEOUT_MAX,
    BLACKJACK_TURN_TIMEOUT_MIN,
    OWNER_ID,
)
from utils.blackjack_game import BlackjackGame, GamePhase
from utils.blackjack_helpers import format_hand_with_value
from utils.blackjack_views import (
    BlackjackGameView,
    BlackjackLobbyView,
    create_game_embed,
    create_results_embed,
)
from utils.helpers import create_error_embed, create_info_embed, create_success_embed

logger = logging.getLogger("smogon_bot.blackjack")


class Blackjack(commands.Cog):
    """
    Blackjack game commands and lifecycle management.

    Tracks active games per channel to prevent multiple games running
    simultaneously in the same context.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Track active games per channel to enforce one game per channel rule
        self.active_games: Dict[int, BlackjackGame] = {}

        logger.info("Blackjack cog initialized (Text Mode)")

    def cog_unload(self):
        """Cleanup when cog is unloaded."""
        logger.info("Blackjack cog unloaded")

    def _get_game(self, channel_id: int) -> Optional[BlackjackGame]:
        """Retrieve the active game in a specific channel."""
        return self.active_games.get(channel_id)

    def _remove_game(self, channel_id: int):
        """Remove a game from the active games registry."""
        if channel_id in self.active_games:
            del self.active_games[channel_id]
            logger.info(f"Removed game from channel {channel_id}")

    @app_commands.command(name="blackjack", description="Play Blackjack with friends")
    @app_commands.describe(
        action="Action to perform",
        max_players=f"Maximum number of players ({BLACKJACK_MIN_PLAYERS}-{BLACKJACK_MAX_PLAYERS})",
        timeout=f"Turn timeout in seconds ({BLACKJACK_TURN_TIMEOUT_MIN}-{BLACKJACK_TURN_TIMEOUT_MAX})",
        player="Player to challenge (for quick-start only)",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="start", value="start"),
            app_commands.Choice(name="quick-start", value="quick-start"),
            app_commands.Choice(name="leave", value="leave"),
            app_commands.Choice(name="showhand", value="showhand"),
            app_commands.Choice(name="end", value="end"),
            app_commands.Choice(name="debug", value="debug"),
        ]
    )
    async def blackjack(
        self,
        interaction: discord.Interaction,
        action: app_commands.Choice[str],
        max_players: Optional[int] = BLACKJACK_MAX_PLAYERS,
        timeout: Optional[int] = BLACKJACK_TURN_TIMEOUT_DEFAULT,
        player: Optional[discord.Member] = None,
    ):
        """
        Main blackjack command routing.

        Args:
            interaction: The Discord interaction.
            action: The specific sub-command/action to execute.
            max_players: Optional limit for lobby size (default 3).
            timeout: Optional turn duration limit (default 60s).
            player: Optional target user for quick-start mode.
        """

        if action.value == "start":
            await self._start_game(interaction, max_players, timeout)

        elif action.value == "quick-start":
            await self._quick_start_game(interaction, player)

        elif action.value == "leave":
            await self._leave_game(interaction)

        elif action.value == "showhand":
            await self._show_hand(interaction)

        elif action.value == "end":
            await self._end_game(interaction)

        elif action.value == "debug":
            await self._debug_game(interaction)

    async def _start_game(
        self, interaction: discord.Interaction, max_players: int, timeout: int
    ):
        """
        Start a new multiplayer blackjack game with a lobby.

        Validates configuration, creates the game instance, and sends the lobby interface.
        """

        # Validate parameters
        if max_players < BLACKJACK_MIN_PLAYERS or max_players > BLACKJACK_MAX_PLAYERS:
            embed = create_error_embed(
                "Invalid Configuration",
                f"Max players must be between {BLACKJACK_MIN_PLAYERS} and {BLACKJACK_MAX_PLAYERS}!",
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if timeout < BLACKJACK_TURN_TIMEOUT_MIN or timeout > BLACKJACK_TURN_TIMEOUT_MAX:
            embed = create_error_embed(
                "Invalid Timeout",
                f"Timeout must be between {BLACKJACK_TURN_TIMEOUT_MIN} and {BLACKJACK_TURN_TIMEOUT_MAX} seconds!",
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Check if game already exists in channel
        channel_id = interaction.channel_id
        existing_game = self._get_game(channel_id)

        if existing_game and existing_game.phase != GamePhase.ENDED:
            embed = create_error_embed(
                "Game Active", "A game is already in progress in this channel!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Create new game
        game = BlackjackGame(
            channel_id=channel_id,
            dealer_id=interaction.user.id,
            dealer_name=interaction.user.display_name,
            max_players=max_players,
            timeout=timeout,
        )

        self.active_games[channel_id] = game

        logger.info(
            "Blackjack game started",
            extra={
                "channel_id": channel_id,
                "dealer_id": interaction.user.id,
                "dealer_name": interaction.user.display_name,
                "max_players": max_players,
                "timeout": timeout,
            },
        )

        # Cleanup function closure to be passed to views
        def cleanup_game():
            if channel_id in self.active_games:
                del self.active_games[channel_id]
                logger.info(f"Game cleaned up for channel {channel_id}")

        # Create lobby view with cleanup callback
        lobby_view = BlackjackLobbyView(
            game, timeout=BLACKJACK_LOBBY_TIMEOUT, cleanup_callback=cleanup_game
        )
        lobby_embed = lobby_view.create_lobby_embed()

        await interaction.response.send_message(embed=lobby_embed, view=lobby_view)

        # Store message reference for the view to handle updates
        message = await interaction.original_response()
        lobby_view.message = message

    async def _quick_start_game(
        self, interaction: discord.Interaction, player: Optional[discord.Member]
    ):
        """
        Start an immediate 1v1 blackjack game (Slash Command).

        Skips the lobby phase and deals cards immediately to the command user (Dealer)
        and the mentioned user (Player).
        """
        # Check if player was mentioned
        if player is None:
            embed = create_error_embed(
                "Missing Player",
                "You must mention a player!\n"
                "Usage: `/blackjack quick-start @player`\n\n"
                "💡 Tip: You can also use `.bj @player` for quick access.",
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Validate player
        if player.bot:
            embed = create_error_embed("Invalid Opponent", "Cannot play with bots!")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if player.id == interaction.user.id:
            embed = create_error_embed(
                "Invalid Opponent", "You cannot play against yourself!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Check if game already exists in channel
        channel_id = interaction.channel_id
        existing_game = self._get_game(channel_id)

        if existing_game and existing_game.phase != GamePhase.ENDED:
            embed = create_error_embed(
                "Game Active", "A game is already in progress in this channel!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Create new game
        game = BlackjackGame(
            channel_id=channel_id,
            dealer_id=interaction.user.id,
            dealer_name=interaction.user.display_name,
            max_players=BLACKJACK_QUICK_START_PLAYERS,
            timeout=BLACKJACK_TURN_TIMEOUT_DEFAULT,
        )

        # Add player
        if not game.add_player(player.id, player.display_name):
            embed = create_error_embed(
                "Setup Failed", f"Failed to add {player.mention} to the game!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        self.active_games[channel_id] = game

        logger.info(
            f"Quick-start blackjack: {interaction.user.display_name} (dealer) vs "
            f"{player.display_name} (player) in channel {channel_id}"
        )

        # Send confirmation
        await interaction.response.send_message(
            f"🎴 **Blackjack Game Starting!**\n"
            f"🎲 Dealer: {interaction.user.mention}\n"
            f"👤 Player: {player.mention}\n\n"
            f"Dealing cards..."
        )

        setup_msg = await interaction.original_response()

        # Start game immediately
        game.start_game()

        # Send dealer their hole card privately
        dealer_embed = discord.Embed(
            title="🔒 Your Hand (Private)",
            description=format_hand_with_value(game.dealer.hands[0].cards),
            color=discord.Color.gold(),
        )

        dealer_embed.add_field(
            name="Visible to Players",
            value=format_hand_with_value(game.dealer.hands[0].cards, hide_second=True),
            inline=False,
        )

        dealer_embed.set_footer(
            text="Use /blackjack showhand to view this again • Your hole card is hidden from other players"
        )

        try:
            await interaction.user.send(embed=dealer_embed)
        except discord.Forbidden:
            logger.warning(f"Could not DM dealer {interaction.user.display_name}")
            await interaction.followup.send(
                f"⚠️ {interaction.user.mention} I couldn't DM you! Please enable DMs from server members.",
                ephemeral=True,
            )

        # Cleanup function closure
        def cleanup_game():
            if channel_id in self.active_games:
                del self.active_games[channel_id]
                logger.info(f"Game cleaned up for channel {channel_id}")

        # Check if game ended immediately (dealer blackjack or auto-stand)
        if game.phase == GamePhase.RESULTS:
            results_embed = create_results_embed(game)
            await setup_msg.edit(content=None, embed=results_embed)
            cleanup_game()
            return

        # Create game view with buttons and cleanup callback
        game_view = BlackjackGameView(
            game, timeout=game.timeout, cleanup_callback=cleanup_game
        )

        # Initial game display
        game_embed = create_game_embed(game)
        await setup_msg.edit(content=None, embed=game_embed, view=game_view)

        game_view.message = setup_msg

        # Check again if game ended (dealer auto-stand during init)
        if game.phase == GamePhase.RESULTS:
            results_embed = create_results_embed(game)
            await setup_msg.edit(embed=results_embed, view=None, attachments=[])
            cleanup_game()
            game_view.stop()
            return

        # Start turn timer
        asyncio.create_task(game_view.start_turn_timer())

    async def _leave_game(self, interaction: discord.Interaction):
        """Allow a player to leave the game lobby before it starts."""

        channel_id = interaction.channel_id
        game = self._get_game(channel_id)

        if not game:
            embed = create_error_embed(
                "No Game", "No game in progress in this channel!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if game.phase != GamePhase.LOBBY:
            embed = create_error_embed(
                "Game Started", "Cannot leave - game already started!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Check if user is in game
        user_id = interaction.user.id

        if user_id == game.dealer_id:
            embed = create_error_embed(
                "Dealer Restrictions",
                "Dealer cannot leave - use `/blackjack end` to cancel the game!",
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if game.remove_player(user_id):
            embed = create_success_embed("Left Game", "You left the game lobby!")
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            embed = create_error_embed("Action Failed", "You're not in this game!")
            await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _show_hand(self, interaction: discord.Interaction):
        """
        Show the Dealer their full hand (including hole card) privately.
        Restricted to the Dealer of the current game.
        """

        channel_id = interaction.channel_id
        game = self._get_game(channel_id)

        if not game:
            embed = create_error_embed(
                "No Game", "No game in progress in this channel!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if interaction.user.id != game.dealer_id:
            embed = create_error_embed(
                "Permission Denied", "Only the dealer can use this command!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if game.phase == GamePhase.LOBBY:
            embed = create_error_embed("Game Not Started", "Game hasn't started yet!")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Show dealer's full hand
        dealer_hand = game.dealer.hands[0].cards

        # Respect the game's visual style setting
        use_emojis = game.use_emojis

        embed = discord.Embed(
            title="🔒 Your Hand (Private)",
            description=format_hand_with_value(dealer_hand, use_emojis=use_emojis),
            color=discord.Color.gold(),
        )

        # Show what players see
        visible_text = format_hand_with_value(
            dealer_hand,
            hide_second=not game.should_reveal_hole_card(),
            use_emojis=use_emojis,
        )

        embed.add_field(name="Visible to Players", value=visible_text, inline=False)

        embed.set_footer(text="This information is private to you")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _end_game(self, interaction: discord.Interaction):
        """
        Force end the current game.

        Authorized for:
        1. The Bot Owner
        2. Server Administrators
        3. The Game Host (Dealer)
        """
        channel_id = interaction.channel_id
        game = self._get_game(channel_id)

        # Check if game exists first
        if not game:
            embed = create_error_embed(
                "No Game", "No game in progress in this channel!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Check permissions
        # 1. Bot Owner
        is_owner = OWNER_ID and interaction.user.id == OWNER_ID
        # 2. Server Admin
        is_admin = (
            interaction.guild and interaction.user.guild_permissions.administrator
        )
        # 3. Game Host (Dealer)
        is_host = interaction.user.id == game.dealer_id

        if not (is_owner or is_admin or is_host):
            embed = create_error_embed(
                "Permission Denied",
                "Only the Game Host, Server Admins, or Bot Owner can force end the game!",
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Remove game
        self._remove_game(channel_id)

        embed = create_info_embed(
            "Game Ended", f"Game forcefully ended by {interaction.user.mention}."
        )
        # Override color to red for forced end
        embed.color = discord.Color.red()

        await interaction.response.send_message(embed=embed)

        logger.info(
            f"Game forcefully ended in channel {channel_id} by {interaction.user.id}"
        )

    async def _debug_game(self, interaction: discord.Interaction):
        """
        Dump full game state for debugging.
        Owner-only command.
        """

        if not OWNER_ID or interaction.user.id != OWNER_ID:
            embed = create_error_embed(
                "Access Denied", "Only the bot owner can use this command!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        channel_id = interaction.channel_id
        game = self._get_game(channel_id)

        if not game:
            embed = create_error_embed(
                "No Game", "No game in progress in this channel!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Create debug embed with full game state
        embed = discord.Embed(title="🔍 Game Debug Info", color=discord.Color.blue())

        embed.add_field(name="Phase", value=game.phase.value, inline=True)

        embed.add_field(
            name="Current Turn",
            value=game.get_current_player().username
            if game.get_current_player()
            else "None",
            inline=True,
        )

        embed.add_field(
            name="Deck Remaining", value=f"{len(game.deck)} cards", inline=True
        )

        # Use game state for consistency
        use_emojis = game.use_emojis

        # Dealer's hand (full)
        dealer_hand = game.dealer.hands[0].cards
        embed.add_field(
            name=f"🎲 Dealer ({game.dealer.username})",
            value=format_hand_with_value(dealer_hand, use_emojis=use_emojis),
            inline=False,
        )

        # Players' hands (full)
        for player in game.players:
            player_text = []
            for hand_idx, hand in enumerate(player.hands):
                hand_prefix = f"Hand {hand_idx + 1}: " if len(player.hands) > 1 else ""
                hand_text = format_hand_with_value(hand.cards, use_emojis=use_emojis)
                player_text.append(f"{hand_prefix}{hand_text} [{hand.status.value}]")

            embed.add_field(
                name=f"👤 {player.username}", value="\n".join(player_text), inline=False
            )

        embed.set_footer(text="All cards visible for debugging")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @commands.command(name="bj", aliases=["blackjack"])
    @commands.max_concurrency(3, commands.BucketType.default, wait=False)
    async def bj_prefix(
        self, ctx: commands.Context, player: Optional[discord.Member] = None
    ):
        """
        Quick-start 1v1 blackjack game (Prefix Command).

        Usage: .bj @user
        - Command author becomes dealer.
        - Mentioned user becomes player.
        - Game starts immediately without lobby.
        """
        # Check if player was mentioned
        if player is None:
            embed = create_error_embed(
                "Invalid Usage",
                "**Usage:** `.bj @user`\n"
                "Example: `.bj @Friend` to start a blackjack game with them!\n\n"
                "💡 **Slash Command Available:** Try `/blackjack quick-start @player` for the same feature!",
            )
            await ctx.send(embed=embed)
            return

        # Check if in guild
        if not ctx.guild:
            embed = create_error_embed(
                "Error", "This command can only be used in a server."
            )
            await ctx.send(embed=embed)
            return

        # Validate player
        if player.bot:
            embed = create_error_embed("Invalid Opponent", "Cannot play with bots!")
            await ctx.send(embed=embed)
            return

        if player.id == ctx.author.id:
            embed = create_error_embed(
                "Invalid Opponent", "You cannot play against yourself!"
            )
            await ctx.send(embed=embed)
            return

        # Check if game already exists in channel
        channel_id = ctx.channel.id
        existing_game = self._get_game(channel_id)

        if existing_game and existing_game.phase != GamePhase.ENDED:
            embed = create_error_embed(
                "Game Active", "A game is already in progress in this channel!"
            )
            await ctx.send(embed=embed)
            return

        # Create new game
        game = BlackjackGame(
            channel_id=channel_id,
            dealer_id=ctx.author.id,
            dealer_name=ctx.author.display_name,
            max_players=BLACKJACK_QUICK_START_PLAYERS,
            timeout=BLACKJACK_TURN_TIMEOUT_DEFAULT,
        )

        # Add player
        if not game.add_player(player.id, player.display_name):
            embed = create_error_embed(
                "Setup Failed", f"Failed to add {player.mention} to the game!"
            )
            await ctx.send(embed=embed)
            return

        self.active_games[channel_id] = game

        logger.info(
            f"Quick-start blackjack: {ctx.author.display_name} (dealer) vs "
            f"{player.display_name} (player) in channel {channel_id}"
        )

        # Send confirmation
        setup_msg = await ctx.send(
            f"🎴 **Blackjack Game Starting!**\n"
            f"🎲 Dealer: {ctx.author.mention}\n"
            f"👤 Player: {player.mention}\n\n"
            f"Dealing cards..."
        )

        # Start game
        game.start_game()

        # Send dealer their hole card privately
        dealer_embed = discord.Embed(
            title="🔒 Your Hand (Private)",
            description=format_hand_with_value(
                game.dealer.hands[0].cards, use_emojis=True
            ),
            color=discord.Color.gold(),
        )

        dealer_embed.add_field(
            name="Visible to Players",
            value=format_hand_with_value(
                game.dealer.hands[0].cards, hide_second=True, use_emojis=True
            ),
            inline=False,
        )

        dealer_embed.set_footer(
            text="Use /blackjack showhand to view this again • Your hole card is hidden from other players"
        )

        try:
            await ctx.author.send(embed=dealer_embed)
        except discord.Forbidden:
            logger.warning(f"Could not DM dealer {ctx.author.display_name}")
            await ctx.send(
                f"⚠️ {ctx.author.mention} I couldn't DM you! Please enable DMs from server members.",
                delete_after=10,
            )

        # Cleanup function closure
        def cleanup_game():
            if channel_id in self.active_games:
                del self.active_games[channel_id]
                logger.info(f"Game cleaned up for channel {channel_id}")

        # Check if game ended immediately (dealer blackjack or auto-stand)
        if game.phase == GamePhase.RESULTS:
            results_embed = create_results_embed(game)
            await setup_msg.edit(content=None, embed=results_embed)
            cleanup_game()
            return

        # Create game view with buttons and cleanup callback
        game_view = BlackjackGameView(
            game, timeout=game.timeout, cleanup_callback=cleanup_game
        )

        # Text mode display
        game_embed = create_game_embed(game)
        await setup_msg.edit(content=None, embed=game_embed, view=game_view)

        game_view.message = setup_msg

        # Check again if game ended (dealer auto-stand)
        if game.phase == GamePhase.RESULTS:
            results_embed = create_results_embed(game)
            await setup_msg.edit(embed=results_embed, view=None, attachments=[])
            cleanup_game()
            game_view.stop()
            return

        # Start turn timer
        asyncio.create_task(game_view.start_turn_timer())

    @bj_prefix.error
    async def bj_prefix_error(
        self, ctx: commands.Context, error: commands.CommandError
    ):
        """
        Error handler for the prefix-based blackjack command.

        Handles missing arguments (player mention) and invalid members.
        """
        if isinstance(error, commands.MemberNotFound):
            embed = create_error_embed(
                "User Not Found",
                "Make sure you mention a valid server member.\nExample: `.bj @Friend`",
            )
            await ctx.send(embed=embed)
        elif isinstance(error, commands.MissingRequiredArgument):
            embed = create_error_embed(
                "Invalid Usage",
                "**Usage:** `.bj @user`\n"
                "Example: `.bj @Friend` to start a blackjack game!\n\n"
                "💡 **Slash Command Available:** Try `/blackjack quick-start @player`",
            )
            await ctx.send(embed=embed)
        else:
            # Let global error handler handle it
            raise error


async def setup(bot: commands.Bot):
    """
    Load the Blackjack cog into the bot.

    Args:
        bot: The Discord bot instance.
    """
    await bot.add_cog(Blackjack(bot))
    logger.info("Cog loaded", extra={"cog": "blackjack", "card_assets_valid": True})
