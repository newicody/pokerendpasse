/**
 * table.js — Table de poker PokerEndPasse
 * ────────────────────────────────────────
 * Corrections appliquées :
 *  - Timer barre animée côté client (250 ms)
 *  - Remapping des sièges : joueur courant toujours en bas
 *  - Cartes community révélées progressivement (pas toutes dos)
 *  - Grandes cartes personnelles en bas-centre
 *  - Jetons misés + pot affichés
 *  - Widget deck + status ring SRA
 *  - Historique des mains (main droite)
 *  - Option BB display
 *  - Thèmes : ThemeManager.load() appelé à l'init
 *
 * Dépendances (chargées avant ce fichier) :
 *   theme_manager.js  →  window.ThemeManager
 *   cards.js          →  window.Cards
 *   hand_history.js   →  window.HandHistory
 */
'use strict';

// ════════════════════════════════════════════════════════════════════════════
// STATE
// ════════════════════════════════════════════════════════════════════════════

let ws               = null;
let gameState        = null;
let currentUser      = null;
let isSpectator      = false;
let reconnectAttempts = 0;
let reconnectTimer   = null;
let useBBDisplay     = false;
let prevCommunityLen = 0;   // Pour détecter les nouvelles cartes community
let prevRound        = 0;   // Pour détecter le début d'une nouvelle main

// Récupérés depuis les variables globales injectées par le serveur
const tableId   = window.tableId;
const tableName = window.tableName;

// ════════════════════════════════════════════════════════════════════════════
// MODULE : TIMER (animation côté client)
// ════════════════════════════════════════════════════════════════════════════

const Timer = (() => {
    let _interval = null;
    let _secs     = 0;
    let _maxSecs  = 20;
    let _isMe     = false;

    function _color(pct) {
        if (pct > 50) return '#27ae60';
        if (pct > 25) return '#ff9800';
        return '#e74c3c';
    }

    function _update() {
        _secs = Math.max(0, _secs - 0.25);
        const pct   = _maxSecs > 0 ? (_secs / _maxSecs) * 100 : 0;
        const color = _color(pct);

        // Texte du timer dans le panel action
        const te = document.getElementById('actionTimer');
        if (te) {
            te.textContent = _isMe
                ? `⏱ VOTRE TOUR — ${Math.ceil(_secs)}s`
                : `⏳ ${Math.ceil(_secs)}s`;
            te.style.color = color;
        }

        // Barre sous l'avatar du joueur actif (cherchée dans le DOM)
        const bar = document.querySelector('.player-seat.active-turn .seat-timer-bar');
        if (bar) {
            bar.style.width     = pct + '%';
            bar.style.background = color;
        }

        if (_secs <= 0) stop();
    }

    function start(serverSecs, maxSecs, isMe) {
        stop();
        _secs    = serverSecs;
        _maxSecs = maxSecs || 20;
        _isMe    = isMe;
        _update();
        _interval = setInterval(_update, 250);
    }

    function stop() {
        if (_interval) { clearInterval(_interval); _interval = null; }
        const te = document.getElementById('actionTimer');
        if (te) { te.textContent = ''; te.style.color = ''; }
    }

    return { start, stop };
})();

// ════════════════════════════════════════════════════════════════════════════
// MODULE : DECK WIDGET (status ring SRA)
// ════════════════════════════════════════════════════════════════════════════

const DeckWidget = (() => {
    const ICONS   = { idle: '⚪', committed: '🟡', verified: '✅', error: '🔴', computing: '🔄' };
    const LABELS  = {
        idle:      'Ring: Prêt',
        committed: 'Ring: Commit ✓',
        verified:  'Ring: Vérifié ✅',
        error:     'Ring: Erreur',
        computing: 'Ring: Calcul…',
    };

    function _render(status, detail) {
        const el = document.getElementById('ringStatus');
        if (!el) return;
        el.className = `ring-status rs-${status}`;
        const hash = detail ? `<span class="rs-hash">${detail.substring(0, 10)}…</span>` : '';
        el.innerHTML = `${ICONS[status] || '⚪'} ${LABELS[status] || status}${hash}`;
    }

    return {
        setStatus(status, detail) { _render(status, detail); },
        onCommit(msg)  { _render('committed', msg.commitment); },
        onReveal(msg)  { _render('verified',  msg.commitment); },
        reset()        { _render('idle', ''); },
    };
})();

