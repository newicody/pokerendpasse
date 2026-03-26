/**
 * lobby.js — Page principale du lobby poker
 * Version corrigée — tous les bugs fixés
 *
 * Dépendances (chargées avant) :
 *   /js/settings_manager.js
 *   /js/sound_manager.js
 */

'use strict';

// ═════════════════════════════════════════════════════════════════════════════
// 1. État global
// ═════════════════════════════════════════════════════════════════════════════

let currentUser = null;
let isGuest = false;
let chatWs = null;
let _refreshInterval = null;
const _clocks = {};

// Chat settings
let chatHideJoinMessages = false;
let chatAutoConvertSmileys = true;

// ═════════════════════════════════════════════════════════════════════════════
// 2. Utilitaires
// ═════════════════════════════════════════════════════════════════════════════

function escapeHtml(text) {
    const d = document.createElement('div');
    d.textContent = text ?? '';
    return d.innerHTML;
}

function formatDate(isoStr) {
    if (!isoStr) return 'N/A';
    try { return new Date(isoStr).toLocaleString(); }
    catch (_) { return isoStr; }
}

function formatCountdown(secs, short = false) {
    if (secs === null || secs === undefined || secs < 0) return '—';
    secs = Math.floor(secs);
    const h = Math.floor(secs / 3600);
    const m = Math.floor((secs % 3600) / 60);
    const s = secs % 60;
    if (short) {
        if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
        return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    }
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
}

function getOrdinal(n) {
    const s = ['th', 'st', 'nd', 'rd'], v = n % 100;
    return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

function nowUTC() { return Date.now() / 1000; }

function isoToSec(iso) {
    if (!iso) return null;
    try { return new Date(iso).getTime() / 1000; }
    catch (_) { return null; }
}

function showToast(message, type = 'info') {
    if (typeof SoundManager !== 'undefined') {
        SoundManager.play(type === 'success' ? 'toast_success' : type === 'error' ? 'toast_error' : 'tick');
    }
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

// ═════════════════════════════════════════════════════════════════════════════
// 3. Clock manager (pour les countdowns live)
// ═════════════════════════════════════════════════════════════════════════════

function _startClock(key, fn) {
    _clearClock(key);
    fn(); // appel immédiat
    _clocks[key] = setInterval(fn, 1000);
}

function _clearClock(key) {
    if (_clocks[key]) { clearInterval(_clocks[key]); delete _clocks[key]; }
}

function _clearClocksBy(prefix) {
    Object.keys(_clocks).filter(k => k.startsWith(prefix)).forEach(_clearClock);
}

// ═════════════════════════════════════════════════════════════════════════════
// 4. Auth
// ═════════════════════════════════════════════════════════════════════════════

async function checkAuth() {
    try {
        const response = await fetch('/api/auth/me');
        if (response.ok) {
            const data = await response.json();
            if (data && data.id) {
                currentUser = data;
                isGuest = false;
                // Stocker pour les autres pages
                window.currentUser = currentUser;
                updateUserDisplay();
                document.getElementById('guestWarning')?.classList.add('hidden');
                return;
            }
        }
    } catch (error) {
        console.error('Auth check failed:', error);
    }
    // Mode invité
    isGuest = true;
    currentUser = null;
    window.currentUser = null;
    updateUserDisplay();
    document.getElementById('guestWarning')?.classList.remove('hidden');
}

function updateUserDisplay() {
    const usernameSpan = document.getElementById('username');
    const userStatus = document.getElementById('userStatus');
    const loginBtn = document.getElementById('loginBtn');
    const registerBtn = document.getElementById('registerBtn');
    const logoutBtn = document.getElementById('logoutBtn');
    const profileLink = document.getElementById('profileLink');
    const adminBtn = document.getElementById('adminBtn');
    const avatarDiv = document.getElementById('userAvatar');

    if (currentUser && !isGuest) {
        if (usernameSpan) usernameSpan.textContent = currentUser.username;
        if (userStatus) userStatus.textContent = 'Connected';
        if (loginBtn) loginBtn.style.display = 'none';
        if (registerBtn) registerBtn.style.display = 'none';
        if (logoutBtn) logoutBtn.style.display = 'block';
        if (profileLink) profileLink.style.display = 'inline-block';
        if (adminBtn) adminBtn.style.display = currentUser.is_admin ? 'inline-block' : 'none';
        if (avatarDiv) {
            const src = currentUser.avatar && currentUser.avatar.startsWith('/uploads/')
                ? currentUser.avatar
                : `/assets/images/avatars/${currentUser.avatar || 'default'}.svg`;
            avatarDiv.innerHTML = `<img src="${src}" alt="avatar" style="width:40px;height:40px;border-radius:50%;">`;
        }
    } else {
        if (usernameSpan) usernameSpan.textContent = 'Guest';
        if (userStatus) userStatus.textContent = 'Spectator mode';
        if (loginBtn) loginBtn.style.display = 'block';
        if (registerBtn) registerBtn.style.display = 'block';
        if (logoutBtn) logoutBtn.style.display = 'none';
        if (profileLink) profileLink.style.display = 'none';
        if (adminBtn) adminBtn.style.display = 'none';
        if (avatarDiv) avatarDiv.innerHTML = '<div style="width:40px;height:40px;border-radius:50%;background:#555;display:flex;align-items:center;justify-content:center;">👤</div>';
    }
}

async function login(username, password, rememberMe = false) {
    try {
        const response = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password, remember_me: rememberMe })
        });
        if (response.ok) {
            const data = await response.json();
            currentUser = data.user;
            isGuest = false;
            window.currentUser = currentUser;
            updateUserDisplay();
            closeModal('loginModal');
            showToast('Login successful!', 'success');
            document.getElementById('guestWarning')?.classList.add('hidden');
            initChat();
            await loadTournaments();
        } else {
            const error = await response.json().catch(() => ({}));
            showToast(error.detail || 'Login failed', 'error');
        }
    } catch (error) {
        console.error('Login error:', error);
        showToast('Network error', 'error');
    }
}

