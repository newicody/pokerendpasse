// frontend/table.js
/**
 * table.js — Logique de la table de poker
 * Version remaniée avec :
 * - Chat avec smileys et horodatage optionnel
 * - Options (thème, cartes, table, son, auto-action, etc.)
 * - Affichage détaillé des infos tournoi (prize pool, ITM, ranking)
 * - Gestion WebSocket avec reconnection
 * - Timer d'action, quick bets, raise slider
 * - Animations améliorées
 */

const tableId = window.tableId;
let ws = null, currentUser = null, gameState = null, isSpectator = false;
let showStacksInBB = false, reconnectAttempts = 0, reconnectTimer = null;
let currentQuickBets = [], tournamentInfo = null;
let tournamentTimerInterval = null;
const $ = (id) => document.getElementById(id);

// ══════════════════════════════════════════════════════════════════════════════
// Initialisation
// ══════════════════════════════════════════════════════════════════════════════
async function init() {
    await loadUser();
    loadPreferences();
    setupActions();
    setupQuickBets();
    setupChat();
    setupOptionsModal();
    setupKeyboardShortcuts();
    connectWS();
    startHeartbeat();
    setupBackButton();
    loadTournamentInfo();
    if (typeof SoundManager !== 'undefined') SoundManager.init();
    if (typeof SettingsManager !== 'undefined') {
        SettingsManager.load();
        applyTableSettings();
    }
    // Afficher l'heure locale si demandé (dans un élément facultatif)
    setupLocalTime();
}

// ══════════════════════════════════════════════════════════════════════════════
// Utilitaires
// ══════════════════════════════════════════════════════════════════════════════
function esc(t) { const d = document.createElement('div'); d.textContent = t || ''; return d.innerHTML; }
function toast(message, type = 'info') {
    let c = $('toastContainer') || (() => {
        const c = document.createElement('div'); c.id = 'toastContainer'; c.className = 'toast-container';
        document.body.appendChild(c); return c;
    })();
    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    el.textContent = message;
    c.appendChild(el);
    setTimeout(() => el.classList.add('show'), 10);
    setTimeout(() => { el.classList.remove('show'); setTimeout(() => el.remove(), 300); }, 3000);
}
function formatStack(a) {
    if (a == null) return '0';
    if (showStacksInBB && gameState?.big_blind) return `${(a / gameState.big_blind).toFixed(1)} BB`;
    return a.toLocaleString();
}
function savePreferences() {
    try { localStorage.setItem('poker_table_prefs', JSON.stringify({ showStacksInBB })); } catch(e) {}
}
function loadPreferences() {
    try {
        const p = JSON.parse(localStorage.getItem('poker_table_prefs') || '{}');
        showStacksInBB = p.showStacksInBB || false;
        const t = $('stackDisplayToggle');
        if (t) {
            t.checked = showStacksInBB;
            t.addEventListener('change', () => {
                showStacksInBB = t.checked;
                savePreferences();
                if (gameState) render(gameState);
            });
        }
    } catch(e) {}
}
function applyTableSettings() {
    const theme = SettingsManager.get('theme') || 'dark';
    if (typeof ThemeManager !== 'undefined') ThemeManager.setTheme(theme);
    const cardDeck = SettingsManager.get('cardDeck') || 'standard';
    if (typeof CardsModule !== 'undefined') CardsModule.setDeck(cardDeck);
    const tableStyle = SettingsManager.get('tableStyle') || 'felt';
    document.body.setAttribute('data-table-style', tableStyle);
    const soundEnabled = SettingsManager.get('sound') !== 'off';
    if (typeof SoundManager !== 'undefined') {
        if (soundEnabled) SoundManager.enable();
        else SoundManager.disable();
        SoundManager.setVolume(SettingsManager.get('soundVolume') || 0.5);
    }
    const animSpeed = SettingsManager.get('animationSpeed') || 'normal';
    document.body.setAttribute('data-animation-speed', animSpeed);
    const autoAction = SettingsManager.get('autoAction') || 'never';
    localStorage.setItem('poker_auto_action', autoAction);
    const chatTimestamps = SettingsManager.get('chatTimestamps') !== false;
    localStorage.setItem('poker_chat_timestamps', chatTimestamps ? 'true' : 'false');
}
function setupLocalTime() {
    const timeEl = $('localTime');
    if (timeEl) {
        const update = () => { timeEl.textContent = new Date().toLocaleTimeString(); };
        update();
        setInterval(update, 1000);
    }
}