// ════════════════════════════════════════════════════════════════════════════
// MODULE : RENDU TABLE
// ════════════════════════════════════════════════════════════════════════════

const TableUI = (() => {

    // ── Helpers ──────────────────────────────────────────────────────────────

    function _esc(text) {
        const d = document.createElement('div');
        d.textContent = text ?? '';
        return d.innerHTML;
    }

    function _fmtChips(chips) {
        if (useBBDisplay && gameState?.big_blind > 0) {
            const bb = (chips / gameState.big_blind).toFixed(1);
            return `${bb} BB`;
        }
        return Number(chips).toLocaleString();
    }

    function _avatarUrl(avatar) {
        if (!avatar) return '/assets/images/avatars/default.svg';
        if (avatar.startsWith('/')) return avatar;
        return `/assets/images/avatars/${avatar}.svg`;
    }

    /**
     * Calcule l'index de siège visuel.
     * Tourne les sièges pour que le joueur courant soit toujours en seat 0 (bas).
     */
    function _visualSeat(actualPos, myPos, maxSeats) {
        if (myPos === null || myPos === undefined) return actualPos;
        return (actualPos - myPos + maxSeats) % maxSeats;
    }

    // ── Sièges ───────────────────────────────────────────────────────────────

    function renderSeats(players) {
        const ctr = document.getElementById('playersContainer');
        if (!ctr) return;
        ctr.innerHTML = '';

        const max   = gameState?.max_players || 9;
        const me    = currentUser ? players.find(p => p.user_id === currentUser.id) : null;
        const myPos = me?.position ?? null;

        for (let i = 0; i < max; i++) {
            const pl         = players.find(p => p.position === i) || null;
            const visualSeat = _visualSeat(i, myPos, max);
            const div        = document.createElement('div');
            div.dataset.seat = visualSeat;

            if (!pl) {
                // Siège vide
                div.className = 'player-seat empty';
                div.innerHTML = `
                    <div class="seat-avatar-wrap">
                        <div class="seat-avatar empty-seat">💺</div>
                    </div>
                    <div class="seat-info">
                        <div class="seat-name">Siège ${i + 1}</div>
                    </div>`;
            } else {
                // Siège occupé
                const isMe    = pl.user_id === currentUser?.id;
                const st      = pl.status  || 'active';
                const isTurn  = gameState?.current_actor === pl.user_id && gameState?.status === 'in_progress';
                const isFolded = st === 'folded';
                const isAbsent = st === 'disconnected' || st === 'sitting_out';

                const cls = ['player-seat', 'occupied'];
                if (isMe)     cls.push('me');
                if (isFolded) cls.push('folded');
                if (isAbsent) cls.push('absent');
                if (isTurn)   cls.push('active-turn');
                div.className = cls.join(' ');

                // ── Cartes mini ──
                let cardsHtml = '';
                const inPlay = st === 'active' || st === 'all_in';
                if (pl.hole_cards?.length && !isFolded) {
                    // Mes propres cartes → afficher les vraies côté siège
                    const c0 = Cards.mini(pl.hole_cards[0], !isMe);
                    const c1 = Cards.mini(pl.hole_cards[1], !isMe);
                    cardsHtml = `<div class="seat-cards">${c0}${c1}</div>`;
                } else if (inPlay && gameState?.status === 'in_progress' && !isFolded) {
                    // Autre joueur en jeu : dos de carte
                    cardsHtml = `<div class="seat-cards">${Cards.mini(null, true)}${Cards.mini(null, true)}</div>`;
                }

                // ── Timer bar ──
                const timerHtml = isTurn
                    ? `<div class="seat-timer">
                           <div class="seat-timer-bar" style="width:100%"></div>
                       </div>`
                    : '';

                // ── Marqueurs ──
                const mk = [];
                if (pl.is_dealer)     mk.push('<span class="marker marker-d">D</span>');
                if (pl.is_small_blind) mk.push('<span class="marker marker-sb">SB</span>');
                if (pl.is_big_blind)  mk.push('<span class="marker marker-bb">BB</span>');
                if (st === 'all_in')  mk.push('<span class="marker marker-allin">ALL IN</span>');
                if (isAbsent)         mk.push('<span class="marker marker-afk">AFK</span>');

                // ── Mise du joueur ──
                const bet   = pl.current_bet || pl.bet || 0;
                const chips = pl.chips ?? pl.stack ?? 0;
                const betHtml = bet > 0
                    ? `<div class="seat-bet">
                           <div class="chip-dot"></div>
                           ${bet.toLocaleString()}
                       </div>`
                    : '';

                div.innerHTML = `
                    ${cardsHtml}
                    <div class="seat-avatar-wrap">
                        <img class="seat-avatar" 
                             src="${_avatarUrl(pl.avatar)}"
                             alt="${_esc(pl.username)}"
                             onerror="this.src='/assets/images/avatars/default.svg'">
                        ${timerHtml}
                    </div>
                    <div class="seat-info">
                        <div class="seat-name">${_esc(pl.username)}</div>
                        <div class="seat-chips">${_fmtChips(chips)}</div>
                    </div>
                    ${betHtml}
                    ${mk.length ? `<div class="marker-row">${mk.join('')}</div>` : ''}`;
            }

            ctr.appendChild(div);
        }
    }

    // ── Mes grandes cartes ────────────────────────────────────────────────────

    function renderMyCards(players) {
        const display = document.getElementById('myCardsDisplay');
        const inner   = document.getElementById('myCardsInner');
        if (!display || !inner) return;

        if (!currentUser || isSpectator) {
            display.style.display = 'none';
            return;
        }

        const me = players.find(p => p.user_id === currentUser.id);
        if (!me || !me.hole_cards?.length || me.status === 'folded') {
            display.style.display = 'none';
            return;
        }

        display.style.display = 'flex';
        inner.innerHTML = me.hole_cards
            .map(c => `<div class="my-card">${Cards.html(c)}</div>`)
            .join('');
    }

    // ── Cartes community (révélation progressive) ─────────────────────────────

    function renderCommunity(cards) {
        const ctr = document.getElementById('communityCards');
        if (!ctr) return;

        const newLen = cards ? cards.length : 0;

        // Rien à afficher (début de main ou attente)
        if (newLen === 0) {
            ctr.innerHTML = '';
            prevCommunityLen = 0;
            return;
        }

        // Révélation partielle : on re-render uniquement si changement
        if (newLen === prevCommunityLen) return;

        // Détecter les nouvelles cartes pour HandHistory
        if (newLen === 3 && prevCommunityLen < 3) {
            HandHistory.addEvent('flop', cards.slice(0, 3));
        } else if (newLen === 4 && prevCommunityLen === 3) {
            HandHistory.addEvent('turn', cards[3]);
        } else if (newLen === 5 && prevCommunityLen === 4) {
            HandHistory.addEvent('river', cards[4]);
        }
        prevCommunityLen = newLen;

        // Re-render
        ctr.innerHTML = '';
        cards.forEach((card, i) => {
            const div = document.createElement('div');
            div.className = 'community-card';
            // Séparateur visuel entre flop et turn, turn et river
            if (i === 3 || i === 4) div.classList.add('late-card');
            div.innerHTML = Cards.html(card);
            div.style.animationDelay = `${i * 0.08}s`;
            ctr.appendChild(div);
        });
    }

    // ── Pot ───────────────────────────────────────────────────────────────────

    function renderPot(pot) {
        const el = document.getElementById('pot');
        if (!el) return;
        if (!pot || pot === 0) {
            el.style.display = 'none';
        } else {
            el.style.display = '';
            el.textContent = `Pot: ${pot.toLocaleString()}`;
        }
    }

    // ── Infos de jeu ──────────────────────────────────────────────────────────

    function renderInfo(s) {
        const STATUS_LABELS = {
            waiting: 'Attente', in_progress: 'En jeu', finished: 'Terminé', showdown: 'Showdown',
        };
        _setText('gameStatus',   STATUS_LABELS[s.status] || s.status);
        _setText('gameRound',    s.round || 0);
        _setText('bettingRound', s.betting_round || 'Preflop');
        _setText('gameBlinds',   `${s.small_blind || '?'}/${s.big_blind || '?'}`);
        _setText('tableName',    s.table_name || tableName || 'Table');

        // Joueurs encore en jeu
        const alive = (s.players || []).filter(p => p.status !== 'eliminated').length;
        _setText('playersAlive', alive);

        // Chips + mise du joueur courant
        if (currentUser) {
            const me = (s.players || []).find(p => p.user_id === currentUser.id);
            if (me) {
                _setText('playerChips', `${_fmtChips(me.chips ?? me.stack ?? 0)} chips`);
            }
        }
    }

    function _setText(id, val) {
        const el = document.getElementById(id);
        if (el) el.textContent = val;
    }

    // ── Actions ───────────────────────────────────────────────────────────────

    function renderActions(isMyTurn, s) {
        const panel = document.getElementById('actionPanel');
        if (!panel) return;
        panel.style.display = isMyTurn ? 'block' : 'none';
        if (!isMyTurn) return;

        const me       = (s.players || []).find(p => p.user_id === currentUser?.id);
        const myBet    = me?.current_bet || me?.bet || 0;
        const tableBet = s.current_bet || 0;
        const toCall   = tableBet - myBet;

        const checkBtn = document.getElementById('checkBtn');
        const callBtn  = document.getElementById('callBtn');
        if (checkBtn && callBtn) {
            if (toCall <= 0) {
                checkBtn.style.display = '';
                callBtn.style.display  = 'none';
            } else {
                checkBtn.style.display = 'none';
                callBtn.style.display  = '';
                callBtn.textContent    = `Call ${toCall.toLocaleString()} (C)`;
            }
        }

        // Slider de raise
        const minRaise = s.min_raise || s.big_blind || 20;
        const myChips  = me?.chips ?? me?.stack ?? 0;
        const slider   = document.getElementById('raiseAmount');
        if (slider) {
            slider.min   = minRaise;
            slider.max   = myChips;
            slider.step  = Math.max(1, Math.floor(s.big_blind / 2) || 5);
            slider.value = Math.min(Math.max(slider.value, minRaise), myChips);
            const valEl = document.getElementById('raiseValue');
            if (valEl) valEl.textContent = Number(slider.value).toLocaleString();
        }
    }

    return { renderSeats, renderMyCards, renderCommunity, renderPot, renderInfo, renderActions };
})();

