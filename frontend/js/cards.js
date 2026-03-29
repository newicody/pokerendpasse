/**
 * cards.js — Module de rendu des cartes
 * Support multi-decks : standard, fourcolor, classic, minimal
 */
const CardsModule = (() => {
    let currentDeck = 'standard';

    const SUITS = {
        h: { symbol: '♥', name: 'hearts' },
        d: { symbol: '♦', name: 'diamonds' },
        c: { symbol: '♣', name: 'clubs' },
        s: { symbol: '♠', name: 'spades' },
    };

    // Couleurs par deck et suit
    const COLORS = {
        standard:  { h: '#e74c3c', d: '#e74c3c', c: '#2c3e50', s: '#2c3e50' },
        fourcolor: { h: '#e74c3c', d: '#3498db', c: '#27ae60', s: '#2c3e50' },
        classic:   { h: '#c0392b', d: '#c0392b', c: '#1a1a2e', s: '#1a1a2e' },
        minimal:   { h: '#666', d: '#666', c: '#333', s: '#333' },
    };

    const RANK_DISPLAY = {
        '2': '2', '3': '3', '4': '4', '5': '5', '6': '6', '7': '7',
        '8': '8', '9': '9', 'T': '10', 'J': 'J', 'Q': 'Q', 'K': 'K', 'A': 'A',
    };

    function parseCard(code) {
        if (!code || code.length < 2) return null;
        const rank = code[0];
        const suit = code[1];
        return { rank, suit, display: RANK_DISPLAY[rank] || rank };
    }

    function renderCard(code, faceDown = false) {
        if (faceDown || !code) {
            return `<div class="card card-back"><div class="card-back-design">🂠</div></div>`;
        }
        const c = parseCard(code);
        if (!c) return `<div class="card card-unknown">?</div>`;

        const suitInfo = SUITS[c.suit] || { symbol: '?', name: 'unknown' };
        const color = (COLORS[currentDeck] || COLORS.standard)[c.suit] || '#333';

        return `<div class="card card-face ${suitInfo.name}" style="color:${color}">
            <div class="card-corner top-left">
                <span class="card-rank">${c.display}</span>
                <span class="card-suit">${suitInfo.symbol}</span>
            </div>
            <div class="card-center">${suitInfo.symbol}</div>
            <div class="card-corner bottom-right">
                <span class="card-rank">${c.display}</span>
                <span class="card-suit">${suitInfo.symbol}</span>
            </div>
        </div>`;
    }

    function setDeck(deckName) {
        if (COLORS[deckName]) currentDeck = deckName;
    }

    function getDeck() { return currentDeck; }

    return { renderCard, setDeck, getDeck, parseCard };
})();

window.CardsModule = CardsModule;
