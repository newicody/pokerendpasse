// frontend/js/admin.js
let currentUser = null;
let usersData = [];
let currentBlindLevels = [];

// Initialisation
async function init() {
    console.log('Initializing admin panel...');
    await checkAdmin();
    await loadAppearanceSettings();  // Ajouter cette ligne
    setupEventListeners();
    loadOverview();
    loadUsers();
    loadTables();
    loadTournaments();
    
    setInterval(() => {
        loadOverview();
        loadUsers();
        loadTables();
        loadTournaments();
    }, 10000);
}

// Vérifier les droits admin
async function checkAdmin() {
    try {
        const response = await fetch('/api/auth/me');
        if (!response.ok) {
            window.location.href = '/login';
            return;
        }
        currentUser = await response.json();
        if (!currentUser.is_admin) {
            window.location.href = '/lobby';
            return;
        }
        console.log('Admin user:', currentUser.username);
    } catch (error) {
        console.error('Auth check failed:', error);
        window.location.href = '/login';
    }
}

// Tab management
function setupEventListeners() {
    // Tab buttons
    document.querySelectorAll('.admin-tabs .tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const tabId = btn.dataset.tab;
            document.querySelectorAll('.admin-tabs .tab-btn').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById(tabId).classList.add('active');
            
            if (tabId === 'users') loadUsers();
            if (tabId === 'tables') loadTables();
            if (tabId === 'tournaments') loadTournaments();
            if (tabId === 'overview') loadOverview();
        });
    });
    
    // Search users
    const searchBtn = document.getElementById('searchUserBtn');
    const userSearch = document.getElementById('userSearch');
    if (searchBtn) {
        searchBtn.addEventListener('click', () => {
            loadUsers(userSearch?.value || '');
        });
    }
    if (userSearch) {
        userSearch.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') loadUsers(e.target.value);
        });
    }
    
    // Add user
    const addUserBtn = document.getElementById('addUserBtn');
    if (addUserBtn) {
        addUserBtn.addEventListener('click', () => {
            resetUserForm();
            document.getElementById('userEditModal').style.display = 'block';
        });
    }
    
    // Create tournament button
    const createTournamentBtn = document.getElementById('createTournamentAdminBtn');
    if (createTournamentBtn) {
        createTournamentBtn.addEventListener('click', () => {
            console.log('Create tournament button clicked');
            initTournamentForm();
            document.getElementById('tournamentModal').style.display = 'block';
        });
    }
    
    // Save settings buttons
    const saveServerBtn = document.getElementById('saveServerSettings');
    if (saveServerBtn) saveServerBtn.addEventListener('click', saveServerSettings);
    
    const saveTournamentSettingsBtn = document.getElementById('saveTournamentSettings');
    if (saveTournamentSettingsBtn) saveTournamentSettingsBtn.addEventListener('click', saveTournamentSettings);
    
    // Modal close buttons
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

// Load overview stats
async function loadOverview() {
    try {
        const response = await fetch('/api/admin/stats');
        if (response.ok) {
            const stats = await response.json();
            document.getElementById('totalUsers').textContent = stats.total_users || 0;
            document.getElementById('activeUsers').textContent = stats.active_users || 0;
            document.getElementById('totalTables').textContent = stats.total_tables || 0;
            document.getElementById('totalTournaments').textContent = stats.active_tournaments || 0;
            document.getElementById('totalChips').textContent = stats.total_chips || 0;
            document.getElementById('totalHands').textContent = stats.total_hands || 0;
        }
    } catch (error) {
        console.error('Error loading stats:', error);
    }
}

// Load users
async function loadUsers(search = '') {
    const tbody = document.getElementById('usersTable');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="6" class="loading">Loading users...</td></tr>';
    
    try {
        let url = '/api/admin/users';
        if (search) url += `?search=${encodeURIComponent(search)}`;
        
        const response = await fetch(url);
        if (response.ok) {
            usersData = await response.json();
            renderUsersTable(usersData);
        } else {
            tbody.innerHTML = '<tr><td colspan="6" class="loading">Error loading users</td></tr>';
        }
    } catch (error) {
        console.error('Error loading users:', error);
        tbody.innerHTML = '<tr><td colspan="6" class="loading">Error loading users</td></tr>';
    }
}