async function register(username, password, email) {
    try {
        const response = await fetch('/api/auth/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password, email })
        });
        if (response.ok) {
            const data = await response.json();
            currentUser = data.user;
            isGuest = false;
            window.currentUser = currentUser;
            updateUserDisplay();
            closeModal('registerModal');
            showToast('Registration successful!', 'success');
            document.getElementById('guestWarning')?.classList.add('hidden');
            initChat();
            await loadTournaments();
        } else {
            const error = await response.json().catch(() => ({}));
            showToast(error.detail || 'Registration failed', 'error');
        }
    } catch (error) {
        console.error('Register error:', error);
        showToast('Network error', 'error');
    }
}

async function logout() {
    try {
        await fetch('/api/auth/logout', { method: 'POST' });
    } catch (_) { }
    currentUser = null;
    isGuest = true;
    window.currentUser = null;
    updateUserDisplay();
    document.getElementById('guestWarning')?.classList.remove('hidden');
    if (chatWs) { chatWs.close(); chatWs = null; }
    showToast('Logged out', 'info');
}

function showLoginModal() {
    const m = document.getElementById('loginModal');
    if (m) m.style.display = 'flex';
}

function showRegisterModal() {
    const m = document.getElementById('registerModal');
    if (m) m.style.display = 'flex';
}

// Rendre accessible globalement
window.showLoginModal = showLoginModal;
window.showRegisterModal = showRegisterModal;

// ═════════════════════════════════════════════════════════════════════════════
// 5. Chargement & rendu des tournois
// ═════════════════════════════════════════════════════════════════════════════

async function loadTournaments() {
    try {
        const res = await fetch('/api/tournaments');
        if (!res.ok) throw new Error('API error');
        const all = await res.json();

        const active = all.filter(t => t.status === 'in_progress');
        const upcoming = all.filter(t => t.status === 'registration' || t.status === 'starting');
        const finished = all.filter(t => t.status === 'finished').slice(0, 5);

        renderActiveTournaments(active);
        renderUpcomingTournaments(upcoming);
        renderFinishedTournaments(finished);
    } catch (e) {
        console.error('loadTournaments error:', e);
    }
}

