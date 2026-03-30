/**
 * lobby.js — Logique du lobby PokerEndPasse
 */

let currentUser = null;
let chatWs = null;
let chatReconnectTimer = null;

const $ = (id) => document.getElementById(id);

// ══════════════════════════════════════════════════════════════════════════════
// Init
// ══════════════════════════════════════════════════════════════════════════════
async function init() {
    await checkAuth();
    setupModals();
    setupOptionsModal();
    setupChat();
    await loadTournaments();
    await loadTables();
    setInterval(loadTournaments, 15000);
    setInterval(loadTables, 10000);
    if (typeof SoundManager !== 'undefined') SoundManager.init();
}

// ══════════════════════════════════════════════════════════════════════════════
// Auth
// ══════════════════════════════════════════════════════════════════════════════
async function checkAuth() {
    try {
        const resp = await fetch('/api/auth/me');
        if (resp.ok) {
            const data = await resp.json();
            if (data.authenticated && data.user) {
                currentUser = data.user;
                updateAuthUI();
                return;
            }
        }
    } catch (e) {}
    currentUser = null;
    updateAuthUI();
}

function updateAuthUI() {
    const display = $('userDisplay');
    const loginBtn = $('loginBtn');
    const registerBtn = $('registerBtn');
    const logoutBtn = $('logoutBtn');
    const adminLink = $('adminLink');
    const profileBtn = $('profileBtn');

    if (currentUser) {
        if (display) display.textContent = `👤 ${currentUser.username}`;
        if (loginBtn) loginBtn.style.display = 'none';
        if (registerBtn) registerBtn.style.display = 'none';
        if (logoutBtn) logoutBtn.style.display = '';
        if (profileBtn) profileBtn.style.display = '';
        if (adminLink) adminLink.style.display = currentUser.is_admin ? '' : 'none';
        if ($('chatInput')) { $('chatInput').disabled = false; $('chatSend').disabled = false; }
        // Mettre à jour l'avatar dans le profil
        const avatar = $('profileAvatar');
        if (avatar && currentUser.avatar && currentUser.avatar !== 'default') {
            avatar.src = currentUser.avatar;
        }
    } else {
        if (display) display.textContent = '';
        if (loginBtn) loginBtn.style.display = '';
        if (registerBtn) registerBtn.style.display = '';
        if (logoutBtn) logoutBtn.style.display = 'none';
        if (profileBtn) profileBtn.style.display = 'none';
        if (adminLink) adminLink.style.display = 'none';
    }
}

async function login(username, password, remember) {
    try {
        const resp = await fetch('/api/auth/login', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password, remember_me: remember }),
        });
        if (resp.ok) {
            const data = await resp.json();
            currentUser = data.user;
            updateAuthUI();
            closeModal('loginModal');
            showToast('Connecté!', 'success');
            connectChat();
        } else {
            const err = await resp.json().catch(() => ({}));
            showToast(err.detail || 'Erreur de connexion', 'error');
        }
    } catch (e) { showToast('Erreur réseau', 'error'); }
}

async function register(username, password, email) {
    try {
        const resp = await fetch('/api/auth/register', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password, email }),
        });
        if (resp.ok) {
            closeModal('registerModal');
            showToast('Compte créé! Connectez-vous.', 'success');
        } else {
            const err = await resp.json().catch(() => ({}));
            showToast(err.detail || 'Erreur', 'error');
        }
    } catch (e) { showToast('Erreur réseau', 'error'); }
}

async function logout() {
    await fetch('/api/auth/logout', { method: 'POST' });
    currentUser = null;
    updateAuthUI();
    showToast('Déconnecté', 'info');
}

// ══════════════════════════════════════════════════════════════════════════════
// Tournaments
// ══════════════════════════════════════════════════════════════════════════════
async function loadTournaments() {
    try {
        const resp = await fetch('/api/tournaments');
        if (!resp.ok) return;
        const tournaments = await resp.json();
        renderTournaments(tournaments);
    } catch (e) {}
}