// ════════════════════════════════════════════════════════════════════════════
// WEBSOCKET
// ════════════════════════════════════════════════════════════════════════════

function connectWS() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const uid   = currentUser?.id || 'spectator';
    ws = new WebSocket(`${proto}//${location.host}/ws/${tableId}/${uid}`);

    ws.onopen = () => {
        reconnectAttempts = 0;
        if (!isSpectator) toast('Connecté', 'success');
    };

    ws.onmessage = e => {
        try { onMessage(JSON.parse(e.data)); }
        catch (err) { console.error('[WS] Parse error:', err); }
    };

    ws.onclose = () => {
        if (!isSpectator) toast('Déconnecté', 'error');
        scheduleReconnect();
    };

    ws.onerror = () => {};
}

function scheduleReconnect() {
    if (reconnectTimer) clearTimeout(reconnectTimer);
    if (reconnectAttempts >= 10) {
        toast('Connexion perdue', 'error');
        return;
    }
    const delay = Math.min(1000 * Math.pow(2, reconnectAttempts++), 30000);
    reconnectTimer = setTimeout(connectWS, delay);
}

function onMessage(msg) {
    switch (msg.type) {
        case 'game_update':
        case 'game_state':
            render(msg.data || msg);
            break;

        case 'deck_commitment':
            DeckWidget.onCommit(msg);
            break;

        case 'deck_reveal':
            DeckWidget.onReveal(msg);
            break;

        case 'hand_result':
            // Fin de main : archiver dans HandHistory
            HandHistory.endHand(msg.winners || [], msg.pot || 0);
            DeckWidget.reset();
            break;

        case 'reconnected':
            toast('Reconnecté !', 'success');
            break;

        case 'blind_level_change':
            toast(`Niveau ${msg.level} : ${msg.small_blind}/${msg.big_blind}`, 'info');
            break;

        case 'player_eliminated':
            toast(`${msg.username || '?'} éliminé (#${msg.rank})`, 'info');
            loadTournamentInfo();
            break;

        case 'table_chat':
            addTableChat(msg);
            break;

        case 'error':
            toast(msg.message || 'Erreur', 'error');
            break;

        case 'pong':
            break;

        default:
            // Ignorer les messages inconnus silencieusement
            break;
    }
}

