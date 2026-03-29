/**
 * table.js — Logique principale de la table de poker
 * Support Hold'em + PLO, quick bets, timer, thèmes
 */

// ══════════════════════════════════════════════════════════════════════════════
// Globals
// ══════════════════════════════════════════════════════════════════════════════
const tableId = window.tableId;
let ws = null;
let currentUser = null;
let gameState = null;
let isSpectator = false;
let showStacksInBB = false;
let reconnectAttempts = 0;
let reconnectTimer = null;
let currentQuickBets = [];

const $ = (id) => document.getElementById(id);

// ══════════════════════════════════════════════════════════════════════════════
// Init
// ══════════════════════════════════════════════════════════════════════════════
async function init() {
    await loadUser();
    loadPreferences();
    setupActions();
    setupQuickBets();
    setupChat();
    setupThemeModal();
    setupKeyboardShortcuts();
    connectWS();
    if (typeof SoundManager !== 'undefined') SoundManager.init();
}

async function loadUser() {
    try {
        const resp = await fetch('/api/auth/me');
        if (resp.ok) {
            const data = await resp.json();
            if (data?.user?.id) { currentUser = data.user; return; }
        }
    } catch (e) { console.error('Load user:', e); }
    currentUser = null;
}

function loadPreferences() {
    try {
        const prefs = JSON.parse(localStorage.getItem('poker_table_prefs') || '{}');
        showStacksInBB = prefs.showStacksInBB || false;
        const toggle = $('stackDisplayToggle');
        if (toggle) {
            toggle.checked = showStacksInBB;
            toggle.addEventListener('change', () => {
                showStacksInBB = toggle.checked;
                savePreferences();
                if (gameState) render(gameState);
            });
        }
    } catch (e) {}
}

function savePreferences() {
    try {
        localStorage.setItem('poker_table_prefs', JSON.stringify({ showStacksInBB }));
    } catch (e) {}
}

// ══════════════════════════════════════════════════════════════════════════════
// WebSocket
// ══════════════════════════════════════════════════════════════════════════════
function connectWS() {
    if (ws && (ws.readyState === 0 || ws.readyState === 1)) return;
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const userId = currentUser?.id || 'spectator';
    ws = new WebSocket(`${proto}//${location.host}/ws/${tableId}/${userId}`);

    ws.onopen = () => {
        reconnectAttempts = 0;
        if (!isSpectator) toast('Connecté', 'success');
    };
    ws.onmessage = (e) => {
        try { onMessage(JSON.parse(e.data)); } catch (err) { console.error('WS:', err); }
    };
    ws.onclose = () => {
        if (!isSpectator) toast('Déconnecté', 'error');
        reconnect();
    };
    ws.onerror = () => {};
}

function reconnect() {
    if (reconnectTimer) clearTimeout(reconnectTimer);
    if (reconnectAttempts >= 10) { toast('Connexion perdue', 'error'); return; }
    reconnectTimer = setTimeout(connectWS, Math.min(1000 * Math.pow(2, reconnectAttempts++), 30000));
}

function sendWS(data) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(data));
}

