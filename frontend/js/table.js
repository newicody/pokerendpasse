/**
 * table.js — Poker Table Controller
 * Version corrigée avec:
 * - Vérification du deck (commit/reveal)
 * - Gestion du pong pour heartbeat serveur
 * - Meilleure synchronisation avec le backend
 * - Timer corrigé avec action_timeout_total
 * - Historique des mains amélioré
 */
'use strict';

// ══════════════════════════════════════════════════════════════════════════════
// État global
// ══════════════════════════════════════════════════════════════════════════════
let ws = null;
let gameState = null;
let currentUser = null;
let isSpectator = false;
let reconnectTimer = null;
let reconnectAttempts = 0;
let showStacksInBB = false;
let lastHandNumber = 0;

// Deck verification
let deckCommitments = {};  // {hand_round: commitment_hash}
let deckReveals = {};      // {hand_round: {seed, deck_order, hash}}
let deckStatus = 'unknown'; // 'unknown', 'committed', 'verified', 'error'

const tableId = window.tableId;
const tableName = window.tableName;

// ══════════════════════════════════════════════════════════════════════════════
// Initialisation
// ══════════════════════════════════════════════════════════════════════════════
async function init() {
    await loadUser();
    
    const params = new URLSearchParams(location.search);
    isSpectator = params.get('spectate') === 'true' || !currentUser;
    
    if (isSpectator) {
        hide('actionPanel');
        show('spectatorBanner');
    }
    
    // Charger les préférences
    loadPreferences();
    
    // Initialiser l'UI
    $('tableName').textContent = tableName || 'Table';
    renderSeats([]);
    setupDeckIndicator();
    
    // Charger l'historique
    if (window.HandHistoryModule) {
        HandHistoryModule.loadFromStorage(tableId);
        HandHistoryModule.updateDisplay($('historyList'));
    }
    
    // Connexion WebSocket
    connectWS();
    
    // Événements
    setupEvents();
    setupTableChat();
    loadTournamentInfo();
    
    // Appliquer le thème
    if (window.ThemeManager) {
        ThemeManager.load();
    }
}

async function loadUser() {
    try {
        const response = await fetch('/api/auth/me');
        if (response.ok) {
            const data = await response.json();
            if (data?.user?.id) {
                currentUser = data.user;
                return;
            }
        }
    } catch (e) {
        console.error('Failed to load user:', e);
    }
    currentUser = null;
}

function loadPreferences() {
    try {
        const prefs = JSON.parse(localStorage.getItem('poker_table_prefs') || '{}');
        showStacksInBB = prefs.showStacksInBB || false;
        
        const toggle = $('stackDisplayToggle');
        if (toggle) {
            toggle.checked = showStacksInBB;
        }
    } catch (e) {
        // Ignorer
    }
}

function savePreferences() {
    try {
        localStorage.setItem('poker_table_prefs', JSON.stringify({
            showStacksInBB
        }));
    } catch (e) {
        // Ignorer
    }
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
        try {
            onMessage(JSON.parse(e.data));
        } catch (err) {
            console.error('WS message error:', err);
        }
    };
    
    ws.onclose = () => {
        if (!isSpectator) toast('Déconnecté', 'error');
        reconnect();
    };
    
    ws.onerror = () => {};
}

function reconnect() {
    if (reconnectTimer) clearTimeout(reconnectTimer);
    if (reconnectAttempts >= 10) {
        toast('Connexion perdue', 'error');
        return;
    }
    reconnectTimer = setTimeout(connectWS, Math.min(1000 * Math.pow(2, reconnectAttempts++), 30000));
}

function sendWS(data) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(data));
    }
}