// ════════════════════════════════════════════════════════════════════════════
// RENDU PRINCIPAL
// ════════════════════════════════════════════════════════════════════════════

function render(s) {
    if (!s) return;
    gameState = s;

    const players = s.players || [];

    // Début de nouvelle main ?
    if (s.round && s.round !== prevRound) {
        HandHistory.startHand(s.round, s.small_blind, s.big_blind);
        prevRound        = s.round;
        prevCommunityLen = 0;   // reset pour la nouvelle main
        DeckWidget.setStatus('computing');
    }

    // Showdown : enregistrer
    if (s.status === 'showdown') {
        HandHistory.addEvent('showdown', null);
    }

    TableUI.renderSeats(players);
    TableUI.renderMyCards(players);
    TableUI.renderCommunity(s.community_cards);
    TableUI.renderPot(s.pot);
    TableUI.renderInfo(s);

    // Timer
    if (s.action_timer != null && s.current_actor && s.status === 'in_progress') {
        const isMe = s.current_actor === currentUser?.id;
        Timer.start(s.action_timer, 20, isMe);
    } else {
        Timer.stop();
    }

    // Actions panel
    if (!isSpectator && currentUser) {
        const isMyTurn = s.current_actor === currentUser.id && s.status === 'in_progress';
        TableUI.renderActions(isMyTurn, s);
    }
}

