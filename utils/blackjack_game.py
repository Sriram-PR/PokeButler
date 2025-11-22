"""
Blackjack game logic and state management.

This module implements the core state machine for the multiplayer Blackjack game.
It handles:
- Lobby management (joining/leaving).
- Card dealing and deck management.
- Turn-based gameplay flow.
- Rule enforcement (Hit, Stand, Double Down, Split, Surrender).
- Dealer AI logic (Soft 17 rules).
- Win condition evaluation.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from config.settings import (
    BLACKJACK_INITIAL_CARDS_COUNT,
)
from utils.blackjack_deck import Card, Deck
from utils.blackjack_helpers import (
    calculate_hand_value,
    can_split,
    is_blackjack,
    is_bust,
    is_soft_hand,
)

logger = logging.getLogger("smogon_bot.blackjack")


class GamePhase(Enum):
    """Enumeration of game phases."""

    LOBBY = "lobby"
    DEALING = "dealing"
    PLAYING = "playing"
    DEALER_TURN = "dealer_turn"
    RESULTS = "results"
    ENDED = "ended"


class HandStatus(Enum):
    """Enumeration of hand statuses."""

    ACTIVE = "active"
    STAND = "stand"
    BUST = "bust"
    BLACKJACK = "blackjack"
    SPLIT_ACES = (
        "split_aces"  # Split aces that auto-stood (usually receive only 1 card)
    )
    SURRENDER = "surrender"  # Player surrendered (late surrender)


@dataclass
class PlayerHand:
    """
    Represents a specific hand held by a player.

    Players may have multiple hands if they split pairs.

    Attributes:
        cards: List of Card objects in the hand.
        status: Current status of the hand (Active, Bust, Stand, etc.).
        is_split: Whether this hand resulted from a split.
        is_split_aces: Whether this hand resulted from splitting Aces (special rules apply).
    """

    cards: List[Card] = field(default_factory=list)
    status: HandStatus = HandStatus.ACTIVE
    is_split: bool = False
    is_split_aces: bool = False


@dataclass
class Player:
    """
    Represents a participant in the game (User or Dealer).

    Attributes:
        user_id: Discord User ID.
        username: Display name.
        hands: List of PlayerHand objects (starts with 1).
        is_dealer: True if this is the dealer bot/host.
        current_hand_index: Index of the hand currently being played (for splits).
    """

    user_id: int
    username: str
    hands: List[PlayerHand] = field(default_factory=lambda: [PlayerHand()])
    is_dealer: bool = False
    current_hand_index: int = 0

    def get_current_hand(self) -> PlayerHand:
        """
        Get the hand currently being played.

        Returns:
            The active PlayerHand object.
        """
        return self.hands[self.current_hand_index]

    def has_multiple_hands(self) -> bool:
        """Check if player has multiple hands (has split)."""
        return len(self.hands) > 1

    def all_hands_finished(self) -> bool:
        """Check if all of the player's hands have finished playing."""
        return all(hand.status != HandStatus.ACTIVE for hand in self.hands)