function renderTournaments(tournaments) {
    const container = $('tournamentsList');
    if (!container) return;
    if (!tournaments.length) {
        container.innerHTML = '<div class="loading">Aucun tournoi pour le moment</div>';
        return;
    }
    container.innerHTML = tournaments.map(t => {
        const statusClass = `status-${t.status}`;
        const variantLabel = t.game_variant === 'plo' ? 'PLO' : "Hold'em";
        const canReg = t.can_register && currentUser;
        const isRegistered = t.registered_players?.some(p => p.user_id === currentUser?.id);
        const timeInfo = t.time_until_start > 0
            ? `Début dans ${Math.floor(t.time_until_start / 60)}min`
            : (t.status === 'in_progress' ? `Niveau ${t.current_level + 1}` : '');

        let actionBtn = '';
        if (t.status === 'registration') {
            if (isRegistered) {
                actionBtn = `<button class="btn-danger btn-small" onclick="unregisterTournament('${t.id}')">Se désinscrire</button>`;
            } else if (canReg) {
                actionBtn = `<button class="btn-success btn-small" onclick="registerTournament('${t.id}')">S'inscrire</button>`;
            }
        }
        if (t.status === 'in_progress' && isRegistered) {
            actionBtn = `<button class="btn-primary btn-small" onclick="joinMyTable('${t.id}')">Rejoindre ma table</button>`;
        }
        if (t.status === 'finished') {
            actionBtn = `<a href="/tournament/${t.id}/results" class="btn-primary btn-small">📊 Résultats</a>`;
        }
        const spectateBtn = t.status === 'in_progress' && t.tables?.length
            ? `<a href="/table/${t.tables[0]}" class="btn-small">👁️ Regarder</a>` : '';

        return `<div class="tournament-card">
            <h3>${escapeHtml(t.name)} <span class="status-badge ${statusClass}">${t.status}</span></h3>
            <div class="meta">
                <span>🎮 ${variantLabel}</span>
                <span>👥 ${t.players_count}/${t.max_players}</span>
                <span>💰 ${t.prize_pool || 'Freeroll'}</span>
            </div>
            <div class="meta"><span>${timeInfo}</span></div>
            ${t.current_blinds ? `<div class="meta"><span>Blinds: ${t.current_blinds.small_blind}/${t.current_blinds.big_blind}</span></div>` : ''}
            <div class="actions">${actionBtn} ${spectateBtn}</div>
        </div>`;
    }).join('');
}

async function registerTournament(tid) {
    if (!currentUser) { showToast('Connectez-vous d\'abord', 'error'); return; }
    try {
        const resp = await fetch(`/api/tournaments/${tid}/register`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: currentUser.id }),
        });
        if (resp.ok) { showToast('Inscrit!', 'success'); loadTournaments(); }
        else { const e = await resp.json(); showToast(e.detail || 'Erreur', 'error'); }
    } catch (e) { showToast('Erreur', 'error'); }
}

async function unregisterTournament(tid) {
    if (!currentUser) return;
    try {
        await fetch(`/api/tournaments/${tid}/unregister`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: currentUser.id }),
        });
        showToast('Désinscrit', 'info');
        loadTournaments();
    } catch (e) {}
}

async function joinMyTable(tid) {
    if (!currentUser) return;
    try {
        const resp = await fetch(`/api/tournaments/${tid}/my-table?user_id=${currentUser.id}`);
        if (resp.ok) {
            const data = await resp.json();
            window.location.href = `/table/${data.table_id}`;
        } else {
            showToast('Table introuvable', 'error');
        }
    } catch (e) { showToast('Erreur', 'error'); }
}

// ══════════════════════════════════════════════════════════════════════════════
// Tables
// ══════════════════════════════════════════════════════════════════════════════
async function loadTables() {
    try {
        const resp = await fetch('/api/tables');
        if (!resp.ok) return;
        renderTables(await resp.json());
    } catch (e) {}
}