function renderActiveTournaments(tournaments) {
    const grid = document.getElementById('activeTournamentsGrid');
    if (!grid) return;
    _clearClocksBy('active_');

    if (!tournaments.length) {
        grid.innerHTML = '<div class="empty-state">No active tournaments</div>';
        return;
    }

    grid.innerHTML = tournaments.map(t => `
        <div class="tournament-card tournament-card--active" onclick="showTournamentDetails('${t.id}')">
            <div class="tournament-header">
                <span class="tournament-name">🏆 ${escapeHtml(t.name)}</span>
                <span class="tournament-status in_progress">🎲 In Progress</span>
            </div>
            <div class="tournament-details">
                <div><span class="label">Players:</span><span class="value">${t.players_count}</span></div>
                <div><span class="label">Level:</span><span class="value">${t.current_level + 1}</span></div>
                <div><span class="label">Blinds:</span><span class="value">${t.current_blinds?.small_blind ?? '?'}/${t.current_blinds?.big_blind ?? '?'}</span></div>
                <div><span class="label">Prize:</span><span class="value">${(t.prize_pool || 0).toLocaleString()}</span></div>
            </div>
            <div class="clock-bar">
                <span>⏱ Next level: </span>
                <span id="blind-clock-${t.id}">—</span>
            </div>
            <button class="spectate-btn" onclick="event.stopPropagation(); window.showTournamentTables('${t.id}')">
                👁 Watch Tables
            </button>
        </div>
    `).join('');

    // Clocks de blind par tournoi
    tournaments.forEach(t => {
        let secs = t.seconds_until_next_level ?? null;
        _startClock(`active_${t.id}`, () => {
            const el = document.getElementById(`blind-clock-${t.id}`);
            if (!el) { _clearClock(`active_${t.id}`); return; }
            if (secs === null) { el.textContent = '—'; return; }
            el.textContent = formatCountdown(secs, true);
            el.style.color = secs <= 30 ? '#e74c3c' : secs <= 60 ? '#ff9800' : '#27ae60';
            secs = Math.max(0, secs - 1);
        });
    });
}

function renderUpcomingTournaments(tournaments) {
    const grid = document.getElementById('upcomingTournamentsGrid');
    if (!grid) return;
    _clearClocksBy('upcoming_');

    if (!tournaments.length) {
        grid.innerHTML = '<div class="empty-state">No upcoming tournaments</div>';
        return;
    }

    grid.innerHTML = tournaments.map(t => {
        const isRegistered = currentUser && t.registered_players
            ? t.registered_players.some(p => p.user_id === currentUser.id)
            : false;
        return `
        <div class="tournament-card" onclick="showTournamentDetails('${t.id}')">
            <div class="tournament-header">
                <span class="tournament-name">📅 ${escapeHtml(t.name)}</span>
                <span class="tournament-status registration">📝 Registration</span>
            </div>
            <div class="tournament-details">
                <div><span class="label">Players:</span><span class="value">${t.players_count}/${t.max_players}</span></div>
                <div><span class="label">Start:</span><span class="value">${formatDate(t.start_time)}</span></div>
                <div><span class="label">Prize:</span><span class="value">${(t.prize_pool || 0).toLocaleString()}</span></div>
                <div><span class="label">Blinds:</span><span class="value">${t.blind_structure?.[0]?.small_blind ?? 10}/${t.blind_structure?.[0]?.big_blind ?? 20}</span></div>
            </div>
            <div class="clock-bar">
                <span>⏰ Starts in: </span>
                <span id="start-clock-${t.id}">—</span>
            </div>
            ${isRegistered
            ? `<button class="join-btn" style="background:#e74c3c" onclick="event.stopPropagation(); window.unregisterFromTournament('${t.id}')">❌ Cancel Registration</button>`
            : t.can_register
                ? `<button class="join-btn" onclick="event.stopPropagation(); window.registerForTournament('${t.id}')">✅ Register</button>`
                : `<div style="text-align:center;padding:8px;opacity:0.6">Registration closed</div>`
        }
        </div>
    `}).join('');

    // Clocks countdown vers start
    tournaments.forEach(t => {
        const startSec = isoToSec(t.start_time);
        _startClock(`upcoming_${t.id}`, () => {
            const el = document.getElementById(`start-clock-${t.id}`);
            if (!el) { _clearClock(`upcoming_${t.id}`); return; }
            if (!startSec) { el.textContent = '—'; return; }
            const d = startSec - nowUTC();
            el.textContent = d > 0 ? formatCountdown(d) : 'Starting...';
            el.style.color = d < 60 ? '#e74c3c' : d < 300 ? '#ff9800' : '#27ae60';
        });
    });
}