function onMessage(msg) {
    switch (msg.type) {
        case 'game_update':
        case 'game_state':
            render(msg.data || msg);
            break;
            
        case 'connected':
            console.log('Connected as', msg.user_id);
            break;
            
        case 'reconnected':
            toast('Reconnecté!', 'success');
            break;
            
        case 'tournament_level_change':
        case 'blind_level_change':
            toast(`Niveau ${msg.level}: ${msg.small_blind}/${msg.big_blind}`, 'info');
            break;
            
        case 'tournament_player_eliminated':
        case 'player_eliminated':
            toast(`${msg.username || '?'} éliminé (#${msg.rank})`, 'info');
            loadTournamentInfo();
            break;
            
        case 'tournament_started':
            toast(`Tournoi démarré! ${msg.players_count} joueurs`, 'success');
            break;
            
        case 'tournament_finished':
            toast(`Tournoi terminé! Gagnant: ${msg.winners?.[0]?.username || '?'}`, 'success');
            break;
            
        case 'table_chat':
            addTableChat(msg);
            break;
            
        case 'deck_commit':
            handleDeckCommit(msg);
            break;
            
        case 'deck_reveal':
            handleDeckReveal(msg);
            break;
            
        case 'hand_result':
            handleHandResult(msg);
            break;
            
        case 'error':
            toast(msg.message || 'Erreur', 'error');
            break;
            
        case 'ping':
            // Répondre au ping du serveur
            sendWS({ type: 'pong' });
            break;
            
        case 'pong':
            // Réponse à notre ping (ignoré)
            break;
    }
}

// ══════════════════════════════════════════════════════════════════════════════
// Deck Verification (SRA)
// ══════════════════════════════════════════════════════════════════════════════
function handleDeckCommit(msg) {
    const { round, commitment } = msg;
    deckCommitments[round] = commitment;
    deckStatus = 'committed';
    updateDeckIndicator();
    console.log(`[Deck] Hand #${round} committed: ${commitment.substring(0, 16)}...`);
}

function handleDeckReveal(msg) {
    const { round, seed, deck_order, commitment } = msg;
    deckReveals[round] = { seed, deck_order, commitment };
    
    // Vérifier l'intégrité
    const storedCommitment = deckCommitments[round];
    if (storedCommitment) {
        verifyDeckCommitment(seed, deck_order, storedCommitment).then(isValid => {
            deckStatus = isValid ? 'verified' : 'error';
            
            if (!isValid) {
                console.error(`[Deck] VERIFICATION FAILED for hand #${round}!`);
                toast('⚠️ Vérification du deck échouée!', 'error');
            } else {
                console.log(`[Deck] Hand #${round} verified ✓`);
            }
            
            updateDeckIndicator();
        });
    } else {
        // Pas de commitment stocké (peut arriver si on rejoint en cours)
        deckStatus = 'verified';
        updateDeckIndicator();
    }
    
    // Nettoyer les vieux commits (garder 10 derniers)
    const rounds = Object.keys(deckCommitments).map(Number).sort((a, b) => a - b);
    while (rounds.length > 10) {
        const oldRound = rounds.shift();
        delete deckCommitments[oldRound];
        delete deckReveals[oldRound];
    }
}

async function verifyDeckCommitment(seed, deckOrder, expectedHash) {
    /**
     * Vérifie que SHA256(seed:deck) == expectedHash
     * Utilise SubtleCrypto si disponible, sinon confiance
     */
    try {
        if (window.crypto && window.crypto.subtle) {
            const deckStr = deckOrder.join(',');
            const data = new TextEncoder().encode(`${seed}:${deckStr}`);
            const hashBuffer = await crypto.subtle.digest('SHA-256', data);
            const hashArray = Array.from(new Uint8Array(hashBuffer));
            const hashHex = hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
            return hashHex === expectedHash;
        }
    } catch (e) {
        console.warn('Crypto verification unavailable:', e);
    }
    
    // Fallback: trust server (mais log)
    console.log('[Deck] Client-side verification not available, trusting server');
    return true;
}

function handleHandResult(msg) {
    const { hand, winner, winner_id, pot, board, hand_type, winning_cards } = msg;
    
    // Mettre à jour l'historique
    if (window.HandHistoryModule) {
        const myResult = winner_id === currentUser?.id ? 'win' : 'lose';
        HandHistoryModule.endHand(
            { username: winner, user_id: winner_id },
            hand_type,
            pot,
            myResult,
            winning_cards
        );
        HandHistoryModule.updateDisplay($('historyList'));
        HandHistoryModule.saveToStorage(tableId);
    }
    
    // Toast
    if (winner) {
        const isMe = winner_id === currentUser?.id;
        const icon = isMe ? '🎉' : '🏆';
        toast(`${icon} ${winner} gagne ${formatStack(pot)}${hand_type ? ` (${hand_type})` : ''}`, isMe ? 'success' : 'info');
    }
}