// ══════════════════════════════════════════════════════════════════════════════
// User & Auth
// ══════════════════════════════════════════════════════════════════════════════
async function loadUser() {
    try {
        const r = await fetch('/api/auth/me');
        if (r.ok) {
            const d = await r.json();
            if (d?.user?.id) {
                currentUser = d.user;
                return;
            }
        }
    } catch(e) {}
    currentUser = null;
}

// ══════════════════════════════════════════════════════════════════════════════
// WebSocket
// ══════════════════════════════════════════════════════════════════════════════
function connectWS() {
    if (ws && (ws.readyState === 0 || ws.readyState === 1)) return;
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${proto}//${location.host}/ws/${tableId}/${currentUser?.id || 'spectator'}`);
    ws.onopen = () => {
        reconnectAttempts = 0;
        if (!isSpectator) toast('Connecté', 'success');
    };
    ws.onmessage = (e) => {
        try {
            onMessage(JSON.parse(e.data));
        } catch (err) { console.error('WS parse:', err); }
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
function startHeartbeat() {
    setInterval(() => {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'ping' }));
        } else if (ws && ws.readyState === WebSocket.CLOSED) {
            reconnect();
        }
    }, 30000);
}
function sendWS(data) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(data));
    }
}

// ══════════════════════════════════════════════════════════════════════════════
// Message handling
// ══════════════════════════════════════════════════════════════════════════════
function onMessage(msg) {
    console.log('[DEBUG] WS message:', msg.type, msg);
    switch (msg.type) {
        case 'game_update':
        case 'game_state':
            if (msg.is_spectator !== undefined) isSpectator = msg.is_spectator;
            gameState = msg.data || msg;
            if (msg.quick_bets) currentQuickBets = msg.quick_bets;
            render(gameState);
            break;
        case 'hole_cards':
            if (gameState) {
                const me = gameState.players?.find(p => p.user_id === currentUser?.id);
                if (me) {
                    me.hole_cards = msg.cards;
                    updateMyCards();
                    // Animation de distribution
                    const cardElements = document.querySelectorAll('.my-cards-container .card');
                    const fromX = window.innerWidth / 2;
                    const fromY = window.innerHeight / 4;
                    cardElements.forEach((card, idx) => {
                        if (idx < msg.cards.length) animateCardDeal(card, { x: fromX, y: fromY });
                    });
                }
            }
            break;
        case 'community_cards':
            if (gameState) {
                gameState.community_cards = msg.cards;
                updateCommunityCards(msg.cards);
                const newCards = msg.cards.slice(-(msg.cards.length - (gameState.community_cards?.length || 0)));
                const communityCards = document.querySelectorAll('.community-cards .card');
                communityCards.forEach((card, idx) => {
                    if (idx >= communityCards.length - newCards.length) animateCommunityCard(card);
                });
            }
            if (typeof SoundManager !== 'undefined') SoundManager.play('flip');
            break;
        case 'player_action':
            if (typeof SoundManager !== 'undefined') {
                if (['call', 'raise', 'all-in'].includes(msg.action)) SoundManager.play('bet');
                else if (msg.action === 'fold') SoundManager.play('fold');
                else if (msg.action === 'check') SoundManager.play('check');
            }
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
        case 'reconnected':
            toast('Reconnecté!', 'success');
            sendWS({ type: 'request_full_state' });
            break;
        case 'tournament_level_change':
            toast(`📊 Niveau ${msg.level}: Blinds ${msg.small_blind}/${msg.big_blind}`, 'info');
            if (typeof SoundManager !== 'undefined') SoundManager.play('turn');
            loadTournamentInfo();
            break;
        case 'tournament_paused':
            toast('⏸ Tournoi en pause…', 'info');
            if (typeof TimerModule !== 'undefined') TimerModule.stop();
            loadTournamentInfo();
            break;
        case 'tournament_finished':
            toast(`🏆 Tournoi terminé! Gagnant: ${msg.winner?.username || '?'}`, 'success');
            setTimeout(() => { window.location.href = msg.results_url || '/lobby'; }, 5000);
            break;
        case 'tournament_player_eliminated':
            toast(`💀 ${msg.username || '?'} éliminé — #${msg.rank}`, 'info');
            if (msg.user_id === currentUser?.id) toast('Vous avez été éliminé!', 'error');
            loadTournamentInfo();
            break;
        case 'table_chat':
            appendChatMessage(msg.username, msg.message, msg.timestamp);
            break;
        case 'table_change':
            toast(`🔄 ${msg.message || 'Changement de table'}`, 'info');
            setTimeout(() => { window.location.href = `/table/${msg.new_table_id}`; }, 2000);
            break;
        case 'player_moved':
            toast(`🔄 ${msg.username} déplacé vers une autre table`, 'info');
            break;
        case 'ping':
            sendWS({ type: 'pong' });
            break;
        case 'error':
            console.error('[DEBUG] Server error:', msg.message);
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
    const spectatorIndicator = $('spectatorModeIndicator');
    const actionBar = $('actionBar');
    if (spectatorIndicator) spectatorIndicator.style.display = isSpectator ? 'block' : 'none';
    if (actionBar) {
        actionBar.style.opacity = isSpectator ? '0.5' : '1';
        actionBar.style.pointerEvents = isSpectator ? 'none' : 'auto';
    }
    renderPlayers(state);
    updateCommunityCards(state.community_cards || []);
    updatePot(state.pot || 0, state.side_pots);
    updateGameInfo(state);
    updateActions(state);
    updateMyCards();
    updateActionTimer(state);
    updateQuickBetsUI(state);
    const b = $('spectatorBanner');
    if (b) b.style.display = isSpectator ? 'block' : 'none';
}

function getPositionsWithPlayerCentered(playerCount, myPosition) {
    const STANDARD_POSITIONS = {
        2: [{top:'85%',left:'50%'},{top:'15%',left:'50%'}],
        3: [{top:'85%',left:'50%'},{top:'15%',left:'25%'},{top:'15%',left:'75%'}],
        4: [{top:'85%',left:'50%'},{top:'50%',left:'15%'},{top:'15%',left:'50%'},{top:'50%',left:'85%'}],
        5: [{top:'85%',left:'50%'},{top:'65%',left:'15%'},{top:'30%',left:'15%'},{top:'30%',left:'85%'},{top:'65%',left:'85%'}],
        6: [{top:'85%',left:'50%'},{top:'70%',left:'15%'},{top:'35%',left:'10%'},{top:'15%',left:'50%'},{top:'35%',left:'90%'},{top:'70%',left:'85%'}],
        7: [{top:'85%',left:'50%'},{top:'75%',left:'10%'},{top:'50%',left:'5%'},{top:'20%',left:'25%'},{top:'20%',left:'75%'},{top:'50%',left:'95%'},{top:'75%',left:'90%'}],
        8: [{top:'85%',left:'50%'},{top:'75%',left:'10%'},{top:'50%',left:'5%'},{top:'25%',left:'15%'},{top:'15%',left:'50%'},{top:'25%',left:'85%'},{top:'50%',left:'95%'},{top:'75%',left:'90%'}],
        9: [{top:'85%',left:'50%'},{top:'75%',left:'8%'},{top:'55%',left:'5%'},{top:'30%',left:'12%'},{top:'15%',left:'35%'},{top:'15%',left:'65%'},{top:'30%',left:'88%'},{top:'55%',left:'95%'},{top:'75%',left:'92%'}]
    };
    const key = Math.min(Math.max(playerCount, 2), 9);
    let positions = [...(STANDARD_POSITIONS[key] || STANDARD_POSITIONS[9])];
    if (myPosition >= 0 && myPosition < playerCount && myPosition !== 0) {
        const rotated = [];
        for (let i = 0; i < playerCount; i++) {
            rotated[i] = positions[(i + myPosition) % playerCount];
        }
        positions = rotated;
    }
    return positions;
}

function renderPlayers(state) {
    const container = $('playersContainer');
    if (!container) return;
    container.innerHTML = '';
    const players = state.players || [];
    const myPosition = state.my_position;
    const positions = getPositionsWithPlayerCentered(players.length, myPosition);
    const numHole = state.game_variant === 'plo' ? 4 : 2;
    players.forEach((p, idx) => {
        const el = document.createElement('div');
        const isCurrentPlayer = (p.user_id === currentUser?.id);
        const pos = positions[idx] || { top: '50%', left: '50%' };
        let statusClass = '';
        if (p.status === 'folded') statusClass = 'folded';
        else if (p.status === 'eliminated') statusClass = 'eliminated';
        else if (p.status === 'all_in') statusClass = 'all_in';
        else if (p.status === 'sitting_out') statusClass = 'sitting_out';
        el.className = `player-seat ${statusClass} ${p.user_id === state.current_actor ? 'active-player' : ''} ${isCurrentPlayer ? 'current-player' : ''}`;
        el.style.top = pos.top;
        el.style.left = pos.left;
        const stack = formatStack(p.chips || p.stack || 0);
        const betDisplay = p.current_bet > 0 ? `<div class="player-bet-chip">${p.current_bet.toLocaleString()}</div>` : '';
        const roleTag = p.is_dealer ? '<span class="role-tag dealer">D</span>' :
                        p.is_small_blind ? '<span class="role-tag sb">SB</span>' :
                        p.is_big_blind ? '<span class="role-tag bb">BB</span>' : '';
        let cardsHtml = '';
        if (p.status !== 'folded' && p.status !== 'eliminated') {
            if (p.hole_cards && p.hole_cards.length > 0) {
                if (isCurrentPlayer || isSpectator) {
                    cardsHtml = p.hole_cards.map(c => {
                        if (typeof CardsModule !== 'undefined') return CardsModule.renderCard(c, false);
                        return `<div class="mini-card">${c}</div>`;
                    }).join('');
                } else {
                    cardsHtml = Array(numHole).fill('<div class="mini-card back"></div>').join('');
                }
            } else if (p.status === 'active' || p.status === 'all_in') {
                cardsHtml = Array(numHole).fill('<div class="mini-card back"></div>').join('');
            }
        }
        const lastAct = p.last_action ? `<div class="last-action">${p.last_action}</div>` : '';
        const avatarUrl = p.avatar && p.avatar !== 'default' ? p.avatar : '/assets/avatars/default.svg';
        el.innerHTML = `
            <div class="player-avatar">
                <img src="${avatarUrl}" alt="${esc(p.username)}" onerror="this.src='/assets/avatars/default.svg'">
                ${roleTag}
            </div>
            <div class="player-name">${esc(p.username)}</div>
            <div class="player-stack">${stack}</div>
            <div class="player-cards">${cardsHtml}</div>
            ${betDisplay}
            ${lastAct}
        `;
        container.appendChild(el);
    });
}

function updateCommunityCards(cards) {
    const c = $('communityCards');
    if (!c) return;
    c.innerHTML = '';
    if (!cards?.length) return;
    cards.forEach(card => {
        if (typeof CardsModule !== 'undefined') c.innerHTML += CardsModule.renderCard(card, false);
        else { const el = document.createElement('div'); el.className = 'community-card'; el.textContent = card; c.appendChild(el); }
    });
}

function updatePot(pot, sidePots) {
    const el = $('potDisplay');
    if (!el) return;
    if (sidePots && sidePots.length > 1) {
        const parts = sidePots.map((sp, i) => `P${i+1}:${sp.amount.toLocaleString()}`).join(' · ');
        el.innerHTML = `<span class="pot-main">Pot: ${pot.toLocaleString()}</span> <span class="pot-side">(${parts})</span>`;
    } else {
        el.textContent = `Pot: ${pot.toLocaleString()}`;
    }
}

function updateGameInfo(state) {
    const set = (id, t) => { const el = $(id); if (el) el.textContent = t; };
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

function updateMyCards() {
    const c = $('myCardsContainer');
    if (!c || !currentUser) return;
    const me = gameState?.players?.find(p => p.user_id === currentUser.id);
    if (!me?.hole_cards?.length) { c.classList.add('hidden'); return; }
    c.classList.remove('hidden');
    c.innerHTML = me.hole_cards.map(card => {
        if (typeof CardsModule !== 'undefined') return CardsModule.renderCard(card, false);
        return `<div class="my-card">${card}</div>`;
    }).join('');
}

function updateActions(state) {
    const myTurn = state.current_actor === currentUser?.id;
    const me = state.players?.find(p => p.user_id === currentUser?.id);
    const foldBtn = $('foldBtn');
    const checkBtn = $('checkBtn');
    const raiseBtn = $('raiseBtn');
    const callBtn = $('callBtn');
    if (foldBtn) foldBtn.disabled = !myTurn;
    if (checkBtn) checkBtn.disabled = !myTurn;
    if (raiseBtn) raiseBtn.disabled = !myTurn;
    if (myTurn && me) {
        const tableBet = state.current_bet || 0;
        const myBet = me.current_bet || 0;
        if (tableBet > myBet) {
            if (checkBtn) checkBtn.style.display = 'none';
            if (callBtn) {
                callBtn.style.display = '';
                callBtn.disabled = false;
                const toCall = Math.min(tableBet - myBet, me.chips || 0);
                callBtn.textContent = `Call ${toCall.toLocaleString()} (C)`;
            }
        } else {
            if (checkBtn) checkBtn.style.display = '';
            if (callBtn) callBtn.style.display = 'none';
        }
        if (raiseBtn && me.chips > 0) raiseBtn.disabled = false;
        const sl = $('raiseAmount');
        if (sl) {
            const minRaise = state.min_raise || state.big_blind || 10;
            sl.min = minRaise;
            sl.max = me.chips || 1000;
            sl.value = Math.min(Math.max(minRaise, Math.floor(me.chips / 4)), sl.max);
            const raiseValue = $('raiseValue');
            if (raiseValue) {
                raiseValue.value = sl.value;
                raiseValue.min = minRaise;
                raiseValue.max = me.chips || 1000;
            }
        }
    } else {
        if (checkBtn) checkBtn.style.display = '';
        if (callBtn) callBtn.style.display = 'none';
        if (raiseBtn) raiseBtn.disabled = true;
    }
}

function updateQuickBetsUI(state) {
    const c = $('quickBets');
    if (!c) return;
    const myTurn = state.current_actor === currentUser?.id;
    c.style.display = myTurn ? 'flex' : 'none';
    if (!myTurn || !currentQuickBets?.length) return;
    document.querySelectorAll('.qb-btn').forEach(btn => {
        const key = btn.dataset.key;
        const bet = currentQuickBets.find(b => b.key === key);
        if (bet) {
            btn.style.display = '';
            btn.textContent = `${bet.label} (${bet.amount.toLocaleString()})`;
        } else {
            btn.style.display = 'none';
        }
    });
}

function updateActionTimer(state) {
    const el = $('actionTimer');
    if (!el) return;
    const isMyTurn = state.current_actor === currentUser?.id;
    const hasTimer = state.action_timer !== null && state.action_timer !== undefined;
    if (!isMyTurn || !hasTimer || state.action_timer <= 0) {
        el.classList.add('hidden');
        el.classList.remove('timer-warning');
        el.innerHTML = '';
        if (typeof TimerModule !== 'undefined') TimerModule.stop();
        return;
    }
    el.classList.remove('hidden');
    const total = state.action_timeout_total || 20;
    const remaining = state.action_timer;
    if (remaining <= 5 && isMyTurn) el.classList.add('timer-warning');
    else el.classList.remove('timer-warning');
    if (typeof TimerModule !== 'undefined') {
        TimerModule.start(remaining, total, (secs, pct) => {
            if (el) {
                const color = pct > 0.5 ? 'var(--success)' : pct > 0.2 ? 'var(--warning)' : 'var(--danger)';
                el.innerHTML = `
                    <div class="timer-bar-bg">
                        <div class="timer-bar-fill" style="width:${pct * 100}%;background:${color}"></div>
                    </div>
                    <span class="timer-text">⏱ ${secs}s</span>
                `;
            }
            if (secs === 5 && isMyTurn && typeof SoundManager !== 'undefined') SoundManager.play('timer');
            if (secs === 0) doAction('fold');
        });
    } else {
        el.textContent = `⏱ ${remaining}s`;
    }
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
    const sl = $('raiseAmount'), inp = $('raiseValue');
    if (sl && inp) {
        sl.addEventListener('input', () => { inp.value = sl.value; });
        inp.addEventListener('input', () => { sl.value = inp.value; });
    }
}
function doAction(action, amount = 0) {
    if (gameState?.current_actor !== currentUser?.id) {
        toast('Ce n\'est pas votre tour', 'error');
        return;
    }
    if (action === 'call' || action === 'raise' || action === 'all_in') {
        const playerElement = document.querySelector('.player-seat.current-player');
        const potElement = $('potDisplay');
        if (playerElement && potElement && amount > 0) animateChip(playerElement, potElement, amount);
    }
    sendWS({ type: 'action', action: action, amount: amount });
    hideRaiseSlider();
    if (typeof SoundManager !== 'undefined') SoundManager.play('chip');
}
function showRaiseSlider() { const el = $('raiseSlider'); if (el) el.style.display = 'flex'; }
function hideRaiseSlider() { const el = $('raiseSlider'); if (el) el.style.display = 'none'; }
function confirmRaise() { const a = parseInt($('raiseValue')?.value || $('raiseAmount')?.value || 0); if (a > 0) doAction('raise', a); }
function setupQuickBets() {
    document.querySelectorAll('.qb-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const key = btn.dataset.key;
            const bet = currentQuickBets.find(b => b.key === key);
            if (bet) {
                if (key === 'allin') doAction('all_in', bet.amount);
                else doAction('raise', bet.amount);
            }
        });
    });
}

