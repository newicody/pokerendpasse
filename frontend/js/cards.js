/**
 * cards.js — Module de rendu des cartes
 * Gère l'affichage des cartes de poker (grandes et mini).
 * Toujours fond blanc pour les cartes face visible, peu importe le thème.
 */
'use strict';

window.Cards = (() => {

    // Table de correspondance couleur → symbole et classe CSS
    const SUITS = {
        h: { sym: '♥', cls: 'hearts' },
        d: { sym: '♦', cls: 'diamonds' },
        c: { sym: '♣', cls: 'clubs'  },
        s: { sym: '♠', cls: 'spades' },
    };

    // Affichage des rangs (T → 10, lettres restent)
    const RANK_DISPLAY = { T: '10', J: 'J', Q: 'Q', K: 'K', A: 'A' };

    /**
     * Parse une carte string (ex: "Ah", "Td", "2c") en objet {rank, suit}.
     * Retourne null si la carte est invalide ou dos.
     */
    function parse(card) {
        if (!card || card === 'back' || card.length < 2) return null;
        const suitChar = card.slice(-1);
        const rankChar = card.slice(0, -1);
        const suit = SUITS[suitChar];
        if (!suit) return null;
        return {
            rank: RANK_DISPLAY[rankChar] || rankChar,
            suit,
        };
    }

    return {
        /**
         * Grande carte (community cards, mes cartes en bas).
         * Toujours fond blanc.
         */
        html(card) {
            const p = parse(card);
            if (!p) {
                // Carte dos
                return `<div class="card-back-face">
                    <div class="card-back-pattern"></div>
                </div>`;
            }
            return `<div class="card-face ${p.suit.cls}">
                <span class="cf-tl">${p.rank}<br>${p.suit.sym}</span>
                <span class="cf-mid">${p.suit.sym}</span>
                <span class="cf-br">${p.suit.sym}<br>${p.rank}</span>
            </div>`;
        },

        /**
         * Mini carte pour les sièges joueurs.
         * @param {string} card  - code carte ou null
         * @param {boolean} back - forcer l'affichage dos
         */
        mini(card, back = false) {
            if (back || !card) {
                return `<span class="card-mini back">🂠</span>`;
            }
            const p = parse(card);
            if (!p) return `<span class="card-mini back">🂠</span>`;
            return `<span class="card-mini ${p.suit.cls}">${p.rank}${p.suit.sym}</span>`;
        },

        /**
         * Vérifie si une carte est valide.
         */
        isValid(card) {
            return parse(card) !== null;
        },

        /**
         * Retourne la classe CSS de couleur pour une carte.
         */
        suitClass(card) {
            if (!card) return '';
            const p = parse(card);
            return p ? p.suit.cls : '';
        },
    };
})();