function onMessage(msg) {
    switch (msg.type) {
        case 'game_update':
        case 'game_state':
            if (msg.is_spectator !== undefined) isSpectator = msg.is_spectator;
            gameState = msg.data || msg;
            if (msg.quick_bets) currentQuickBets = msg.quick_bets;
            render(gameState);
            break;
        case 'hole_cards':
            // Per-player hole cards (sécurité)
            if (gameState) {
                const me = gameState.players?.find(p => p.user_id === currentUser?.id);
                if (me) me.hole_cards = msg.cards;
                updateMyCards();
            }
            break;
        case 'community_cards':
            if (gameState) gameState.community_cards = msg.cards;
            updateCommunityCards(msg.cards);
            if (typeof SoundManager !== 'undefined') SoundManager.play('flip');
            break;
        case 'player_action':
            if (typeof SoundManager !== 'undefined') {
                if (['call', 'raise', 'all-in'].includes(msg.action)) SoundManager.play('bet');
            }
            toast(`${msg.username || msg.user_id}: ${msg.action} ${msg.amount ? msg.amount : ''}`, 'info');
            break;
        case 'hand_result':
            handleHandResult(msg);
            break;
        case 'deck_commitment':
            if ($('deckStatus')) $('deckStatus').textContent = '🔒 Committed';
            break;
        case 'deck_reveal':
            if ($('deckStatus')) $('deckStatus').textContent = '✅ Verified';
            break;
        case 'connected': break;
        case 'reconnected': toast('Reconnecté!', 'success'); break;
        case 'tournament_level_change':
            toast(`Niveau ${msg.level}: ${msg.small_blind}/${msg.big_blind}`, 'info');
            break;
        case 'tournament_player_eliminated':
            toast(`${msg.username || '?'} éliminé (#${msg.rank})`, 'info');
            break;
        case 'table_chat':
            appendChatMessage(msg.username, msg.message);
            break;
        case 'ping':
            sendWS({ type: 'pong' });
            break;
        case 'error':
            toast(msg.message || 'Erreur', 'error');
            break;
    }
}

// ══════════════════════════════════════════════════════════════════════════════
// Render
// ══════════════════════════════════════════════════════════════════════════════
function render(state) {
    if (!state) return;
    gameState = state;

    renderPlayers(state);
    updateCommunityCards(state.community_cards || []);
    updatePot(state.pot || 0);
    updateGameInfo(state);
    updateActions(state);
    updateMyCards();
    updateActionTimer(state);
    updateQuickBetsUI(state);

    // Spectateur
    const banner = $('spectatorBanner');
    if (banner) banner.style.display = isSpectator ? 'block' : 'none';
}

function renderPlayers(state) {
    const container = $('playersContainer');
    if (!container) return;
    container.innerHTML = '';

    const players = state.players || [];
    const positions = getPositions(players.length, state.max_players || 9);

    players.forEach((p, i) => {
        const el = document.createElement('div');
        el.className = `player-seat ${p.status || ''} ${p.user_id === state.current_actor ? 'active-player' : ''}`;
        const pos = positions[i] || { top: '50%', left: '50%' };
        el.style.top = pos.top;
        el.style.left = pos.left;

        const stack = formatStack(p.chips || p.stack || 0);
        const betDisplay = p.current_bet > 0 ? `<div class="player-bet-chip">${p.current_bet}</div>` : '';
        const roleTag = p.is_dealer ? '<span class="role-tag dealer">D</span>' :
                        p.is_small_blind ? '<span class="role-tag sb">SB</span>' :
                        p.is_big_blind ? '<span class="role-tag bb">BB</span>' : '';

        const cardsHtml = (p.hole_cards && p.hole_cards.length > 0)
            ? p.hole_cards.map(c => typeof CardsModule !== 'undefined' ? CardsModule.renderCard(c, false) : `<div class="mini-card">${c}</div>`).join('')
            : (p.status === 'active' || p.status === 'all_in' ? '<div class="mini-card back"></div><div class="mini-card back"></div>' : '');

        const lastAction = p.last_action ? `<div class="last-action">${p.last_action}</div>` : '';

        el.innerHTML = `
            <div class="player-avatar">
                <img src="${p.avatar || '/assets/avatars/default.svg'}" alt="${p.username}" onerror="this.src='/assets/avatars/default.svg'">
                ${roleTag}
            </div>
            <div class="player-name">${escapeHtml(p.username)}</div>
            <div class="player-stack">${stack}</div>
            <div class="player-cards">${cardsHtml}</div>
            ${betDisplay}
            ${lastAction}
        `;
        container.appendChild(el);
    });
}

function getPositions(count, max) {
    // Positions autour de l'ovale
    const positions = [];
    for (let i = 0; i < count; i++) {
        const angle = (i / Math.max(count, max)) * 2 * Math.PI - Math.PI / 2;
        const rx = 45, ry = 40;
        positions.push({
            top: `${50 + ry * Math.sin(angle)}%`,
            left: `${50 + rx * Math.cos(angle)}%`,
        });
    }
    return positions;
}