function renderFinishedTournaments(tournaments) {
    const grid = document.getElementById('finishedTournamentsGrid');
    if (!grid) return;

    if (!tournaments.length) {
        grid.innerHTML = '<div class="empty-state">No finished tournaments yet</div>';
        return;
    }

    grid.innerHTML = tournaments.map(t => `
        <div class="tournament-card" onclick="showTournamentDetails('${t.id}')" style="opacity:0.7">
            <div class="tournament-header">
                <span class="tournament-name">🏁 ${escapeHtml(t.name)}</span>
                <span class="tournament-status" style="background:rgba(150,150,150,0.3);color:#aaa">Finished</span>
            </div>
            <div class="tournament-details">
                <div><span class="label">Players:</span><span class="value">${t.total_players || t.players_count}</span></div>
                <div><span class="label">Prize:</span><span class="value">${(t.prize_pool || 0).toLocaleString()}</span></div>
            </div>
        </div>
    `).join('');
}

// ═════════════════════════════════════════════════════════════════════════════
// 6. Détails du tournoi (modal)
// ═════════════════════════════════════════════════════════════════════════════

window.showTournamentDetails = async function (tournamentId) {
    const modal = document.getElementById('tournamentModal');
    const detailsDiv = document.getElementById('tournamentDetails');
    if (!modal || !detailsDiv) return;

    detailsDiv.innerHTML = '<div class="loading">Loading...</div>';
    modal.style.display = 'flex';

    try {
        const res = await fetch(`/api/tournaments/${tournamentId}`);
        if (!res.ok) throw new Error('API error');
        const t = await res.json();

        const isRegistered = currentUser
            ? (t.registered_players || t.players || []).some(p => p.user_id === currentUser.id && p.status === 'registered')
            : false;

        const blindsHtml = (t.blind_structure || []).map((b, i) => `
            <div class="blind-level-item" ${i === t.current_level ? 'style="background:rgba(255,215,0,0.15);font-weight:bold"' : ''}>
                <span class="level-num">${b.level || i + 1}</span>
                <span>${b.small_blind}/${b.big_blind}</span>
                <span>${b.duration || 10} min</span>
            </div>
        `).join('') || '<div style="opacity:0.5">Default structure</div>';

        const playersHtml = (t.registered_players || []).map((p, i) => `
            <div class="player-item">
                <span>#${i + 1} ${escapeHtml(p.username)}</span>
                <small>${formatDate(p.registered_at)}</small>
            </div>
        `).join('') || '<div style="opacity:0.5">No players yet</div>';

        const prizesHtml = (t.prizes || []).map(p => `
            <div class="prize-item">
                <span>${getOrdinal(p.rank)}</span>
                <span>${p.amount?.toLocaleString() || 0} (${p.percentage}%)</span>
            </div>
        `).join('') || '<div style="opacity:0.5">No prizes configured</div>';

        const rankingHtml = (t.ranking || []).map(p => `
            <div class="player-item">
                <span>#${p.eliminated_rank} ${escapeHtml(p.username)}</span>
            </div>
        `).join('');

        // Status labels
        const statusLabels = {
            registration: '📝 Registration Open',
            starting: '⚡ Starting...',
            in_progress: '🎲 In Progress',
            finished: '🏁 Finished',
            cancelled: '❌ Cancelled',
        };

        // Action button
        let actionHtml = '';
        if (t.status === 'registration') {
            if (isRegistered) {
                actionHtml = `<button class="unregister-tournament-btn" onclick="window.unregisterFromTournament('${t.id}')">❌ Cancel Registration</button>`;
            } else if (t.can_register) {
                actionHtml = `<button class="register-tournament-btn" onclick="window.registerForTournament('${t.id}')">✅ Register Now</button>`;
            } else {
                actionHtml = '<div class="status-message">Registration not available</div>';
            }
        } else if (t.status === 'in_progress') {
            actionHtml = `<button class="spectate-tournament-btn" onclick="window.showTournamentTables('${t.id}')">👁 Watch Tables</button>`;
        } else if (t.status === 'finished') {
            actionHtml = '<div class="status-message">🏁 Tournament finished</div>';
        }

        detailsDiv.innerHTML = `
            <div class="tournament-info-header">
                <h2>🏆 ${escapeHtml(t.name)}</h2>
                <span class="tournament-status ${t.status}">${statusLabels[t.status] ?? t.status}</span>
            </div>
            ${t.description ? `<p style="opacity:0.8;margin-bottom:15px">${escapeHtml(t.description)}</p>` : ''}

            <div class="tournament-timeline" style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:20px">
                <div><span style="opacity:0.6">Registration:</span><br>${formatDate(t.registration_start)} — ${formatDate(t.registration_end)}</div>
                <div><span style="opacity:0.6">Start:</span><br>${formatDate(t.start_time)}</div>
                <div><span style="opacity:0.6">Players:</span><br>${t.players_count}/${t.max_players}</div>
                <div><span style="opacity:0.6">Level:</span><br>${(t.current_level || 0) + 1} — ${t.current_blinds?.small_blind ?? '?'}/${t.current_blinds?.big_blind ?? '?'}</div>
            </div>

            <div class="tournament-tabs" style="display:flex;gap:5px;border-bottom:1px solid rgba(255,215,0,0.3);margin-bottom:15px">
                <button class="tab-btn active" data-tab="blinds">Blinds</button>
                <button class="tab-btn" data-tab="players">Players (${t.players_count})</button>
                <button class="tab-btn" data-tab="prizes">Prizes</button>
                ${rankingHtml ? '<button class="tab-btn" data-tab="ranking">Ranking</button>' : ''}
            </div>

            <div class="tournament-tab-content active" data-tab-content="blinds">
                <div class="blind-structure"><h4>Blind Structure</h4>
                    <div class="blind-structure-list">${blindsHtml}</div>
                </div>
            </div>
            <div class="tournament-tab-content" data-tab-content="players">
                <div class="registered-players"><h4>Registered Players</h4>
                    <div class="players-list">${playersHtml}</div>
                </div>
            </div>
            <div class="tournament-tab-content" data-tab-content="prizes">
                <div class="prize-structure"><h4>Prize Structure</h4>
                    <div class="prize-list">${prizesHtml}</div>
                </div>
            </div>
            ${rankingHtml ? `
            <div class="tournament-tab-content" data-tab-content="ranking">
                <div class="ranking"><h4>Live Ranking</h4>
                    <div class="players-list">${rankingHtml}</div>
                </div>
            </div>` : ''}

            <div style="margin-top:20px">${actionHtml}</div>
        `;

        // Bind tabs
        const tabBtns = detailsDiv.querySelectorAll('.tab-btn');
        const tabContents = detailsDiv.querySelectorAll('.tournament-tab-content');
        tabBtns.forEach(btn => {
            btn.onclick = () => {
                const tabId = btn.dataset.tab;
                tabBtns.forEach(b => b.classList.toggle('active', b.dataset.tab === tabId));
                tabContents.forEach(c => c.classList.toggle('active', c.dataset.tabContent === tabId));
            };
        });

    } catch (e) {
        console.error('Error loading tournament details:', e);
        detailsDiv.innerHTML = '<div class="error">Failed to load tournament details</div>';
    }
};

