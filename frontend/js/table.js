/**
 * table.js — Page de table de poker
 * Version corrigée — spectateurs, reconnexion, actions
 */

'use strict';

let ws = null;
let gameState = null;
let actionTimeout = null;
let currentUser = null;
let isSpectator = false;
let reconnectTimer = null;
let reconnectAttempts = 0;
const MAX_RECONNECT = 10;

const tableId = window.tableId;
const tableName = window.tableName;

// ═════════════════════════════════════════════════════════════════════════════
// Init
// ═════════════════════════════════════════════════════════════════════════════

async function init() {
    console.log('Initializing table page...', { tableId, tableName });

    // Charger l'utilisateur — compatible avec lobby.js et api.js
    await loadCurrentUser();

    const urlParams = new URLSearchParams(window.location.search);
    isSpectator = urlParams.get('spectate') === 'true' || !currentUser;

    if (isSpectator) {
        document.getElementById('actionPanel').style.display = 'none';
        document.getElementById('spectatorBanner').style.display = 'block';
    }

    const tableNameEl = document.getElementById('tableName');
    if (tableNameEl) tableNameEl.textContent = tableName || 'Table';

    connectWebSocket();
    setupEventListeners();
}

async function loadCurrentUser() {
    // D'abord essayer /api/auth/me (méthode correcte avec cookies)
    try {
        const response = await fetch('/api/auth/me');
        if (response.ok) {
            const data = await response.json();
            if (data && data.id) {
                currentUser = data;
                window.currentUser = data;
                return;
            }
        }
    } catch (_) { }

    // Fallback : window.initCurrentUser si disponible
    if (typeof window.initCurrentUser === 'function') {
        try {
            await window.initCurrentUser();
            currentUser = window.currentUser;
            return;
        } catch (_) { }
    }

    // Pas connecté
    currentUser = null;
    window.currentUser = null;
}

// ═════════════════════════════════════════════════════════════════════════════
// WebSocket
// ═════════════════════════════════════════════════════════════════════════════

function connectWebSocket() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
        return;
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const userId = currentUser?.id || 'spectator';
    const wsUrl = `${protocol}//${window.location.host}/ws/${tableId}/${userId}`;

    console.log('Connecting to table WS:', wsUrl);
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        console.log('Table WS connected');
        reconnectAttempts = 0;
        if (!isSpectator) {
            showToast('Connected to table', 'success');
        }
    };

    ws.onmessage = (event) => {
        try {
            const message = JSON.parse(event.data);
            handleWebSocketMessage(message);
        } catch (e) {
            console.error('Error parsing WS message:', e);
        }
    };

    ws.onclose = (event) => {
        console.log('Table WS disconnected', event.code);
        if (!isSpectator) {
            showToast('Disconnected from table', 'error');
        }
        scheduleReconnect();
    };

    ws.onerror = (error) => {
        console.error('Table WS error:', error);
    };
}

function scheduleReconnect() {
    if (reconnectTimer) clearTimeout(reconnectTimer);
    if (reconnectAttempts >= MAX_RECONNECT) {
        showToast('Connection lost. Please refresh the page.', 'error');
        return;
    }
    const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 30000);
    reconnectAttempts++;
    console.log(`Reconnecting in ${delay}ms (attempt ${reconnectAttempts})`);
    reconnectTimer = setTimeout(connectWebSocket, delay);
}

// ═════════════════════════════════════════════════════════════════════════════
// Message handling
// ═════════════════════════════════════════════════════════════════════════════

function handleWebSocketMessage(message) {
    switch (message.type) {
        case 'game_update':
        case 'game_state':
            updateGameState(message.data || message);
            break;
        case 'reconnected':
            showToast('Reconnected successfully!', 'success');
            break;
        case 'player_connected':
            showToast(`Player connected`, 'info');
            break;
        case 'player_disconnected':
            showToast(`Player disconnected`, 'info');
            break;
        case 'blind_level_change':
            showToast(`Blind Level ${message.level}: ${message.small_blind}/${message.big_blind}`, 'info');
            break;
        case 'player_eliminated':
            showToast(`${message.username} eliminated (#${message.rank})`, 'info');
            break;
        case 'error':
            showToast(message.message || 'Error', 'error');
            break;
        case 'pong':
            break;
        default:
            console.log('Unknown WS message type:', message.type);
    }
}

