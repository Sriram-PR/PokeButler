"""
Helper functions for Blackjack game logic and display.

This module contains pure functions for calculating hand values, determining
win conditions, formatting output strings, and handling specific rule checks
like Soft 17 detection.
"""

from typing import List

from config.settings import (
    BLACKJACK_ACE_HIGH_VALUE,
    BLACKJACK_ACE_LOW_VALUE,
    BLACKJACK_FACE_CARD_VALUE,
    BLACKJACK_INITIAL_CARDS_COUNT,
    BLACKJACK_VALUE,
)
from utils.assets import CARD_BACK_EMOJI
from utils.blackjack_deck import Card


def calculate_hand_value(cards: List[Card]) -> int:
    """
    Calculate the best numerical value of a hand.

    Automatically handles the dual nature of Aces (1 or 11). It initially
    counts all Aces as 11. If the total exceeds 21 (bust), it converts
    Aces from 11 to 1 until the total is under 21 or no Aces remain to be
    converted.

    Args:
        cards: List of Card objects.

    Returns:
        The highest valid integer value of the hand.
    """
    if not cards:
        return 0

    total = 0
    aces = 0

    # Count value and number of Aces
    for card in cards:
        if card.rank == "A":
            aces += 1
            total += BLACKJACK_ACE_HIGH_VALUE  # Count Ace as 11 initially
        elif card.rank in ["J", "Q", "K"]:
            total += BLACKJACK_FACE_CARD_VALUE
        else:
            total += int(card.rank)

    # Adjust for Aces if bust
    while total > BLACKJACK_VALUE and aces > 0:
        total -= (
            BLACKJACK_ACE_HIGH_VALUE - BLACKJACK_ACE_LOW_VALUE
        )  # Convert an Ace from 11 to 1
        aces -= 1

    return total


def is_blackjack(cards: List[Card]) -> bool:
    """
    Check if a hand is a natural Blackjack.

    A Blackjack is defined strictly as a hand with exactly 2 cards totaling 21.
    21 with 3+ cards is just "21", not Blackjack.

    Args:
        cards: List of Card objects.

    Returns:
        True if Blackjack, False otherwise.
    """
    if len(cards) != BLACKJACK_INITIAL_CARDS_COUNT:
        return False

    return calculate_hand_value(cards) == BLACKJACK_VALUE


def is_bust(cards: List[Card]) -> bool:
    """
    Check if a hand has exceeded the maximum value.

    Args:
        cards: List of Card objects.

    Returns:
        True if total value > 21.
    """
    return calculate_hand_value(cards) > BLACKJACK_VALUE


def is_soft_hand(cards: List[Card]) -> bool:
    """
    Check if a hand is "soft".

    A soft hand is defined as one containing an Ace that is currently being
    counted as 11. If hitting results in a bust, the Ace can become a 1,
    saving the hand. A "hard" hand has no Aces, or all Aces are forced to be 1.

    Args:
        cards: List of Card objects.

    Returns:
        True if the hand is soft, False otherwise.
    """
    has_ace = any(card.rank == "A" for card in cards)

    if not has_ace:
        return False

    # Calculate without Ace bonus
    total_without_ace = sum(
        BLACKJACK_FACE_CARD_VALUE
        if card.rank in ["J", "Q", "K"]
        else BLACKJACK_ACE_LOW_VALUE
        if card.rank == "A"
        else int(card.rank)
        for card in cards
    )

    # If using Ace as 11 doesn't bust, it's soft
    return (
        total_without_ace + (BLACKJACK_ACE_HIGH_VALUE - BLACKJACK_ACE_LOW_VALUE)
        <= BLACKJACK_VALUE
    )


def can_split(cards: List[Card]) -> bool:
    """
    Check if a hand can be split.

    Splitting is allowed only when the hand has exactly 2 cards of the same rank.
    (e.g., Two 8s, Two Kings).

    Args:
        cards: List of Card objects.

    Returns:
        True if split is allowed.
    """
    if len(cards) != BLACKJACK_INITIAL_CARDS_COUNT:
        return False

    return cards[0].rank == cards[1].rank


