// frontend/js/hand_history.js
/**
 * hand_history.js — Gestion de l'historique des mains
 * Affiche les dernières mains jouées sur la table.
 * Permet de charger depuis le serveur et de sauvegarder localement.
 */

const HandHistory = (() => {
    const _hands = [];
    const MAX = 50;

    // Charge l'historique depuis le serveur pour une table donnée
    async function loadFromServer(tableId, limit = 20) {
        try {
            const resp = await fetch(`/api/tables/${tableId}/history?limit=${limit}`);
            if (resp.ok) {
                const history = await resp.json();
                _hands.length = 0;
                _hands.push(...history);
                _render();
                return true;
            }
        } catch (e) {
            console.error('Failed to load history:', e);
        }
        return false;
    }

    // Ajoute une main à l'historique (appelé à la fin d'une main)
    function add(data) {
        _hands.unshift(data);
        if (_hands.length > MAX) _hands.pop();
        _render();
        try {
            // Sauvegarde locale pour persistance (optionnel)
            const saved = JSON.parse(localStorage.getItem('poker_hand_history') || '{}');
            saved[data.table_id || 'current'] = _hands.slice(0, 20);
            localStorage.setItem('poker_hand_history', JSON.stringify(saved));
        } catch(e) {}
    }

    // Affiche l'historique dans l'élément prévu
    function _render() {
        const el = document.getElementById('historyList');
        if (!el) return;
        if (!_hands.length) {
            el.innerHTML = '<div class="hh-empty">Aucune main jouée</div>';
            return;
        }
        // Limiter l'affichage aux 10 dernières mains
        el.innerHTML = _hands.slice(0, 10).map(h => {
            const winners = (h.winners || []).map(w => w.username).join(', ');
            const pot = h.pot?.toLocaleString() || '0';
            const date = h.timestamp ? new Date(h.timestamp).toLocaleTimeString() : '';
            const handNumber = h.hand || h.round || '?';
            return `<div class="hh-entry">
                <span class="hh-round">#${handNumber}</span>
                <span class="hh-winner">${winners || '?'}</span>
                <span class="hh-pot">${pot}</span>
                <span class="hh-time">${date}</span>
            </div>`;
        }).join('');
    }

    // Vide l'historique
    function clear() {
        _hands.length = 0;
        _render();
    }

    // Retourne toutes les mains (pour export éventuel)
    function getAll() {
        return [..._hands];
    }

    return { add, clear, getAll, loadFromServer };
})();

window.HandHistory = HandHistory;