function renderUsersTable(users) {
    const tbody = document.getElementById('usersTable');
    if (!tbody) return;
    
    if (!users || users.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="loading">No users found</td></tr>';
        return;
    }
    
    tbody.innerHTML = users.map(user => `
        <tr>
            <td>${user.id.substring(0, 8)}...</td>
            <td>${escapeHtml(user.username)}</td>
            <td>${user.email || '-'}</td>
            <td><span class="badge ${user.is_admin ? 'admin' : 'user'}">${user.is_admin ? 'Admin' : 'User'}</span></td>
            <td><span class="badge ${user.status === 'active' ? 'active' : 'banned'}">${user.status || 'active'}</span></td>
            <td>
                <button class="action-btn edit" onclick="window.editUser('${user.id}')">Edit</button>
                <button class="action-btn ${user.is_admin ? 'promote' : 'edit'}" onclick="window.toggleAdmin('${user.id}', ${!user.is_admin})">${user.is_admin ? 'Demote' : 'Promote'}</button>
                <button class="action-btn delete" onclick="window.deleteUser('${user.id}')">Delete</button>
            </td>
        </tr>
    `).join('');
}

window.editUser = function(userId) {
    const user = usersData.find(u => u.id === userId);
    if (!user) return;
    
    document.getElementById('editUserId').value = user.id;
    document.getElementById('editUsername').value = user.username;
    document.getElementById('editEmail').value = user.email || '';
    document.getElementById('editRole').value = user.is_admin ? 'admin' : 'user';
    document.getElementById('editStatus').value = user.status || 'active';
    
    document.getElementById('userEditModal').style.display = 'block';
};

document.getElementById('userEditForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const userId = document.getElementById('editUserId').value;
    const data = {
        username: document.getElementById('editUsername').value,
        email: document.getElementById('editEmail').value,
        is_admin: document.getElementById('editRole').value === 'admin',
        status: document.getElementById('editStatus').value
    };
    
    try {
        const response = await fetch(`/api/admin/users/${userId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        
        if (response.ok) {
            alert('User updated successfully');
            document.getElementById('userEditModal').style.display = 'none';
            loadUsers();
        } else {
            const error = await response.json();
            alert(error.detail || 'Update failed');
        }
    } catch (error) {
        console.error('Error updating user:', error);
        alert('Update failed');
    }
});

window.toggleAdmin = async function(userId, makeAdmin) {
    try {
        const response = await fetch(`/api/admin/users/${userId}/role`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ is_admin: makeAdmin })
        });
        
        if (response.ok) {
            alert('User role updated');
            loadUsers();
        } else {
            alert('Update failed');
        }
    } catch (error) {
        console.error('Error toggling admin:', error);
        alert('Update failed');
    }
};

window.deleteUser = async function(userId) {
    if (!confirm('Are you sure you want to delete this user?')) return;
    
    try {
        const response = await fetch(`/api/admin/users/${userId}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            alert('User deleted');
            loadUsers();
        } else {
            alert('Delete failed');
        }
    } catch (error) {
        console.error('Error deleting user:', error);
        alert('Delete failed');
    }
};

// Load tables
async function loadTables() {
    const tbody = document.getElementById('tablesTable');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="6" class="loading">Loading tables...</td></tr>';
    
    try {
        const response = await fetch('/api/tables');
        if (response.ok) {
            const tables = await response.json();
            renderTablesTable(tables);
        } else {
            tbody.innerHTML = '<tr><td colspan="6" class="loading">Error loading tables</td></tr>';
        }
    } catch (error) {
        console.error('Error loading tables:', error);
        tbody.innerHTML = '<tr><td colspan="6" class="loading">Error loading tables</td></tr>';
    }
}

function renderTablesTable(tables) {
    const tbody = document.getElementById('tablesTable');
    if (!tbody) return;
    
    if (!tables || tables.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="loading">No active tables</td></tr>';
        return;
    }
    
    tbody.innerHTML = tables.map(table => `
        <tr>
            <td>${table.id}</td>
            <td>${escapeHtml(table.name)}</td>
            <td>${table.current_players}/${table.max_players}</td>
            <td><span class="badge ${table.status}">${table.status}</span></td>
            <td>${table.small_blind}/${table.big_blind}</td>
            <td><button class="action-btn delete" onclick="window.closeTable('${table.id}')">Close</button></td>
        </tr>
    `).join('');
}