function updateCommunityCards(cards) {
    const container = $('communityCards');
    if (!container) return;
    container.innerHTML = '';
    if (!cards?.length) return;
    cards.forEach(c => {
        if (typeof CardsModule !== 'undefined') {
            container.innerHTML += CardsModule.renderCard(c, false);
        } else {
            const el = document.createElement('div');
            el.className = 'community-card';
            el.textContent = c;
            container.appendChild(el);
        }
    });
}

function updatePot(pot) {
    const el = $('potDisplay');
    if (el) el.textContent = `Pot: ${pot.toLocaleString()}`;
}

function updateMyCards() {
    const container = $('myCardsContainer');
    if (!container || !currentUser) return;
    const myPlayer = gameState?.players?.find(p => p.user_id === currentUser.id);
    if (!myPlayer?.hole_cards?.length) {
        container.classList.add('hidden');
        return;
    }
    container.classList.remove('hidden');
    container.innerHTML = myPlayer.hole_cards
        .map(c => typeof CardsModule !== 'undefined' ? CardsModule.renderCard(c, false) : `<div class="my-card">${c}</div>`)
        .join('');
}

function updateGameInfo(state) {
    const set = (id, text) => { const el = $(id); if (el) el.textContent = text; };
    set('handNumber', `#${state.round || 0}`);
    set('gameVariant', state.game_variant === 'plo' ? 'PLO' : "Hold'em");
    const streets = { preflop: 'Preflop', flop: 'Flop', turn: 'Turn', river: 'River', showdown: 'Showdown' };
    set('bettingRound', streets[state.betting_round] || state.betting_round || '');
    set('gameBlinds', `${state.small_blind}/${state.big_blind}`);
    const alive = state.players?.filter(p => !['folded', 'eliminated'].includes(p.status)).length || 0;
    set('playersAlive', String(alive));
    const me = state.players?.find(p => p.user_id === currentUser?.id);
    set('myChipsInfo', me ? formatStack(me.chips || me.stack || 0) : '—');
}

// ══════════════════════════════════════════════════════════════════════════════
// Actions
// ══════════════════════════════════════════════════════════════════════════════
function setupActions() {
    $('foldBtn')?.addEventListener('click', () => doAction('fold'));
    $('checkBtn')?.addEventListener('click', () => doAction('check'));
    $('callBtn')?.addEventListener('click', () => doAction('call'));
    $('raiseBtn')?.addEventListener('click', () => showRaiseSlider());
    $('confirmRaise')?.addEventListener('click', confirmRaise);
    $('cancelRaise')?.addEventListener('click', hideRaiseSlider);

    const slider = $('raiseAmount');
    const input = $('raiseValue');
    if (slider && input) {
        slider.addEventListener('input', () => { input.value = slider.value; });
        input.addEventListener('input', () => { slider.value = input.value; });
    }
}

function updateActions(state) {
    const isMyTurn = state.current_actor === currentUser?.id;
    const me = state.players?.find(p => p.user_id === currentUser?.id);

    $('foldBtn').disabled = !isMyTurn;
    $('checkBtn').disabled = !isMyTurn;
    $('raiseBtn').disabled = !isMyTurn;

    // Check vs Call
    if (me && state.current_bet > (me.current_bet || 0)) {
        $('checkBtn').style.display = 'none';
        $('callBtn').style.display = '';
        $('callBtn').disabled = !isMyTurn;
        const toCall = Math.min(state.current_bet - (me.current_bet || 0), me.chips || 0);
        $('callBtn').textContent = `Call ${toCall} (C)`;
    } else {
        $('checkBtn').style.display = '';
        $('callBtn').style.display = 'none';
    }

    // Slider range
    if (me && isMyTurn) {
        const slider = $('raiseAmount');
        if (slider) {
            slider.min = state.min_raise || state.big_blind || 10;
            slider.max = me.chips || 1000;
            slider.value = Math.max(Number(slider.min), Number(slider.value));
        }
    }
}