// ══════════════════════════════════════════════════════════════════════════════
// Hand Result
// ══════════════════════════════════════════════════════════════════════════════
function handleHandResult(msg) {
    if (typeof SoundManager !== 'undefined') SoundManager.play('win');
    const winners = msg.winners || [];
    toast(`🏆 ${winners.map(w => `${w.username} +${w.amount?.toLocaleString() || 0} (${w.hand || '?'})`).join(', ')}`, 'success');
    if (msg.side_pots && msg.side_pots.length > 1) toast(msg.side_pots.map((sp, i) => `Pot ${i+1}: ${sp.amount.toLocaleString()}`).join(' | '), 'info');
    if (msg.showdown) {
        msg.showdown.forEach(p => {
            if (gameState?.players) {
                const gp = gameState.players.find(x => x.user_id === p.user_id);
                if (gp) gp.hole_cards = p.hole_cards;
            }
        });
        if (gameState) render(gameState);
    }
    if (typeof HandHistory !== 'undefined') HandHistory.add({ round: gameState?.round || 0, winners, pot: msg.pot, community: msg.community_cards || [] });
    // Animation pot gagné
    const potEl = $('potDisplay');
    if (potEl) potEl.classList.add('pot-won');
    setTimeout(() => { if (potEl) potEl.classList.remove('pot-won'); }, 600);
}