window.closeTable = async function(tableId) {
    if (!confirm('Are you sure you want to close this table?')) return;
    
    try {
        const response = await fetch(`/api/admin/tables/${tableId}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            alert('Table closed');
            loadTables();
        } else {
            alert('Failed to close table');
        }
    } catch (error) {
        console.error('Error closing table:', error);
        alert('Failed to close table');
    }
};

// Load tournaments
async function loadTournaments() {
    const tbody = document.getElementById('tournamentsTable');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="7" class="loading">Loading tournaments...</td></tr>';
    
    try {
        const response = await fetch('/api/tournaments');
        if (response.ok) {
            const tournaments = await response.json();
            renderTournamentsTable(tournaments);
        } else {
            tbody.innerHTML = '<tr><td colspan="7" class="loading">Error loading tournaments</td></tr>';
        }
    } catch (error) {
        console.error('Error loading tournaments:', error);
        tbody.innerHTML = '<tr><td colspan="7" class="loading">Error loading tournaments</td></tr>';
    }
}

function renderTournamentsTable(tournaments) {
    const tbody = document.getElementById('tournamentsTable');
    if (!tbody) return;
    
    if (!tournaments || tournaments.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="loading">No tournaments</td></tr>';
        return;
    }
    
    tbody.innerHTML = tournaments.map(t => `
        <tr>
            <td>${escapeHtml(t.name)}</td>
            <td>${new Date(t.registration_start).toLocaleString()}<br><small>to ${new Date(t.registration_end).toLocaleString()}</small></td>
            <td>${new Date(t.start_time).toLocaleString()}</td>
            <td>${t.players_count}/${t.max_players}</td>
            <td>💰 ${t.prize_pool?.toLocaleString() || 0}</td>
            <td><span class="badge ${t.status}">${t.status}</span></td>
            <td>
                <button class="action-btn edit" onclick="window.editTournament('${t.id}')">Edit</button>
                <button class="action-btn delete" onclick="window.cancelTournament('${t.id}')">Cancel</button>
            </td>
        </tr>
    `).join('');
}



window.cancelTournament = async function(tournamentId) {
    if (!confirm('Are you sure you want to cancel this tournament?')) return;
    
    try {
        const response = await fetch(`/api/admin/tournaments/${tournamentId}`, {
            method: 'DELETE'
        });
        
        if (response.ok) {
            alert('Tournament cancelled');
            loadTournaments();
        } else {
            alert('Failed to cancel tournament');
        }
    } catch (error) {
        console.error('Error cancelling tournament:', error);
        alert('Failed to cancel tournament');
    }
};

// Blind structure functions
function renderBlindLevels() {
    const container = document.getElementById('blindLevelsList');
    if (!container) return;
    
    if (!currentBlindLevels.length) {
        container.innerHTML = '<div class="empty-message">No blind levels. Click "Add Level" to start.</div>';
        return;
    }
    
    container.innerHTML = currentBlindLevels.map((level, index) => `
        <div class="blind-level-row">
            <span class="level-num">Level ${level.level}</span>
            <input type="number" value="${level.small_blind}" onchange="window.updateBlindLevel(${index}, 'small_blind', this.value)">
            <span>/</span>
            <input type="number" value="${level.big_blind}" onchange="window.updateBlindLevel(${index}, 'big_blind', this.value)">
            <span class="duration-label">Duration:</span>
            <input type="number" value="${level.duration}" onchange="window.updateBlindLevel(${index}, 'duration', this.value)">
            <span>min</span>
            <button class="btn-small delete" onclick="window.removeBlindLevel(${index})">×</button>
        </div>
    `).join('');
}

function renderEditBlindLevels() {
    const container = document.getElementById('editBlindLevelsList');
    if (!container) return;
    
    if (!currentBlindLevels.length) {
        container.innerHTML = '<div class="empty-message">No blind levels configured</div>';
        return;
    }
    
    container.innerHTML = currentBlindLevels.map((level, index) => `
        <div class="blind-level-row">
            <span class="level-num">Level ${level.level}</span>
            <input type="number" value="${level.small_blind}" onchange="window.updateEditBlindLevel(${index}, 'small_blind', this.value)">
            <span>/</span>
            <input type="number" value="${level.big_blind}" onchange="window.updateEditBlindLevel(${index}, 'big_blind', this.value)">
            <span>Duration:</span>
            <input type="number" value="${level.duration}" onchange="window.updateEditBlindLevel(${index}, 'duration', this.value)">
            <span>min</span>
            <button class="btn-small delete" onclick="window.removeEditBlindLevel(${index})">×</button>
        </div>
    `).join('');
}

window.updateBlindLevel = function(index, field, value) {
    if (currentBlindLevels[index]) {
        currentBlindLevels[index][field] = parseInt(value);
    }
    renderBlindLevels();
};

window.updateEditBlindLevel = function(index, field, value) {
    if (currentBlindLevels[index]) {
        currentBlindLevels[index][field] = parseInt(value);
    }
    renderEditBlindLevels();
};

window.addBlindLevel = function() {
    currentBlindLevels.push({
        level: currentBlindLevels.length + 1,
        small_blind: currentBlindLevels.length > 0 ? currentBlindLevels[currentBlindLevels.length - 1].small_blind * 2 : 10,
        big_blind: currentBlindLevels.length > 0 ? currentBlindLevels[currentBlindLevels.length - 1].big_blind * 2 : 20,
        duration: 10
    });
    renderBlindLevels();
};

window.addEditBlindLevel = function() {
    currentBlindLevels.push({
        level: currentBlindLevels.length + 1,
        small_blind: currentBlindLevels.length > 0 ? currentBlindLevels[currentBlindLevels.length - 1].small_blind * 2 : 10,
        big_blind: currentBlindLevels.length > 0 ? currentBlindLevels[currentBlindLevels.length - 1].big_blind * 2 : 20,
        duration: 10
    });
    renderEditBlindLevels();
};

window.removeBlindLevel = function(index) {
    currentBlindLevels.splice(index, 1);
    currentBlindLevels.forEach((l, i) => l.level = i + 1);
    renderBlindLevels();
};

window.removeEditBlindLevel = function(index) {
    currentBlindLevels.splice(index, 1);
    currentBlindLevels.forEach((l, i) => l.level = i + 1);
    renderEditBlindLevels();
};

function generateBlindLevels() {
    const initialSB = parseInt(document.getElementById('initialSmallBlind')?.value || 10);
    const initialBB = parseInt(document.getElementById('initialBigBlind')?.value || 20);
    const duration = parseInt(document.getElementById('defaultLevelDuration')?.value || 10);
    const increaseType = document.getElementById('blindIncreaseType')?.value || 'standard';
    
    const multipliers = {
        'standard': [1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5, 6, 7, 8, 9, 10],
        'slow': [1, 1.25, 1.5, 1.75, 2, 2.25, 2.5, 2.75, 3, 3.5, 4, 4.5, 5, 6],
        'fast': [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 18, 20]
    };
    
    const mult = multipliers[increaseType] || multipliers.standard;
    currentBlindLevels = [];
    
    for (let i = 0; i < 20; i++) {
        const multiplier = mult[Math.min(i, mult.length - 1)];
        currentBlindLevels.push({
            level: i + 1,
            small_blind: Math.floor(initialSB * multiplier),
            big_blind: Math.floor(initialBB * multiplier),
            duration: duration
        });
    }
    renderBlindLevels();
}



function updatePrizePreview() {
    const maxPlayers = parseInt(document.getElementById('tournamentMaxPlayers')?.value || 100);
    const prizePool = parseInt(document.getElementById('tournamentPrizePool')?.value || 0);
    const itmPercentage = parseFloat(document.getElementById('tournamentItm')?.value || 10);
    
    if (prizePool === 0) {
        const container = document.getElementById('prizePreviewList');
        if (container) container.innerHTML = '<div class="empty-message">No prize pool - ranking only</div>';
        return;
    }
    
    const numPaid = Math.max(1, Math.floor(maxPlayers * itmPercentage / 100));
    const distribution = [25, 15, 10, 8, 7, 6, 5, 4, 3, 2, 1.5, 1, 0.5];
    
    let prizes = [];
    let remaining = prizePool;
    
    for (let i = 0; i < numPaid - 1 && i < distribution.length; i++) {
        const amount = Math.floor(prizePool * distribution[i] / 100);
        prizes.push({ rank: i + 1, percentage: distribution[i], amount: amount });
        remaining -= amount;
    }
    
    prizes.push({ rank: numPaid, percentage: parseFloat((remaining / prizePool * 100).toFixed(1)), amount: remaining });
    
    const container = document.getElementById('prizePreviewList');
    if (container) {
        container.innerHTML = prizes.map(p => `
            <div class="prize-preview-item">
                <span>${p.rank}${getOrdinal(p.rank)} place</span>
                <span>${p.percentage}% (💰 ${p.amount.toLocaleString()} chips)</span>
            </div>
        `).join('');
    }
}

// frontend/js/admin.js - Modifier editTournament
window.editTournament = async function(tournamentId) {
    try {
        const response = await fetch(`/api/tournaments/${tournamentId}`);
        if (!response.ok) throw new Error('Failed to load tournament');
        const tournament = await response.json();
        
        document.getElementById('editTournamentId').value = tournament.id;
        document.getElementById('editTournamentName').value = tournament.name;
        document.getElementById('editTournamentDescription').value = tournament.description || '';
        document.getElementById('editMaxPlayers').value = tournament.max_players;
        document.getElementById('editMinPlayersToStart').value = tournament.min_players_to_start || 4;
        document.getElementById('editPrizePool').value = tournament.prize_pool || 0;
        document.getElementById('editItmPercentage').value = tournament.itm_percentage || 10;
        
        // Formater les dates
        const formatDateForInput = (dateStr) => {
            if (!dateStr) return '';
            return dateStr.slice(0, 16);
        };
        
        document.getElementById('editRegistrationStart').value = formatDateForInput(tournament.registration_start);
        document.getElementById('editRegistrationEnd').value = formatDateForInput(tournament.registration_end);
        document.getElementById('editStartTime').value = formatDateForInput(tournament.start_time);
        
        // Blind structure
        currentBlindLevels = tournament.blind_structure || [];
        renderEditBlindLevels();
        
        // Initialiser les onglets d'édition
        initEditFormTabs();
        
        document.getElementById('editTournamentModal').style.display = 'block';
    } catch (error) {
        console.error('Error loading tournament:', error);
        alert('Failed to load tournament');
    }
};

function initEditFormTabs() {
    const editModal = document.getElementById('editTournamentModal');
    if (!editModal) return;
    
    const tabs = editModal.querySelectorAll('.form-tabs .tab-btn');
    const panes = editModal.querySelectorAll('.tab-pane');
    
    tabs.forEach(tab => {
        tab.onclick = () => {
            const tabId = tab.getAttribute('data-tab');
            tabs.forEach(t => t.classList.remove('active'));
            panes.forEach(p => p.classList.remove('active'));
            tab.classList.add('active');
            const activePane = editModal.querySelector(`#${tabId}`);
            if (activePane) activePane.classList.add('active');
        };
    });
}