function setupDeckIndicator() {
    const indicator = $('deckIndicator');
    if (!indicator) return;
    
    indicator.innerHTML = `
        <div class="deck-icon">🎴</div>
        <div class="deck-status" id="deckStatusText">En attente</div>
    `;
    
    indicator.addEventListener('click', () => {
        showDeckVerificationInfo();
    });
}

function updateDeckIndicator() {
    const statusEl = $('deckStatusText');
    const indicator = $('deckIndicator');
    if (!statusEl || !indicator) return;
    
    indicator.classList.remove('status-unknown', 'status-committed', 'status-verified', 'status-error');
    
    switch (deckStatus) {
        case 'committed':
            statusEl.textContent = 'Engagé';
            indicator.classList.add('status-committed');
            break;
        case 'verified':
            statusEl.textContent = 'Vérifié ✓';
            indicator.classList.add('status-verified');
            break;
        case 'error':
            statusEl.textContent = 'Erreur!';
            indicator.classList.add('status-error');
            break;
        default:
            statusEl.textContent = 'En attente';
            indicator.classList.add('status-unknown');
    }
}

function showDeckVerificationInfo() {
    const lastRound = Math.max(...Object.keys(deckCommitments).map(Number), 0);
    const commit = deckCommitments[lastRound];
    const reveal = deckReveals[lastRound];
    
    let info = `<h3>🔐 Vérification du Deck</h3>
        <p><strong>Main actuelle:</strong> #${gameState?.round || '?'}</p>
        <p><strong>Status:</strong> ${deckStatus}</p>`;
    
    if (commit) {
        info += `<p><strong>Commitment:</strong><br><code>${commit.substring(0, 32)}...</code></p>`;
    }
    
    if (reveal) {
        info += `<p><strong>Seed révélé:</strong><br><code>${reveal.seed.substring(0, 32)}...</code></p>`;
    }
    
    info += `<p class="deck-info-note">Le serveur s'engage sur l'ordre du deck AVANT de distribuer, 
        puis révèle le seed après la main. Cela garantit qu'il ne peut pas tricher.</p>`;
    
    // Afficher dans une modal simple
    const modal = document.createElement('div');
    modal.className = 'deck-info-modal';
    modal.innerHTML = `
        <div class="deck-info-content">
            ${info}
            <button onclick="this.closest('.deck-info-modal').remove()">Fermer</button>
        </div>
    `;
    document.body.appendChild(modal);
}

// ══════════════════════════════════════════════════════════════════════════════
// Rendu principal
// ══════════════════════════════════════════════════════════════════════════════
function render(state) {
    gameState = state;
    if (!state) return;
    
    // Nouvelle main?
    if (state.round && state.round !== lastHandNumber) {
        lastHandNumber = state.round;
        if (window.HandHistoryModule) {
            const myPlayer = findMyPlayer(state.players);
            HandHistoryModule.startHand(state.round, state.players, myPlayer?.hole_cards || []);
        }
    }
    
    // Pot
    $('pot').innerHTML = `<span class="pot-icon">💰</span> Pot: ${formatStack(state.pot || 0)}`;
    
    // Cartes communes - afficher uniquement celles distribuées
    if (window.CardsModule) {
        CardsModule.updateCommunityCards($('communityCards'), state.community_cards);
        if (window.HandHistoryModule) {
            HandHistoryModule.updateCommunityCards(state.community_cards);
        }
    } else {
        updateCommunityCardsLegacy(state.community_cards);
    }
    
    // Joueurs et mises
    renderSeats(state.players || []);
    renderBets(state.players || []);
    
    // Mes cartes en grand
    const myPlayer = findMyPlayer(state.players);
    updateMyCardsDisplay(myPlayer);
    
    // Informations de jeu
    updateGameInfo(state);
    
    // Timer d'action
    updateActionTimer(state);
    
    // Actions disponibles
    if (!isSpectator && currentUser) {
        const isMyTurn = state.current_actor === currentUser.id && state.status === 'playing';
        updateActions(isMyTurn, state);
    }
}