// ══════════════════════════════════════════════════════════════════════════════
// Chat
// ══════════════════════════════════════════════════════════════════════════════
function setupChat() {
    const inp = $('tableChatInput');
    const btn = $('tableChatSend');
    if (!inp || !btn) return;
    if (currentUser) {
        inp.disabled = false;
        btn.disabled = false;
    }
    const send = () => {
        const text = inp.value.trim();
        if (!text) return;
        sendWS({ type: 'chat', message: text });
        inp.value = '';
    };
    btn.addEventListener('click', send);
    inp.addEventListener('keypress', (e) => { if (e.key === 'Enter') send(); });
    // Smileys
    const sBtn = $('chatSmileyBtn');
    const sDrop = $('chatSmileyDropdown');
    if (sBtn && sDrop) {
        const emojis = ['😊','😂','🤣','😍','🤔','😎','🙄','😢','😡','🎉','👍','👎','🔥','💰','🃏','♠️','♥️','♣️','♦️','🏆','😏','🤑','😤','🥳'];
        sDrop.innerHTML = emojis.map(e => `<span class="emoji-item">${e}</span>`).join('');
        sBtn.addEventListener('click', (e) => { e.stopPropagation(); sDrop.classList.toggle('visible'); });
        sDrop.addEventListener('click', (e) => {
            if (e.target.classList.contains('emoji-item') && inp) {
                inp.value += e.target.textContent;
                inp.focus();
                sDrop.classList.remove('visible');
            }
        });
        document.addEventListener('click', () => sDrop.classList.remove('visible'));
    }
}
function appendChatMessage(username, message, timestamp) {
    const c = $('tableChatMessages');
    if (!c) return;
    const div = document.createElement('div');
    div.className = 'tchat-msg';
    const showTimestamps = SettingsManager?.get('chatTimestamps') !== false;
    let timeStr = '';
    if (showTimestamps && timestamp) {
        const d = new Date(timestamp);
        timeStr = `[${d.toLocaleTimeString()}] `;
    }
    div.innerHTML = `${timeStr}<strong>${esc(username)}</strong>: ${esc(message)}`;
    c.appendChild(div);
    c.scrollTop = c.scrollHeight;
    while (c.children.length > 100) c.removeChild(c.firstChild);
}