// ═════════════════════════════════════════════════════════════════════════════
// Game state rendering
// ═════════════════════════════════════════════════════════════════════════════

function updateGameState(state) {
    gameState = state;
    if (!state) return;

    updatePot(state.pot);
    updateCommunityCards(state.community_cards);
    updatePlayers(state.players);
    updateGameInfo(state);

    // Actions (seulement si joueur, pas spectateur)
    if (!isSpectator && currentUser) {
        const myIdx = state.current_player_index;
        const players = state.players || [];
        const isMyTurn = players[myIdx]?.user_id === currentUser.id && state.status === 'in_progress';
        updateActionButtons(isMyTurn, state);
    }
}

function updatePot(pot) {
    const potEl = document.getElementById('pot');
    if (potEl) potEl.textContent = `Pot: ${(pot || 0).toLocaleString()}`;
}

function updateCommunityCards(cards) {
    const cardIds = ['flop1', 'flop2', 'flop3', 'turn', 'river'];
    cardIds.forEach((id, i) => {
        const el = document.getElementById(id);
        if (!el) return;
        if (cards && cards[i]) {
            el.className = 'card';
            el.innerHTML = renderCard(cards[i]);
        } else {
            el.className = 'card back';
            el.innerHTML = '';
        }
    });
}

function renderCard(cardStr) {
    if (!cardStr || cardStr === 'back') return '';
    // Format: "14h" = Ace of hearts, "13s" = King of spades
    const rank = cardStr.slice(0, -1);
    const suit = cardStr.slice(-1);
    const suitSymbol = getSuitSymbol(suit);
    const suitClass = getSuitClass(suit);
    const rankDisplay = getRankDisplay(rank);
    return `<span class="card-face ${suitClass}">${rankDisplay}${suitSymbol}</span>`;
}

function updatePlayers(players) {
    const container = document.getElementById('playersContainer');
    if (!container || !players) return;

    container.innerHTML = '';

    const positions = getPositions(players.length);

    players.forEach((player, index) => {
        const pos = positions[index] || { top: '50%', left: '50%' };
        const isMe = player.user_id === currentUser?.id;
        const isActive = player.status === 'active' || player.status === 'all_in';
        const isCurrent = gameState?.players?.[gameState.current_player_index]?.user_id === player.user_id;

        const playerDiv = document.createElement('div');
        playerDiv.className = `player-seat ${isMe ? 'me' : ''} ${!isActive ? 'folded' : ''} ${isCurrent ? 'active-turn' : ''}`;
        playerDiv.style.cssText = `position:absolute;top:${pos.top};left:${pos.left};transform:translate(-50%,-50%)`;

        // Cartes (masquées pour les autres sauf si showdown)
        let cardsHtml = '';
        if (player.hole_cards && player.hole_cards.length > 0) {
            cardsHtml = `<div class="player-cards">
                ${player.hole_cards.map(c => `<div class="mini-card ${getSuitClass(c.slice(-1))}">${getRankDisplay(c.slice(0, -1))}${getSuitSymbol(c.slice(-1))}</div>`).join('')}
            </div>`;
        } else if (isActive && gameState?.status === 'in_progress') {
            cardsHtml = `<div class="player-cards"><div class="mini-card back"></div><div class="mini-card back"></div></div>`;
        }

        playerDiv.innerHTML = `
            ${cardsHtml}
            <div class="player-info-box">
                <div class="player-name" title="${escapeHtml(player.username)}">${escapeHtml(player.username)}</div>
                <div class="player-chips">${(player.chips ?? 0).toLocaleString()}</div>
            </div>
            ${player.current_bet > 0 ? `<div class="player-bet">Bet: ${player.current_bet}</div>` : ''}
            ${player.is_dealer ? '<div class="dealer-button-marker">D</div>' : ''}
            ${player.is_small_blind ? '<div class="blind-marker">SB</div>' : ''}
            ${player.is_big_blind ? '<div class="blind-marker">BB</div>' : ''}
            ${player.status === 'all_in' ? '<div class="allin-marker">ALL IN</div>' : ''}
        `;

        container.appendChild(playerDiv);
    });

    // Update player info panel
    if (currentUser) {
        const me = players.find(p => p.user_id === currentUser.id);
        if (me) {
            const chipsEl = document.getElementById('playerChips');
            const betEl = document.getElementById('playerBet');
            if (chipsEl) chipsEl.textContent = `${(me.chips ?? 0).toLocaleString()} chips`;
            if (betEl) betEl.textContent = `Bet: ${me.current_bet || 0}`;
        }
    }
}

