"""
Discord UI views for the Blackjack game.

This module implements the interactive components (Buttons, Views) for:
- Game Lobby: Joining, setting options, starting the game.
- Active Game: Hit, Stand, Double, Split, Surrender actions.
- Real-time updates: Turn timers and visual countdowns.

It handles the presentation layer, forwarding user actions to the
BlackjackGame model logic (MVC pattern).
"""

import asyncio
import logging
import time
from typing import Callable, Optional

import discord

from config.settings import (
    BLACKJACK_TURN_TIMER_UPDATE_INTERVAL,
    BLACKJACK_TURN_TIMER_WARNING_THRESHOLD,
    BLACKJACK_VALUE,
)
from utils.blackjack_game import BlackjackGame, GamePhase, HandStatus
from utils.blackjack_helpers import (
    calculate_hand_value,
    can_split,
    determine_winner,
    format_hand,
    format_hand_with_value,
    get_result_message,
    is_blackjack,
)
from utils.helpers import create_error_embed, create_success_embed

logger = logging.getLogger("smogon_bot.blackjack")


class BlackjackLobbyView(discord.ui.View):
    """
    View for the pre-game lobby phase.

    Allows players to join, the dealer to toggle visual settings, and the
    dealer to start or cancel the game.
    """

    def __init__(
        self,
        game: BlackjackGame,
        timeout: int,
        cleanup_callback: Callable[[], None] = None,
    ):
        """
        Initialize the lobby view.

        Args:
            game: The BlackjackGame model instance.
            timeout: View timeout in seconds.
            cleanup_callback: Function to remove the game from the global registry
                when the view expires or game starts.
        """
        super().__init__(timeout=timeout)
        self.game = game
        self.cleanup_callback = cleanup_callback
        self.message: Optional[discord.Message] = None
        self._update_style_button_label()

    def _update_style_button_label(self):
        """Update the style toggle button label based on current game state."""
        # Find the style button (custom_id="style_toggle")
        for child in self.children:
            if (
                isinstance(child, discord.ui.Button)
                and child.custom_id == "style_toggle"
            ):
                mode_text = "Emojis" if self.game.use_emojis else "Text"
                child.label = f"Style: {mode_text}"
                child.emoji = "🎨" if self.game.use_emojis else "📝"
                break

    @discord.ui.button(
        label="Join as Player", style=discord.ButtonStyle.green, emoji="👥"
    )
    async def join_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Handle 'Join' button click."""
        # Check if already full
        if self.game.is_lobby_full():
            embed = create_error_embed("Lobby Full", "Game is full!")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Try to add player
        if self.game.add_player(interaction.user.id, interaction.user.display_name):
            embed = create_success_embed(
                "Joined",
                f"You joined the game! ({self.game.get_player_count()}/{self.game.max_players})",
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

            # Update lobby embed live
            if self.message:
                embed = self.create_lobby_embed()
                await self.message.edit(embed=embed, view=self)
        else:
            embed = create_error_embed(
                "Join Failed",
                "Cannot join - you may already be in the game or you're the dealer!",
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(
        label="Style: Emojis",
        style=discord.ButtonStyle.secondary,
        emoji="🎨",
        custom_id="style_toggle",
        row=1,
    )
    async def style_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """
        Toggle card display style (Dealer only).

        Switches between Custom Emojis (visual) and Plain Text (accessibility).
        """
        if interaction.user.id != self.game.dealer_id:
            embed = create_error_embed(
                "Permission Denied", "Only the dealer can change the table style!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Toggle state
        self.game.toggle_style()

        # Update button UI
        self._update_style_button_label()

        # Update embed to show change
        embed = self.create_lobby_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(
        label="Start Game", style=discord.ButtonStyle.primary, emoji="🎮"
    )
    async def start_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """
        Start the game (Dealer only).

        Transitions game state to DEALING/PLAYING and replaces the view.
        """
        if interaction.user.id != self.game.dealer_id:
            embed = create_error_embed(
                "Permission Denied", "Only the dealer can start the game!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if self.game.get_player_count() == 0:
            embed = create_error_embed(
                "Cannot Start", "Need at least 1 player to start!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Start game state machine
        self.game.start_game()

        await interaction.response.defer()

        # Stop lobby view (prevents further interactions)
        self.stop()

        # Send dealer their hole card privately via DM
        dealer_embed = self.create_dealer_private_embed()
        try:
            await interaction.user.send(embed=dealer_embed)
        except discord.Forbidden:
            logger.warning(f"Could not DM dealer {interaction.user.display_name}")

        # Check if game immediately ended (dealer blackjack or dealer auto-stand at 17+)
        if self.game.phase == GamePhase.RESULTS:
            # Game ended immediately
            results_embed = create_results_embed(self.game)
            await self.message.edit(embed=results_embed, view=None)
            if self.cleanup_callback:
                self.cleanup_callback()
            return

        # Create active game view
        game_view = BlackjackGameView(
            self.game, timeout=self.game.timeout, cleanup_callback=self.cleanup_callback
        )

        # Display game board
        game_embed = create_game_embed(self.game)
        await self.message.edit(embed=game_embed, view=game_view)

        game_view.message = self.message

        # Check again if game ended (dealer could have auto-stood during initialization)
        if self.game.phase == GamePhase.RESULTS:
            results_embed = create_results_embed(self.game)
            await self.message.edit(embed=results_embed, view=None, attachments=[])
            if self.cleanup_callback:
                self.cleanup_callback()
            game_view.stop()
            return

        # Start turn timer background task
        asyncio.create_task(game_view.start_turn_timer())

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red, emoji="❌")
    async def cancel_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Cancel the game logic (Dealer only)."""
        if interaction.user.id != self.game.dealer_id:
            embed = create_error_embed(
                "Permission Denied", "Only the dealer can cancel the game!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        self.stop()
        if self.cleanup_callback:
            self.cleanup_callback()

        embed = discord.Embed(
            title="❌ Game Cancelled",
            description=f"Dealer {interaction.user.mention} cancelled the game.",
            color=discord.Color.red(),
        )

        await interaction.response.edit_message(embed=embed, view=None)

    async def on_timeout(self) -> None:
        """
        Handle view timeout to prevent memory leaks.

        Crucially, this method breaks the circular reference between the View
        and the Discord Message object by setting `self.message = None`.
        This allows the Python garbage collector to reclaim resources.
        """
        if self.cleanup_callback:
            self.cleanup_callback()

        if self.message:
            try:
                embed = discord.Embed(
                    title="⏰ Game Cancelled",
                    description="Lobby timed out.",
                    color=discord.Color.red(),
                )
                await self.message.edit(embed=embed, view=None)
            except (discord.NotFound, discord.HTTPException):
                pass
            finally:
                # BREAK CIRCULAR REFERENCE
                self.message = None

        self.stop()

    def create_lobby_embed(self) -> discord.Embed:
        """Generate the lobby status embed."""
        embed = discord.Embed(
            title="🃏 Blackjack Game Lobby", color=discord.Color.blue()
        )

        dealer_user = f"<@{self.game.dealer_id}>"
        embed.add_field(name="🎲 Dealer", value=dealer_user, inline=True)

        players_text = (
            "\n".join(f"• <@{p.user_id}>" for p in self.game.players)
            if self.game.players
            else "*Waiting for players...*"
        )

        embed.add_field(
            name=f"👥 Players ({self.game.get_player_count()}/{self.game.max_players})",
            value=players_text,
            inline=True,
        )

        # Show current style in lobby
        style_text = "Custom Emojis 🎨" if self.game.use_emojis else "Classic Text 📝"
        embed.add_field(name="🖼️ Visuals", value=style_text, inline=True)

        embed.add_field(
            name="⏱️ Turn Timeout", value=f"{self.game.timeout}s", inline=True
        )

        embed.set_footer(
            text="Click 'Join as Player' to join • Dealer clicks 'Start Game' when ready"
        )

        return embed

    def create_dealer_private_embed(self) -> discord.Embed:
        """Generate private embed showing dealer's hole card."""
        dealer_hand = self.game.dealer.hands[0].cards
        use_emojis = self.game.use_emojis

        embed = discord.Embed(
            title="🔒 Your Hand (Private)",
            description=format_hand_with_value(dealer_hand, use_emojis=use_emojis),
            color=discord.Color.gold(),
        )

        embed.add_field(
            name="Visible to Players",
            value=format_hand(dealer_hand, hide_second=True, use_emojis=use_emojis),
            inline=False,
        )

        embed.set_footer(
            text="Use /blackjack showhand to view this again • Your hole card is hidden from other players"
        )

        return embed


class BlackjackGameView(discord.ui.View):
    """
    View for the active gameplay phase.

    Dynamically displays buttons (Hit, Stand, Double, Split) based on the
    current player's valid moves. Handles turn timeouts.
    """

    def __init__(
        self,
        game: BlackjackGame,
        timeout: int,
        cleanup_callback: Callable[[], None] = None,
    ):
        """
        Initialize game view.

        Args:
            game: The BlackjackGame model instance.
            timeout: Turn timeout in seconds.
            cleanup_callback: Function to remove game from registry on end.
        """
        super().__init__(timeout=timeout)
        self.game = game
        self.cleanup_callback = cleanup_callback
        self.message: Optional[discord.Message] = None
        self.turn_timeout = timeout
        self.turn_task: Optional[asyncio.Task] = None
        self._timer_lock = asyncio.Lock()
        # Track turn start time for countdown calculations
        self.turn_start_time: Optional[float] = None
        self.update_buttons()

    def update_buttons(self) -> None:
        """
        Refresh button states based on the current turn.

        Enables/Disables Split, Double Down, and Surrender based on rules.
        """
        self.clear_items()

        current_player = self.game.get_current_player()

        if not current_player or self.game.is_game_over():
            return

        current_hand = current_player.get_current_hand()

        # Hit button
        hit_button = discord.ui.Button(
            label="Hit", style=discord.ButtonStyle.primary, emoji="🎯", custom_id="hit"
        )

        # Disable hit for dealer if ≥17 (Hard) or Hitting Soft 17 Allowed logic
        if current_player.is_dealer and not self.game.can_dealer_hit():
            hit_button.disabled = True

        hit_button.callback = self.hit_callback
        self.add_item(hit_button)

        # Stand button
        stand_button = discord.ui.Button(
            label="Stand",
            style=discord.ButtonStyle.secondary,
            emoji="✋",
            custom_id="stand",
        )

        # Disable stand for dealer if <17
        if current_player.is_dealer and not self.game.can_dealer_stand():
            stand_button.disabled = True

        stand_button.callback = self.stand_callback
        self.add_item(stand_button)

        # Double Down (players only, 2 cards)
        if not current_player.is_dealer and len(current_hand.cards) == 2:
            double_button = discord.ui.Button(
                label="Double Down",
                style=discord.ButtonStyle.success,
                emoji="2️⃣",
                custom_id="double",
            )
            double_button.callback = self.double_callback
            self.add_item(double_button)

        # Split (players only, pairs)
        if not current_player.is_dealer and can_split(current_hand.cards):
            split_button = discord.ui.Button(
                label="Split",
                style=discord.ButtonStyle.success,
                emoji="✂️",
                custom_id="split",
            )
            split_button.callback = self.split_callback
            self.add_item(split_button)

        # Surrender (players only, 2 cards, no split)
        if (
            not current_player.is_dealer
            and len(current_hand.cards) == 2
            and not current_hand.is_split
        ):
            surrender_button = discord.ui.Button(
                label="Surrender",
                style=discord.ButtonStyle.danger,
                emoji="🏳️",
                custom_id="surrender",
            )
            surrender_button.callback = self.surrender_callback
            self.add_item(surrender_button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """
        Verify that the user clicking the button is the current player.
        """
        current_player = self.game.get_current_player()

        if not current_player:
            embed = create_error_embed("Game Error", "No active player!")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return False

        if interaction.user.id != current_player.user_id:
            embed = create_error_embed(
                "Not Your Turn", f"It's {current_player.username}'s turn!"
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return False

        return True

    async def hit_callback(self, interaction: discord.Interaction) -> None:
        """Handle 'Hit' action."""
        card = self.game.hit(interaction.user.id)

        if card:
            await self.update_game_state(interaction)
        else:
            embed = create_error_embed("Invalid Move", "Cannot hit at this time!")
            await interaction.response.send_message(embed=embed, ephemeral=True)

    async def stand_callback(self, interaction: discord.Interaction) -> None:
        """Handle 'Stand' action."""
        if self.game.stand(interaction.user.id):
            await self.update_game_state(interaction)
        else:
            embed = create_error_embed("Invalid Move", "Cannot stand at this time!")
            await interaction.response.send_message(embed=embed, ephemeral=True)

    async def double_callback(self, interaction: discord.Interaction) -> None:
        """Handle 'Double Down' action."""
        card = self.game.double_down(interaction.user.id)

        if card:
            await self.update_game_state(interaction)
        else:
            embed = create_error_embed("Invalid Move", "Cannot double down!")
            await interaction.response.send_message(embed=embed, ephemeral=True)

    async def split_callback(self, interaction: discord.Interaction) -> None:
        """Handle 'Split' action."""
        if self.game.split(interaction.user.id):
            await self.update_game_state(interaction)
        else:
            embed = create_error_embed("Invalid Move", "Cannot split!")
            await interaction.response.send_message(embed=embed, ephemeral=True)

    async def surrender_callback(self, interaction: discord.Interaction) -> None:
        """Handle 'Surrender' action."""
        if self.game.surrender(interaction.user.id):
            await self.update_game_state(interaction)
        else:
            embed = create_error_embed("Invalid Move", "Cannot surrender!")
            await interaction.response.send_message(embed=embed, ephemeral=True)

    async def update_game_state(self, interaction: discord.Interaction) -> None:
        """
        Refreshes the game UI after an action.

        1. Cancels the current turn timer.
        2. Checks if game ended.
        3. Updates buttons for the next state.
        4. Edits the message embed.
        5. Starts a new turn timer.
        """
        await interaction.response.defer()

        # Cancel turn timer with lock to prevent race condition
        async with self._timer_lock:
            if self.turn_task and not self.turn_task.done():
                self.turn_task.cancel()
                try:
                    await self.turn_task
                except asyncio.CancelledError:
                    pass
                self.turn_task = None

        # Check if game over (could happen from auto-stand)
        if self.game.phase == GamePhase.RESULTS:
            results_embed = create_results_embed(self.game)
            await self.message.edit(embed=results_embed, view=None, attachments=[])
            if self.cleanup_callback:
                self.cleanup_callback()
            self.stop()
            return

        # Update buttons for next turn
        self.update_buttons()

        # Check if game moved to results after updating (dealer auto-stand case)
        if self.game.phase == GamePhase.RESULTS:
            results_embed = create_results_embed(self.game)
            await self.message.edit(embed=results_embed, view=None, attachments=[])
            if self.cleanup_callback:
                self.cleanup_callback()
            self.stop()
            return

        # Update game display
        game_embed = create_game_embed(self.game)
        await self.message.edit(embed=game_embed, view=self)

        # Start new turn timer
        asyncio.create_task(self.start_turn_timer())

    async def start_turn_timer(self) -> None:
        """
        Start the turn timeout background task.

        Uses a lock (`_timer_lock`) to ensure only one timer is running at a time,
        preventing race conditions when users spam buttons.
        """
        async with self._timer_lock:
            # Cancel existing timer if running
            if self.turn_task and not self.turn_task.done():
                self.turn_task.cancel()
                try:
                    await self.turn_task
                except asyncio.CancelledError:
                    pass

            # Record turn start time for countdown
            self.turn_start_time = time.time()

            # Create new timer task
            self.turn_task = asyncio.create_task(self._turn_timeout())

    async def _turn_timeout(self) -> None:
        """
        Handle turn timeout logic.

        Checks elapsed time and updates the embed footer with a countdown
        when the timer is close to expiring (warning threshold).
        Forces an 'Auto-Stand' if the time runs out.
        """
        try:
            elapsed = 0
            last_update = 0

            while elapsed < self.turn_timeout:
                await asyncio.sleep(1)
                elapsed += 1
                remaining = self.turn_timeout - elapsed

                # Update embed footer with countdown when ≤ warning threshold
                if remaining <= BLACKJACK_TURN_TIMER_WARNING_THRESHOLD:
                    # Only update every N seconds to avoid rate limits
                    if (
                        elapsed - last_update >= BLACKJACK_TURN_TIMER_UPDATE_INTERVAL
                        or remaining <= 5
                    ):
                        try:
                            await self._update_turn_countdown(remaining)
                            last_update = elapsed
                        except discord.HTTPException as e:
                            logger.warning(f"Failed to update countdown: {e}")

            # Timeout reached - auto-stand
            current_player = self.game.get_current_player()
            if current_player:
                logger.info(
                    "Player turn timed out",
                    extra={
                        "user_id": current_player.user_id,
                        "username": current_player.username,
                        "timeout_seconds": self.turn_timeout,
                        "action": "auto_stand",
                    },
                )
                self.game.stand(current_player.user_id)

                # Update game state
                if self.game.phase == GamePhase.RESULTS:
                    results_embed = create_results_embed(self.game)
                    await self.message.edit(
                        embed=results_embed, view=None, attachments=[]
                    )
                    if self.cleanup_callback:
                        self.cleanup_callback()
                    self.stop()
                else:
                    self.update_buttons()

                    # Check again after updating buttons (dealer could have auto-stood)
                    if self.game.phase == GamePhase.RESULTS:
                        results_embed = create_results_embed(self.game)
                        await self.message.edit(
                            embed=results_embed, view=None, attachments=[]
                        )
                        if self.cleanup_callback:
                            self.cleanup_callback()
                        self.stop()
                        return

                    # Update embed
                    game_embed = create_game_embed(self.game)
                    await self.message.edit(embed=game_embed, view=self)

                    asyncio.create_task(self.start_turn_timer())

        except asyncio.CancelledError:
            # Timer was cancelled (normal operation)
            pass
        except Exception as e:
            logger.error(f"Error in turn timeout: {e}", exc_info=True)

    async def _update_turn_countdown(self, remaining_seconds: int) -> None:
        """
        Update the embed footer with the remaining seconds.

        Called periodically by `_turn_timeout` to provide visual urgency.
        """
        try:
            current_player = self.game.get_current_player()
            if not current_player:
                return

            # Get current embed with updated countdown
            game_embed = create_game_embed(self.game, countdown=remaining_seconds)
            await self.message.edit(embed=game_embed)

        except Exception as e:
            logger.debug(f"Error updating countdown: {e}")

    async def on_timeout(self) -> None:
        """
        Handle view timeout to prevent memory leaks.

        Crucially, this method breaks the circular reference between the View
        and the Discord Message object by setting `self.message = None`.
        """
        if self.cleanup_callback:
            self.cleanup_callback()

        if self.message:
            try:
                await self.message.edit(view=None)
            except (discord.NotFound, discord.HTTPException):
                pass
            finally:
                # BREAK CIRCULAR REFERENCE
                self.message = None

        self.stop()


def create_game_embed(
    game: BlackjackGame, countdown: Optional[int] = None
) -> discord.Embed:
    """
    Create the main gameplay embed showing the table state.

    Args:
        game: The BlackjackGame instance.
        countdown: Optional remaining seconds to display in the footer.

    Returns:
        Discord Embed object.
    """
    embed = discord.Embed(title="🃏 Blackjack Game", color=discord.Color.green())

    # Retrieve preference
    use_emojis = game.use_emojis

    # Dealer's hand
    dealer_hand = game.dealer.hands[0].cards
    reveal_hole = game.should_reveal_hole_card()

    dealer_text = format_hand_with_value(
        dealer_hand, hide_second=not reveal_hole, use_emojis=use_emojis
    )

    embed.add_field(
        name=f"🎲 Dealer ({game.dealer.username})", value=dealer_text, inline=False
    )

    embed.add_field(name="", value="", inline=False)  # Separator

    # Players' hands
    for player in game.players:
        player_text_lines = []

        for hand_idx, hand in enumerate(player.hands):
            hand_prefix = f"Hand {hand_idx + 1}: " if len(player.hands) > 1 else ""
            hand_text = format_hand_with_value(hand.cards, use_emojis=use_emojis)

            # Add status indicators
            if hand.status == HandStatus.BLACKJACK:
                hand_text += " (BLACKJACK! 🎉)"
            elif hand.status == HandStatus.BUST:
                hand_text += " (BUST 💥)"
            elif hand.status == HandStatus.STAND:
                hand_text += " (STAND ✋)"
            elif hand.status == HandStatus.SPLIT_ACES:
                hand_text += " (SPLIT ACES - STAND ✋)"
            elif hand.status == HandStatus.SURRENDER:
                hand_text += " (SURRENDER 🏳️)"

            player_text_lines.append(f"{hand_prefix}{hand_text}")

        player_full_text = "\n".join(player_text_lines)

        # Indicate current turn
        current_player = game.get_current_player()
        if (
            current_player
            and current_player.user_id == player.user_id
            and not player.is_dealer
        ):
            if player.has_multiple_hands():
                player_full_text = f"**YOUR TURN** (Playing Hand {player.current_hand_index + 1})\n{player_full_text}"
            else:
                player_full_text = f"**YOUR TURN**\n{player_full_text}"
        elif player.all_hands_finished():
            player_full_text += "\n*[Waiting...]*"

        embed.add_field(
            name=f"👤 {player.username}", value=player_full_text, inline=False
        )

    # Footer logic
    style_name = "Emojis" if use_emojis else "Text"
    current_player = game.get_current_player()

    if current_player:
        if (
            countdown is not None
            and countdown <= BLACKJACK_TURN_TIMER_WARNING_THRESHOLD
        ):
            footer_text = f"⏰ {countdown}s remaining • Current turn: {current_player.username} • Style: {style_name}"
        else:
            footer_text = f"Current turn: {current_player.username} • {game.timeout}s timeout • Style: {style_name}"
    else:
        footer_text = f"Game in progress... • Style: {style_name}"

    embed.set_footer(text=footer_text)

    return embed


def create_results_embed(game: BlackjackGame) -> discord.Embed:
    """
    Create the final results embed.

    Calculates wins/losses/pushes for every hand.

    Args:
        game: The completed BlackjackGame instance.

    Returns:
        Discord Embed object.
    """
    embed = discord.Embed(title="🃏 Game Results", color=discord.Color.gold())

    # Retrieve preference
    use_emojis = game.use_emojis

    # Check if all players busted (dealer didn't play)
    all_players_busted_surrendered = all(
        all(
            hand.status in [HandStatus.BUST, HandStatus.SURRENDER]
            for hand in player.hands
        )
        for player in game.players
    )

    # Dealer's final hand
    dealer_hand = game.dealer.hands[0].cards
    dealer_value = calculate_hand_value(dealer_hand)
    dealer_bj = is_blackjack(dealer_hand)

    formatted_hand = format_hand_with_value(dealer_hand, use_emojis=use_emojis)

    if all_players_busted_surrendered:
        # Dealer didn't play - show hole card but indicate auto-win
        dealer_text = (
            f"{formatted_hand} - **AUTO-WIN** 🏆\n*All players busted/surrendered*"
        )
    else:
        dealer_status = ""
        if dealer_bj:
            dealer_status = " (BLACKJACK! 🎉)"
        elif dealer_value > BLACKJACK_VALUE:
            dealer_status = " (BUST 💥)"

        dealer_text = f"{formatted_hand}{dealer_status}"

    embed.add_field(
        name=f"🎲 Dealer ({game.dealer.username})", value=dealer_text, inline=False
    )

    embed.add_field(name="", value="", inline=False)  # Separator

    # Players' results
    for player in game.players:
        player_results = []

        for hand_idx, hand in enumerate(player.hands):
            hand_prefix = f"Hand {hand_idx + 1}: " if len(player.hands) > 1 else ""
            hand_text = format_hand_with_value(hand.cards, use_emojis=use_emojis)

            player_value = calculate_hand_value(hand.cards)
            player_bj = is_blackjack(hand.cards)

            # Determine result
            if hand.status == HandStatus.BUST:
                result = "lose"
            elif hand.status == HandStatus.SURRENDER:
                result = "surrender"  # Special display case
                hand_text += " (Surrendered 🏳️)"
            else:
                result = determine_winner(
                    player_value, dealer_value, player_bj, dealer_bj
                )

            if result != "surrender":
                result_text = get_result_message(result)
                player_results.append(f"{hand_prefix}{hand_text} - {result_text}")
            else:
                player_results.append(f"{hand_prefix}{hand_text}")

        player_full_text = "\n".join(player_results)

        embed.add_field(
            name=f"👤 {player.username}", value=player_full_text, inline=False
        )

    if all_players_busted_surrendered:
        embed.set_footer(text="Dealer wins - All players busted! • GG!")
    else:
        embed.set_footer(text="GG! Thanks for playing • Dealer can start a new game")

    return embed