// Ajouter les champs manquants dans editTournamentForm
document.getElementById('editTournamentForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const tournamentId = document.getElementById('editTournamentId').value;
    const formatDate = (dateStr) => dateStr ? new Date(dateStr).toISOString() : null;
    
    const data = {
        name: document.getElementById('editTournamentName').value,
        description: document.getElementById('editTournamentDescription').value,
        max_players: parseInt(document.getElementById('editMaxPlayers').value),
        min_players_to_start: parseInt(document.getElementById('editMinPlayersToStart')?.value || 4),
        registration_start: formatDate(document.getElementById('editRegistrationStart').value),
        registration_end: formatDate(document.getElementById('editRegistrationEnd').value),
        start_time: formatDate(document.getElementById('editStartTime').value),
        prize_pool: parseInt(document.getElementById('editPrizePool').value),
        itm_percentage: parseFloat(document.getElementById('editItmPercentage').value),
        blind_structure: currentBlindLevels
    };
    
    try {
        const response = await fetch(`/api/tournaments/${tournamentId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        
        if (response.ok) {
            alert('Tournament updated successfully!');
            closeModal('editTournamentModal');
            loadTournaments();
        } else {
            const error = await response.json();
            alert(error.detail || 'Update failed');
        }
    } catch (error) {
        console.error('Error updating tournament:', error);
        alert('Update failed');
    }
});

function getOrdinal(n) {
    const s = ['th', 'st', 'nd', 'rd'];
    const v = n % 100;
    return s[(v - 20) % 10] || s[v] || s[0];
}

function formatDateTimeLocal(date) {
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}T${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

function initFormTabs() {
    // Onglets du modal de création
    const createModal = document.getElementById('tournamentModal');
    if (createModal) {
        const tabs = createModal.querySelectorAll('.form-tabs .tab-btn');
        const panes = createModal.querySelectorAll('.tab-pane');
        
        tabs.forEach(tab => {
            tab.onclick = () => {
                const tabId = tab.getAttribute('data-tab');
                // Désactiver tous les onglets
                tabs.forEach(t => t.classList.remove('active'));
                // Désactiver tous les panneaux
                panes.forEach(p => p.classList.remove('active'));
                // Activer l'onglet cliqué
                tab.classList.add('active');
                // Activer le panneau correspondant
                const activePane = createModal.querySelector(`#tab-${tabId}`);
                if (activePane) activePane.classList.add('active');
            };
        });
    }
    
    // Onglets du modal d'édition
    const editModal = document.getElementById('editTournamentModal');
    if (editModal) {
        const tabs = editModal.querySelectorAll('.form-tabs .tab-btn');
        const panes = editModal.querySelectorAll('.tab-pane');
        
        tabs.forEach(tab => {
            tab.onclick = () => {
                const tabId = tab.getAttribute('data-tab');
                // Désactiver tous les onglets
                tabs.forEach(t => t.classList.remove('active'));
                // Désactiver tous les panneaux
                panes.forEach(p => p.classList.remove('active'));
                // Activer l'onglet cliqué
                tab.classList.add('active');
                // Activer le panneau correspondant
                let activePane = editModal.querySelector(`#${tabId}`);
                if (!activePane) {
                    activePane = editModal.querySelector(`#edit-${tabId.replace('edit-', '')}`);
                }
                if (activePane) activePane.classList.add('active');
            };
        });
    }
}