// ══════════════════════════════════════════════════════════════════════════════
// Tournament Info
// ══════════════════════════════════════════════════════════════════════════════
async function loadTournamentInfo() {
    try {
        const r = await fetch(`/api/tables/${tableId}`);
        if (!r.ok) return;
        const t = await r.json();
        if (!t.tournament_id) return;
        const tr = await fetch(`/api/tournaments/${t.tournament_id}`);
        if (!tr.ok) return;
        tournamentInfo = await tr.json();
        updateTournamentBar();
        if (tournamentInfo.status === 'in_progress' && tournamentInfo.seconds_until_next_level !== null) {
            startTournamentTimer();
        }
    } catch(e) { console.error('loadTournamentInfo error:', e); }
}
function updateTournamentBar() {
    const bar = $('tournamentInfo');
    if (!bar || !tournamentInfo) {
        if (bar) bar.style.display = 'none';
        return;
    }
    bar.style.display = 'flex';
    const b = tournamentInfo.current_blinds || {};
    const lv = (tournamentInfo.current_level || 0) + 1;
    const nl = tournamentInfo.seconds_until_next_level;
    let nlS = '—';
    if (nl !== null && nl !== undefined && nl > 0) {
        const mins = Math.floor(nl / 60);
        const secs = nl % 60;
        nlS = `${mins}:${String(secs).padStart(2, '0')}`;
    }
    const v = tournamentInfo.game_variant === 'plo' ? 'PLO' : "Hold'em";
    const pl = `${tournamentInfo.players_count || '?'}/${tournamentInfo.max_players || '?'}`;
    const pr = tournamentInfo.prize_pool > 0 ? `💰 ${tournamentInfo.prize_pool.toLocaleString()}` : '🆓 Freeroll';
    const itm = tournamentInfo.itm_percentage ? `🎯 ITM ${tournamentInfo.itm_percentage}%` : '';
    const pa = tournamentInfo.status === 'paused' ? '<span style="color:var(--warning);font-weight:bold">⏸ PAUSE</span>' : '';
    const totalDuration = (tournamentInfo.current_blinds?.duration || 10) * 60;
    const progress = totalDuration > 0 && nl > 0 ? ((totalDuration - nl) / totalDuration * 100) : 0;
    bar.innerHTML = `
        <span>🏆 <strong>${esc(tournamentInfo.name)}</strong></span>
        <span>🎮 ${v}</span>
        <span>📊 Niv ${lv} — ${b.small_blind || '?'}/${b.big_blind || '?'}</span>
        <span class="timer-text">⏱ ${nlS}</span>
        <div class="level-progress" style="width:80px;height:4px;background:rgba(255,255,255,0.2);border-radius:2px;overflow:hidden;">
            <div style="width:${progress}%;height:100%;background:var(--accent);"></div>
        </div>
        <span>👥 ${pl}</span>
        <span>${pr}</span>
        <span>${itm}</span>
        ${pa}
    `;
}
function startTournamentTimer() {
    if (tournamentTimerInterval) clearInterval(tournamentTimerInterval);
    tournamentTimerInterval = setInterval(() => {
        if (tournamentInfo && tournamentInfo.seconds_until_next_level !== null && tournamentInfo.seconds_until_next_level !== undefined) {
            if (tournamentInfo.seconds_until_next_level > 0) {
                tournamentInfo.seconds_until_next_level -= 1;
                updateTournamentBar();
                const timerSpan = document.querySelector('#tournamentInfo .timer-text');
                if (tournamentInfo.seconds_until_next_level <= 10 && tournamentInfo.seconds_until_next_level > 0) {
                    if (timerSpan) timerSpan.style.color = 'var(--danger)';
                } else if (timerSpan) {
                    timerSpan.style.color = '';
                }
            }
        }
    }, 1000);
}