function getPositions(count) {
    // Positions circulaires autour de la table
    const layouts = {
        2: [{ top: '85%', left: '50%' }, { top: '15%', left: '50%' }],
        3: [{ top: '85%', left: '50%' }, { top: '30%', left: '15%' }, { top: '30%', left: '85%' }],
        4: [{ top: '85%', left: '50%' }, { top: '50%', left: '10%' }, { top: '15%', left: '50%' }, { top: '50%', left: '90%' }],
        5: [{ top: '85%', left: '50%' }, { top: '65%', left: '10%' }, { top: '20%', left: '20%' }, { top: '20%', left: '80%' }, { top: '65%', left: '90%' }],
        6: [{ top: '85%', left: '50%' }, { top: '65%', left: '10%' }, { top: '25%', left: '10%' }, { top: '15%', left: '50%' }, { top: '25%', left: '90%' }, { top: '65%', left: '90%' }],
        7: [{ top: '85%', left: '50%' }, { top: '70%', left: '8%' }, { top: '35%', left: '8%' }, { top: '10%', left: '30%' }, { top: '10%', left: '70%' }, { top: '35%', left: '92%' }, { top: '70%', left: '92%' }],
        8: [{ top: '85%', left: '50%' }, { top: '70%', left: '8%' }, { top: '40%', left: '5%' }, { top: '15%', left: '25%' }, { top: '15%', left: '50%' }, { top: '15%', left: '75%' }, { top: '40%', left: '95%' }, { top: '70%', left: '92%' }],
        9: [{ top: '85%', left: '50%' }, { top: '75%', left: '8%' }, { top: '50%', left: '5%' }, { top: '25%', left: '8%' }, { top: '10%', left: '30%' }, { top: '10%', left: '70%' }, { top: '25%', left: '92%' }, { top: '50%', left: '95%' }, { top: '75%', left: '92%' }],
    };
    return layouts[count] || layouts[9] || [];
}

function updateGameInfo(state) {
    const statusSpan = document.getElementById('gameStatus');
    const roundSpan = document.getElementById('gameRound');
    const bettingRoundSpan = document.getElementById('bettingRound');

    const statusMap = {
        'waiting': 'Waiting for players',
        'in_progress': 'In Game',
        'finished': 'Hand Complete',
        'showdown': 'Showdown',
    };

    if (statusSpan) statusSpan.textContent = statusMap[state.status] || state.status || 'Unknown';
    if (roundSpan) roundSpan.textContent = state.round || 0;
    if (bettingRoundSpan) bettingRoundSpan.textContent = state.betting_round || 'Preflop';
}

function updateActionButtons(isMyTurn, state) {
    const panel = document.getElementById('actionPanel');
    const foldBtn = document.getElementById('foldBtn');
    const checkBtn = document.getElementById('checkBtn');
    const callBtn = document.getElementById('callBtn');
    const raiseBtn = document.getElementById('raiseBtn');

    if (!isMyTurn || state.status !== 'in_progress') {
        if (panel) panel.style.display = 'none';
        return;
    }

    if (panel) panel.style.display = 'flex';

    const myPlayer = state.players?.find(p => p.user_id === currentUser?.id);
    const toCall = (state.current_bet || 0) - (myPlayer?.current_bet || 0);

    if (toCall <= 0) {
        if (checkBtn) { checkBtn.style.display = 'block'; checkBtn.textContent = 'Check'; }
        if (callBtn) callBtn.style.display = 'none';
    } else {
        if (checkBtn) checkBtn.style.display = 'none';
        if (callBtn) {
            callBtn.style.display = 'block';
            callBtn.textContent = toCall >= (myPlayer?.chips || 0) ? `All-In ${myPlayer?.chips}` : `Call ${toCall}`;
        }
    }

    const canRaise = (myPlayer?.chips || 0) > toCall;
    if (raiseBtn) raiseBtn.disabled = !canRaise;
    if (foldBtn) foldBtn.disabled = false;
}

// ═════════════════════════════════════════════════════════════════════════════
// Actions
// ═════════════════════════════════════════════════════════════════════════════

function sendAction(action, amount = 0) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'action', action, amount }));
    } else {
        showToast('Not connected to server', 'error');
    }
}