// ════════════════════════════════════════════════════════════════════════════
// ACTIONS JOUEUR
// ════════════════════════════════════════════════════════════════════════════

async function sendAction(action, amount = 0) {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        toast('Pas de connexion', 'error');
        return;
    }
    if (!currentUser || isSpectator) return;

    try {
        const resp = await fetch(`/api/tables/${tableId}/action`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: currentUser.id, action, amount }),
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            toast(err.detail || 'Erreur action', 'error');
        }
    } catch (e) {
        toast('Erreur réseau', 'error');
    }
}

// ════════════════════════════════════════════════════════════════════════════
// CHAT DE TABLE
// ════════════════════════════════════════════════════════════════════════════

function setupTableChat() {
    const input  = document.getElementById('tableChatInput');
    const sendBtn = document.getElementById('tableChatSend');
    if (!input || !sendBtn) return;

    if (!isSpectator && currentUser) {
        input.disabled  = false;
        sendBtn.disabled = false;
    }

    const send = () => {
        const msg = input.value.trim();
        if (!msg || !ws || ws.readyState !== WebSocket.OPEN) return;
        ws.send(JSON.stringify({ type: 'table_chat', message: msg, user_id: currentUser?.id }));
        input.value = '';
    };

    sendBtn.addEventListener('click', send);
    input.addEventListener('keydown', e => {
        if (e.key === 'Enter') { e.preventDefault(); send(); }
    });
}

function addTableChat(msg) {
    const box = document.getElementById('tableChatMessages');
    if (!box) return;

    const isSystem = !msg.user_id || msg.user_id === 'system';
    const div = document.createElement('div');
    div.className = isSystem ? 'tchat-msg tchat-system' : 'tchat-msg';
    div.innerHTML = isSystem
        ? `<i>${escapeHtml(msg.message || '')}</i>`
        : `<span class="tchat-user">${escapeHtml(msg.username || '?')}</span>: ${escapeHtml(msg.message || '')}`;
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;

    // Limiter l'historique affiché
    while (box.children.length > 100) box.removeChild(box.firstChild);
}

// ════════════════════════════════════════════════════════════════════════════
// TOURNOI INFO
// ════════════════════════════════════════════════════════════════════════════

async function loadTournamentInfo() {
    const bar = document.getElementById('tournamentInfo');
    if (!bar) return;
    if (!gameState?.tournament_id) return;

    try {
        const r = await fetch(`/api/tournaments/${gameState.tournament_id}`);
        if (!r.ok) return;
        const t = await r.json();
        bar.innerHTML = `
            <span>🏆 ${escapeHtml(t.name || '')}</span>
            <span>Niveau ${t.current_level ?? '?'}</span>
            <span>Blinds: ${t.small_blind ?? '?'}/${t.big_blind ?? '?'}</span>
            <span>Joueurs: ${t.players_alive ?? '?'}</span>`;
    } catch (_) {}
}

// ════════════════════════════════════════════════════════════════════════════
// EVENTS & SETUP
// ════════════════════════════════════════════════════════════════════════════