function initTournamentForm() {
    console.log('Initializing tournament form...');
    initFormTabs();
    // Setup generate blinds button
    const generateBtn = document.getElementById('generateBlindsBtn');
    if (generateBtn) {
        generateBtn.onclick = generateBlindLevels;
    }
    
    // Setup prize preview
    const prizeInputs = ['tournamentMaxPlayers', 'tournamentPrizePool', 'tournamentItm'];
    prizeInputs.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.onchange = updatePrizePreview;
            el.oninput = updatePrizePreview;
        }
    });
    
    // Generate default blinds
    generateBlindLevels();
    updatePrizePreview();
    
    // Set default dates
    const now = new Date();
    const tomorrow = new Date(now);
    tomorrow.setDate(tomorrow.getDate() + 1);
    const nextWeek = new Date(now);
    nextWeek.setDate(nextWeek.getDate() + 7);
    
    const regStartInput = document.getElementById('tournamentRegistrationStart');
    const regEndInput = document.getElementById('tournamentRegistrationEnd');
    const startTimeInput = document.getElementById('tournamentStartTime');
    
    if (regStartInput) regStartInput.value = formatDateTimeLocal(now);
    if (regEndInput) regEndInput.value = formatDateTimeLocal(tomorrow);
    if (startTimeInput) startTimeInput.value = formatDateTimeLocal(nextWeek);
}