// ══════════════════════════════════════════════════════════════════════════════
// Options Modal (settings)
// ══════════════════════════════════════════════════════════════════════════════
function setupOptionsModal() {
    const btn = $('tableOptionsBtn');
    const modal = $('optionsModal');
    if (!btn || !modal) return;
    btn.addEventListener('click', () => {
        const s = SettingsManager.load();
        const map = {
            soundSetting: 'sound',
            soundVolume: 'soundVolume',
            animationSpeed: 'animationSpeed',
            cardDisplay: 'cardDeck',
            autoAction: 'autoAction',
            showHistory: 'showHistory',
            chatTimestamps: 'chatTimestamps',
            tableBackground: 'tableStyle',
        };
        for (const [elId, key] of Object.entries(map)) {
            const el = $(elId);
            if (el && s[key] !== undefined) {
                if (el.type === 'checkbox') el.checked = s[key];
                else el.value = s[key];
            }
        }
        modal.style.display = 'flex';
    });
    modal.querySelector('.close')?.addEventListener('click', () => modal.style.display = 'none');
    modal.addEventListener('click', (e) => { if (e.target === modal) modal.style.display = 'none'; });
    $('applyTableSettings')?.addEventListener('click', () => {
        const ns = {
            sound: $('soundSetting')?.value || 'on',
            soundVolume: parseFloat($('soundVolume')?.value) || 0.5,
            animationSpeed: $('animationSpeed')?.value || 'normal',
            cardDeck: $('cardDisplay')?.value || 'standard',
            autoAction: $('autoAction')?.value || 'never',
            showHistory: $('showHistory')?.value || 'all',
            chatTimestamps: $('chatTimestamps')?.checked || false,
            tableStyle: $('tableBackground')?.value || 'felt',
        };
        SettingsManager.save(ns);
        applyTableSettings();
        modal.style.display = 'none';
        toast('Préférences sauvegardées', 'success');
    });
}