// ═════════════════════════════════════════════════════════════════════════════
// 7. Actions tournoi
// ═════════════════════════════════════════════════════════════════════════════

window.registerForTournament = async function (tournamentId) {
    if (!currentUser || isGuest) { showLoginModal(); return; }
    try {
        const res = await fetch(`/api/tournaments/${tournamentId}/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: currentUser.id }),
        });
        if (res.ok) {
            showToast('Registration successful!', 'success');
            closeModal('tournamentModal');
            await loadTournaments();
        } else {
            const err = await res.json().catch(() => ({}));
            showToast(err.detail || 'Registration failed', 'error');
        }
    } catch (_) { showToast('Network error', 'error'); }
};

window.unregisterFromTournament = async function (tournamentId) {
    if (!confirm('Cancel your registration?')) return;
    try {
        const res = await fetch(`/api/tournaments/${tournamentId}/unregister`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });
        if (res.ok) {
            showToast('Registration cancelled', 'info');
            closeModal('tournamentModal');
            await loadTournaments();
        } else {
            showToast('Could not cancel registration', 'error');
        }
    } catch (_) { showToast('Network error', 'error'); }
};

// ═════════════════════════════════════════════════════════════════════════════
// 8. Spectating tables
// ═════════════════════════════════════════════════════════════════════════════

window.showTournamentTables = async function (tournamentId) {
    try {
        const res = await fetch(`/api/tournaments/${tournamentId}/tables`);
        if (!res.ok) throw new Error('API error');
        const tables = await res.json();

        const modal = document.getElementById('tournamentTablesModal');
        const listDiv = document.getElementById('tournamentTablesList');
        if (!modal || !listDiv) return;

        listDiv.innerHTML = tables.length
            ? tables.map(tb => `
                <div class="table-item">
                    <div>
                        <strong>🎲 ${escapeHtml(tb.name)}</strong>
                        <small>${tb.current_players}/${tb.max_players} players</small>
                    </div>
                    <button class="watch-table-btn" onclick="window.watchTable('${tb.id}')">👁 Watch</button>
                </div>`).join('')
            : '<div class="empty-state">No tables available</div>';

        modal.style.display = 'flex';
    } catch (_) { showToast('Could not load tables', 'error'); }
};

window.watchTable = function (tableId) {
    window.location.href = `/table/${tableId}?spectate=true`;
};

// ═════════════════════════════════════════════════════════════════════════════
// 9. Chat WebSocket
// ═════════════════════════════════════════════════════════════════════════════

function initChat() {
    if (!currentUser || isGuest) return;
    if (chatWs && chatWs.readyState === WebSocket.OPEN) return;

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${protocol}//${window.location.host}/ws/chat`;

    console.log('Connecting to chat:', url);

    try {
        chatWs = new WebSocket(url);

        chatWs.onopen = () => {
            console.log('Chat connected');
            chatWs.send(JSON.stringify({
                type: 'join',
                user_id: currentUser.id,
                username: currentUser.username
            }));
            // Activer input
            const input = document.getElementById('chatInput');
            const btn = document.getElementById('chatSendBtn');
            if (input) input.disabled = false;
            if (btn) btn.disabled = false;
        };

        chatWs.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                handleChatMessage(msg);
            } catch (e) {
                console.error('Chat parse error:', e);
            }
        };

        chatWs.onclose = () => {
            console.log('Chat disconnected');
            const input = document.getElementById('chatInput');
            const btn = document.getElementById('chatSendBtn');
            if (input) input.disabled = true;
            if (btn) btn.disabled = true;
            // Reconnexion auto après 5s
            setTimeout(() => {
                if (currentUser && !isGuest) initChat();
            }, 5000);
        };

        chatWs.onerror = (error) => {
            console.error('Chat WS error:', error);
        };
    } catch (error) {
        console.error('Failed to create chat WebSocket:', error);
    }
}