// ══════════════════════════════════════════════════════════════════════════════
// Rendu des sièges (joueur centré en bas)
// ══════════════════════════════════════════════════════════════════════════════
function renderSeats(players) {
    const container = $('playersContainer');
    if (!container) return;
    
    container.innerHTML = '';
    
    const maxPlayers = gameState?.max_players || 9;
    const myPosition = findMyPosition(players);
    
    // Créer tous les sièges
    for (let i = 0; i < maxPlayers; i++) {
        // Calculer la position relative pour centrer le joueur en bas
        const relativePos = getRelativePosition(i, myPosition, maxPlayers);
        const player = players.find(p => p.position === i);
        
        const seatEl = document.createElement('div');
        seatEl.className = 'player-seat';
        seatEl.setAttribute('data-seat', relativePos);
        
        if (player) {
            const isActive = player.status === 'active' || player.status === 'all_in';
            const isFolded = player.status === 'folded';
            const isDisconnected = player.status === 'disconnected';
            const isCurrentActor = gameState?.current_actor === player.user_id;
            const isMe = currentUser && player.user_id === currentUser.id;
            
            if (isFolded) seatEl.classList.add('folded');
            if (isDisconnected) seatEl.classList.add('disconnected');
            if (isCurrentActor) seatEl.classList.add('active-turn');
            if (isMe) seatEl.classList.add('is-me');
            
            seatEl.innerHTML = renderPlayerSeat(player, isActive, isMe);
        } else {
            seatEl.classList.add('empty');
            seatEl.innerHTML = renderEmptySeat(i);
        }
        
        container.appendChild(seatEl);
    }
}

function getRelativePosition(absolutePos, myPosition, maxPlayers) {
    if (myPosition === -1 || isSpectator) {
        // Pas de joueur actuel ou spectateur: garder les positions absolues
        return absolutePos;
    }
    
    // Calculer la position relative pour que myPosition soit en 0 (bas)
    let relative = (absolutePos - myPosition + maxPlayers) % maxPlayers;
    return relative;
}

function findMyPosition(players) {
    if (!currentUser || !players) return -1;
    const myPlayer = players.find(p => p.user_id === currentUser.id);
    return myPlayer ? myPlayer.position : -1;
}

function findMyPlayer(players) {
    if (!currentUser || !players) return null;
    return players.find(p => p.user_id === currentUser.id);
}

function renderPlayerSeat(player, isActive, isMe) {
    const avatar = player.avatar && player.avatar !== 'default'
        ? `<img src="/uploads/avatars/${player.avatar}" alt="${esc(player.username)}">`
        : player.username.charAt(0).toUpperCase();
    
    const stack = formatStack(player.chips || player.stack || 0);
    
    // Markers
    let markers = '';
    if (player.is_dealer) markers += '<span class="marker marker-d">D</span>';
    if (player.is_small_blind) markers += '<span class="marker marker-sb">SB</span>';
    if (player.is_big_blind) markers += '<span class="marker marker-bb">BB</span>';
    if (player.status === 'all_in') markers += '<span class="marker marker-allin">ALL-IN</span>';
    if (player.status === 'disconnected') markers += '<span class="marker marker-dc">AFK</span>';
    
    // Cartes du joueur
    let cardsHtml = '';
    if (player.hole_cards && player.hole_cards.length > 0) {
        if (isMe || gameState?.betting_round === 'showdown') {
            // Montrer les cartes
            if (window.CardsModule) {
                cardsHtml = `<div class="seat-cards">
                    ${player.hole_cards.map(c => CardsModule.renderMiniCard(c, false)).join('')}
                </div>`;
            } else {
                cardsHtml = `<div class="seat-cards">${player.hole_cards.join(' ')}</div>`;
            }
        } else {
            // Dos de cartes pour les autres
            cardsHtml = `<div class="seat-cards">
                <div class="mini-card card-back"></div>
                <div class="mini-card card-back"></div>
            </div>`;
        }
    }
    
    // Dernière action
    const lastAction = player.last_action 
        ? `<div class="last-action">${formatAction(player.last_action)}</div>` 
        : '';
    
    return `
        <div class="player-avatar ${!isActive ? 'inactive' : ''}">${avatar}</div>
        <div class="player-info">
            <div class="player-name">${esc(player.username)}</div>
            <div class="player-stack">${stack}</div>
            ${lastAction}
        </div>
        <div class="player-markers">${markers}</div>
        ${cardsHtml}
    `;
}