function setupEventListeners() {
    const foldBtn = document.getElementById('foldBtn');
    const checkBtn = document.getElementById('checkBtn');
    const callBtn = document.getElementById('callBtn');
    const raiseBtn = document.getElementById('raiseBtn');
    const leaveBtn = document.getElementById('leaveTableBtn');
    const raiseAmount = document.getElementById('raiseAmount');
    const raiseValue = document.getElementById('raiseValue');
    const confirmRaise = document.getElementById('confirmRaise');
    const cancelRaise = document.getElementById('cancelRaise');

    if (foldBtn) foldBtn.onclick = () => sendAction('fold');
    if (checkBtn) checkBtn.onclick = () => sendAction('check');
    if (callBtn) callBtn.onclick = () => sendAction('call');

    if (raiseBtn) {
        raiseBtn.onclick = () => {
            const slider = document.getElementById('raiseSlider');
            if (slider) slider.style.display = 'block';
            if (raiseAmount && gameState) {
                const minRaise = gameState.min_raise || 10;
                const myPlayer = gameState.players?.find(p => p.user_id === currentUser?.id);
                const maxRaise = myPlayer?.chips || 1000;
                raiseAmount.min = minRaise;
                raiseAmount.max = maxRaise;
                raiseAmount.value = minRaise;
                if (raiseValue) raiseValue.textContent = minRaise;
            }
        };
    }

    if (raiseAmount) {
        raiseAmount.oninput = (e) => {
            if (raiseValue) raiseValue.textContent = e.target.value;
        };
    }

    if (confirmRaise) {
        confirmRaise.onclick = () => {
            const amount = raiseAmount ? parseInt(raiseAmount.value) : 100;
            sendAction('raise', amount);
            const slider = document.getElementById('raiseSlider');
            if (slider) slider.style.display = 'none';
        };
    }

    if (cancelRaise) {
        cancelRaise.onclick = () => {
            const slider = document.getElementById('raiseSlider');
            if (slider) slider.style.display = 'none';
        };
    }

    if (leaveBtn) {
        leaveBtn.onclick = async () => {
            if (confirm('Are you sure you want to leave the table?')) {
                if (!isSpectator && currentUser) {
                    try {
                        await fetch(`/api/tables/${tableId}/leave?user_id=${currentUser.id}`, { method: 'POST' });
                    } catch (_) { }
                }
                window.location.href = '/lobby';
            }
        };
    }

    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        const panel = document.getElementById('actionPanel');
        if (!panel || panel.style.display === 'none' || isSpectator) return;
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

        if (e.key === 'f' || e.key === 'F') {
            e.preventDefault();
            sendAction('fold');
        } else if (e.key === 'c' || e.key === 'C') {
            e.preventDefault();
            const myPlayer = gameState?.players?.find(p => p.user_id === currentUser?.id);
            const toCall = (gameState?.current_bet || 0) - (myPlayer?.current_bet || 0);
            sendAction(toCall <= 0 ? 'check' : 'call');
        } else if (e.key === 'r' || e.key === 'R') {
            e.preventDefault();
            const raiseBtn2 = document.getElementById('raiseBtn');
            if (raiseBtn2 && !raiseBtn2.disabled) raiseBtn2.click();
        }
    });

    // Ping keep-alive
    setInterval(() => {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping' }));
        }
    }, 30000);
}

// ═════════════════════════════════════════════════════════════════════════════
// Utilities
// ═════════════════════════════════════════════════════════════════════════════

function showToast(message, type = 'info') {
    let toast = document.getElementById('toast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'toast';
        toast.className = 'toast';
        document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.className = `toast ${type} show`;
    setTimeout(() => toast.classList.remove('show'), 3000);
}

function getSuitSymbol(suit) {
    return { 'h': '♥', 'd': '♦', 'c': '♣', 's': '♠' }[suit] || suit;
}

function getSuitClass(suit) {
    return { 'h': 'heart', 'd': 'diamond', 'c': 'club', 's': 'spade' }[suit] || '';
}

function getRankDisplay(rank) {
    const r = parseInt(rank);
    if (r === 14 || r === 1) return 'A';
    if (r === 13) return 'K';
    if (r === 12) return 'Q';
    if (r === 11) return 'J';
    return r;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text ?? '';
    return div.innerHTML;
}

// Start
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