function handleChatMessage(msg) {
    if (msg.type === 'system') {
        if (chatHideJoinMessages && (msg.message?.includes('joined') || msg.message?.includes('left'))) return;
        addChatMessage(null, msg.message, 'system');
        // Update user count
        if (msg.user_count !== undefined) {
            const countEl = document.getElementById('chatUserCount');
            if (countEl) countEl.textContent = `${msg.user_count} online`;
        }
    } else if (msg.type === 'message') {
        addChatMessage(msg.username, msg.message, msg.user_id === currentUser?.id ? 'self' : 'user', msg.mediaType, msg.data, msg.filename);
    }
}

function addChatMessage(username, message, type = 'user', mediaType = null, mediaData = null, filename = null) {
    const container = document.getElementById('chatMessages');
    if (!container) return;

    const div = document.createElement('div');
    div.className = `chat-message ${type}`;
    const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    if (type === 'system') {
        div.innerHTML = `<span class="time">[${time}]</span> ${escapeHtml(message)}`;
    } else if (mediaType === 'image' && mediaData) {
        div.innerHTML = `
            <span class="username">${escapeHtml(username)}</span>
            <span class="time">[${time}]</span>
            <div style="margin-top:5px"><img src="${mediaData}" alt="${escapeHtml(filename || 'image')}" style="max-width:200px;border-radius:8px;cursor:pointer" onclick="window.open('${mediaData}')"></div>
        `;
    } else {
        let text = escapeHtml(message);
        if (chatAutoConvertSmileys) {
            text = text.replace(/:\)/g, '😊').replace(/;\)/g, '😉').replace(/:D/g, '😃')
                .replace(/:\(/g, '😢').replace(/:P/g, '😛').replace(/<3/g, '❤️')
                .replace(/:O/g, '😮').replace(/XD/g, '😆');
        }
        div.innerHTML = `
            <span class="username">${escapeHtml(username)}</span>
            <span class="time">[${time}]</span>
            <span class="message-text">${text}</span>
        `;
    }

    container.appendChild(div);
    div.scrollIntoView({ behavior: 'smooth' });

    // Limiter à 200 messages
    while (container.children.length > 200) {
        container.removeChild(container.firstChild);
    }
}