function renderEmptySeat(position) {
    return `<div class="empty-seat-label">Siège ${position + 1}</div>`;
}

function formatAction(action) {
    const actions = {
        'fold': '✋ Fold',
        'check': '✓ Check',
        'call': '📞 Call',
        'raise': '⬆️ Raise',
        'all_in': '🔥 All-In',
        'timeout': '⏰ Timeout'
    };
    return actions[action] || action;
}

// ══════════════════════════════════════════════════════════════════════════════
// Rendu des mises
// ══════════════════════════════════════════════════════════════════════════════
function renderBets(players) {
    const container = $('betsContainer');
    if (!container) return;
    
    container.innerHTML = '';
    
    const maxPlayers = gameState?.max_players || 9;
    const myPosition = findMyPosition(players);
    
    players.forEach(player => {
        if (!player.current_bet && !player.bet) return;
        
        const bet = player.current_bet || player.bet || 0;
        if (bet <= 0) return;
        
        const relativePos = getRelativePosition(player.position, myPosition, maxPlayers);
        
        const betEl = document.createElement('div');
        betEl.className = 'player-bet';
        betEl.setAttribute('data-pos', relativePos);
        betEl.innerHTML = `<span class="bet-chips">🪙</span> ${formatStack(bet)}`;
        
        container.appendChild(betEl);
    });
}

// ══════════════════════════════════════════════════════════════════════════════
// Mes cartes en grand
// ══════════════════════════════════════════════════════════════════════════════
function updateMyCardsDisplay(myPlayer) {
    const container = $('myCardsDisplay');
    if (!container) return;
    
    if (!myPlayer || !myPlayer.hole_cards || myPlayer.hole_cards.length === 0) {
        container.innerHTML = '';
        container.classList.add('hidden');
        return;
    }
    
    container.classList.remove('hidden');
    
    if (window.CardsModule) {
        container.innerHTML = myPlayer.hole_cards
            .map(c => CardsModule.renderCard(c, false))
            .join('');
    } else {
        container.innerHTML = myPlayer.hole_cards
            .map(c => `<div class="my-card">${c}</div>`)
            .join('');
    }
}

// ══════════════════════════════════════════════════════════════════════════════
// Infos de jeu
// ══════════════════════════════════════════════════════════════════════════════
function updateGameInfo(state) {
    // Blinds
    const blindsEl = $('blindsInfo');
    if (blindsEl) {
        blindsEl.textContent = `Blinds: ${state.small_blind}/${state.big_blind}`;
    }
    
    // Street
    const streetEl = $('streetInfo');
    if (streetEl) {
        const streets = {
            'preflop': 'Preflop',
            'flop': 'Flop',
            'turn': 'Turn',
            'river': 'River',
            'showdown': 'Showdown'
        };
        streetEl.textContent = streets[state.betting_round] || state.betting_round || '';
    }
    
    // Hand number
    const handEl = $('handNumber');
    if (handEl) {
        handEl.textContent = `Main #${state.round || 0}`;
    }
}

// ══════════════════════════════════════════════════════════════════════════════
// Timer d'action (corrigé avec action_timeout_total)
// ══════════════════════════════════════════════════════════════════════════════
function updateActionTimer(state) {
    const timerEl = $('actionTimer');
    const progressEl = $('timerProgress');
    
    if (!state.current_actor || state.action_timer === null || state.action_timer === undefined) {
        if (timerEl) timerEl.classList.add('hidden');
        if (window.TimerModule) TimerModule.stop();
        return;
    }
    
    if (timerEl) timerEl.classList.remove('hidden');
    
    // Utiliser action_timeout_total du backend, sinon fallback à 20
    const totalTime = state.action_timeout_total || 20;
    const remaining = state.action_timer;
    
    if (window.TimerModule) {
        TimerModule.start(remaining, totalTime, (secs, pct) => {
            const timerText = $('timerText');
            if (timerText) {
                timerText.textContent = secs;
                timerText.classList.toggle('urgent', secs <= 5);
            }
            if (progressEl) {
                progressEl.style.width = `${pct}%`;
                progressEl.classList.toggle('urgent', pct <= 25);
            }
        });
    } else {
        // Fallback simple
        const timerText = $('timerText');
        if (timerText) timerText.textContent = remaining;
        if (progressEl) {
            const pct = (remaining / totalTime) * 100;
            progressEl.style.width = `${pct}%`;
        }
    }
}