def format_hand(
    cards: List[Card], hide_second: bool = False, use_emojis: bool = True
) -> str:
    """
    Format a list of cards into a display string.

    Args:
        cards: List of Card objects.
        hide_second: If True, the second card is replaced with a card back emoji/text.
            Used for the Dealer's hole card.
        use_emojis: If True, uses custom discord emojis. If False, uses text (e.g., A♠).

    Returns:
        Formatted string of cards.
    """
    if not cards:
        return "—"

    display_cards = []

    # Process visible cards
    for i, card in enumerate(cards):
        if hide_second and i == 1:
            # Hidden card
            if use_emojis:
                display_cards.append(CARD_BACK_EMOJI)
            else:
                display_cards.append("??")
        else:
            # Visible card
            if use_emojis:
                display_cards.append(card.get_emoji())
            else:
                display_cards.append(str(card))

    # Join with space
    return " ".join(display_cards)


def format_hand_with_value(
    cards: List[Card], hide_second: bool = False, use_emojis: bool = True
) -> str:
    """
    Format a hand string including its numerical value.

    Args:
        cards: List of Card objects.
        hide_second: If True, hides the second card and the total value.
        use_emojis: Whether to use custom emojis.

    Returns:
        String in format "Card1 Card2 = Value" or "Card1 ?? = ?".
    """
    hand_str = format_hand(cards, hide_second, use_emojis)

    if hide_second:
        return f"{hand_str} = ?"

    value = calculate_hand_value(cards)

    # Add soft indicator if applicable
    if is_soft_hand(cards):
        return f"{hand_str} = {value} (soft)"

    return f"{hand_str} = {value}"


def determine_winner(
    player_value: int,
    dealer_value: int,
    player_blackjack: bool = False,
    dealer_blackjack: bool = False,
) -> str:
    """
    Determine the result of a completed hand against the dealer.

    Logic:
    - Blackjack beats 21.
    - Busts are automatic losses (checked prior to this, but handled logically).
    - Higher value wins.
    - Ties are Pushes.

    Args:
        player_value: Integer value of player's hand.
        dealer_value: Integer value of dealer's hand.
        player_blackjack: True if player has natural blackjack.
        dealer_blackjack: True if dealer has natural blackjack.

    Returns:
        String result: "win", "lose", or "push".
    """
    # Both blackjack = push
    if player_blackjack and dealer_blackjack:
        return "push"

    # Player blackjack beats dealer non-blackjack
    if player_blackjack:
        return "win"

    # Dealer blackjack beats player non-blackjack
    if dealer_blackjack:
        return "lose"

    # Player bust = lose
    if player_value > BLACKJACK_VALUE:
        return "lose"

    # Dealer bust = player wins (if player didn't bust)
    if dealer_value > BLACKJACK_VALUE:
        return "win"

    # Compare values
    if player_value > dealer_value:
        return "win"
    elif player_value < dealer_value:
        return "lose"
    else:
        return "push"


def get_hand_status_emoji(status: str) -> str:
    """
    Get a visual emoji indicator for a specific hand status.

    Args:
        status: The status string (e.g., 'bust', 'win').

    Returns:
        Emoji character string.
    """
    status_emojis = {
        "active": "🎯",
        "stand": "✋",
        "bust": "💥",
        "blackjack": "🎉",
        "win": "🏆",
        "lose": "💔",
        "push": "🤝",
    }

    return status_emojis.get(status, "❓")


def get_result_message(result: str) -> str:
    """
    Get a human-readable result message.

    Args:
        result: Result code ("win", "lose", "push").

    Returns:
        Formatted string description.
    """
    messages = {"win": "WIN! 🏆", "lose": "LOSE 💔", "push": "PUSH 🤝"}

    return messages.get(result, "???")