function sendChatMessage() {
    const input = document.getElementById('chatInput');
    if (!input || !chatWs || chatWs.readyState !== WebSocket.OPEN) return;

    const text = input.value.trim();
    if (!text) return;

    chatWs.send(JSON.stringify({ type: 'message', message: text }));
    input.value = '';
}

// ═════════════════════════════════════════════════════════════════════════════
// 10. Modals & event listeners
// ═════════════════════════════════════════════════════════════════════════════

function closeModal(modalId) {
    const m = document.getElementById(modalId);
    if (m) m.style.display = 'none';
}
window.closeModal = closeModal;

function setupAuthModals() {
    // Login form
    const loginForm = document.getElementById('loginForm');
    if (loginForm) {
        loginForm.onsubmit = (e) => {
            e.preventDefault();
            login(
                document.getElementById('loginUsername').value,
                document.getElementById('loginPassword').value,
                document.getElementById('rememberMe')?.checked
            );
        };
    }

    // Register form
    const registerForm = document.getElementById('registerForm');
    if (registerForm) {
        registerForm.onsubmit = (e) => {
            e.preventDefault();
            register(
                document.getElementById('regUsername').value,
                document.getElementById('regPassword').value,
                document.getElementById('regEmail')?.value
            );
        };
    }

    // Close buttons
    document.querySelectorAll('.modal .close').forEach(closeBtn => {
        closeBtn.onclick = () => {
            closeBtn.closest('.modal').style.display = 'none';
        };
    });

    // Click outside modal
    window.addEventListener('click', (event) => {
        if (event.target.classList.contains('modal')) {
            event.target.style.display = 'none';
        }
    });
}

function setupEventListeners() {
    // Auth buttons
    document.getElementById('loginBtn')?.addEventListener('click', showLoginModal);
    document.getElementById('registerBtn')?.addEventListener('click', showRegisterModal);
    document.getElementById('logoutBtn')?.addEventListener('click', logout);

    // Chat
    document.getElementById('chatSendBtn')?.addEventListener('click', sendChatMessage);
    document.getElementById('chatInput')?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') sendChatMessage();
    });

    // Chat settings
    document.getElementById('chatSettingsBtn')?.addEventListener('click', () => {
        const m = document.getElementById('chatSettingsModal');
        if (m) {
            document.getElementById('hideJoinMessages').checked = chatHideJoinMessages;
            document.getElementById('autoConvertSmileys').checked = chatAutoConvertSmileys;
            m.style.display = 'flex';
        }
    });

    document.getElementById('saveChatSettings')?.addEventListener('click', () => {
        chatHideJoinMessages = document.getElementById('hideJoinMessages')?.checked ?? false;
        chatAutoConvertSmileys = document.getElementById('autoConvertSmileys')?.checked ?? true;
        try {
            localStorage.setItem('poker_chat_settings', JSON.stringify({ chatHideJoinMessages, chatAutoConvertSmileys }));
        } catch (_) { }
        closeModal('chatSettingsModal');
        showToast('Chat settings saved', 'success');
    });

    // Load chat settings
    try {
        const saved = JSON.parse(localStorage.getItem('poker_chat_settings') || '{}');
        chatHideJoinMessages = saved.chatHideJoinMessages ?? false;
        chatAutoConvertSmileys = saved.chatAutoConvertSmileys ?? true;
    } catch (_) { }

    // Smiley picker
    const smileyBtn = document.getElementById('smileyBtn');
    const smileyDropdown = document.getElementById('smileyDropdown');
    if (smileyBtn && smileyDropdown) {
        const emojis = ['😊', '😂', '🤣', '😍', '🤔', '😎', '🙄', '😢', '😡', '🎉', '👍', '👎', '🔥', '💰', '🃏', '♠️', '♥️', '♣️', '♦️', '🏆'];
        smileyDropdown.innerHTML = emojis.map(e => `<span class="emoji-item" style="cursor:pointer;font-size:20px;padding:4px">${e}</span>`).join('');
        smileyDropdown.style.cssText = 'position:absolute;bottom:100%;left:0;background:rgba(0,0,0,0.9);border:1px solid rgba(255,215,0,0.3);border-radius:8px;padding:8px;display:none;flex-wrap:wrap;gap:4px;max-width:250px;z-index:100';

        smileyBtn.onclick = () => {
            smileyDropdown.style.display = smileyDropdown.style.display === 'none' ? 'flex' : 'none';
        };

        smileyDropdown.addEventListener('click', (e) => {
            if (e.target.classList.contains('emoji-item')) {
                const input = document.getElementById('chatInput');
                if (input) {
                    input.value += e.target.textContent;
                    input.focus();
                }
                smileyDropdown.style.display = 'none';
            }
        });
    }
}

