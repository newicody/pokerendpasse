/**
 * hand_history.js — Historique des mains joué
 */
const HandHistory = (() => {
    const _hands = [];
    const MAX = 50;

    function add(data) {
        _hands.unshift(data);
        if (_hands.length > MAX) _hands.pop();
        _render();
    }

    function _render() {
        const el = document.getElementById('historyList');
        if (!el) return;
        if (!_hands.length) {
            el.innerHTML = '<div class="hh-empty">Aucune main jouée</div>';
            return;
        }
        el.innerHTML = _hands.map(h => {
            const winners = (h.winners || []).map(w => w.username).join(', ');
            const cards = (h.community || []).join(' ');
            return `<div class="hh-entry">
                <span class="hh-round">#${h.round}</span>
                <span class="hh-winner">${winners}</span>
                <span class="hh-pot">${h.pot}</span>
                <span class="hh-cards">${cards}</span>
            </div>`;
        }).join('');
    }

    function clear() { _hands.length = 0; _render(); }
    function getAll() { return [..._hands]; }

    return { add, clear, getAll };
})();

window.HandHistory = HandHistory;
