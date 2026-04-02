// frontend/js/admin.js
/**
 * admin.js — Interface d'administration PokerEndPasse
 * Gère les tournois (création, édition, pause, reprise, suppression),
 * les utilisateurs, les statistiques, les actions admin sur les joueurs (mute, exclude).
 * Compatible avec le nouveau SettingsManager et les modules backend corrigés.
 */

const $ = (id) => document.getElementById(id);

// ── Initialisation ─────────────────────────────────────────────────────────
async function init() {
    setupTabs();
    await loadDashboard();
    await loadTournaments();
    await loadUsers();
    // Éventuellement synchroniser le thème avec les préférences
    if (typeof SettingsManager !== 'undefined') {
        const theme = SettingsManager.get('theme') || 'dark';
        if (typeof ThemeManager !== 'undefined') ThemeManager.setTheme(theme);
    }
}

// ── Tabs ───────────────────────────────────────────────────────────────────
function setupTabs() {
    document.querySelectorAll('.admin-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.admin-tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            tab.classList.add('active');
            const target = $(tab.dataset.tab);
            if (target) target.classList.add('active');
        });
    });
}

// ── Dashboard ──────────────────────────────────────────────────────────────
async function loadDashboard() {
    try {
        const resp = await fetch('/api/admin/stats');
        if (!resp.ok) return;
        const data = await resp.json();
        $('statActivePlayers').textContent = data.active_players || 0;
        $('statTables').textContent = data.total_tables || 0;
        $('statTournaments').textContent = data.tournaments || 0;
        $('statTotalPlayers').textContent = data.total_players || 0;
    } catch (e) { console.error('Dashboard:', e); }
}

// ── Tournaments ────────────────────────────────────────────────────────────
async function loadTournaments() {
    try {
        const resp = await fetch('/api/tournaments');
        if (!resp.ok) return;
        const tournaments = await resp.json();
        renderAdminTournaments(tournaments);
    } catch (e) {}
}

function renderAdminTournaments(tournaments) {
    const container = $('adminTournamentsList');
    if (!container) return;
    if (!tournaments.length) { container.innerHTML = '<p style="color:var(--text-muted)">Aucun tournoi</p>'; return; }

    container.innerHTML = `<table class="data-table">
        <thead>
            <tr><th>Nom</th><th>Variante</th><th>Status</th><th>Joueurs</th><th>Début</th><th>Actions</th></tr>
        </thead>
        <tbody>${tournaments.map(t => `
            <tr>
                <td>${esc(t.name)}</td>
                <td>${t.game_variant === 'plo' ? 'PLO' : "Hold'em"}</td>
                <td><span class="status-badge status-${t.status}">${t.status}</span></td>
                <td>${t.players_count}/${t.max_players}</td>
                <td>${t.start_time ? new Date(t.start_time).toLocaleString().slice(0, 16) : '—'}</td>
                <td>
                    ${t.status === 'in_progress' ? `<button class="action-btn-sm warn" onclick="pauseTournament('${t.id}')">⏸ Pause</button>` : ''}
                    ${t.status === 'paused' ? `<button class="action-btn-sm success" onclick="resumeTournament('${t.id}')">▶ Reprendre</button>` : ''}
                    <button class="action-btn-sm edit" onclick="editTournament('${t.id}')">✏️ Éditer</button>
                    <button class="action-btn-sm edit" onclick="showTournamentPlayers('${t.id}')">👥 Joueurs</button>
                    <button class="action-btn-sm danger" onclick="deleteTournament('${t.id}')">🗑</button>
                </td>
            </tr>
        `).join('')}</tbody>
    </table>`;
}