function setupEvents() {
    // Boutons d'action
    document.getElementById('foldBtn')?.addEventListener('click', () => sendAction('fold'));
    document.getElementById('checkBtn')?.addEventListener('click', () => sendAction('check'));
    document.getElementById('callBtn')?.addEventListener('click', () => sendAction('call'));

    document.getElementById('raiseBtn')?.addEventListener('click', () => {
        const slider = document.getElementById('raiseSlider');
        if (slider) slider.style.display = slider.style.display === 'none' ? 'flex' : 'none';
    });

    document.getElementById('confirmRaise')?.addEventListener('click', () => {
        const amt = parseInt(document.getElementById('raiseAmount')?.value || '0');
        sendAction('raise', amt);
        const slider = document.getElementById('raiseSlider');
        if (slider) slider.style.display = 'none';
    });

    document.getElementById('cancelRaise')?.addEventListener('click', () => {
        const slider = document.getElementById('raiseSlider');
        if (slider) slider.style.display = 'none';
    });

    // Slider raise → valeur en temps réel
    document.getElementById('raiseAmount')?.addEventListener('input', e => {
        const valEl = document.getElementById('raiseValue');
        if (valEl) valEl.textContent = Number(e.target.value).toLocaleString();
    });

    // Quitter la table
    document.getElementById('leaveTableBtn')?.addEventListener('click', async () => {
        if (!confirm('Quitter la table ?')) return;
        if (!isSpectator && currentUser) {
            try {
                await fetch(`/api/tables/${tableId}/leave?user_id=${currentUser.id}`, { method: 'POST' });
            } catch (_) {}
        }
        location.href = '/lobby';
    });

    // Option BB
    document.getElementById('bbDisplay')?.addEventListener('change', e => {
        useBBDisplay = e.target.checked;
        if (gameState) render(gameState);
    });

    // Sélecteur de thème
    const themeSelect = document.getElementById('themeSelect');
    if (themeSelect && window.ThemeManager) {
        ThemeManager.populateSelect(themeSelect);
        themeSelect.addEventListener('change', e => {
            ThemeManager.save(e.target.value);
        });
    }

    // Raccourcis clavier
    document.addEventListener('keydown', e => {
        const panel = document.getElementById('actionPanel');
        if (!panel || panel.style.display === 'none' || isSpectator) return;
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

        switch (e.key.toLowerCase()) {
            case 'f':
                e.preventDefault();
                sendAction('fold');
                break;
            case 'c': {
                e.preventDefault();
                const me = gameState?.players?.find(p => p.user_id === currentUser?.id);
                const toCall = (gameState?.current_bet || 0) - (me?.current_bet || me?.bet || 0);
                sendAction(toCall <= 0 ? 'check' : 'call');
                break;
            }
            case 'r':
                e.preventDefault();
                document.getElementById('raiseBtn')?.click();
                break;
        }
    });

    // Ping WebSocket
    setInterval(() => {
        if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ping' }));
    }, 25000);

    // Rafraîchissement infos tournoi
    setInterval(loadTournamentInfo, 15000);
}

// ════════════════════════════════════════════════════════════════════════════
// UTILITAIRES
// ════════════════════════════════════════════════════════════════════════════

function toast(message, type = 'info') {
    let el = document.getElementById('toast');
    if (!el) {
        el = document.createElement('div');
        el.id = 'toast';
        el.className = 'toast';
        document.body.appendChild(el);
    }
    el.textContent = message;
    el.className = `toast ${type} show`;
    clearTimeout(el._t);
    el._t = setTimeout(() => el.classList.remove('show'), 3000);
}

function escapeHtml(text) {
    const d = document.createElement('div');
    d.textContent = text ?? '';
    return d.innerHTML;
}

// ════════════════════════════════════════════════════════════════════════════
// INITIALISATION
// ════════════════════════════════════════════════════════════════════════════

async function loadUser() {
    try {
        const r = await fetch('/api/auth/me');
        if (r.ok) {
            const d = await r.json();
            if (d?.id) { currentUser = d; return; }
        }
    } catch (_) {}
    currentUser = null;
}

async function init() {
    // Appliquer le thème sauvegardé
    if (window.ThemeManager) {
        ThemeManager.load();
        const themeSelect = document.getElementById('themeSelect');
        if (themeSelect) ThemeManager.populateSelect(themeSelect);
    }

    await loadUser();

    const params = new URLSearchParams(location.search);
    isSpectator  = params.get('spectate') === 'true' || !currentUser;

    if (isSpectator) {
        const sb = document.getElementById('spectatorBanner');
        if (sb) sb.style.display = 'block';
        const ap = document.getElementById('actionPanel');
        if (ap) ap.style.display = 'none';
    }

    // Nom de table initial
    const tn = document.getElementById('tableName');
    if (tn) tn.textContent = tableName || 'Table';

    // Initialiser HandHistory
    HandHistory.render();

    // Connexion WS
    connectWS();

    // Wiring UI
    setupEvents();
    setupTableChat();
    loadTournamentInfo();
}

// Lancement
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
