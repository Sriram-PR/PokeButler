"""
Card and Deck classes for the Blackjack game.

This module provides the fundamental abstractions for playing cards and
shuffled decks used in the game. It supports:
- Standard 52-card decks.
- Multiple decks combined into a single "shoe".
- Custom Discord emoji representation for cards.
"""

import random
from dataclasses import dataclass
from typing import List

from config.settings import BLACKJACK_NUM_DECKS_IN_SHOE
from utils.assets import CARD_EMOJIS


@dataclass
class Card:
    """
    Represents a standard playing card.

    Attributes:
        suit: The card suit (♠, ♥, ♦, ♣).
        rank: The card rank (A, 2-10, J, Q, K).
    """

    suit: str
    rank: str

    def __str__(self) -> str:
        """
        Get the text representation of the card (e.g., 'A♠').

        Returns:
            String representation.
        """
        return f"{self.rank}{self.suit}"

    def get_emoji(self) -> str:
        """
        Get the custom Discord emoji for this card.

        Falls back to text representation if the emoji ID is not configured
        in the assets registry.

        Returns:
            Discord emoji string or text fallback.
        """
        # Map suit symbols to names
        suit_map = {"♠": "spades", "♥": "hearts", "♦": "diamonds", "♣": "clubs"}

        # Map rank symbols to names
        rank_map = {"A": "ace", "J": "jack", "Q": "queen", "K": "king"}

        suit_name = suit_map.get(self.suit, "spades")
        rank_name = rank_map.get(self.rank, self.rank)

        key = f"{rank_name}_{suit_name}"

        # Return emoji or fallback to text if missing
        return CARD_EMOJIS.get(key, str(self))

    @property
    def value(self) -> int:
        """
        Get the numerical value of the card for Blackjack.

        Note:
            Aces return 11 here by default. The hand calculation logic in
            `blackjack_helpers.py` handles converting Aces to 1 if the hand busts.

        Returns:
            Integer value (2-10, or 11 for Ace).
        """
        if self.rank == "A":
            return 11
        elif self.rank in ["J", "Q", "K"]:
            return 10
        else:
            return int(self.rank)


class Deck:
    """
    Represents a shoe containing multiple shuffled standard decks.

    The number of decks included is determined by `BLACKJACK_NUM_DECKS_IN_SHOE`
    in settings.
    """

    SUITS = ["♠", "♥", "♦", "♣"]
    RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]

    def __init__(self, seed: int = None):
        """
        Initialize the deck and shuffle it.

        Args:
            seed: Optional random seed for reproducible shuffling (useful for testing).
        """
        self.seed = seed or random.randint(1, 1000000)
        self.cards: List[Card] = []
        self._initialize_decks()
        self._shuffle()

    def _initialize_decks(self):
        """Create multiple standard decks based on configuration."""
        for _ in range(BLACKJACK_NUM_DECKS_IN_SHOE):
            for suit in self.SUITS:
                for rank in self.RANKS:
                    self.cards.append(Card(suit=suit, rank=rank))

    def _shuffle(self):
        """Shuffle the deck using the configured seed."""
        random.seed(self.seed)
        random.shuffle(self.cards)

    def draw(self) -> Card:
        """
        Draw the top card from the deck.

        Returns:
            The drawn Card object.

        Raises:
            IndexError: If the deck is empty.
        """
        if not self.cards:
            raise IndexError("Deck is empty - no more cards to draw")

        return self.cards.pop()

    def cards_remaining(self) -> int:
        """Get number of cards remaining in the shoe."""
        return len(self.cards)

    def __len__(self) -> int:
        """Return number of cards in deck."""
        return len(self.cards)

    def __repr__(self) -> str:
        """String representation of deck status."""
        return f"<Deck: {len(self.cards)} cards remaining, seed={self.seed}>"
