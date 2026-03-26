// frontend/js/table.js
let ws = null;
let gameState = null;
let actionTimeout = null;
let currentUser = null;
let isSpectator = false;

const tableId = window.tableId;
const tableName = window.tableName;

async function init() {
    console.log('Initializing table page...');
    
    await window.initCurrentUser();
    currentUser = window.currentUser;
    
    const urlParams = new URLSearchParams(window.location.search);
    isSpectator = urlParams.get('spectate') === 'true';
    
    if (!currentUser || isSpectator) {
        document.getElementById('actionPanel').style.display = 'none';
        document.getElementById('spectatorBanner').style.display = 'block';
    }
    
    document.getElementById('tableName').textContent = tableName;
    
    connectWebSocket();
    setupEventListeners();
}

function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/${tableId}/${currentUser?.id || 'spectator'}`;
    
    ws = new WebSocket(wsUrl);
    
    ws.onopen = () => {
        console.log('WebSocket connected');
        if (!isSpectator) {
            showToast('Connected to table', 'success');
        }
    };
    
    ws.onmessage = (event) => {
        try {
            const message = JSON.parse(event.data);
            handleWebSocketMessage(message);
        } catch (e) {
            console.error('Error parsing message:', e);
        }
    };
    
    ws.onclose = () => {
        console.log('WebSocket disconnected');
        if (!isSpectator) {
            showToast('Disconnected from table', 'error');
            setTimeout(connectWebSocket, 3000);
        }
    };
}

function handleWebSocketMessage(message) {
    switch (message.type) {
        case 'game_update':
        case 'game_state':
            updateGameState(message.data || message);
            break;
        case 'error':
            showToast(message.message, 'error');
            break;
    }
}

function updateGameState(state) {
    gameState = state;
    if (!state) return;
    
    updatePot(state.pot);
    updateCommunityCards(state.community_cards);
    updatePlayers(state.players);
    updateGameInfo(state);
    
    if (!isSpectator) {
        const isMyTurn = state.current_player === currentUser?.id;
        updateActionButtons(isMyTurn, state);
    }
}

function updatePot(pot) {
    const potElement = document.getElementById('pot');
    if (potElement) potElement.textContent = `Pot: ${pot} chips`;
}

function updateCommunityCards(cards) {
    const container = document.getElementById('communityCards');
    if (!container) return;
    
    const positions = ['flop1', 'flop2', 'flop3', 'turn', 'river'];
    
    for (let i = 0; i < positions.length; i++) {
        const cardDiv = document.getElementById(positions[i]);
        if (cards && cards[i]) {
            const card = cards[i];
            const suit = getSuitSymbol(card[0]);
            const rank = getRankDisplay(card.substring(1));
            const suitClass = getSuitClass(card[0]);
            cardDiv.className = `card ${suitClass}`;
            cardDiv.innerHTML = `${rank}${suit}`;
        } else {
            cardDiv.className = 'card back';
            cardDiv.innerHTML = '';
        }
    }
}

function updatePlayers(players) {
    const container = document.getElementById('playersContainer');
    if (!container) return;
    
    container.innerHTML = '';
    
    const radius = 280;
    const centerX = 350;
    const centerY = 280;
    const angleStep = (2 * Math.PI) / players.length;
    
    players.forEach((player, index) => {
        let angle = index * angleStep - Math.PI / 2;
        const x = centerX + radius * Math.cos(angle);
        const y = centerY + radius * Math.sin(angle);
        
        const playerDiv = document.createElement('div');
        playerDiv.className = 'player-seat';
        if (player.user_id === currentUser?.id) {
            playerDiv.classList.add('current-player');
        }
        if (player.is_dealer) {
            playerDiv.classList.add('dealer');
        }
        playerDiv.style.left = `${x}px`;
        playerDiv.style.top = `${y}px`;
        
        const avatarUrl = `/assets/images/avatars/${player.avatar || 'default'}.svg`;
        
        playerDiv.innerHTML = `
            <div class="player-avatar" style="background-image: url('${avatarUrl}');"></div>
            <div class="player-name">${escapeHtml(player.username)}</div>
            <div class="player-chips">💰 ${player.chips}</div>
            ${player.current_bet > 0 ? `<div class="player-bet">Bet: ${player.current_bet}</div>` : ''}
            <div class="player-cards">
                ${player.hole_cards && player.user_id === currentUser?.id ? 
                    player.hole_cards.map(card => {
                        const suit = getSuitSymbol(card[0]);
                        const rank = getRankDisplay(card.substring(1));
                        const suitClass = getSuitClass(card[0]);
                        return `<div class="card ${suitClass}">${rank}${suit}</div>`;
                    }).join('') : 
                    '<div class="card back"></div><div class="card back"></div>'
                }
            </div>
            ${player.is_dealer ? '<div class="dealer-button-marker">D</div>' : ''}
            ${player.is_small_blind ? '<div class="blind-marker">SB</div>' : ''}
            ${player.is_big_blind ? '<div class="blind-marker">BB</div>' : ''}
        `;
        
        container.appendChild(playerDiv);
    });
}

function updateGameInfo(state) {
    const statusSpan = document.getElementById('gameStatus');
    const roundSpan = document.getElementById('gameRound');
    const bettingRoundSpan = document.getElementById('bettingRound');
    
    if (statusSpan) statusSpan.textContent = state.status === 'in_progress' ? 'In Game' : state.status;
    if (roundSpan) roundSpan.textContent = state.round;
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
    
    const currentPlayer = state.players?.find(p => p.user_id === currentUser?.id);
    const toCall = (state.current_bet || 0) - (currentPlayer?.current_bet || 0);
    
    if (toCall === 0) {
        if (checkBtn) checkBtn.style.display = 'block';
        if (callBtn) callBtn.style.display = 'none';
    } else {
        if (checkBtn) checkBtn.style.display = 'none';
        if (callBtn) {
            callBtn.style.display = 'block';
            callBtn.textContent = `Call ${toCall}`;
        }
    }
    
    const canRaise = currentPlayer?.chips > toCall;
    if (raiseBtn) raiseBtn.disabled = !canRaise;
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
                raiseAmount.min = minRaise;
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
                    await fetch(`/api/tables/${tableId}/leave?user_id=${currentUser.id}`, {
                        method: 'POST'
                    });
                }
                window.location.href = '/lobby';
            }
        };
    }
    
    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        if (document.getElementById('actionPanel')?.style.display !== 'none') {
            if (e.key === 'f' || e.key === 'F') {
                e.preventDefault();
                sendAction('fold');
            } else if (e.key === 'c' || e.key === 'C') {
                e.preventDefault();
                const currentPlayer = gameState?.players?.find(p => p.user_id === currentUser?.id);
                const toCall = (gameState?.current_bet || 0) - (currentPlayer?.current_bet || 0);
                sendAction(toCall === 0 ? 'check' : 'call');
            }
        }
    });
}

function sendAction(action, amount = 0) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'action', action, amount }));
    } else {
        showToast('Not connected to server', 'error');
    }
}

function showToast(message, type = 'info') {
    const toast = document.getElementById('toast');
    if (toast) {
        toast.textContent = message;
        toast.className = `toast ${type} show`;
        setTimeout(() => toast.classList.remove('show'), 3000);
    }
}

function getSuitSymbol(suit) {
    const symbols = { 'h': '♥', 'd': '♦', 'c': '♣', 's': '♠' };
    return symbols[suit] || suit;
}

function getSuitClass(suit) {
    const classes = { 'h': 'heart', 'd': 'diamond', 'c': 'club', 's': 'spade' };
    return classes[suit] || '';
}

function getRankDisplay(rank) {
    const rankNum = parseInt(rank);
    if (rankNum === 14) return 'A';
    if (rankNum === 13) return 'K';
    if (rankNum === 12) return 'Q';
    if (rankNum === 11) return 'J';
    if (rankNum === 10) return '10';
    return rankNum;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

init();
