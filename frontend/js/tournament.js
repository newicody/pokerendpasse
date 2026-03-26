// frontend/js/tournament.js
let currentUser = null;
let isAdmin = false;

async function init() {
    await window.initCurrentUser();
    currentUser = window.currentUser;
    
    if (!currentUser) {
        window.location.href = '/';
        return;
    }
    
    // Vérifier si admin (à implémenter)
    isAdmin = currentUser.username === 'admin';
    
    if (isAdmin) {
        document.getElementById('createTournamentBtn').style.display = 'block';
        document.getElementById('createTournamentBtn').onclick = showCreateModal;
    }
    
    await loadTournaments();
    setupEventListeners();
}

async function loadTournaments() {
    try {
        const response = await fetch('/api/tournaments');
        const tournaments = await response.json();
        renderTournaments(tournaments);
    } catch (error) {
        console.error('Error loading tournaments:', error);
        document.getElementById('tournamentsList').innerHTML = 
            '<div class="error">Error loading tournaments</div>';
    }
}

function renderTournaments(tournaments) {
    const container = document.getElementById('tournamentsList');
    
    if (!tournaments || tournaments.length === 0) {
        container.innerHTML = '<div class="empty">No tournaments scheduled</div>';
        return;
    }
    
    container.innerHTML = tournaments.map(t => `
        <div class="tournament-card" data-id="${t.id}">
            <div class="tournament-header">
                <h3>${escapeHtml(t.name)}</h3>
                <div class="tournament-status ${t.status}">${t.status}</div>
            </div>
            <div class="tournament-details">
                <div><span class="label">📅 Start:</span> ${new Date(t.start_time).toLocaleString()}</div>
                <div><span class="label">👥 Players:</span> ${t.players_count}/${t.max_players}</div>
                <div><span class="label">💰 Buy-in:</span> ${t.buy_in} chips</div>
                <div><span class="label">🏆 Prize Pool:</span> ${t.prize_pool} chips</div>
            </div>
            ${t.status === 'registration' ? 
                `<button class="register-btn" onclick="registerTournament('${t.id}')">Register</button>` : 
                t.status === 'in_progress' ? 
                '<div class="status-badge">In Progress</div>' : 
                '<div class="status-badge">Finished</div>'
            }
        </div>
    `).join('');
}

async function registerTournament(tournamentId) {
    if (!currentUser) {
        alert('Please login first');
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
            loadTournaments();
        } else {
            const error = await response.json();
            alert(error.detail || 'Registration failed');
        }
    } catch (error) {
        console.error('Error registering:', error);
        alert('Registration failed');
    }
}

function showCreateModal() {
    const modal = document.getElementById('createTournamentModal');
    modal.style.display = 'block';
}

function setupEventListeners() {
    const modal = document.getElementById('createTournamentModal');
    const closeBtn = modal.querySelector('.close');
    const form = document.getElementById('createTournamentForm');
    
    closeBtn.onclick = () => modal.style.display = 'none';
    
    form.onsubmit = async (e) => {
        e.preventDefault();
        
        const tournamentData = {
            name: document.getElementById('tournamentName').value,
            start_time: document.getElementById('startTime').value,
            max_players: parseInt(document.getElementById('maxPlayers').value),
            buy_in: parseInt(document.getElementById('buyIn').value)
        };
        
        try {
            const response = await fetch('/api/tournaments', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(tournamentData)
            });
            
            if (response.ok) {
                alert('Tournament created successfully!');
                modal.style.display = 'none';
                form.reset();
                loadTournaments();
            } else {
                const error = await response.json();
                alert(error.detail || 'Creation failed');
            }
        } catch (error) {
            console.error('Error creating tournament:', error);
            alert('Creation failed');
        }
    };
    
    window.onclick = (event) => {
        if (event.target === modal) {
            modal.style.display = 'none';
        }
    };
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

init();