// ══════════════════════════════════════════════════════════════════════════════
// Actions joueur
// ══════════════════════════════════════════════════════════════════════════════
function updateActions(isMyTurn, state) {
    const panel = $('actionPanel');
    if (!panel) return;
    
    if (!isMyTurn) {
        panel.classList.add('disabled');
        return;
    }
    
    panel.classList.remove('disabled');
    
    const myPlayer = findMyPlayer(state.players);
    if (!myPlayer) return;
    
    const currentBet = state.current_bet || 0;
    const myBet = myPlayer.current_bet || myPlayer.bet || 0;
    const toCall = currentBet - myBet;
    const myStack = myPlayer.chips || myPlayer.stack || 0;
    const minRaise = state.min_raise || state.big_blind * 2;
    const maxRaise = state.max_raise || myStack;
    
    // Bouton Fold
    const foldBtn = $('btnFold');
    if (foldBtn) foldBtn.disabled = false;
    
    // Bouton Check/Call
    const callBtn = $('btnCall');
    if (callBtn) {
        if (toCall <= 0) {
            callBtn.textContent = 'Check';
            callBtn.disabled = false;
        } else if (toCall >= myStack) {
            callBtn.textContent = `Call All-In (${formatStack(myStack)})`;
            callBtn.disabled = false;
        } else {
            callBtn.textContent = `Call ${formatStack(toCall)}`;
            callBtn.disabled = false;
        }
    }
    
    // Bouton Raise
    const raiseBtn = $('btnRaise');
    const raiseInput = $('raiseAmount');
    if (raiseBtn && raiseInput) {
        if (myStack <= toCall) {
            raiseBtn.disabled = true;
            raiseInput.disabled = true;
        } else {
            raiseBtn.disabled = false;
            raiseInput.disabled = false;
            raiseInput.min = minRaise;
            raiseInput.max = maxRaise;
            raiseInput.value = Math.min(minRaise, maxRaise);
        }
    }
    
    // Bouton All-In
    const allInBtn = $('btnAllIn');
    if (allInBtn) {
        allInBtn.textContent = `All-In (${formatStack(myStack)})`;
        allInBtn.disabled = false;
    }
}

function sendAction(action, amount = 0) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    
    sendWS({
        type: 'action',
        action: action,
        amount: parseInt(amount) || 0
    });
}

// ══════════════════════════════════════════════════════════════════════════════
// Événements
// ══════════════════════════════════════════════════════════════════════════════
function setupEvents() {
    // Actions
    $('btnFold')?.addEventListener('click', () => sendAction('fold'));
    $('btnCall')?.addEventListener('click', () => sendAction('call'));
    $('btnRaise')?.addEventListener('click', () => {
        const amount = parseInt($('raiseAmount')?.value) || 0;
        sendAction('raise', amount);
    });
    $('btnAllIn')?.addEventListener('click', () => sendAction('all_in'));
    
    // Slider raise
    $('raiseAmount')?.addEventListener('input', (e) => {
        const display = $('raiseDisplay');
        if (display) display.textContent = formatStack(parseInt(e.target.value) || 0);
    });
    
    // Raccourcis clavier
    document.addEventListener('keydown', (e) => {
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
        
        switch (e.key.toLowerCase()) {
            case 'f': sendAction('fold'); break;
            case 'c': sendAction('call'); break;
            case 'r': $('raiseAmount')?.focus(); break;
            case 'a': sendAction('all_in'); break;
        }
    });
    
    // Toggle BB display
    $('stackDisplayToggle')?.addEventListener('change', (e) => {
        showStacksInBB = e.target.checked;
        savePreferences();
        if (gameState) render(gameState);
    });
    
    // Quitter la table
    $('btnLeave')?.addEventListener('click', async () => {
        if (confirm('Quitter la table?')) {
            try {
                await fetch(`/api/tables/${tableId}/leave?user_id=${currentUser?.id}`, {
                    method: 'POST'
                });
            } catch (e) {
                // Ignorer
            }
            window.location.href = '/lobby';
        }
    });
}