function doAction(action, amount = 0) {
    sendWS({ type: 'action', action, amount });
    hideRaiseSlider();
    if (typeof SoundManager !== 'undefined') SoundManager.play('chip');
}

function showRaiseSlider() {
    const el = $('raiseSlider');
    if (el) el.style.display = 'flex';
}

function hideRaiseSlider() {
    const el = $('raiseSlider');
    if (el) el.style.display = 'none';
}

function confirmRaise() {
    const amount = parseInt($('raiseValue')?.value || $('raiseAmount')?.value || 0);
    if (amount > 0) doAction('raise', amount);
}

// ══════════════════════════════════════════════════════════════════════════════
// Quick Bets
// ══════════════════════════════════════════════════════════════════════════════
function setupQuickBets() {
    document.querySelectorAll('.qb-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const key = btn.dataset.key;
            const bet = currentQuickBets.find(b => b.key === key);
            if (bet) {
                if (key === 'allin') {
                    doAction('all_in', bet.amount);
                } else {
                    doAction('raise', bet.amount);
                }
            }
        });
    });
}

function updateQuickBetsUI(state) {
    const container = $('quickBets');
    if (!container) return;
    const isMyTurn = state.current_actor === currentUser?.id;
    container.style.display = isMyTurn ? 'flex' : 'none';

    if (!isMyTurn || !currentQuickBets?.length) return;

    document.querySelectorAll('.qb-btn').forEach(btn => {
        const key = btn.dataset.key;
        const bet = currentQuickBets.find(b => b.key === key);
        if (bet) {
            btn.style.display = '';
            btn.textContent = `${bet.label} (${bet.amount})`;
        } else {
            btn.style.display = 'none';
        }
    });
}

// ══════════════════════════════════════════════════════════════════════════════
// Timer
// ══════════════════════════════════════════════════════════════════════════════
function updateActionTimer(state) {
    const timerEl = $('actionTimer');
    if (!state.current_actor || state.action_timer == null) {
        if (timerEl) timerEl.classList.add('hidden');
        if (typeof TimerModule !== 'undefined') TimerModule.stop();
        return;
    }
    if (timerEl) timerEl.classList.remove('hidden');
    const total = state.action_timeout_total || 20;
    const remaining = state.action_timer;
    if (typeof TimerModule !== 'undefined') {
        TimerModule.start(remaining, total, (secs) => {
            if (timerEl) timerEl.textContent = `⏱ ${secs}s`;
        });
    } else if (timerEl) {
        timerEl.textContent = `⏱ ${remaining}s`;
    }
}

// ══════════════════════════════════════════════════════════════════════════════
// Hand Result
// ══════════════════════════════════════════════════════════════════════════════
function handleHandResult(msg) {
    if (typeof SoundManager !== 'undefined') SoundManager.play('win');
    const winners = msg.winners || [];
    const names = winners.map(w => `${w.username} (${w.hand || '?'})`).join(', ');
    toast(`Gagnant: ${names} — Pot: ${msg.pot}`, 'success');

    // Showdown cards
    if (msg.showdown) {
        msg.showdown.forEach(p => {
            // Mettre à jour les cartes visibles
            if (gameState?.players) {
                const gp = gameState.players.find(x => x.user_id === p.user_id);
                if (gp) gp.hole_cards = p.hole_cards;
            }
        });
        if (gameState) render(gameState);
    }

    if (typeof HandHistory !== 'undefined') {
        HandHistory.add({
            round: gameState?.round || 0,
            winners, pot: msg.pot,
            community: msg.community_cards || [],
        });
    }
}

// ══════════════════════════════════════════════════════════════════════════════
// Chat
// ══════════════════════════════════════════════════════════════════════════════
function setupChat() {
    const input = $('tableChatInput');
    const btn = $('tableChatSend');
    if (!input || !btn) return;
    if (currentUser) { input.disabled = false; btn.disabled = false; }

    const send = () => {
        const text = input.value.trim();
        if (!text) return;
        sendWS({ type: 'chat', message: text });
        input.value = '';
    };
    btn.addEventListener('click', send);
    input.addEventListener('keypress', (e) => { if (e.key === 'Enter') send(); });
}