// ══════════════════════════════════════════════════════════════════════════════
// Keyboard shortcuts
// ══════════════════════════════════════════════════════════════════════════════
function setupKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
        if (gameState?.current_actor !== currentUser?.id) return;
        switch (e.key.toLowerCase()) {
            case 'f': doAction('fold'); break;
            case 'c': ($('callBtn')?.style.display !== 'none') ? doAction('call') : doAction('check'); break;
            case 'r': showRaiseSlider(); break;
            case 'a': const al = currentQuickBets.find(b => b.key === 'allin'); if (al) doAction('all_in', al.amount); break;
            case 'escape': hideRaiseSlider(); break;
        }
    });
}

// ══════════════════════════════════════════════════════════════════════════════
// Animations
// ══════════════════════════════════════════════════════════════════════════════
function animateChip(fromElement, toElement, amount) {
    if (!fromElement || !toElement) return;
    const fromRect = fromElement.getBoundingClientRect();
    const toRect = toElement.getBoundingClientRect();
    const startX = fromRect.left + fromRect.width / 2 - toRect.left;
    const startY = fromRect.top + fromRect.height / 2 - toRect.top;
    const chip = document.createElement('div');
    chip.className = 'chip-animation';
    chip.style.left = toRect.left + 'px';
    chip.style.top = toRect.top + 'px';
    chip.style.setProperty('--startX', startX + 'px');
    chip.style.setProperty('--startY', startY + 'px');
    const label = document.createElement('span');
    label.textContent = amount.toLocaleString();
    label.style.position = 'absolute';
    label.style.top = '-20px';
    label.style.left = '50%';
    label.style.transform = 'translateX(-50%)';
    label.style.fontSize = '10px';
    label.style.fontWeight = 'bold';
    label.style.color = 'var(--accent)';
    label.style.whiteSpace = 'nowrap';
    chip.appendChild(label);
    document.body.appendChild(chip);
    setTimeout(() => chip.remove(), 500);
}
function animateCardDeal(cardElement, fromPosition) {
    if (!cardElement) return;
    const rect = cardElement.getBoundingClientRect();
    const startX = fromPosition.x - rect.left;
    const startY = fromPosition.y - rect.top;
    cardElement.style.setProperty('--startX', startX + 'px');
    cardElement.style.setProperty('--startY', startY + 'px');
    cardElement.classList.add('card-deal-animation');
    setTimeout(() => cardElement.classList.remove('card-deal-animation'), 400);
}
function animateCommunityCard(cardElement) {
    if (!cardElement) return;
    cardElement.classList.add('card-flip-animation');
    setTimeout(() => cardElement.classList.remove('card-flip-animation'), 300);
}

// ══════════════════════════════════════════════════════════════════════════════
// Back button & cleanup
// ══════════════════════════════════════════════════════════════════════════════
function setupBackButton() {
    const backBtn = $('backToLobbyBtn');
    if (backBtn) {
        backBtn.addEventListener('click', () => {
            if (gameState) {
                localStorage.setItem('last_table_state', JSON.stringify({
                    table_id: tableId,
                    timestamp: Date.now(),
                    hand: gameState.round
                }));
            }
            if (tournamentTimerInterval) clearInterval(tournamentTimerInterval);
            if (reconnectTimer) clearTimeout(reconnectTimer);
            window.location.href = '/lobby';
        });
    }
}

// Start
document.addEventListener('DOMContentLoaded', init);
