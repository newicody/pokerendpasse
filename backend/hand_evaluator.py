# backend/hand_evaluator.py
"""Système d'évaluation des mains de poker - Version simplifiée"""

from typing import List, Tuple, Dict
from collections import Counter

class HandEvaluator:
    """Évaluateur de mains de poker"""
    
    RANK_VALUES = {
        '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8,
        '9': 9, '10': 10, 'J': 11, 'Q': 12, 'K': 13, 'A': 14
    }
    
    HAND_RANKS = {
        'high_card': 1,
        'one_pair': 2,
        'two_pair': 3,
        'three_of_a_kind': 4,
        'straight': 5,
        'flush': 6,
        'full_house': 7,
        'four_of_a_kind': 8,
        'straight_flush': 9,
        'royal_flush': 10
    }
    
    @classmethod
    def evaluate(cls, cards: List[str]) -> Tuple[int, List[int], str]:
        """
        Évalue une main de poker
        Retourne: (rank, [valeurs pour comparaison], hand_name)
        """
        if not cards or len(cards) < 5:
            return (cls.HAND_RANKS['high_card'], [0], "High Card")
        
        # Convertir les cartes
        parsed = cls._parse_cards(cards)
        suits = [s for s, r in parsed]
        ranks = [r for s, r in parsed]
        
        # Vérifier les combinaisons
        is_flush = len(set(suits)) == 1
        is_straight, straight_high = cls._is_straight(ranks)
        
        rank_counts = Counter(ranks)
        counts = sorted(rank_counts.values(), reverse=True)
        
        if is_flush and is_straight:
            # Quinte flush
            if max(ranks) == 14 and min(ranks) == 10:
                return (cls.HAND_RANKS['royal_flush'], [14], "Royal Flush")
            return (cls.HAND_RANKS['straight_flush'], [straight_high], "Straight Flush")
        
        if 4 in counts:
            # Carré
            four_rank = [r for r, c in rank_counts.items() if c == 4][0]
            kicker = [r for r, c in rank_counts.items() if c != 4][0]
            return (cls.HAND_RANKS['four_of_a_kind'], [four_rank, kicker], "Four of a Kind")
        
        if 3 in counts and 2 in counts:
            # Full house
            three_rank = [r for r, c in rank_counts.items() if c == 3][0]
            two_rank = [r for r, c in rank_counts.items() if c == 2][0]
            return (cls.HAND_RANKS['full_house'], [three_rank, two_rank], "Full House")
        
        if is_flush:
            # Couleur
            return (cls.HAND_RANKS['flush'], sorted(ranks, reverse=True)[:5], "Flush")
        
        if is_straight:
            # Quinte
            return (cls.HAND_RANKS['straight'], [straight_high], "Straight")
        
        if 3 in counts:
            # Brelan
            three_rank = [r for r, c in rank_counts.items() if c == 3][0]
            kickers = sorted([r for r, c in rank_counts.items() if c != 3], reverse=True)
            return (cls.HAND_RANKS['three_of_a_kind'], [three_rank] + kickers[:2], "Three of a Kind")
        
        if counts.count(2) == 2:
            # Deux paires
            pairs = sorted([r for r, c in rank_counts.items() if c == 2], reverse=True)
            kicker = [r for r, c in rank_counts.items() if c == 1][0]
            return (cls.HAND_RANKS['two_pair'], pairs + [kicker], "Two Pair")
        
        if 2 in counts:
            # Une paire
            pair_rank = [r for r, c in rank_counts.items() if c == 2][0]
            kickers = sorted([r for r, c in rank_counts.items() if c == 1], reverse=True)
            return (cls.HAND_RANKS['one_pair'], [pair_rank] + kickers[:3], "One Pair")
        
        # Carte haute
        return (cls.HAND_RANKS['high_card'], sorted(ranks, reverse=True)[:5], "High Card")
    
    @classmethod
    def _parse_cards(cls, cards: List[str]) -> List[Tuple[str, int]]:
        """Parse les cartes du format 's10' ou 'hA'"""
        result = []
        for card in cards:
            if len(card) >= 2:
                suit = card[0]
                rank_str = card[1:]
                if rank_str.isdigit():
                    rank = int(rank_str)
                else:
                    rank = cls.RANK_VALUES.get(rank_str.upper(), 0)
                result.append((suit, rank))
        return result
    
    @classmethod
    def _is_straight(cls, ranks: List[int]) -> Tuple[bool, int]:
        """Vérifie si c'est une quinte et retourne la carte haute"""
        unique_ranks = sorted(set(ranks))
        
        # Vérifier la quinte normale
        for i in range(len(unique_ranks) - 4):
            if unique_ranks[i+4] - unique_ranks[i] == 4:
                return (True, unique_ranks[i+4])
        
        # Vérifier la quinte As-5 (A,2,3,4,5)
        if set([14, 2, 3, 4, 5]).issubset(set(unique_ranks)):
            return (True, 5)
        
        return (False, 0)