function appendChatMessage(username, message) {
    const container = $('tableChatMessages');
    if (!container) return;
    const div = document.createElement('div');
    div.className = 'tchat-msg';
    div.innerHTML = `<strong>${escapeHtml(username)}</strong>: ${escapeHtml(message)}`;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

// ══════════════════════════════════════════════════════════════════════════════
// Theme Modal
// ══════════════════════════════════════════════════════════════════════════════
function setupThemeModal() {
    const btn = $('themeToggleBtn');
    const modal = $('themeModal');
    if (!btn || !modal) return;

    btn.addEventListener('click', () => { modal.style.display = 'flex'; });
    modal.querySelector('.close')?.addEventListener('click', () => { modal.style.display = 'none'; });
    modal.addEventListener('click', (e) => { if (e.target === modal) modal.style.display = 'none'; });

    $('applyTheme')?.addEventListener('click', () => {
        const theme = $('themeSelect')?.value || 'dark';
        const cardDeck = $('cardDeckSelect')?.value || 'standard';
        const tableStyle = $('tableStyleSelect')?.value || 'felt';

        if (typeof ThemeManager !== 'undefined') ThemeManager.setTheme(theme);
        if (typeof CardsModule !== 'undefined') CardsModule.setDeck(cardDeck);
        document.body.setAttribute('data-table-style', tableStyle);

        try {
            localStorage.setItem('poker_visual_prefs', JSON.stringify({ theme, cardDeck, tableStyle }));
        } catch (e) {}

        modal.style.display = 'none';
        toast('Thème appliqué', 'success');
    });

    // Charger les préférences
    try {
        const prefs = JSON.parse(localStorage.getItem('poker_visual_prefs') || '{}');
        if (prefs.theme && typeof ThemeManager !== 'undefined') ThemeManager.setTheme(prefs.theme);
        if (prefs.cardDeck && typeof CardsModule !== 'undefined') CardsModule.setDeck(prefs.cardDeck);
        if (prefs.tableStyle) document.body.setAttribute('data-table-style', prefs.tableStyle);
        if (prefs.theme) { const el = $('themeSelect'); if (el) el.value = prefs.theme; }
        if (prefs.cardDeck) { const el = $('cardDeckSelect'); if (el) el.value = prefs.cardDeck; }
        if (prefs.tableStyle) { const el = $('tableStyleSelect'); if (el) el.value = prefs.tableStyle; }
    } catch (e) {}
}

// ══════════════════════════════════════════════════════════════════════════════
// Keyboard Shortcuts
// ══════════════════════════════════════════════════════════════════════════════
function setupKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
        const isMyTurn = gameState?.current_actor === currentUser?.id;
        if (!isMyTurn) return;

        switch (e.key.toLowerCase()) {
            case 'f': doAction('fold'); break;
            case 'c':
                if ($('callBtn')?.style.display !== 'none') doAction('call');
                else doAction('check');
                break;
            case 'r': showRaiseSlider(); break;
            case 'escape': hideRaiseSlider(); break;
        }
    });
}

// ══════════════════════════════════════════════════════════════════════════════
// Utilities
// ══════════════════════════════════════════════════════════════════════════════
function formatStack(amount) {
    if (amount == null) return '0';
    if (showStacksInBB && gameState?.big_blind) {
        return `${(amount / gameState.big_blind).toFixed(1)} BB`;
    }
    return amount.toLocaleString();
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function toast(message, type = 'info') {
    let container = $('toastContainer') || (() => {
        const c = document.createElement('div');
        c.id = 'toastContainer';
        c.className = 'toast-container';
        document.body.appendChild(c);
        return c;
    })();
    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    el.textContent = message;
    container.appendChild(el);
    setTimeout(() => el.classList.add('show'), 10);
    setTimeout(() => { el.classList.remove('show'); setTimeout(() => el.remove(), 300); }, 3000);
}

// ══════════════════════════════════════════════════════════════════════════════
// Start
// ══════════════════════════════════════════════════════════════════════════════
document.addEventListener('DOMContentLoaded', init);