document.getElementById('tournamentForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const formatDate = (dateStr) => dateStr ? new Date(dateStr).toISOString() : null;
    
    const data = {
        name: document.getElementById('tournamentName')?.value,
        description: document.getElementById('tournamentDescription')?.value,
        max_players: parseInt(document.getElementById('tournamentMaxPlayers')?.value || 100),
        min_players_to_start: parseInt(document.getElementById('minPlayersToStart')?.value || 4),
        registration_start: formatDate(document.getElementById('tournamentRegistrationStart')?.value),
        registration_end: formatDate(document.getElementById('tournamentRegistrationEnd')?.value),
        start_time: formatDate(document.getElementById('tournamentStartTime')?.value),
        blind_structure: currentBlindLevels,
        prize_pool: parseInt(document.getElementById('tournamentPrizePool')?.value || 0),
        itm_percentage: parseFloat(document.getElementById('tournamentItm')?.value || 10),
        time_bank_seconds: parseInt(document.getElementById('timeBank')?.value || 30),
        time_bank_extensions: parseInt(document.getElementById('timeBankExtensions')?.value || 3),
        auto_start_full: document.getElementById('autoStartFull')?.checked || false,
        spectators_allowed: document.getElementById('spectatorsAllowed')?.checked || true,
        chat_enabled: document.getElementById('chatEnabled')?.checked || true
    };    
    if (!data.name) {
        alert('Tournament name is required');
        return;
    }
    
    try {
        const response = await fetch('/api/tournaments', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        
        if (response.ok) {
            alert('Tournament created successfully!');
            closeModal('tournamentModal');
            loadTournaments();
            document.getElementById('tournamentForm').reset();
            currentBlindLevels = [];
            renderBlindLevels();
        } else {
            const error = await response.json();
            alert('Failed to create tournament: ' + (error.detail || JSON.stringify(error)));
        }
    } catch (error) {
        console.error('Error creating tournament:', error);
        alert('Failed to create tournament');
    }
});