function renderTables(tables) {
    const container = $('tablesList');
    if (!container) return;
    if (!tables.length) {
        container.innerHTML = '<div class="loading">Aucune table active</div>';
        return;
    }
    container.innerHTML = tables.map(t => `
        <div class="table-card">
            <h3>${escapeHtml(t.name)}</h3>
            <div class="meta">
                <span>👥 ${t.players?.length || 0}/${t.max_players}</span>
                <span>${t.game_variant === 'plo' ? 'PLO' : "Hold'em"}</span>
                <span class="status-badge status-${t.status}">${t.status}</span>
            </div>
            <div class="actions">
                <a href="/table/${t.id}" class="btn-small">👁️ Voir</a>
            </div>
        </div>
    `).join('');
}

// ══════════════════════════════════════════════════════════════════════════════
// Chat
// ══════════════════════════════════════════════════════════════════════════════
function setupChat() {
    const input = $('chatInput');
    const btn = $('chatSend');
    if (!input || !btn) return;

    const send = () => {
        const text = input.value.trim();
        if (!text || !chatWs || chatWs.readyState !== WebSocket.OPEN) return;
        chatWs.send(JSON.stringify({ type: 'message', message: text }));
        input.value = '';
    };
    btn.addEventListener('click', send);
    input.addEventListener('keypress', (e) => { if (e.key === 'Enter') send(); });

    // Smileys
    const sBtn = $('smileyBtn');
    const sDrop = $('smileyDropdown');
    if (sBtn && sDrop) {
        const emojis = ['😊','😂','🤣','😍','🤔','😎','🙄','😢','😡','🎉','👍','👎','🔥','💰','🃏','♠️','♥️','♣️','♦️','🏆','😏','🤑','😤','🥳'];
        sDrop.innerHTML = emojis.map(e => `<span class="emoji-item">${e}</span>`).join('');
        sBtn.addEventListener('click', (e) => { e.stopPropagation(); sDrop.classList.toggle('visible'); });
        sDrop.addEventListener('click', (e) => {
            if (e.target.classList.contains('emoji-item') && input) {
                input.value += e.target.textContent;
                input.focus();
                sDrop.classList.remove('visible');
            }
        });
        document.addEventListener('click', () => sDrop.classList.remove('visible'));
    }

    connectChat();
}

function connectChat() {
    if (!currentUser) return;
    if (chatWs && (chatWs.readyState === 0 || chatWs.readyState === 1)) return;
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    chatWs = new WebSocket(`${proto}//${location.host}/ws/chat`);
    chatWs.onopen = () => {
        chatWs.send(JSON.stringify({ type: 'join', user_id: currentUser.id, username: currentUser.username }));
    };
    chatWs.onmessage = (e) => {
        try { handleChatMessage(JSON.parse(e.data)); } catch (err) {}
    };
    chatWs.onclose = () => {
        chatReconnectTimer = setTimeout(connectChat, 5000);
    };
}