class BlackjackGame:
    """
    Main game class managing the Blackjack state machine.

    Enforced Rules:
    - **Dealer Strategy**: H17 (Hit on Soft 17).
    - **Blackjack**: Pays 3:2 (conceptually), beats regular 21.
    - **Splitting**: Allowed on pairs. Sequential dealing used.
    - **Split Aces**: Receive exactly one card and auto-stand.
    - **Double Down**: Allowed on any initial two cards.
    - **Surrender**: Late surrender allowed on initial two cards.

    Attributes:
        channel_id: Discord Channel ID where the game is running.
        dealer_id: Discord User ID of the host (who controls the start button).
        max_players: Maximum number of players allowed.
        timeout: Turn timeout in seconds.
    """

    def __init__(
        self,
        channel_id: int,
        dealer_id: int,
        dealer_name: str,
        max_players: int = 3,
        timeout: int = 60,
    ):
        self.channel_id = channel_id
        self.dealer_id = dealer_id
        self.max_players = max_players
        self.timeout = timeout

        # Style Setting (Default: True for Emojis)
        self.use_emojis: bool = True

        # Initialize dealer as first player (special flag)
        self.dealer = Player(user_id=dealer_id, username=dealer_name, is_dealer=True)

        self.players: List[Player] = []
        self.deck = Deck()
        self.phase = GamePhase.LOBBY
        self.current_turn_index = 0

        logger.info(
            "Blackjack game created",
            extra={
                "channel_id": channel_id,
                "dealer_id": dealer_id,
                "dealer_name": dealer_name,
                "max_players": max_players,
                "timeout_seconds": timeout,
            },
        )

    def toggle_style(self) -> bool:
        """
        Toggle between Emoji and Text display modes.

        Returns:
            The new boolean state (True=Emoji, False=Text).
        """
        self.use_emojis = not self.use_emojis
        return self.use_emojis

    # ==================== LOBBY MANAGEMENT ====================

    def add_player(self, user_id: int, username: str) -> bool:
        """
        Add a player to the game lobby.

        Args:
            user_id: Discord User ID.
            username: Discord Display Name.

        Returns:
            True if added successfully, False if full, already joined, or game started.
        """
        if self.phase != GamePhase.LOBBY:
            logger.warning("Cannot add player - game already started")
            return False

        if len(self.players) >= self.max_players:
            logger.warning(f"Cannot add player - game full ({self.max_players})")
            return False

        # Check if already joined
        if any(p.user_id == user_id for p in self.players):
            logger.warning(f"Player {username} already in game")
            return False

        # Cannot join as both dealer and player (dealer host plays the house)
        if user_id == self.dealer_id:
            logger.warning("Dealer cannot join as player")
            return False

        player = Player(user_id=user_id, username=username)
        self.players.append(player)

        logger.info(
            "Player joined game",
            extra={
                "user_id": user_id,
                "username": username,
                "player_count": len(self.players),
            },
        )
        return True

    def remove_player(self, user_id: int) -> bool:
        """
        Remove a player from the lobby.

        Args:
            user_id: Discord User ID.

        Returns:
            True if removed, False if not in lobby or game started.
        """
        if self.phase != GamePhase.LOBBY:
            return False

        self.players = [p for p in self.players if p.user_id != user_id]
        logger.info(f"Player {user_id} left game")
        return True

    def get_player_count(self) -> int:
        """Get number of active players (excluding dealer)."""
        return len(self.players)

    def is_lobby_full(self) -> bool:
        """Check if the lobby has reached maximum capacity."""
        return len(self.players) >= self.max_players

    # ==================== GAME START ====================

    def start_game(self) -> bool:
        """
        Transition the game from LOBBY to PLAYING phase.

        Deals initial cards and checks for immediate Blackjacks.

        Returns:
            True if started successfully, False otherwise.
        """
        if self.phase != GamePhase.LOBBY:
            logger.warning("Cannot start - game not in lobby phase")
            return False

        if len(self.players) == 0:
            logger.warning("Cannot start - no players joined")
            return False

        self.phase = GamePhase.DEALING
        logger.info(f"Starting game with {len(self.players)} player(s)")

        # Deal initial cards
        self._deal_initial_cards()

        # Check for dealer blackjack (game ends immediately)
        if is_blackjack(self.dealer.hands[0].cards):
            logger.info("Dealer has blackjack - game ends immediately")
            self.dealer.hands[0].status = HandStatus.BLACKJACK
            self.phase = GamePhase.RESULTS
            return True

        # Check for player blackjacks (they auto-stand/win, but game continues for others)
        for player in self.players:
            if is_blackjack(player.hands[0].cards):
                logger.info(f"Player {player.username} has blackjack - auto-stand")
                player.hands[0].status = HandStatus.BLACKJACK

        # Move to playing phase
        self.phase = GamePhase.PLAYING
        self.current_turn_index = 0

        # Fast-forward turn if the first players have Blackjack (are already finished)
        while (
            self.current_turn_index < len(self.players)
            and self.players[self.current_turn_index].all_hands_finished()
        ):
            logger.info(
                f"Skipping {self.players[self.current_turn_index].username} (Hands finished)"
            )
            self.current_turn_index += 1

        # If everyone had Blackjack, move straight to Dealer
        if self.current_turn_index >= len(self.players):
            logger.info(
                "All players finished (Blackjacks) - moving to dealer's turn immediately"
            )
            self.phase = GamePhase.DEALER_TURN
            self._check_dealer_auto_stand()

        return True

    def _deal_initial_cards(self):
        """
        Deal 2 cards to each player and dealer in round-robin fashion.

        Standard dealing procedure:
        1. Card 1 to Player 1, Player 2... Dealer (Face Up)
        2. Card 2 to Player 1, Player 2... Dealer (Hole Card/Face Down)
        """
        logger.info(
            "Dealing initial cards",
            extra={"player_count": len(self.players), "deck_size": len(self.deck)},
        )

        # Round 1
        for player in self.players:
            card = self.deck.draw()
            player.hands[0].cards.append(card)
            logger.debug(f"Dealt {card} to {player.username}")

        dealer_card_1 = self.deck.draw()
        self.dealer.hands[0].cards.append(dealer_card_1)
        logger.debug(f"Dealt {dealer_card_1} to dealer (face up)")

        # Round 2
        for player in self.players:
            card = self.deck.draw()
            player.hands[0].cards.append(card)
            logger.debug(f"Dealt {card} to {player.username}")

        dealer_card_2 = self.deck.draw()
        self.dealer.hands[0].cards.append(dealer_card_2)
        logger.debug(f"Dealt {dealer_card_2} to dealer (face down - hole card)")

    # ==================== TURN MANAGEMENT ====================

    def get_current_player(self) -> Optional[Player]:
        """
        Get the player object whose turn it is currently.

        Returns:
            Player object or None if not in a playing phase.
        """
        if self.phase == GamePhase.DEALER_TURN:
            return self.dealer

        if self.phase != GamePhase.PLAYING:
            return None

        if 0 <= self.current_turn_index < len(self.players):
            return self.players[self.current_turn_index]

        return None

    def get_turn_order(self) -> List[Player]:
        """Get the full list of participants in turn order."""
        return self.players + [self.dealer]

    def _check_all_players_busted_or_surrendered(self) -> bool:
        """
        Check if every non-dealer player has busted or surrendered.
        If true, the dealer does not need to play out their hand.

        Returns:
            True if all players are busted/surrendered.
        """
        if not self.players:
            return False

        for player in self.players:
            # Check if player has ANY hand that's still potentially competitive
            for hand in player.hands:
                if hand.status in [
                    HandStatus.ACTIVE,
                    HandStatus.STAND,
                    HandStatus.BLACKJACK,
                    HandStatus.SPLIT_ACES,
                ]:
                    return False

        return True

    def _advance_turn(self):
        """
        Advance the game state to the next hand or next player.

        Logic:
        1. If current player has more hands (from split), move to next hand.
           - Note: Sequential Dealing rule applies here (deal 2nd card to split hand).
        2. If current player finished, move to next player.
        3. If all players finished, move to Dealer.
        4. If Dealer finished, move to Results.
        """
        current_player = self.get_current_player()

        if current_player and not current_player.all_hands_finished():
            # Still has hands to play
            if current_player.current_hand_index < len(current_player.hands) - 1:
                current_player.current_hand_index += 1

                # SEQUENTIAL SPLIT LOGIC:
                # If we move to a split hand that only has 1 card, deal the second card now
                current_hand = current_player.get_current_hand()
                if len(current_hand.cards) == 1:
                    new_card = self.deck.draw()
                    current_hand.cards.append(new_card)
                    logger.info(
                        f"Dealt second card to {current_player.username}'s split hand: {new_card}"
                    )

                    # Handle Aces specifically if split (usually you only get one card)
                    if current_hand.is_split_aces:
                        current_hand.status = HandStatus.SPLIT_ACES
                        # Recursively advance since this hand is now done
                        self._advance_turn()
                        return

                logger.info(
                    f"Moving to {current_player.username}'s next hand "
                    f"({current_player.current_hand_index + 1}/{len(current_player.hands)})"
                )
                return

        # Check if current player is dealer and has finished (bust or stand)
        if current_player and current_player.is_dealer:
            if current_player.get_current_hand().status in [
                HandStatus.BUST,
                HandStatus.STAND,
            ]:
                logger.info("Dealer finished (bust or stand) - moving to results")
                self.phase = GamePhase.RESULTS
                return

        # Check if all players have busted or surrendered (Dealer doesn't need to play)
        if self._check_all_players_busted_or_surrendered():
            logger.info(
                "All players busted/surrendered - dealer wins automatically, skipping dealer turn"
            )
            self.phase = GamePhase.RESULTS
            return

        # Move to next player
        self.current_turn_index += 1

        # Skip players who finished all hands (e.g., immediate Blackjack)
        while (
            self.current_turn_index < len(self.players)
            and self.players[self.current_turn_index].all_hands_finished()
        ):
            self.current_turn_index += 1

        # If all players done, move to dealer
        if self.current_turn_index >= len(self.players):
            logger.info("All players finished - moving to dealer's turn")
            self.phase = GamePhase.DEALER_TURN
            # Check if dealer should auto-stand based on initial cards
            self._check_dealer_auto_stand()
        else:
            logger.info(
                f"Moving to {self.players[self.current_turn_index].username}'s turn"
            )

    def _check_dealer_auto_stand(self):
        """
        Evaluate if Dealer should stand based on House Rules (H17).

        Rule: Dealer HITS on Soft 17.
        - Hand < 17: HIT
        - Hand = 17 (Soft): HIT
        - Hand = 17 (Hard): STAND
        - Hand > 17: STAND
        """
        if self.phase != GamePhase.DEALER_TURN:
            return

        dealer_hand = self.dealer.hands[0]
        hand_value = calculate_hand_value(dealer_hand.cards)
        is_soft = is_soft_hand(dealer_hand.cards)

        # Dealer must HIT on 16 or lower
        if hand_value < 17:
            return False

        # Dealer must HIT on Soft 17 (H17 Rule)
        if hand_value == 17 and is_soft:
            return False

        # Otherwise, Dealer STANDS (Hard 17+ or Soft 18+)
        dealer_hand.status = HandStatus.STAND
        self.phase = GamePhase.RESULTS
        logger.info(
            f"Dealer auto-stand at {hand_value} (Soft: {is_soft}) - moving to results"
        )
        return True

    # ==================== PLAYER ACTIONS ====================

    def hit(self, user_id: int) -> Optional[Card]:
        """
        Perform 'Hit' action: Draw one card.

        Args:
            user_id: ID of the user performing the action.

        Returns:
            The drawn Card, or None if the action is invalid.
        """
        current_player = self.get_current_player()

        if not current_player or current_player.user_id != user_id:
            logger.warning(f"Hit failed - not {user_id}'s turn")
            return None

        # Dealer-specific: check if can hit (H17 Logic)
        if current_player.is_dealer:
            if self.can_dealer_stand():
                logger.warning("Dealer cannot hit (must stand)")
                return None

        current_hand = current_player.get_current_hand()

        if current_hand.status != HandStatus.ACTIVE:
            logger.warning(f"Cannot hit - hand already {current_hand.status}")
            return None

        # Draw card
        card = self.deck.draw()
        current_hand.cards.append(card)

        logger.info(
            "Player hit",
            extra={
                "player": current_player.username,
                "user_id": current_player.user_id,
                "card": str(card),
                "hand_value": calculate_hand_value(current_hand.cards),
            },
        )

        # Check for bust
        if is_bust(current_hand.cards):
            current_hand.status = HandStatus.BUST
            logger.info(f"{current_player.username} bust!")
            self._advance_turn()
        # Check if dealer should auto-stand after hitting
        elif current_player.is_dealer:
            if self.can_dealer_stand():
                current_hand.status = HandStatus.STAND
                self.phase = GamePhase.RESULTS
                logger.info("Dealer auto-stand after hit - moving to results")

        return card

    def stand(self, user_id: int) -> bool:
        """
        Perform 'Stand' action: End turn for current hand.

        Args:
            user_id: ID of the user performing the action.

        Returns:
            True if successful, False if invalid.
        """
        current_player = self.get_current_player()

        if not current_player or current_player.user_id != user_id:
            logger.warning(f"Stand failed - not {user_id}'s turn")
            return False

        # Dealer-specific: check if can stand (H17 Logic)
        if current_player.is_dealer:
            if not self.can_dealer_stand():
                logger.warning("Dealer cannot stand (must hit on Soft 17 or < 17)")
                return False

        current_hand = current_player.get_current_hand()

        if current_hand.status != HandStatus.ACTIVE:
            logger.warning(f"Cannot stand - hand already {current_hand.status}")
            return False

        current_hand.status = HandStatus.STAND
        logger.info(f"{current_player.username} stands")

        # If dealer stands, move to results
        if current_player.is_dealer:
            self.phase = GamePhase.RESULTS
            logger.info("Dealer stood - moving to results")
        else:
            self._advance_turn()

        return True

    def double_down(self, user_id: int) -> Optional[Card]:
        """
        Perform 'Double Down' action: Double bet (conceptually), draw 1 card, stand.

        Args:
            user_id: ID of the user performing the action.

        Returns:
            The drawn Card, or None if action invalid.
        """
        current_player = self.get_current_player()

        if not current_player or current_player.user_id != user_id:
            return None

        if current_player.is_dealer:
            logger.warning("Dealer cannot double down")
            return None

        current_hand = current_player.get_current_hand()

        # Can only double on first 2 cards OR after split
        if len(current_hand.cards) != BLACKJACK_INITIAL_CARDS_COUNT:
            logger.warning("Can only double down on 2 cards")
            return None

        if current_hand.status != HandStatus.ACTIVE:
            return None

        # Draw exactly one card
        card = self.deck.draw()
        current_hand.cards.append(card)

        logger.info(f"{current_player.username} doubled down - drew {card}")

        # Check for bust
        if is_bust(current_hand.cards):
            current_hand.status = HandStatus.BUST
            logger.info(f"{current_player.username} bust after double down!")
        else:
            current_hand.status = HandStatus.STAND

        self._advance_turn()
        return card

    def split(self, user_id: int) -> bool:
        """
        Perform 'Split' action: Split a pair into two hands.

        Logic:
        1. Validates hand is a pair.
        2. Splits cards into Hand A and Hand B.
        3. Deals 2nd card to Hand A immediately (Sequential Dealing).
        4. Hand B receives 2nd card when turn advances to it.

        Args:
            user_id: ID of the user performing the action.

        Returns:
            True if split successful, False otherwise.
        """
        current_player = self.get_current_player()

        if not current_player or current_player.user_id != user_id:
            return False

        if current_player.is_dealer:
            logger.warning("Dealer cannot split")
            return False

        current_hand = current_player.get_current_hand()

        if not can_split(current_hand.cards):
            logger.warning("Cannot split - not a pair")
            return False

        if current_hand.status != HandStatus.ACTIVE:
            return False

        # Split the pair
        card1 = current_hand.cards[0]
        card2 = current_hand.cards[1]

        is_aces = card1.rank == "A"

        # Create two new hands
        hand1 = PlayerHand(cards=[card1], is_split=True, is_split_aces=is_aces)
        hand2 = PlayerHand(cards=[card2], is_split=True, is_split_aces=is_aces)

        # SEQUENTIAL DEALING:
        # Deal second card to Hand 1 immediately
        new_card1 = self.deck.draw()
        hand1.cards.append(new_card1)
        # Hand 2 gets its second card ONLY when we start playing it (in _advance_turn)

        logger.info(
            f"{current_player.username} split {card1.rank}s - "
            f"Hand 1: {card1} {new_card1}, Hand 2: {card2} (Waiting)"
        )

        # Replace current hand with split hands
        current_player.hands[current_player.current_hand_index] = hand1
        current_player.hands.insert(current_player.current_hand_index + 1, hand2)

        # Split Aces rule: auto-stand both hands
        if is_aces:
            hand1.status = HandStatus.SPLIT_ACES
            # Must deal Hand 2 its card now since we won't "play" it
            hand2.cards.append(self.deck.draw())
            hand2.status = HandStatus.SPLIT_ACES
            logger.info("Split Aces - both hands auto-stand")
            self._advance_turn()

        return True

    def surrender(self, user_id: int) -> bool:
        """
        Perform 'Surrender' action: Forfeit half bet (conceptually) and end hand.

        Only allowed on initial two cards before any other action.

        Args:
            user_id: ID of the user performing the action.

        Returns:
            True if successful, False if invalid.
        """
        current_player = self.get_current_player()
        if not current_player or current_player.user_id != user_id:
            return False

        if current_player.is_dealer:
            return False

        current_hand = current_player.get_current_hand()

        # Surrender only allowed on initial two cards and no split
        if len(current_hand.cards) != 2 or current_hand.is_split:
            logger.warning("Surrender only allowed on initial 2 cards")
            return False

        if current_hand.status != HandStatus.ACTIVE:
            return False

        current_hand.status = HandStatus.SURRENDER
        logger.info(f"{current_player.username} surrendered")
        self._advance_turn()
        return True

    # ==================== GAME STATE ====================

    def get_dealer_hand(self, reveal_hole_card: bool = False) -> List[Card]:
        """
        Get dealer's hand cards.

        Args:
            reveal_hole_card: If True, returns all cards. If False, hides the
                second card (hole card) unless the game is over or it's dealer's turn.

        Returns:
            List of visible cards.
        """
        if reveal_hole_card or self.phase in [GamePhase.DEALER_TURN, GamePhase.RESULTS]:
            return self.dealer.hands[0].cards

        # Hide hole card during player turns
        return self.dealer.hands[0].cards[:1]

    def should_reveal_hole_card(self) -> bool:
        """Check if hole card should be revealed based on current game phase."""
        return self.phase in [GamePhase.DEALER_TURN, GamePhase.RESULTS]

    def is_game_over(self) -> bool:
        """Check if game has reached a terminal state."""
        return self.phase in [GamePhase.RESULTS, GamePhase.ENDED]

    def can_dealer_hit(self) -> bool:
        """
        Check if dealer is allowed/required to hit.

        Rule: Hit if < 17 OR (Hit if 17 AND Soft).

        Returns:
            True if dealer should hit.
        """
        if not self.dealer.hands[0].cards:
            return False

        hand = self.dealer.hands[0].cards
        val = calculate_hand_value(hand)
        is_soft = is_soft_hand(hand)

        # Hit if < 17
        if val < 17:
            return True
        # Hit if 17 and Soft (H17)
        if val == 17 and is_soft:
            return True

        return False

    def can_dealer_stand(self) -> bool:
        """Check if dealer should stand (Hard 17+ or Soft 18+)."""
        return not self.can_dealer_hit()

    def get_game_summary(self) -> Dict:
        """
        Get a dictionary summary of the game state for logging.

        Returns:
            Dictionary with key game attributes.
        """
        return {
            "channel_id": self.channel_id,
            "phase": self.phase.value,
            "dealer": self.dealer.username,
            "players": [p.username for p in self.players],
            "current_turn": self.get_current_player().username
            if self.get_current_player()
            else None,
            "deck_remaining": len(self.deck),
        }
