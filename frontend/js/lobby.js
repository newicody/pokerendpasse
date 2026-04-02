// frontend/js/lobby.js
/**
 * lobby.js — Logique du lobby PokerEndPasse
 * Version avec options avancées (profil, jeu, son, chat, réseau, historique, admin)
 */

const $ = (id) => document.getElementById(id);
let currentUser = null;
let chatWs = null;
let chatReconnectTimer = null;

// ══════════════════════════════════════════════════════════════════════════════
// Initialisation
// ══════════════════════════════════════════════════════════════════════════════
async function init() {
    await checkAuth();
    setupModals();
    setupOptionsModal();
    setupChat();
    setupLocalTime();
    await loadTournaments();
    await loadTables();
    setInterval(loadTournaments, 15000);
    setInterval(loadTables, 10000);
    if (typeof SoundManager !== 'undefined') SoundManager.init();
    if (typeof SettingsManager !== 'undefined') {
        SettingsManager.load();
        applyGlobalSettings();
    }
    setupThemeSelector();
    setupCardDeckSelector();
    setupTableStyleSelector();
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
    const optionsBtn = $('optionsBtn');

    if (currentUser) {
        i	f (display) display.textContent = `👤 ${currentUser.username}`;
        if (loginBtn) loginBtn.style.display = 'none';
        if (registerBtn) registerBtn.style.display = 'none';
        if (logoutBtn) logoutBtn.style.display = '';
        if (optionsBtn) optionsBtn.style.display = '';
        if ($('chatInput')) { $('chatInput').disabled = false; $('chatSend').disabled = false; }
        // Mettre à jour l'avatar dans le profil
        const avatar = $('profileAvatar');
        if (avatar && currentUser.avatar && currentUser.avatar !== 'default') {
            avatar.src = currentUser.avatar;
        }
        // Afficher ou masquer l'onglet admin
        const adminTabBtn = document.getElementById('adminTabBtn');
        if (adminTabBtn) adminTabBtn.style.display = currentUser.is_admin ? '' : 'none'
        // Remplir le champ pseudo
        const usernameField = $('profileUsername');
        if (usernameField) usernameField.value = currentUser.username;
        const emailField = $('profileEmail');
        if (emailField && currentUser.email) emailField.value = currentUser.email;
    } else {
        if (display) display.textContent = '';
        if (loginBtn) loginBtn.style.display = '';
        if (registerBtn) registerBtn.style.display = '';
        if (logoutBtn) logoutBtn.style.display = 'none';
        if (optionsBtn) optionsBtn.style.display = '';
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
    if (!currentUser) {
        showToast('Connectez-vous d\'abord', 'error');
        return;
    }

    try {
        const resp = await fetch(`/api/tournaments/${tid}/my-table?user_id=${currentUser.id}`);

        if (resp.ok) {
            const data = await resp.json();
            if (data.table_id) {
                window.location.href = `/table/${data.table_id}`;
                return;
            }
        }

        if (resp.status === 404) {
            const error = await resp.json().catch(() => ({}));
            if (error.reassign || error.waiting || !error.table_id) {
                showToast('Recherche de votre table...', 'info');

                const rejoinResp = await fetch(`/api/tournaments/${tid}/rejoin`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ user_id: currentUser.id })
                });

                if (rejoinResp.ok) {
                    const data = await rejoinResp.json();
                    if (data.table_id) {
                        showToast('Table trouvée!', 'success');
                        window.location.href = `/table/${data.table_id}`;
                        return;
                    }
                } else {
                    const err = await rejoinResp.json();
                    showToast(err.detail || 'Impossible de rejoindre le tournoi', 'error');
                }
            } else {
                showToast(error.detail || 'Vous n\'êtes pas inscrit à ce tournoi', 'error');
            }
        } else {
            showToast('Erreur lors de la récupération de la table', 'error');
        }
    } catch (e) {
        console.error(e);
        showToast('Erreur réseau', 'error');
    }
}