function handleChatMessage(msg) {
    const container = $('chatMessages');
    if (!container) return;
    const div = document.createElement('div');
    div.className = 'msg';
    if (msg.type === 'system') {
        div.className += ' msg-system';
        div.textContent = msg.message;
    } else if (msg.type === 'message') {
        div.innerHTML = `<span class="msg-user">${escapeHtml(msg.username)}</span>: ${escapeHtml(msg.message)}`;
    }
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

// ══════════════════════════════════════════════════════════════════════════════
// Modals
// ══════════════════════════════════════════════════════════════════════════════
function setupModals() {
    $('loginBtn')?.addEventListener('click', () => openModal('loginModal'));
    $('registerBtn')?.addEventListener('click', () => openModal('registerModal'));
    $('logoutBtn')?.addEventListener('click', logout);
    $('profileBtn')?.addEventListener('click', () => openModal('profileModal'));

    $('loginForm')?.addEventListener('submit', (e) => {
        e.preventDefault();
        login($('loginUsername').value, $('loginPassword').value, $('rememberMe')?.checked);
    });
    $('registerForm')?.addEventListener('submit', (e) => {
        e.preventDefault();
        register($('regUsername').value, $('regPassword').value, $('regEmail')?.value);
    });

    // Avatar upload
    $('uploadAvatarBtn')?.addEventListener('click', async () => {
        const fileInput = $('avatarUpload');
        const statusEl = $('uploadStatus');
        if (!fileInput?.files?.length) {
            if (statusEl) statusEl.textContent = 'Sélectionnez un fichier';
            return;
        }
        const file = fileInput.files[0];
        if (file.size > 2 * 1024 * 1024) {
            if (statusEl) statusEl.textContent = 'Fichier trop volumineux (max 2 Mo)';
            return;
        }
        const formData = new FormData();
        formData.append('file', file);
        try {
            if (statusEl) statusEl.textContent = 'Upload en cours…';
            const resp = await fetch('/api/profile/avatar', { method: 'POST', body: formData });
            if (resp.ok) {
                const data = await resp.json();
                if (data.avatar) {
                    currentUser.avatar = data.avatar;
                    const img = $('profileAvatar');
                    if (img) img.src = data.avatar;
                }
                if (statusEl) statusEl.innerHTML = '<span style="color:var(--success)">Avatar mis à jour!</span>';
                showToast('Avatar mis à jour', 'success');
            } else {
                const err = await resp.json().catch(() => ({}));
                if (statusEl) statusEl.textContent = err.detail || 'Erreur upload';
            }
        } catch (e) {
            if (statusEl) statusEl.textContent = 'Erreur réseau';
        }
    });

    document.querySelectorAll('.modal .close').forEach(btn => {
        btn.addEventListener('click', () => btn.closest('.modal').style.display = 'none');
    });
    window.addEventListener('click', (e) => {
        if (e.target.classList.contains('modal')) e.target.style.display = 'none';
    });
}

function setupOptionsModal() {
    $('optionsBtn')?.addEventListener('click', () => {
        if (typeof SettingsManager !== 'undefined') {
            const s = SettingsManager.load();
            const map = { soundSetting: 'sound', animationSpeed: 'animationSpeed',
                          cardDisplay: 'cardDisplay', autoAction: 'autoAction', showHistory: 'showHistory' };
            for (const [elId, key] of Object.entries(map)) {
                const el = $(elId);
                if (el && s[key] !== undefined) el.value = s[key];
            }
        }
        openModal('optionsModal');
    });

    $('saveSettings')?.addEventListener('click', () => {
        const ns = {
            sound: $('soundSetting')?.value || 'on',
            animationSpeed: $('animationSpeed')?.value || 'normal',
            cardDisplay: $('cardDisplay')?.value || 'standard',
            autoAction: $('autoAction')?.value || 'never',
            showHistory: $('showHistory')?.value || 'all',
        };
        if (typeof SettingsManager !== 'undefined') SettingsManager.save(ns);
        if (typeof SoundManager !== 'undefined') SoundManager.loadPreferences();
        closeModal('optionsModal');
        showToast('Préférences sauvegardées', 'success');
    });
}

function openModal(id) { const m = $(id); if (m) m.style.display = 'flex'; }
function closeModal(id) { const m = $(id); if (m) m.style.display = 'none'; }

// ══════════════════════════════════════════════════════════════════════════════
// Utils
// ══════════════════════════════════════════════════════════════════════════════
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
}

function showToast(message, type = 'info') {
    let container = $('toastContainer') || (() => {
        const c = document.createElement('div');
        c.id = 'toastContainer'; c.className = 'toast-container';
        document.body.appendChild(c); return c;
    })();
    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    el.textContent = message;
    container.appendChild(el);
    setTimeout(() => el.classList.add('show'), 10);
    setTimeout(() => { el.classList.remove('show'); setTimeout(() => el.remove(), 300); }, 3000);
}

// Start
document.addEventListener('DOMContentLoaded', init);
