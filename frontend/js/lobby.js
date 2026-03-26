// frontend/js/lobby.js
let refreshInterval = null;
let currentUser = null;
let isGuest = false;
let chatWs = null;

// frontend/js/lobby.js - Ajouter au début
function loadTheme() {
    const savedTheme = localStorage.getItem('poker_theme') || 'dark';
    document.body.className = `theme-${savedTheme}`;
    
    // Appliquer le CSS personnalisé
    const customCss = localStorage.getItem('poker_custom_css');
    if (customCss) {
        let styleTag = document.getElementById('custom-css');
        if (!styleTag) {
            styleTag = document.createElement('style');
            styleTag.id = 'custom-css';
            document.head.appendChild(styleTag);
        }
        styleTag.textContent = customCss;
    }
    
    const customCssUrl = localStorage.getItem('poker_custom_css_url');
    if (customCssUrl) {
        let linkTag = document.getElementById('custom-css-link');
        if (!linkTag) {
            linkTag = document.createElement('link');
            linkTag.id = 'custom-css-link';
            linkTag.rel = 'stylesheet';
            document.head.appendChild(linkTag);
        }
        linkTag.href = customCssUrl;
    }
}

// Appeler loadTheme() dans init()

async function init() {
    console.log('Initializing lobby...');
    loadTheme();
    await checkAuth();
    await loadTournaments();
    
    if (refreshInterval) clearInterval(refreshInterval);
    refreshInterval = setInterval(() => {
        loadTournaments();
    }, 5000);
    
    setupEventListeners();
    setupAuthModals();
    setupOptionsModal();
    initChat();
    updateServerTime();
    setInterval(updateServerTime, 1000);
}

async function checkAuth() {
    try {
        const response = await fetch('/api/auth/me');
        if (response.ok) {
            currentUser = await response.json();
            isGuest = false;
            console.log('User logged in:', currentUser.username);
            
            if (currentUser.is_admin) {
                const adminBtn = document.getElementById('adminBtn');
                if (adminBtn) adminBtn.style.display = 'inline-block';
            }
        } else {
            isGuest = true;
            currentUser = { username: 'Guest', id: null, avatar: null };
            console.log('Guest mode');
        }
        updateUserDisplay();
    } catch (error) {
        console.error('Auth check failed:', error);
        isGuest = true;
        currentUser = { username: 'Guest', id: null, avatar: null };
        updateUserDisplay();
    }
}

function updateUserDisplay() {
    const usernameSpan = document.getElementById('username');
    const loginBtn = document.getElementById('loginBtn');
    const registerBtn = document.getElementById('registerBtn');
    const logoutBtn = document.getElementById('logoutBtn');
    const profileLink = document.getElementById('profileLink');
    const guestWarning = document.getElementById('guestWarning');
    const userAvatar = document.getElementById('userAvatar');
    
    if (usernameSpan) usernameSpan.textContent = currentUser.username;
    
    if (currentUser && !isGuest) {
        if (loginBtn) loginBtn.style.display = 'none';
        if (registerBtn) registerBtn.style.display = 'none';
        if (logoutBtn) logoutBtn.style.display = 'block';
        if (profileLink) profileLink.style.display = 'inline-block';
        if (guestWarning) guestWarning.classList.add('hidden');
        
        if (userAvatar && currentUser.avatar) {
            const predefinedAvatars = ['default', 'panda', 'tiger', 'dragon', 'phoenix'];
            let avatarUrl;
            
            if (predefinedAvatars.includes(currentUser.avatar)) {
                avatarUrl = `/assets/images/avatars/${currentUser.avatar}.svg`;
            } else {
                avatarUrl = currentUser.avatar;
            }
            
            userAvatar.style.backgroundImage = `url('${avatarUrl}')`;
            userAvatar.style.backgroundSize = 'cover';
            userAvatar.style.backgroundPosition = 'center';
            userAvatar.style.backgroundColor = 'transparent';
        } else if (userAvatar) {
            userAvatar.style.backgroundImage = '';
            userAvatar.style.backgroundColor = 'linear-gradient(135deg, #ffd700, #ffb347)';
        }
    } else {
        if (loginBtn) loginBtn.style.display = 'block';
        if (registerBtn) registerBtn.style.display = 'block';
        if (logoutBtn) logoutBtn.style.display = 'none';
        if (profileLink) profileLink.style.display = 'none';
        if (guestWarning) guestWarning.classList.remove('hidden');
        if (userAvatar) userAvatar.style.backgroundImage = '';
    }
}