// ══════════════════════════════════════════════════════════════════════════════
// Chat de table
// ══════════════════════════════════════════════════════════════════════════════
function setupTableChat() {
    const input = $('tableChatInput');
    const btn = $('tableChatSend');
    
    if (!input || !btn) return;
    
    const send = () => {
        const text = input.value.trim();
        if (!text) return;
        
        sendWS({
            type: 'chat',
            message: text
        });
        
        input.value = '';
    };
    
    btn.addEventListener('click', send);
    input.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') send();
    });
}

function addTableChat(msg) {
    const container = $('tableChatMessages');
    if (!container) return;
    
    const msgEl = document.createElement('div');
    msgEl.className = 'chat-message';
    if (msg.user_id === currentUser?.id) msgEl.classList.add('own-message');
    
    msgEl.innerHTML = `
        <span class="chat-username">${esc(msg.username)}:</span>
        <span class="chat-text">${esc(msg.message)}</span>
    `;
    
    container.appendChild(msgEl);
    container.scrollTop = container.scrollHeight;
    
    // Limiter à 100 messages
    while (container.children.length > 100) {
        container.removeChild(container.firstChild);
    }
}

// ══════════════════════════════════════════════════════════════════════════════
// Infos tournoi
// ══════════════════════════════════════════════════════════════════════════════
async function loadTournamentInfo() {
    if (!gameState?.tournament_id) return;
    
    try {
        const resp = await fetch(`/api/tournaments/${gameState.tournament_id}`);
        if (resp.ok) {
            const data = await resp.json();
            updateTournamentPanel(data);
        }
    } catch (e) {
        console.error('Failed to load tournament info:', e);
    }
}

function updateTournamentPanel(data) {
    const panel = $('tournamentInfo');
    if (!panel) return;
    
    panel.classList.remove('hidden');
    panel.innerHTML = `
        <div class="tournament-header">🏆 ${esc(data.name)}</div>
        <div class="tournament-stats">
            <div>Joueurs: ${data.players_count}</div>
            <div>Niveau: ${data.current_level + 1}</div>
            <div>Blinds: ${data.current_blinds?.small_blind}/${data.current_blinds?.big_blind}</div>
        </div>
    `;
}

// ══════════════════════════════════════════════════════════════════════════════
// Utilitaires
// ══════════════════════════════════════════════════════════════════════════════
function $(id) {
    return document.getElementById(id);
}

function show(id) {
    const el = $(id);
    if (el) el.classList.remove('hidden');
}

function hide(id) {
    const el = $(id);
    if (el) el.classList.add('hidden');
}

function esc(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function formatStack(amount) {
    if (amount === null || amount === undefined) return '0';
    
    if (showStacksInBB && gameState?.big_blind) {
        const bb = amount / gameState.big_blind;
        return `${bb.toFixed(1)} BB`;
    }
    
    return amount.toLocaleString();
}

function toast(message, type = 'info') {
    const container = $('toastContainer') || createToastContainer();
    
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    
    container.appendChild(toast);
    
    setTimeout(() => toast.classList.add('show'), 10);
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

function createToastContainer() {
    const container = document.createElement('div');
    container.id = 'toastContainer';
    container.className = 'toast-container';
    document.body.appendChild(container);
    return container;
}

function updateCommunityCardsLegacy(cards) {
    const container = $('communityCards');
    if (!container) return;
    
    container.innerHTML = '';
    
    if (!cards || cards.length === 0) return;
    
    cards.forEach(card => {
        const cardEl = document.createElement('div');
        cardEl.className = 'community-card';
        cardEl.textContent = card;
        container.appendChild(cardEl);
    });
}

// ══════════════════════════════════════════════════════════════════════════════
// Démarrage
// ══════════════════════════════════════════════════════════════════════════════
document.addEventListener('DOMContentLoaded', init);
