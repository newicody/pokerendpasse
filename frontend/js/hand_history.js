/**
 * hand_history.js — Historique des mains de la table
 * Capture les événements de chaque main et les affiche dans le panel droit.
 * Doit être chargé après cards.js.
 */
'use strict';

window.HandHistory = (() => {

    const MAX_HANDS = 15;       // Nombre maximum de mains gardées
    const MAX_VISIBLE = 5;      // Nombre de mains affichées simultanément

    let _hands = [];            // Tableau des mains terminées (newest first)
    let _current = null;        // Main en cours

    // ── Helpers ────────────────────────────────────────────────────────────────

    function _fmtTime(ts) {
        return new Date(ts).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    }

    function _fmtCard(card) {
        return Cards ? Cards.mini(card) : card;
    }

    function _fmtCards(cards) {
        if (!cards || !cards.length) return '—';
        return cards.map(c => _fmtCard(c)).join(' ');
    }

    // ── Cycle d'une main ───────────────────────────────────────────────────────

    /**
     * Démarre le suivi d'une nouvelle main.
     * @param {number} round - numéro de main
     * @param {number} sb    - small blind
     * @param {number} bb    - big blind
     */
    function startHand(round, sb, bb) {
        _current = {
            round,
            blinds: `${sb}/${bb}`,
            ts: Date.now(),
            events: [],
            community: [],
            winners: null,
        };
    }

    /**
     * Enregistre un événement de jeu.
     * @param {string} type   - 'flop'|'turn'|'river'|'action'|'showdown'|'info'
     * @param {*}      data   - données de l'événement
     */
    function addEvent(type, data) {
        if (!_current) return;
        _current.events.push({ type, data, ts: Date.now() });
        // Garder la liste des community cards à jour
        if (type === 'flop')  _current.community = [...(data || [])];
        if (type === 'turn')  _current.community.push(data);
        if (type === 'river') _current.community.push(data);
    }

    /**
     * Termine la main en cours et l'archive.
     * @param {Array<string>} winners - noms des gagnants
     * @param {number} pot            - taille du pot
     */
    function endHand(winners, pot) {
        if (!_current) return;
        _current.winners = winners || [];
        _current.pot = pot || 0;
        _hands.unshift(_current);        // Plus récent en tête
        if (_hands.length > MAX_HANDS) _hands.pop();
        _current = null;
        render();
    }

    // ── Rendu ──────────────────────────────────────────────────────────────────

    function _renderEvent(ev) {
        switch (ev.type) {
            case 'flop':
                return `<span class="he-street">Flop:</span> ${_fmtCards(ev.data)}`;
            case 'turn':
                return `<span class="he-street">Turn:</span> ${_fmtCard(ev.data)}`;
            case 'river':
                return `<span class="he-street">River:</span> ${_fmtCard(ev.data)}`;
            case 'action': {
                const a = ev.data;
                const amtStr = a.amount ? ` ${a.amount.toLocaleString()}` : '';
                const emoji = { fold:'🗂', check:'✋', call:'📞', raise:'📈', all_in:'💥' }[a.action] || '▶';
                return `${emoji} <b>${a.player}</b> ${a.action}${amtStr}`;
            }
            case 'showdown':
                return `👁 Showdown`;
            case 'info':
                return `<i>${ev.data}</i>`;
            default:
                return String(ev.data);
        }
    }

    function _renderHand(h) {
        const winnerStr = h.winners && h.winners.length
            ? `<div class="hh-winner">🏆 ${h.winners.join(', ')} remporte ${h.pot ? h.pot.toLocaleString() : '?'}</div>`
            : '';
        const communityStr = h.community && h.community.length
            ? `<div class="hh-community">${_fmtCards(h.community)}</div>`
            : '';
        const eventsStr = h.events
            .filter(e => e.type !== 'flop' && e.type !== 'turn' && e.type !== 'river')  // street events dans community
            .slice(0, 8)    // limiter la longueur
            .map(e => `<div class="hh-event">${_renderEvent(e)}</div>`)
            .join('');

        return `<details class="hh-hand">
            <summary class="hh-summary">
                Main #${h.round}
                <span class="hh-time">${_fmtTime(h.ts)}</span>
                <span class="hh-blinds">${h.blinds}</span>
            </summary>
            ${communityStr}
            ${eventsStr}
            ${winnerStr}
        </details>`;
    }

    function render() {
        const list = document.getElementById('historyList');
        if (!list) return;
        if (_hands.length === 0) {
            list.innerHTML = '<div class="hh-empty">Aucune main jouée</div>';
            return;
        }
        list.innerHTML = _hands.slice(0, MAX_VISIBLE).map(_renderHand).join('');
        // Ouvrir la dernière main par défaut
        const first = list.querySelector('details');
        if (first) first.open = true;
    }

    // ── Export public ──────────────────────────────────────────────────────────

    return { startHand, addEvent, endHand, render };

})();