async function loadTournaments() {
    try {
        const response = await fetch('/api/tournaments');
        if (!response.ok) throw new Error('Failed to load tournaments');
        const tournaments = await response.json();
        
        const activeTournaments = tournaments.filter(t => t.status === 'in_progress');
        const upcomingTournaments = tournaments.filter(t => t.status === 'registration');
        
        renderActiveTournaments(activeTournaments);
        renderUpcomingTournaments(upcomingTournaments);
    } catch (error) {
        console.error('Error loading tournaments:', error);
    }
}

function renderActiveTournaments(tournaments) {
    const grid = document.getElementById('activeTournamentsGrid');
    if (!grid) return;
    
    if (!tournaments || tournaments.length === 0) {
        grid.innerHTML = '<div class="loading">No active tournaments</div>';
        return;
    }
    
    grid.innerHTML = tournaments.map(t => `
        <div class="tournament-card" onclick="window.showTournamentTables('${t.id}')">
            <div class="tournament-header">
                <div class="tournament-name">🏆 ${escapeHtml(t.name)}</div>
                <div class="tournament-status in_progress">In Progress</div>
            </div>
            <div class="tournament-details">
                <div><span class="label">Players:</span> <span class="value">${t.players_count}/${t.max_players}</span></div>
                <div><span class="label">Started:</span> <span class="value">${new Date(t.start_time).toLocaleString()}</span></div>
                <div><span class="label">Current Blinds:</span> <span class="value">${t.current_blinds?.small_blind}/${t.current_blinds?.big_blind}</span></div>
            </div>
            <button class="spectate-btn" onclick="event.stopPropagation(); window.showTournamentTables('${t.id}')">View Tables</button>
        </div>
    `).join('');
}

function renderUpcomingTournaments(tournaments) {
    const grid = document.getElementById('upcomingTournamentsGrid');
    if (!grid) return;
    
    if (!tournaments || tournaments.length === 0) {
        grid.innerHTML = '<div class="loading">No upcoming tournaments</div>';
        return;
    }
    
    const now = new Date();
    
    grid.innerHTML = tournaments.map(t => {
        const regStart = new Date(t.registration_start);
        const regEnd = new Date(t.registration_end);
        
        let canRegister = now >= regStart && now < regEnd;
        let statusText = canRegister ? '✅ Open' : (now < regStart ? '📅 Soon' : '⏰ Closed');
        
        return `
            <div class="tournament-card">
                <div class="tournament-header">
                    <div class="tournament-name">📅 ${escapeHtml(t.name)}</div>
                    <div class="tournament-status registration">${statusText}</div>
                </div>
                <div class="tournament-details">
                    <div><span class="label">Starts:</span> <span class="value">${new Date(t.start_time).toLocaleString()}</span></div>
                    <div><span class="label">Reg closes:</span> <span class="value">${new Date(t.registration_end).toLocaleString()}</span></div>
                    <div><span class="label">Players:</span> <span class="value">${t.players_count}/${t.max_players}</span></div>
                </div>
                <button class="register-btn" onclick="window.showTournamentDetails('${t.id}')">
                    ${canRegister ? 'Register Now' : 'View Details'}
                </button>
            </div>
        `;
    }).join('');
}