async function editTournament(tid) {
    try {
        const resp = await fetch(`/api/tournaments/${tid}`);
        if (!resp.ok) throw new Error('Tournoi introuvable');
        const t = await resp.json();

        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.style.display = 'flex';

        const formatDate = (iso) => {
            if (!iso) return '';
            const d = new Date(iso);
            return d.toISOString().slice(0, 16);
        };

        modal.innerHTML = `
            <div class="modal-content" style="max-width: 500px;">
                <span class="close">&times;</span>
                <h2>✏️ Éditer: ${esc(t.name)}</h2>
                <form id="editTournamentForm">
                    <div class="form-group"><label>Nom :</label><input type="text" id="editName" value="${esc(t.name)}" required></div>
                    <div class="form-group"><label>Description :</label><textarea id="editDesc" rows="2">${esc(t.description || '')}</textarea></div>
                    <div class="form-group"><label>Variante :</label><select id="editVariant">
                        <option value="holdem" ${t.game_variant === 'holdem' ? 'selected' : ''}>Hold'em</option>
                        <option value="plo" ${t.game_variant === 'plo' ? 'selected' : ''}>PLO</option>
                    </select></div>
                    <div class="form-group"><label>Max joueurs :</label><input type="number" id="editMax" value="${t.max_players}" min="2" max="500"></div>
                    <div class="form-group"><label>Min pour démarrer :</label><input type="number" id="editMin" value="${t.min_players_to_start}" min="2"></div>
                    <div class="form-group"><label>Prize pool (0 = freeroll) :</label><input type="number" id="editPrize" value="${t.prize_pool || 0}"></div>
                    <div class="form-group"><label>ITM % :</label><input type="number" id="editItm" value="${t.itm_percentage || 10}" step="1"></div>
                    <div class="form-group"><label>Début inscriptions :</label><input type="datetime-local" id="editRegStart" value="${formatDate(t.registration_start)}" required></div>
                    <div class="form-group"><label>Fin inscriptions :</label><input type="datetime-local" id="editRegEnd" value="${formatDate(t.registration_end)}" required></div>
                    <div class="form-group"><label>Début tournoi :</label><input type="datetime-local" id="editStart" value="${formatDate(t.start_time)}" required></div>
                    <button type="submit" class="btn-primary">Sauvegarder</button>
                    <button type="button" class="btn-secondary" onclick="this.closest('.modal').remove()">Annuler</button>
                </form>
            </div>
        `;

        document.body.appendChild(modal);
        modal.querySelector('.close')?.addEventListener('click', () => modal.remove());
        modal.addEventListener('click', (e) => { if (e.target === modal) modal.remove(); });

        const form = modal.querySelector('#editTournamentForm');
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const updateData = {
                name: document.getElementById('editName').value,
                description: document.getElementById('editDesc').value,
                game_variant: document.getElementById('editVariant').value,
                max_players: parseInt(document.getElementById('editMax').value),
                min_players_to_start: parseInt(document.getElementById('editMin').value),
                prize_pool: parseInt(document.getElementById('editPrize').value) || 0,
                itm_percentage: parseFloat(document.getElementById('editItm').value) || 10,
                registration_start: new Date(document.getElementById('editRegStart').value).toISOString(),
                registration_end: new Date(document.getElementById('editRegEnd').value).toISOString(),
                start_time: new Date(document.getElementById('editStart').value).toISOString(),
            };
            try {
                const resp = await fetch(`/api/admin/tournaments/${tid}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(updateData),
                });
                if (resp.ok) {
                    alert('Tournoi mis à jour !');
                    modal.remove();
                    loadTournaments();
                } else {
                    const err = await resp.json();
                    alert(err.detail || 'Erreur');
                }
            } catch (e) {
                alert('Erreur réseau');
            }
        });
    } catch (e) {
        alert('Erreur chargement du tournoi');
    }
}

async function createTournament() {
    const data = {
        name: $('tName')?.value,
        description: $('tDesc')?.value || '',
        game_variant: $('tVariant')?.value || 'holdem',
        max_players: parseInt($('tMax')?.value || 100),
        min_players_to_start: parseInt($('tMin')?.value || 4),
        prize_pool: parseInt($('tPrize')?.value || 0),
        itm_percentage: parseFloat($('tItm')?.value || 10),
        registration_start: $('tRegStart')?.value ? new Date($('tRegStart').value).toISOString() : new Date().toISOString(),
        registration_end: $('tRegEnd')?.value ? new Date($('tRegEnd').value).toISOString() : new Date(Date.now() + 3600000).toISOString(),
        start_time: $('tStart')?.value ? new Date($('tStart').value).toISOString() : new Date(Date.now() + 7200000).toISOString(),
    };
    if (!data.name) { alert('Nom requis'); return; }
    try {
        const resp = await fetch('/api/admin/tournaments', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (resp.ok) { alert('Tournoi créé!'); loadTournaments(); }
        else { const e = await resp.json(); alert(e.detail || 'Erreur'); }
    } catch (e) { alert('Erreur réseau'); }
}

async function pauseTournament(tid) {
    await fetch(`/api/admin/tournaments/${tid}/pause`, { method: 'POST' });
    loadTournaments();
}

async function resumeTournament(tid) {
    await fetch(`/api/admin/tournaments/${tid}/resume`, { method: 'POST' });
    loadTournaments();
}

async function deleteTournament(tid) {
    if (!confirm('Supprimer ce tournoi?')) return;
    await fetch(`/api/admin/tournaments/${tid}`, { method: 'DELETE' });
    loadTournaments();
}

async function showTournamentPlayers(tid) {
    try {
        const resp = await fetch(`/api/tournaments/${tid}`);
        if (!resp.ok) return;
        const t = await resp.json();
        const players = t.ranking || [];
        let html = `<h3>Joueurs — ${esc(t.name)}</h3>
            <table class="data-table">
            <thead><tr><th>Pseudo</th><th>Chips</th><th>Status</th><th>Actions</th></tr></thead>
            <tbody>${players.map(p => `<tr>
                <td>${esc(p.username)}</td>
                <td>${p.chips || 0}</td>
                <td>${p.status} ${p.sit_out ? '(absent)' : ''} ${p.muted ? '🔇' : ''}</td>
                <td>
                    ${p.muted
                        ? `<button class="action-btn-sm success" onclick="unmute('${tid}','${p.user_id}')">🔊 Unmute</button>`
                        : `<button class="action-btn-sm warn" onclick="mute('${tid}','${p.user_id}')">🔇 Mute</button>`
                    }
                    ${p.status !== 'eliminated'
                        ? `<button class="action-btn-sm danger" onclick="exclude('${tid}','${p.user_id}')">❌ Exclure</button>`
                        : ''
                    }
                </td>
            </tr>`).join('')}</tbody></table>`;

        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.style.display = 'flex';
        modal.innerHTML = `<div class="modal-content" style="max-width:700px">${html}<br><button class="btn-secondary" onclick="this.closest('.modal').remove()">Fermer</button></div>`;
        document.body.appendChild(modal);
    } catch (e) { alert('Erreur'); }
}

async function mute(tid, uid) {
    await fetch(`/api/admin/tournaments/${tid}/mute`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: uid }),
    });
    document.querySelector('.modal')?.remove();
    showTournamentPlayers(tid);
}

async function unmute(tid, uid) {
    await fetch(`/api/admin/tournaments/${tid}/unmute`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: uid }),
    });
    document.querySelector('.modal')?.remove();
    showTournamentPlayers(tid);
}

async function exclude(tid, uid) {
    const reason = prompt('Raison de l\'exclusion:');
    if (reason === null) return;
    await fetch(`/api/admin/tournaments/${tid}/exclude`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: uid, reason }),
    });
    document.querySelector('.modal')?.remove();
    showTournamentPlayers(tid);
}

// ── Users ──────────────────────────────────────────────────────────────────
async function loadUsers() {
    try {
        const resp = await fetch('/api/admin/users');
        if (!resp.ok) return;
        const users = await resp.json();
        const tbody = document.querySelector('#usersTable tbody');
        if (!tbody) return;
        tbody.innerHTML = users.map(u => `<tr>
            <td>${esc(u.username)}</td>
            <td>${esc(u.email || '—')}</td>
            <td>${u.is_admin ? '✅' : '—'}</td>
            <td>${u.status}</td>
            <td>—</td>
        </tr>`).join('');
    } catch (e) {}
}

// ── Appearance ─────────────────────────────────────────────────────────────
function saveAppearance() {
    const theme = $('adminTheme')?.value || 'dark';
    if (typeof SettingsManager !== 'undefined') {
        SettingsManager.set('theme', theme);
        if (typeof ThemeManager !== 'undefined') ThemeManager.setTheme(theme);
    }
    alert(`Thème "${theme}" sauvegardé.`);
}

// ── Utils ──────────────────────────────────────────────────────────────────
function esc(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
}

// Exposer les fonctions globalement pour les appels inline
window.init = init;
window.pauseTournament = pauseTournament;
window.resumeTournament = resumeTournament;
window.editTournament = editTournament;
window.deleteTournament = deleteTournament;
window.showTournamentPlayers = showTournamentPlayers;
window.mute = mute;
window.unmute = unmute;
window.exclude = exclude;
window.createTournament = createTournament;
window.saveAppearance = saveAppearance;

document.addEventListener('DOMContentLoaded', init);
