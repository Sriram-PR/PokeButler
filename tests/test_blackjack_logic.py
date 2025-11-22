from utils.blackjack_deck import Card, Deck
from utils.blackjack_helpers import (
    calculate_hand_value,
    determine_winner,
    is_bust,
    is_soft_hand,
)


class TestBlackjackHelpers:
    def test_card_values(self):
        assert Card("♠", "A").value == 11
        assert Card("♠", "K").value == 10
        assert Card("♠", "5").value == 5

    def test_hand_calculation_simple(self):
        hand = [Card("♠", "10"), Card("♥", "5")]
        assert calculate_hand_value(hand) == 15

    def test_hand_calculation_aces(self):
        # Ace + 5 = 16 (Soft)
        hand_soft = [Card("♠", "A"), Card("♥", "5")]
        assert calculate_hand_value(hand_soft) == 16

        # Ace + King = 21 (Blackjack)
        hand_bj = [Card("♠", "A"), Card("♥", "K")]
        assert calculate_hand_value(hand_bj) == 21

        # Ace + Ace + 9 = 21 (One ace is 11, one is 1)
        hand_aces = [Card("♠", "A"), Card("♥", "A"), Card("♦", "9")]
        assert calculate_hand_value(hand_aces) == 21

        # Ace + 5 + 10 = 16 (Ace must be 1)
        hand_hard = [Card("♠", "A"), Card("♥", "5"), Card("♦", "10")]
        assert calculate_hand_value(hand_hard) == 16

    def test_is_soft_hand(self):
        assert is_soft_hand([Card("♠", "A"), Card("♥", "5")]) is True
        assert is_soft_hand([Card("♠", "10"), Card("♥", "5")]) is False
        # Hard 16 (Ace is forced to be 1)
        assert is_soft_hand([Card("♠", "A"), Card("♥", "5"), Card("♦", "10")]) is False

    def test_is_bust(self):
        assert is_bust([Card("♠", "10"), Card("♥", "10"), Card("♦", "5")]) is True  # 25
        assert is_bust([Card("♠", "10"), Card("♥", "A")]) is False  # 21

    def test_determine_winner(self):
        # Standard wins
        assert determine_winner(20, 19) == "win"
        assert determine_winner(18, 19) == "lose"
        assert determine_winner(19, 19) == "push"

        # Busts
        assert determine_winner(22, 19) == "lose"  # Player bust
        assert determine_winner(19, 22) == "win"  # Dealer bust

        # Blackjack
        assert (
            determine_winner(21, 21, player_blackjack=True, dealer_blackjack=False)
            == "win"
        )
        assert (
            determine_winner(21, 21, player_blackjack=False, dealer_blackjack=True)
            == "lose"
        )
        assert (
            determine_winner(21, 21, player_blackjack=True, dealer_blackjack=True)
            == "push"
        )


class TestDeck:
    def test_deck_initialization(self):
        # 2 Decks * 52 Cards = 104
        deck = Deck()
        assert len(deck) == 104

    def test_draw_card(self):
        deck = Deck()
        initial_len = len(deck)
        card = deck.draw()
        assert isinstance(card, Card)
        assert len(deck) == initial_len - 1