// frontend/js/lobby.js - Remplacer la fonction showTournamentDetails
window.showTournamentDetails = async function(tournamentId) {
    try {
        const response = await fetch(`/api/tournaments/${tournamentId}`);
        if (!response.ok) throw new Error('Failed to load tournament');
        const tournament = await response.json();
        
        // Vérifier si l'utilisateur est inscrit
        let isRegistered = false;
        if (currentUser && !isGuest && currentUser.id) {
            const regResponse = await fetch(`/api/tournaments/${tournamentId}/registered/${currentUser.id}`);
            if (regResponse.ok) {
                const regData = await regResponse.json();
                isRegistered = regData.registered;
            }
        }
        
        const modal = document.getElementById('tournamentModal');
        const detailsDiv = document.getElementById('tournamentDetails');
        
        const formatDate = (dateStr) => {
            if (!dateStr) return 'N/A';
            return new Date(dateStr).toLocaleString();
        };
        
        const formatTime = (seconds) => {
            if (!seconds) return 'N/A';
            const hours = Math.floor(seconds / 3600);
            const minutes = Math.floor((seconds % 3600) / 60);
            if (hours > 0) return `${hours}h ${minutes}m`;
            if (minutes > 0) return `${minutes}m`;
            return `${seconds}s`;
        };
        
        // Structure des prix
        const prizesHtml = tournament.prizes && tournament.prizes.length ? 
            tournament.prizes.map(p => `
                <div class="prize-item">
                    <span>🏆 ${p.rank}${getOrdinal(p.rank)} place</span>
                    <span>💰 ${p.amount.toLocaleString()} chips (${p.percentage}%)</span>
                </div>
            `).join('') : '<div class="empty-message">No prize pool - ranking only</div>';
        
        // Liste des joueurs inscrits
        const playersHtml = tournament.registered_players && tournament.registered_players.length ?
            tournament.registered_players.map(p => `
                <div class="player-item">
                    <span>👤 ${escapeHtml(p.username)}</span>
                    <small>Registered: ${formatDate(p.registered_at)}</small>
                </div>
            `).join('') : '<div class="empty-message">No players registered yet</div>';
        
        // Structure des blinds
        const blindsHtml = tournament.blind_structure && tournament.blind_structure.length ?
            tournament.blind_structure.map(level => `
                <div class="blind-level-item">
                    <span class="level-num">Level ${level.level}</span>
                    <span class="level-blinds">${level.small_blind}/${level.big_blind}</span>
                    <span class="level-duration">⏱️ ${level.duration} min</span>
                </div>
            `).join('') : '<div class="empty-message">No blind structure configured</div>';
        
        // Informations générales
        const infoHtml = `
            <div class="tournament-description">
                ${tournament.description ? escapeHtml(tournament.description) : 'No description provided'}
            </div>
            
            <div class="tournament-timeline">
                <div class="timeline-item">
                    <span class="timeline-icon">📅</span>
                    <div class="timeline-content">
                        <strong>Registration opens</strong>
                        <div>${formatDate(tournament.registration_start)}</div>
                    </div>
                </div>
                <div class="timeline-item">
                    <span class="timeline-icon">⏰</span>
                    <div class="timeline-content">
                        <strong>Registration closes</strong>
                        <div>${formatDate(tournament.registration_end)}</div>
                        ${tournament.time_until_registration_end ? 
                            `<span class="time-remaining">(${formatTime(tournament.time_until_registration_end)} remaining)</span>` : ''}
                    </div>
                </div>
                <div class="timeline-item">
                    <span class="timeline-icon">🎯</span>
                    <div class="timeline-content">
                        <strong>Tournament starts</strong>
                        <div>${formatDate(tournament.start_time)}</div>
                        ${tournament.time_until_start ? 
                            `<span class="time-remaining">(${formatTime(tournament.time_until_start)} remaining)</span>` : ''}
                    </div>
                </div>
            </div>
            
            <div class="tournament-stats-grid">
                <div class="stat-card">
                    <div class="stat-value">${tournament.players_count}/${tournament.max_players}</div>
                    <div class="stat-label">Players</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">💰 ${tournament.prize_pool.toLocaleString()}</div>
                    <div class="stat-label">Prize Pool</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">${tournament.itm_percentage}%</div>
                    <div class="stat-label">ITM</div>
                </div>
                ${tournament.current_blinds ? `
                <div class="stat-card">
                    <div class="stat-value">${tournament.current_blinds.small_blind}/${tournament.current_blinds.big_blind}</div>
                    <div class="stat-label">Current Blinds</div>
                </div>
                ` : ''}
            </div>
        `;
        
        // Onglets
        const tabsHtml = `
            <div class="tournament-tabs">
                <button class="tab-btn active" data-tab="info">📋 Information</button>
                <button class="tab-btn" data-tab="prizes">🏆 Prize Structure</button>
                <button class="tab-btn" data-tab="blind">🎲 Blind Structure</button>
                <button class="tab-btn" data-tab="players">👥 Registered Players</button>
            </div>
            
            <div class="tournament-tab-content active" id="tab-info">
                ${infoHtml}
            </div>
            <div class="tournament-tab-content" id="tab-prizes">
                <div class="prize-structure">
                    <h4>Prize Distribution</h4>
                    <div class="prize-list">${prizesHtml}</div>
                </div>
            </div>
            <div class="tournament-tab-content" id="tab-blind">
                <div class="blind-structure">
                    <h4>Blind Levels</h4>
                    <div class="blind-structure-list">${blindsHtml}</div>
                </div>
            </div>
            <div class="tournament-tab-content" id="tab-players">
                <div class="registered-players">
                    <h4>Registered Players (${tournament.players_count})</h4>
                    <div class="players-list">${playersHtml}</div>
                </div>
            </div>
        `;
        
        // Bouton d'action
        let actionButton = '';
        const now = new Date();
        const regStart = new Date(tournament.registration_start);
        const regEnd = new Date(tournament.registration_end);
        
        if (tournament.status === 'registration') {
            if (now >= regStart && now < regEnd) {
                if (!isRegistered) {
                    actionButton = `<button class="register-tournament-btn" onclick="window.registerForTournament('${tournamentId}')">✅ Register Now</button>`;
                } else {
                    actionButton = `<button class="unregister-tournament-btn" onclick="window.unregisterFromTournament('${tournamentId}')">❌ Cancel Registration</button>`;
                }
            } else if (now < regStart) {
                actionButton = `<div class="status-message">⏰ Registration opens ${formatDate(tournament.registration_start)}</div>`;
            } else {
                actionButton = `<div class="status-message">📝 Registration closed</div>`;
            }
        } else if (tournament.status === 'in_progress') {
            actionButton = `<button class="spectate-tournament-btn" onclick="window.showTournamentTables('${tournamentId}')">👁️ View Tables & Spectate</button>`;
        }
        
        detailsDiv.innerHTML = `
            <div class="tournament-info-header">
                <h2>🏆 ${escapeHtml(tournament.name)}</h2>
                <div class="tournament-status-badge status-${tournament.status}">
                    ${tournament.status === 'registration' ? '📝 Registration Open' : 
                      tournament.status === 'in_progress' ? '🎲 In Progress' : 
                      tournament.status === 'finished' ? '🏁 Finished' : tournament.status}
                </div>
            </div>
            ${tabsHtml}
            ${actionButton}
        `;
        
        setupTournamentTabs(modal);
        modal.style.display = 'block';
        
    } catch (error) {
        console.error('Error loading tournament details:', error);
        alert('Failed to load tournament details');
    }
};