async function showTournamentDetails(tid) {
    try {
        const resp = await fetch(`/api/tournaments/${tid}`);
        if (!resp.ok) throw new Error('Tournoi introuvable');
        const t = await resp.json();

        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.style.display = 'flex';

        const escLocal = (text) => {
            const div = document.createElement('div');
            div.textContent = text || '';
            return div.innerHTML;
        };

        const blindsHtml = t.current_blinds ?
            `<div class="info-row"><span class="label">Blinds actuels</span><span class="value">${t.current_blinds.small_blind}/${t.current_blinds.big_blind}${t.current_blinds.ante ? ` (ante ${t.current_blinds.ante})` : ''}</span></div>` : '';

        const nextLevelHtml = t.seconds_until_next_level != null ?
            `<div class="info-row"><span class="label">Prochain niveau</span><span class="value">${Math.floor(t.seconds_until_next_level / 60)}:${String(t.seconds_until_next_level % 60).padStart(2, '0')}</span></div>` : '';

        const startTime = new Date(t.start_time).toLocaleString();
        const regStart = new Date(t.registration_start).toLocaleString();
        const regEnd = new Date(t.registration_end).toLocaleString();

        const playersList = t.registered_players?.slice(0, 20).map(p =>
            `<div class="player-item">${escLocal(p.username)}${p.avatar ? `<img src="${p.avatar}" class="mini-avatar">` : ''}</div>`
        ).join('') || '<div class="empty">Aucun joueur inscrit</div>';

        const rankingHtml = t.ranking?.slice(0, 10).map((p, i) => `
            <div class="rank-item">
                <span class="rank-num">${i+1}</span>
                <span class="rank-name">${escLocal(p.username)}</span>
                <span class="rank-chips">${p.chips?.toLocaleString() || 0}</span>
                <span class="rank-status">${p.status === 'registered' ? '✅' : '❌'}</span>
            </div>
        `).join('') || '<div class="empty">Aucun classement</div>';

        const statusClass = `status-${t.status}`;
        const statusText = {
            'registration': '📝 Inscriptions',
            'in_progress': '🔄 En cours',
            'paused': '⏸ Pause',
            'finished': '🏆 Terminé'
        }[t.status] || t.status;

        modal.innerHTML = `
            <div class="modal-content" style="max-width: 700px; max-height: 80vh; overflow-y: auto;">
                <span class="close">&times;</span>
                <h2>🏆 ${escLocal(t.name)} <span class="status-badge ${statusClass}">${statusText}</span></h2>

                <div class="tournament-detail-grid">
                    <div class="detail-section">
                        <h3>📋 Informations</h3>
                        <div class="info-row"><span class="label">Variante</span><span class="value">${t.game_variant === 'plo' ? 'Pot-Limit Omaha' : "No-Limit Hold'em"}</span></div>
                        <div class="info-row"><span class="label">Joueurs</span><span class="value">${t.players_count}/${t.max_players}</span></div>
                        <div class="info-row"><span class="label">Prize pool</span><span class="value">${t.prize_pool > 0 ? `💰 ${t.prize_pool.toLocaleString()}` : '🆓 Freeroll'}</span></div>
                        <div class="info-row"><span class="label">ITM</span><span class="value">${t.itm_percentage}%</span></div>
                        <div class="info-row"><span class="label">Chips départ</span><span class="value">${t.starting_chips?.toLocaleString()}</span></div>
                        ${blindsHtml}
                        ${nextLevelHtml}
                    </div>

                    <div class="detail-section">
                        <h3>⏰ Horaires</h3>
                        <div class="info-row"><span class="label">Début inscriptions</span><span class="value">${regStart}</span></div>
                        <div class="info-row"><span class="label">Fin inscriptions</span><span class="value">${regEnd}</span></div>
                        <div class="info-row"><span class="label">Début tournoi</span><span class="value">${startTime}</span></div>
                    </div>

                    <div class="detail-section">
                        <h3>👥 Inscrits (${t.registered_players?.length || 0})</h3>
                        <div class="players-list">${playersList}</div>
                    </div>

                    <div class="detail-section">
                        <h3>📊 Classement (top 10)</h3>
                        <div class="ranking-list">${rankingHtml}</div>
                    </div>
                </div>
                <div class="detail-actions" style="margin-top: 20px; display: flex; gap: 10px; justify-content: flex-end;">
                    ${t.can_register && currentUser ? 
                        `<button class="btn-success" onclick="registerTournament('${t.id}'); document.querySelector('.modal')?.remove();">S'inscrire</button>` : ''}
                    ${t.status === 'in_progress' && t.registered_players?.some(p => p.user_id === currentUser?.id) ?
                        `<button class="btn-primary" onclick="joinMyTable('${t.id}'); document.querySelector('.modal')?.remove();">🎮 Rejoindre ma table</button>` : ''}
                    ${t.status === 'in_progress' && !t.registered_players?.some(p => p.user_id === currentUser?.id) ?
                        `<button class="btn-secondary" disabled>Tournoi en cours</button>` : ''}
                    ${t.status === 'finished' ?
                        `<a href="/tournament/${t.id}/results" class="btn-primary">📊 Voir les résultats</a>` : ''}
                    ${t.status === 'in_progress' && t.tables?.length ?
                        `<a href="/table/${t.tables[0]}" class="btn-secondary">👁️ Regarder</a>` : ''}
                </div>
                <style>
                    .tournament-detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 16px; }
                    .detail-section { background: var(--bg-tertiary); border-radius: 8px; padding: 12px; border: 1px solid var(--border-subtle); }
                    .detail-section h3 { font-size: 14px; margin-bottom: 10px; color: var(--accent); }
                    .info-row { display: flex; justify-content: space-between; padding: 4px 0; font-size: 13px; }
                    .players-list { max-height: 200px; overflow-y: auto; }
                    .player-item { display: flex; align-items: center; gap: 8px; padding: 4px 0; font-size: 12px; border-bottom: 1px solid var(--border-subtle); }
                    .mini-avatar { width: 24px; height: 24px; border-radius: 50%; object-fit: cover; }
                    .ranking-list { max-height: 200px; overflow-y: auto; }
                    .rank-item { display: flex; gap: 8px; padding: 4px 0; font-size: 12px; border-bottom: 1px solid var(--border-subtle); }
                    .rank-num { width: 30px; font-weight: bold; color: var(--accent); }
                    .rank-name { flex: 1; }
                    .rank-chips { font-family: monospace; color: var(--success); }
                    .rank-status { width: 30px; text-align: center; }
                    .empty { text-align: center; color: var(--text-muted); padding: 20px; }
                    @media (max-width: 600px) { .tournament-detail-grid { grid-template-columns: 1fr; } }
                </style>
            </div>
        `;

        document.body.appendChild(modal);
        modal.querySelector('.close')?.addEventListener('click', () => modal.remove());
        modal.addEventListener('click', (e) => { if (e.target === modal) modal.remove(); });

    } catch (e) {
        console.error(e);
        showToast('Erreur chargement du tournoi', 'error');
    }
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
            actionBtn = `<button class="btn-primary btn-small" onclick="joinMyTable('${t.id}')">🎮 Rejoindre ma table</button>`;
        }
        
        if (t.status === 'finished') {
            actionBtn = `<a href="/tournament/${t.id}/results" class="btn-primary btn-small">📊 Résultats</a>`;
        }
        
        const spectateBtn = t.status === 'in_progress' && t.tables?.length
            ? `<a href="/table/${t.tables[0]}" class="btn-small">👁️ Regarder</a>` : '';
        
        const detailBtn = `<button class="btn-small" onclick="showTournamentDetails('${t.id}')">📋 Détail</button>`;

        // Informations supplémentaires (blinds, prize pool, ITM)
        const blindsHtml = t.current_blinds ?
            `<div class="meta"><span>Blinds: ${t.current_blinds.small_blind}/${t.current_blinds.big_blind}</span></div>` : '';
        const prizeHtml = t.prize_pool > 0 ?
            `<div class="meta"><span>💰 Prize: ${t.prize_pool.toLocaleString()}</span><span>🎯 ITM: ${t.itm_percentage}%</span></div>` :
            `<div class="meta"><span>🆓 Freeroll</span></div>`;

        return `<div class="tournament-card">
            <h3>${escapeHtml(t.name)} <span class="status-badge ${statusClass}">${t.status}</span></h3>
            <div class="meta">
                <span>🎮 ${variantLabel}</span>
                <span>👥 ${t.players_count}/${t.max_players}</span>
            </div>
            ${prizeHtml}
            ${blindsHtml}
            <div class="meta"><span>${timeInfo}</span></div>
            <div class="actions">${actionBtn} ${spectateBtn} ${detailBtn}</div>
        </div>`;
    }).join('');
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
    const showTimestamps = SettingsManager?.get('chatTimestamps') !== false;
    if (msg.type === 'system') {
        div.className += ' msg-system';
        div.textContent = msg.message;
        if (showTimestamps && msg.timestamp) {
            const time = new Date(msg.timestamp).toLocaleTimeString();
            div.innerHTML = `<span class="msg-time">[${time}]</span> ${div.textContent}`;
        }
    } else if (msg.type === 'message') {
        // Vérifier ignore list
        const ignoreList = SettingsManager?.get('chatIgnoreList') || '';
        if (ignoreList.split(',').map(s=>s.trim()).includes(msg.user_id)) return;
        div.innerHTML = `<span class="msg-user">${escapeHtml(msg.username)}</span>: ${escapeHtml(msg.message)}`;
        if (showTimestamps && msg.timestamp) {
            const time = new Date(msg.timestamp).toLocaleTimeString();
            div.innerHTML = `<span class="msg-time">[${time}]</span> ${div.innerHTML}`;
        }
        // Notification sonore
        if (SettingsManager?.get('chatNotifications') && typeof SoundManager !== 'undefined') {
            SoundManager.play('chat');
        }
    }
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

// ══════════════════════════════════════════════════════════════════════════════
// Local Time
// ══════════════════════════════════════════════════════════════════════════════
function setupLocalTime() {
    const timeEl = $('localTime');
    if (!timeEl) return;
    function update() {
        timeEl.textContent = new Date().toLocaleTimeString();
    }
    update();
    setInterval(update, 1000);
}

// ══════════════════════════════════════════════════════════════════════════════
// Settings Manager Integration
// ══════════════════════════════════════════════════════════════════════════════
function applyGlobalSettings() {
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
        // Appliquer les options sonores additionnelles
        SoundManager.setOption('soundOnWin', SettingsManager.get('soundOnWin') !== false);
        SoundManager.setOption('soundOnChat', SettingsManager.get('soundOnChat') !== false);
        SoundManager.setOption('soundOnDeal', SettingsManager.get('soundOnDeal') !== false);
        SoundManager.setOption('soundOnTimer', SettingsManager.get('soundOnTimer') !== false);
        if (SettingsManager.get('customSoundUrl')) {
            SoundManager.setCustomUrl(SettingsManager.get('customSoundUrl'));
        }
    }
    const animSpeed = SettingsManager.get('animationSpeed') || 'normal';
    document.body.setAttribute('data-animation-speed', animSpeed);
    const autoAction = SettingsManager.get('autoAction') || 'never';
    localStorage.setItem('poker_auto_action', autoAction);
    const chatTimestamps = SettingsManager.get('chatTimestamps') !== false;
    localStorage.setItem('poker_chat_timestamps', chatTimestamps ? 'true' : 'false');
    // Appliquer taille de police chat
    const fontSize = SettingsManager.get('chatFontSize') || 'medium';
    document.body.setAttribute('data-chat-font-size', fontSize);
    // Appliquer ignore list
    const ignoreList = SettingsManager.get('chatIgnoreList') || '';
    localStorage.setItem('poker_chat_ignore', ignoreList);
    // Appliquer smileys personnalisés
    const customSmileys = SettingsManager.get('customSmileys') || '';
    if (customSmileys) {
        try {
            const smileys = JSON.parse(customSmileys);
            if (typeof window.updateChatSmileys === 'function') window.updateChatSmileys(smileys);
        } catch(e) {}
    }
    // Réseau
    const networkQuality = SettingsManager.get('networkQuality') || 'auto';
    localStorage.setItem('poker_network_quality', networkQuality);
    const reconnectOnDrop = SettingsManager.get('reconnectOnDrop') !== false;
    localStorage.setItem('poker_reconnect_on_drop', reconnectOnDrop ? 'true' : 'false');
    const reconnectDelay = SettingsManager.get('reconnectDelay') || 5;
    localStorage.setItem('poker_reconnect_delay', reconnectDelay);
    // Historique
    const historyMax = SettingsManager.get('historyMaxEntries') || 50;
    localStorage.setItem('poker_history_max', historyMax);
    const autoSaveHistory = SettingsManager.get('autoSaveHistory') !== false;
    localStorage.setItem('poker_auto_save_history', autoSaveHistory ? 'true' : 'false');
}

function setupThemeSelector() {
    const themeSelect = $('themeSelect');
    if (themeSelect && typeof ThemeManager !== 'undefined') {
        themeSelect.value = SettingsManager.get('theme') || 'dark';
        themeSelect.addEventListener('change', () => {
            const newTheme = themeSelect.value;
            SettingsManager.set('theme', newTheme);
            ThemeManager.setTheme(newTheme);
            showToast('Thème changé', 'success');
        });
    }
}

function setupCardDeckSelector() {
    const deckSelect = $('cardDeckSelect');
    if (deckSelect && typeof CardsModule !== 'undefined') {
        deckSelect.value = SettingsManager.get('cardDeck') || 'standard';
        deckSelect.addEventListener('change', () => {
            const newDeck = deckSelect.value;
            SettingsManager.set('cardDeck', newDeck);
            CardsModule.setDeck(newDeck);
            showToast('Jeu de cartes changé', 'success');
        });
    }
}

function setupTableStyleSelector() {
    const styleSelect = $('tableStyleSelect');
    if (styleSelect) {
        styleSelect.value = SettingsManager.get('tableStyle') || 'felt';
        styleSelect.addEventListener('change', () => {
            const newStyle = styleSelect.value;
            SettingsManager.set('tableStyle', newStyle);
            document.body.setAttribute('data-table-style', newStyle);
            showToast('Style de table changé', 'success');
        });
    }
}

// ══════════════════════════════════════════════════════════════════════════════
// Options Modal (unifiée) – Version complète
// ══════════════════════════════════════════════════════════════════════════════
function setupOptionsModal() {
    const modal = $('optionsModal');
    if (!modal) return;

    // Gestion des onglets
    const tabs = modal.querySelectorAll('.options-tab');
    const contents = modal.querySelectorAll('.options-tab-content');

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const target = tab.dataset.tab;
            tabs.forEach(t => t.classList.remove('active'));
            contents.forEach(c => c.classList.remove('active'));
            tab.classList.add('active');
            const targetTab = document.getElementById(target + 'Tab');
            if (targetTab) targetTab.classList.add('active');
        });
    });

    // Bouton d'ouverture
const adminTabBtn = document.getElementById('adminTabBtn');
if (adminTabBtn) adminTabBtn.style.display = (currentUser && currentUser.is_admin) ? '' : 'none'
    const optionsBtn = $('optionsBtn');
    if (optionsBtn) {
        optionsBtn.addEventListener('click', () => {
            const s = SettingsManager.load();
            const map = {
                themeSelect: 'theme',
                cardDeckSelect: 'cardDeck',
                tableStyleSelect: 'tableStyle',
                soundSetting: 'sound',
                soundVolume: 'soundVolume',
                animationSpeed: 'animationSpeed',
                autoAction: 'autoAction',
                showHistory: 'showHistory',
                chatTimestamps: 'chatTimestamps',
                actionTimer: 'actionTimer',
                networkQuality: 'networkQuality',
                reconnectOnDrop: 'reconnectOnDrop',
                reconnectDelay: 'reconnectDelay',
                chatFontSize: 'chatFontSize',
                chatNotifications: 'chatNotifications',
                soundOnWin: 'soundOnWin',
                soundOnChat: 'soundOnChat',
                soundOnDeal: 'soundOnDeal',
                soundOnTimer: 'soundOnTimer',
                customSoundUrl: 'customSoundUrl',
                chatIgnoreList: 'chatIgnoreList',
                customSmileys: 'customSmileys',
                historyMaxEntries: 'historyMaxEntries',
                autoSaveHistory: 'autoSaveHistory',
                showStacksInBB: 'showStacksInBB',
                autoRebuy: 'autoRebuy',
                maxTables: 'maxTables',
                compressionData: 'compressionData',
            };
            for (const [elId, key] of Object.entries(map)) {
                const el = $(elId);
                if (el && s[key] !== undefined) {
                    if (el.type === 'checkbox') el.checked = s[key];
                    else el.value = s[key];
                }
            }
            if (currentUser && currentUser.is_admin) {
                const adminThemeSelect = $('adminThemeSelect');
                if (adminThemeSelect) adminThemeSelect.value = s.theme || 'dark';
            }
            modal.style.display = 'flex';
        });
    }

    // Fermeture
    modal.querySelector('.close')?.addEventListener('click', () => modal.style.display = 'none');
    modal.addEventListener('click', (e) => { if (e.target === modal) modal.style.display = 'none'; });

    // Sauvegarde des paramètres
    const saveBtn = document.getElementById('saveSettings');
    if (saveBtn) {
        saveBtn.addEventListener('click', () => {
            const ns = {
                theme: $('themeSelect')?.value || 'dark',
                cardDeck: $('cardDeckSelect')?.value || 'standard',
                tableStyle: $('tableStyleSelect')?.value || 'felt',
                sound: $('soundSetting')?.value || 'on',
                soundVolume: parseFloat($('soundVolume')?.value) || 0.5,
                animationSpeed: $('animationSpeed')?.value || 'normal',
                autoAction: $('autoAction')?.value || 'never',
                showHistory: $('showHistory')?.value || 'all',
                chatTimestamps: $('chatTimestamps')?.checked || false,
                actionTimer: parseInt($('actionTimer')?.value) || 30,
                networkQuality: $('networkQuality')?.value || 'auto',
                reconnectOnDrop: $('reconnectOnDrop')?.checked || true,
                reconnectDelay: parseInt($('reconnectDelay')?.value) || 5,
                chatFontSize: $('chatFontSize')?.value || 'medium',
                chatNotifications: $('chatNotifications')?.checked || false,
                soundOnWin: $('soundOnWin')?.checked !== false,
                soundOnChat: $('soundOnChat')?.checked !== false,
                soundOnDeal: $('soundOnDeal')?.checked !== false,
                soundOnTimer: $('soundOnTimer')?.checked !== false,
                customSoundUrl: $('customSoundUrl')?.value || '',
                chatIgnoreList: $('chatIgnoreList')?.value || '',
                customSmileys: $('customSmileys')?.value || '',
                historyMaxEntries: parseInt($('historyMaxEntries')?.value) || 50,
                autoSaveHistory: $('autoSaveHistory')?.checked !== false,
                showStacksInBB: $('showStacksInBB')?.checked || false,
                autoRebuy: $('autoRebuy')?.checked || false,
                maxTables: parseInt($('maxTables')?.value) || 1,
                compressionData: $('compressionData')?.checked || false,
            };
            SettingsManager.save(ns);
            applyGlobalSettings();
            modal.style.display = 'none';
            showToast('Préférences sauvegardées', 'success');
        });
    }

    // Upload avatar
    const uploadBtn = $('uploadAvatarBtn');
    const avatarUpload = $('avatarUpload');
    const uploadStatus = $('uploadStatus');
    if (uploadBtn && avatarUpload) {
        uploadBtn.addEventListener('click', async () => {
            if (!avatarUpload.files?.length) {
                if (uploadStatus) uploadStatus.textContent = 'Sélectionnez un fichier';
                return;
            }
            const file = avatarUpload.files[0];
            if (file.size > 2 * 1024 * 1024) {
                if (uploadStatus) uploadStatus.textContent = 'Fichier trop volumineux (max 2 Mo)';
                return;
            }
            const formData = new FormData();
            formData.append('file', file);
            try {
                if (uploadStatus) uploadStatus.textContent = 'Upload en cours…';
                const resp = await fetch('/api/profile/avatar', { method: 'POST', body: formData });
                if (resp.ok) {
                    const data = await resp.json();
                    if (data.avatar) {
                        if (currentUser) currentUser.avatar = data.avatar;
                        const img = $('profileAvatar');
                        if (img) img.src = data.avatar;
                    }
                    if (uploadStatus) uploadStatus.innerHTML = '<span style="color:var(--success)">Avatar mis à jour!</span>';
                    showToast('Avatar mis à jour', 'success');
                } else {
                    const err = await resp.json().catch(() => ({}));
                    if (uploadStatus) uploadStatus.textContent = err.detail || 'Erreur upload';
                }
            } catch (e) {
                if (uploadStatus) uploadStatus.textContent = 'Erreur réseau';
            }
        });
    }

    // Mise à jour email
    const updateEmailBtn = document.getElementById('updateEmailBtn');
    if (updateEmailBtn) {
        updateEmailBtn.addEventListener('click', async () => {
            const email = $('profileEmail')?.value;
            if (!email) { showToast('Email requis', 'error'); return; }
            const resp = await fetch('/api/profile/email', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email })
            });
            if (resp.ok) {
                showToast('Email mis à jour', 'success');
                if (currentUser) currentUser.email = email;
            } else {
                const err = await resp.json().catch(() => ({}));
                showToast(err.detail || 'Erreur', 'error');
            }
        });
    }

    // Changement mot de passe
    const changePasswordBtn = document.getElementById('changePasswordBtn');
    if (changePasswordBtn) {
        changePasswordBtn.addEventListener('click', async () => {
            const oldPassword = $('oldPassword')?.value;
            const newPassword = $('newPassword')?.value;
            if (!oldPassword || !newPassword) {
                showToast('Remplissez les deux champs', 'error');
                return;
            }
            const resp = await fetch('/api/profile/password', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ current_password: oldPassword, new_password: newPassword })
            });
            if (resp.ok) {
                showToast('Mot de passe changé', 'success');
                $('oldPassword').value = '';
                $('newPassword').value = '';
            } else {
                const err = await resp.json().catch(() => ({}));
                showToast(err.detail || 'Erreur', 'error');
            }
        });
    }

    // Export historique
    const exportBtn = document.getElementById('exportHistoryBtn');
    if (exportBtn) {
        exportBtn.addEventListener('click', () => {
            if (typeof HandHistory !== 'undefined') {
                const history = HandHistory.getAll();
                const dataStr = JSON.stringify(history, null, 2);
                const blob = new Blob([dataStr], {type: 'application/json'});
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `poker_history_${Date.now()}.json`;
                a.click();
                URL.revokeObjectURL(url);
                showToast('Historique exporté', 'success');
            } else {
                showToast('Historique non disponible', 'error');
            }
        });
    }

    // Clear history local
    const clearHistoryBtn = document.getElementById('clearHistoryBtn');
    if (clearHistoryBtn) {
        clearHistoryBtn.addEventListener('click', () => {
            if (typeof HandHistory !== 'undefined') {
                HandHistory.clear();
                showToast('Historique local effacé', 'success');
            } else {
                showToast('Non disponible', 'error');
            }
        });
    }

    // Admin: basculer mode maintenance
    const toggleMaintenanceBtn = document.getElementById('toggleMaintenanceBtn');
    if (toggleMaintenanceBtn && currentUser && currentUser.is_admin) {
        toggleMaintenanceBtn.addEventListener('click', async () => {
            const resp = await fetch('/api/admin/maintenance/toggle', { method: 'POST' });
            if (resp.ok) {
                const data = await resp.json();
                showToast(`Mode maintenance ${data.maintenance ? 'activé' : 'désactivé'}`, 'info');
            } else {
                showToast('Erreur', 'error');
            }
        });
    }

    // Admin: redémarrer toutes les tables
    const restartAllTablesBtn = document.getElementById('restartAllTablesBtn');
    if (restartAllTablesBtn && currentUser && currentUser.is_admin) {
        restartAllTablesBtn.addEventListener('click', async () => {
            const resp = await fetch('/api/admin/restart-tables', { method: 'POST' });
            if (resp.ok) showToast('Toutes les tables redémarrées', 'success');
            else showToast('Erreur', 'error');
        });
    }

    // Admin: vider cache utilisateur
    const clearUserCacheBtn = document.getElementById('clearUserCacheBtn');
    if (clearUserCacheBtn && currentUser && currentUser.is_admin) {
        clearUserCacheBtn.addEventListener('click', () => {
            localStorage.clear();
            showToast('Cache utilisateur vidé', 'success');
        });
    }

    // Admin: afficher liste des connectés
    const listConnectedBtn = document.getElementById('listConnectedBtn');
    if (listConnectedBtn && currentUser && currentUser.is_admin) {
        listConnectedBtn.addEventListener('click', async () => {
            const resp = await fetch('/api/admin/connected-users');
            if (resp.ok) {
                const data = await resp.json();
                showToast(`Connectés: ${data.users.join(', ')}`, 'info');
            } else {
                showToast('Erreur', 'error');
            }
        });
    }

    // Admin: appliquer rate limit
    const applyRateLimitBtn = document.getElementById('applyRateLimitBtn');
    if (applyRateLimitBtn && currentUser && currentUser.is_admin) {
        applyRateLimitBtn.addEventListener('click', async () => {
            const config = $('rateLimitConfig')?.value;
            if (!config) return;
            const [max, window] = config.split(',').map(s=>parseInt(s.trim()));
            if (isNaN(max) || isNaN(window)) { showToast('Format: max_requests,window_seconds', 'error'); return; }
            const resp = await fetch('/api/admin/rate-limit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ max_requests: max, window_seconds: window })
            });
            if (resp.ok) showToast('Rate limit appliqué', 'success');
            else showToast('Erreur', 'error');
        });
    }

    // Sauvegarde du thème admin
    const saveAdminTheme = $('saveAdminTheme');
    if (saveAdminTheme) {
        saveAdminTheme.addEventListener('click', () => {
            const adminTheme = $('adminThemeSelect')?.value || 'dark';
            SettingsManager.set('theme', adminTheme);
            if (typeof ThemeManager !== 'undefined') ThemeManager.setTheme(adminTheme);
            showToast('Thème admin appliqué', 'success');
        });
    }
}

// ══════════════════════════════════════════════════════════════════════════════
// Modals
// ══════════════════════════════════════════════════════════════════════════════
function setupModals() {
    $('loginBtn')?.addEventListener('click', () => openModal('loginModal'));
    $('registerBtn')?.addEventListener('click', () => openModal('registerModal'));
    $('logoutBtn')?.addEventListener('click', logout);

    $('loginForm')?.addEventListener('submit', (e) => {
        e.preventDefault();
        login($('loginUsername').value, $('loginPassword').value, $('rememberMe')?.checked);
    });
    $('registerForm')?.addEventListener('submit', (e) => {
        e.preventDefault();
        register($('regUsername').value, $('regPassword').value, $('regEmail')?.value);
    });

    document.querySelectorAll('.modal .close').forEach(btn => {
        btn.addEventListener('click', () => btn.closest('.modal').style.display = 'none');
    });
    window.addEventListener('click', (e) => {
        if (e.target.classList.contains('modal')) e.target.style.display = 'none';
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