// Save settings
async function saveServerSettings() {
    const settings = {
        server_name: document.getElementById('serverName')?.value,
        max_players_per_table: parseInt(document.getElementById('maxPlayersPerTable')?.value || 9),
        default_small_blind: parseInt(document.getElementById('defaultSmallBlind')?.value || 5),
        default_big_blind: parseInt(document.getElementById('defaultBigBlind')?.value || 10)
    };
    
    try {
        const response = await fetch('/api/admin/settings', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settings)
        });
        
        if (response.ok) {
            alert('Settings saved');
        } else {
            alert('Failed to save settings');
        }
    } catch (error) {
        console.error('Error saving settings:', error);
        alert('Failed to save settings');
    }
}

async function saveTournamentSettings() {
    const settings = {
        tournament_default_itm: parseFloat(document.getElementById('itmPercentage')?.value || 10),
        tournament_default_blind_duration: parseInt(document.getElementById('blindDuration')?.value || 10)
    };
    
    try {
        const response = await fetch('/api/admin/tournament-settings', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settings)
        });
        
        if (response.ok) {
            alert('Tournament settings saved');
        } else {
            alert('Failed to save settings');
        }
    } catch (error) {
        console.error('Error saving tournament settings:', error);
        alert('Failed to save settings');
    }
}

// frontend/js/admin.js - Ajouter la fonction pour appliquer les thèmes
function applyTheme(theme, customCss, customCssUrl) {
    // Appliquer le thème
    document.body.className = `theme-${theme}`;
    
    // Appliquer le CSS personnalisé
    if (customCss) {
        let styleTag = document.getElementById('custom-css');
        if (!styleTag) {
            styleTag = document.createElement('style');
            styleTag.id = 'custom-css';
            document.head.appendChild(styleTag);
        }
        styleTag.textContent = customCss;
    }
    
    // Appliquer l'URL CSS personnalisée
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

// Modifier loadAppearanceSettings
async function loadAppearanceSettings() {
    try {
        const response = await fetch('/api/admin/appearance');
        if (response.ok) {
            const settings = await response.json();
            document.getElementById('themeSelect').value = settings.theme;
            document.getElementById('customCssUrl').value = settings.custom_css_url || '';
            document.getElementById('customCss').value = settings.custom_css || '';
            applyTheme(settings.theme, settings.custom_css, settings.custom_css_url);
        }
    } catch (error) {
        console.error('Error loading appearance:', error);
    }
}

// Modifier saveAppearanceSettings
document.getElementById('saveAppearanceSettings')?.addEventListener('click', async () => {
    const settings = {
        theme: document.getElementById('themeSelect')?.value || 'dark',
        custom_css_url: document.getElementById('customCssUrl')?.value || '',
        custom_css: document.getElementById('customCss')?.value || ''
    };
    
    try {
        const response = await fetch('/api/admin/appearance', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settings)
        });
        
        if (response.ok) {
            alert('Appearance settings saved!');
            applyTheme(settings.theme, settings.custom_css, settings.custom_css_url);
        } else {
            alert('Failed to save appearance settings');
        }
    } catch (error) {
        console.error('Error saving appearance:', error);
        alert('Failed to save appearance settings');
    }
});

function resetUserForm() {
    document.getElementById('editUserId').value = '';
    document.getElementById('editUsername').value = '';
    document.getElementById('editEmail').value = '';
    document.getElementById('editRole').value = 'user';
    document.getElementById('editStatus').value = 'active';
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) modal.style.display = 'none';
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Start
init();