// Fonction pour gérer les onglets
function setupTournamentTabs(modal) {
    const tabs = modal.querySelectorAll('.tournament-tabs .tab-btn');
    const contents = modal.querySelectorAll('.tournament-tab-content');
    
    tabs.forEach(tab => {
        tab.onclick = () => {
            const tabId = tab.dataset.tab;
            tabs.forEach(t => t.classList.remove('active'));
            contents.forEach(c => c.classList.remove('active'));
            tab.classList.add('active');
            const activeContent = modal.querySelector(`#tab-${tabId}`);
            if (activeContent) activeContent.classList.add('active');
        };
    });
}


window.showTournamentTables = async function(tournamentId) {
    try {
        const response = await fetch(`/api/tournaments/${tournamentId}/tables`);
        if (!response.ok) throw new Error('Failed to load tables');
        const tables = await response.json();
        
        const modal = document.getElementById('tournamentTablesModal');
        const listDiv = document.getElementById('tournamentTablesList');
        
        if (!tables || tables.length === 0) {
            listDiv.innerHTML = '<div class="loading">No tables available yet</div>';
        } else {
            listDiv.innerHTML = tables.map(table => `
                <div class="table-item">
                    <div class="table-info">
                        <strong>🎲 ${escapeHtml(table.name)}</strong>
                        <small>${table.current_players}/${table.max_players} players</small>
                    </div>
                    <button class="watch-table-btn" onclick="window.watchTable('${table.id}')">👁️ Watch</button>
                </div>
            `).join('');
        }
        
        modal.style.display = 'block';
    } catch (error) {
        console.error('Error loading tournament tables:', error);
        alert('Failed to load tables');
    }
};

window.watchTable = function(tableId) {
    window.location.href = `/table/${tableId}?spectate=true`;
};