// ═════════════════════════════════════════════════════════════════════════════
// 11. Options / paramètres
// ═════════════════════════════════════════════════════════════════════════════

function setupOptionsModal() {
    const optionsBtn = document.getElementById('optionsBtn');
    const optionsModal = document.getElementById('optionsModal');
    const saveBtn = document.getElementById('saveSettings');

    if (optionsBtn) {
        optionsBtn.onclick = () => {
            if (typeof SettingsManager !== 'undefined') {
                const settings = SettingsManager.load();
                const fields = ['soundSetting', 'animationSpeed', 'cardDisplay', 'autoAction', 'showHistory'];
                // Map setting keys to field ids (soundSetting maps to 'sound')
                const keyMap = { soundSetting: 'sound' };
                fields.forEach(id => {
                    const el = document.getElementById(id);
                    const key = keyMap[id] || id;
                    if (el && settings[key] !== undefined) el.value = settings[key];
                });
            }
            if (optionsModal) optionsModal.style.display = 'flex';
        };
    }

    if (saveBtn) {
        saveBtn.onclick = () => {
            const newSettings = {
                sound: document.getElementById('soundSetting')?.value || 'on',
                animationSpeed: document.getElementById('animationSpeed')?.value || 'normal',
                cardDisplay: document.getElementById('cardDisplay')?.value || 'standard',
                autoAction: document.getElementById('autoAction')?.value || 'never',
                showHistory: document.getElementById('showHistory')?.value || 'all',
            };
            if (typeof SettingsManager !== 'undefined') SettingsManager.save(newSettings);
            if (typeof SoundManager !== 'undefined') SoundManager.loadPreferences();
            closeModal('optionsModal');
            showToast('Settings saved!', 'success');
        };
    }
}

// ═════════════════════════════════════════════════════════════════════════════
// 12. Heure serveur
// ═════════════════════════════════════════════════════════════════════════════

function _startServerClock() {
    async function update() {
        try {
            const res = await fetch('/api/server/time');
            if (res.ok) {
                const data = await res.json();
                const el = document.getElementById('serverTime');
                if (el) el.textContent = data.time || '--:--:--';
            }
        } catch (_) { }
    }
    update();
    setInterval(update, 5000);
}

// ═════════════════════════════════════════════════════════════════════════════
// 13. Initialisation
// ═════════════════════════════════════════════════════════════════════════════

async function init() {
    // Charger sons en premier
    if (typeof SoundManager !== 'undefined') SoundManager.init();

    await checkAuth();
    await loadTournaments();

    // Rafraîchissement auto
    if (_refreshInterval) clearInterval(_refreshInterval);
    _refreshInterval = setInterval(loadTournaments, 10000);

    setupEventListeners();
    setupAuthModals();
    setupOptionsModal();
    _startServerClock();

    // Chat uniquement si connecté
    if (!isGuest) initChat();

    console.log('Lobby initialized', { isGuest, user: currentUser?.username });
}

// Aussi exposer initCurrentUser pour table.js
window.initCurrentUser = async function () {
    await checkAuth();
    return window.currentUser;
};

// Démarrage
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