window.registerForTournament = async function(tournamentId) {
    if (!currentUser || isGuest) {
        alert('Please login or register to join a tournament');
        showLoginModal();
        return;
    }
    
    try {
        const response = await fetch(`/api/tournaments/${tournamentId}/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: currentUser.id })
        });
        
        if (response.ok) {
            alert('Successfully registered for tournament!');
            document.getElementById('tournamentModal').style.display = 'none';
            await loadTournaments();
        } else {
            const error = await response.json();
            alert(error.detail || 'Registration failed');
        }
    } catch (error) {
        console.error('Error registering for tournament:', error);
        alert('Registration failed');
    }
};

window.unregisterFromTournament = async function(tournamentId) {
    if (!currentUser || isGuest) {
        alert('Please login to manage your registration');
        showLoginModal();
        return;
    }
    
    if (!confirm('Are you sure you want to cancel your registration?')) return;
    
    try {
        const response = await fetch(`/api/tournaments/${tournamentId}/unregister`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        if (response.ok) {
            alert('Successfully unregistered from tournament');
            document.getElementById('tournamentModal').style.display = 'none';
            await loadTournaments();
        } else {
            const error = await response.json();
            alert(error.detail || 'Unregistration failed');
        }
    } catch (error) {
        console.error('Error unregistering:', error);
        alert('Unregistration failed');
    }
};

function getOrdinal(n) {
    const s = ['th', 'st', 'nd', 'rd'];
    const v = n % 100;
    return s[(v - 20) % 10] || s[v] || s[0];
}

function initChat() {
    if (!currentUser || isGuest) return;
    
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/chat`;
    
    chatWs = new WebSocket(wsUrl);
    
    chatWs.onopen = () => {
        console.log('Chat connected');
        chatWs.send(JSON.stringify({ type: 'join', user_id: currentUser.id, username: currentUser.username }));
        document.getElementById('chatInput').disabled = false;
        document.getElementById('chatSendBtn').disabled = false;
    };
    
    chatWs.onmessage = (event) => {
        const message = JSON.parse(event.data);
        addChatMessage(message);
        if (message.user_count) {
            document.getElementById('chatUserCount').textContent = `${message.user_count} online`;
        }
    };
    
    chatWs.onclose = () => {
        console.log('Chat disconnected');
        document.getElementById('chatInput').disabled = true;
        document.getElementById('chatSendBtn').disabled = true;
        setTimeout(initChat, 3000);
    };
    
    const chatInput = document.getElementById('chatInput');
    const chatSendBtn = document.getElementById('chatSendBtn');
    
    chatSendBtn.onclick = () => sendChatMessage();
    chatInput.onkeypress = (e) => { if (e.key === 'Enter') sendChatMessage(); };
}

function sendChatMessage() {
    const input = document.getElementById('chatInput');
    const message = input.value.trim();
    if (!message) return;
    
    if (chatWs && chatWs.readyState === WebSocket.OPEN) {
        chatWs.send(JSON.stringify({ type: 'message', username: currentUser.username, message: message }));
        input.value = '';
    }
}

function addChatMessage(message) {
    const container = document.getElementById('chatMessages');
    const time = new Date(message.timestamp).toLocaleTimeString();
    
    const messageDiv = document.createElement('div');
    messageDiv.className = `chat-message ${message.type || ''}`;
    
    if (message.type === 'system') {
        messageDiv.innerHTML = `<span class="time">[${time}]</span> ${escapeHtml(message.message)}`;
    } else {
        messageDiv.innerHTML = `<span class="time">[${time}]</span> <span class="username">${escapeHtml(message.username)}:</span> <span class="text">${escapeHtml(message.message)}</span>`;
    }
    
    container.appendChild(messageDiv);
    messageDiv.scrollIntoView({ behavior: 'smooth' });
    while (container.children.length > 200) container.removeChild(container.firstChild);
}

async function updateServerTime() {
    try {
        const response = await fetch('/api/server/time');
        if (response.ok) {
            const data = await response.json();
            const timeSpan = document.getElementById('serverTime');
            if (timeSpan) timeSpan.textContent = data.time;
        }
    } catch (error) {
        console.error('Error fetching server time:', error);
    }
}

function showLoginModal() {
    const modal = document.getElementById('loginModal');
    if (modal) modal.style.display = 'block';
}

function showRegisterModal() {
    const modal = document.getElementById('registerModal');
    if (modal) modal.style.display = 'block';
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) modal.style.display = 'none';
}

async function login(username, password, rememberMe) {
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
            updateUserDisplay();
            closeModal('loginModal');
            showToast('Login successful!', 'success');
            await loadTournaments();
            if (chatWs) chatWs.close();
            initChat();
        } else {
            const error = await response.json();
            alert(error.detail || 'Login failed');
        }
    } catch (error) {
        console.error('Login error:', error);
        alert('Login failed');
    }
}

async function register(username, password, email) {
    try {
        const response = await fetch('/api/auth/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password, email: email || null })
        });
        
        if (response.ok) {
            alert('Registration successful! Please login.');
            closeModal('registerModal');
            showLoginModal();
        } else {
            const error = await response.json();
            alert(error.detail || 'Registration failed');
        }
    } catch (error) {
        console.error('Registration error:', error);
        alert('Registration failed');
    }
}

async function logout() {
    try {
        await fetch('/api/auth/logout', { method: 'POST' });
        if (chatWs) chatWs.close();
        currentUser = null;
        isGuest = true;
        currentUser = { username: 'Guest', id: null, avatar: null };
        updateUserDisplay();
        showToast('Logged out successfully', 'info');
        await loadTournaments();
    } catch (error) {
        console.error('Logout error:', error);
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

function setupEventListeners() {
    const optionsBtn = document.getElementById('optionsBtn');
    const loginBtn = document.getElementById('loginBtn');
    const registerBtn = document.getElementById('registerBtn');
    const logoutBtn = document.getElementById('logoutBtn');
    const adminBtn = document.getElementById('adminBtn');
    
    if (optionsBtn) optionsBtn.onclick = () => showOptionsModal();
    if (loginBtn) loginBtn.onclick = () => showLoginModal();
    if (registerBtn) registerBtn.onclick = () => showRegisterModal();
    if (logoutBtn) logoutBtn.onclick = () => logout();
    if (adminBtn) adminBtn.onclick = () => window.location.href = '/admin';
}

function setupAuthModals() {
    const loginForm = document.getElementById('loginForm');
    if (loginForm) {
        loginForm.onsubmit = (e) => {
            e.preventDefault();
            const username = document.getElementById('loginUsername')?.value;
            const password = document.getElementById('loginPassword')?.value;
            const rememberMe = document.getElementById('rememberMe')?.checked;
            if (username && password) login(username, password, rememberMe);
        };
    }
    
    const registerForm = document.getElementById('registerForm');
    if (registerForm) {
        registerForm.onsubmit = (e) => {
            e.preventDefault();
            const username = document.getElementById('regUsername')?.value;
            const password = document.getElementById('regPassword')?.value;
            const email = document.getElementById('regEmail')?.value;
            if (username && password) register(username, password, email);
        };
    }
    
    document.querySelectorAll('.modal .close').forEach(closeBtn => {
        closeBtn.onclick = () => {
            const modal = closeBtn.closest('.modal');
            if (modal) modal.style.display = 'none';
        };
    });
    
    window.onclick = (event) => {
        if (event.target.classList.contains('modal')) {
            event.target.style.display = 'none';
        }
    };
}

function showOptionsModal() {
    const modal = document.getElementById('optionsModal');
    if (!modal) return;
    
    const settings = SettingsManager.load();
    const soundSetting = document.getElementById('soundSetting');
    const animationSpeed = document.getElementById('animationSpeed');
    
    if (soundSetting) soundSetting.value = settings.sound;
    if (animationSpeed) animationSpeed.value = settings.animationSpeed;
    
    modal.style.display = 'block';
}

function setupOptionsModal() {
    const optionsModal = document.getElementById('optionsModal');
    const closeBtn = optionsModal?.querySelector('.close');
    const saveBtn = document.getElementById('saveSettings');
    
    if (closeBtn) closeBtn.onclick = () => optionsModal.style.display = 'none';
    
    if (saveBtn) {
        saveBtn.onclick = () => {
            SettingsManager.save({
                sound: document.getElementById('soundSetting')?.value || 'on',
                animationSpeed: document.getElementById('animationSpeed')?.value || 'normal'
            });
            optionsModal.style.display = 'none';
            showToast('Settings saved!', 'success');
        };
    }
}

class SettingsManager {
    static defaults = { sound: 'on', animationSpeed: 'normal' };
    
    static load() {
        const saved = localStorage.getItem('poker_settings');
        if (saved) {
            try {
                return { ...this.defaults, ...JSON.parse(saved) };
            } catch (e) {
                return this.defaults;
            }
        }
        return this.defaults;
    }
    
    static save(settings) {
        localStorage.setItem('poker_settings', JSON.stringify(settings));
    }
}

window.settings = SettingsManager;

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
