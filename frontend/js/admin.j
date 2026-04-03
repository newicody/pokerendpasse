/**
 * admin.js — Interface d'administration PokerEndPasse
 * Pause, mute, exclude, gestion tournois et utilisateurs
 *
 * Corrections :
 *  - Vérification admin au chargement (init)
 *  - Gestion d'erreur sur pause/resume/delete
 *  - Nettoyage modale avant ouverture (plus d'empilement)
 *  - Reset formulaire après création tournoi
 *  - Champ starting_chips ajouté
 *  - Auto-refresh dashboard toutes les 15s
 *  - Logging erreurs loadTournaments
 */

const $ = (id) => document.getElementById(id);
let _dashboardInterval = null;

async function init() {
    // ── Vérifier que l'utilisateur est admin ──
    try {
        const resp = await fetch('/api/auth/me');
        if (!resp.ok) {
            window.location.href = '/lobby';
            return;
        }
        const data = await resp.json();
        if (!data.authenticated || !data.user?.is_admin) {
            alert('Accès réservé aux administrateurs');
            window.location.href = '/lobby';
            return;
        }
    } catch (e) {
        window.location.href = '/lobby';
        return;
    }

    setupTabs();
    await loadDashboard();
    await loadTournaments();
    await loadUsers();

    // Auto-refresh dashboard toutes les 15 secondes
    _dashboardInterval = setInterval(loadDashboard, 15000);
}

// ── Tabs ─────────────────────────────────────────────────────────────────
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

// ── Dashboard ────────────────────────────────────────────────────────────
async function loadDashboard() {
    try {
        const resp = await fetch('/api/admin/stats');
        if (!resp.ok) {
            console.error('Dashboard: HTTP', resp.status);
            return;
        }
        const data = await resp.json();
        $('statActivePlayers').textContent = data.active_players || 0;
        $('statTables').textContent = data.total_tables || 0;
        $('statTournaments').textContent = data.tournaments || 0;
        $('statTotalPlayers').textContent = data.total_players || 0;
    } catch (e) {
        console.error('Dashboard:', e);
    }
}

// ── Tournaments ──────────────────────────────────────────────────────────
async function loadTournaments() {
    try {
        const resp = await fetch('/api/tournaments');
        if (!resp.ok) {
            console.error('loadTournaments: HTTP', resp.status);
            return;
        }
        const tournaments = await resp.json();
        renderAdminTournaments(tournaments);
    } catch (e) {
        console.error('loadTournaments:', e);
    }
}

function renderAdminTournaments(tournaments) {
    const container = $('adminTournamentsList');
    if (!container) return;
    if (!tournaments.length) {
        container.innerHTML = '<p style="color:var(--text-muted)">Aucun tournoi</p>';
        return;
    }

    container.innerHTML = `<table class="data-table">
        <thead><tr><th>Nom</th><th>Variante</th><th>Status</th><th>Joueurs</th><th>Actions</th></tr></thead>
        <tbody>${tournaments.map(t => `<tr>
            <td>${esc(t.name)}</td>
            <td>${t.game_variant === 'plo' ? 'PLO' : "Hold'em"}</td>
            <td><span class="status-badge status-${t.status}">${t.status}</span></td>
            <td>${t.players_count}/${t.max_players}</td>
            <td>
                ${t.status === 'in_progress' ? `<button class="action-btn-sm warn" onclick="pauseTournament('${esc(t.id)}')">⏸ Pause</button>` : ''}
                ${t.status === 'paused' ? `<button class="action-btn-sm success" onclick="resumeTournament('${esc(t.id)}')">▶ Reprendre</button>` : ''}
                <button class="action-btn-sm edit" onclick="showTournamentPlayers('${esc(t.id)}')">👥 Joueurs</button>
                <button class="action-btn-sm danger" onclick="deleteTournament('${esc(t.id)}')">🗑</button>
            </td>
        </tr>`).join('')}</tbody>
    </table>`;
}

async function createTournament() {
    const data = {
        name: $('tName')?.value,
        description: $('tDesc')?.value || '',
        game_variant: $('tVariant')?.value || 'holdem',
        max_players: parseInt($('tMax')?.value || 100),
        min_players_to_start: parseInt($('tMin')?.value || 4),
        starting_chips: parseInt($('tChips')?.value || 10000),
        prize_pool: parseInt($('tPrize')?.value || 0),
        itm_percentage: parseFloat($('tItm')?.value || 10),
        registration_start: $('tRegStart')?.value ? new Date($('tRegStart').value).toISOString() : new Date().toISOString(),
        registration_end: $('tRegEnd')?.value ? new Date($('tRegEnd').value).toISOString() : new Date(Date.now() + 3600000).toISOString(),
        start_time: $('tStart')?.value ? new Date($('tStart').value).toISOString() : new Date(Date.now() + 7200000).toISOString(),
    };
    if (!data.name) { alert('Nom requis'); return; }
    try {
        const resp = await fetch('/api/admin/tournaments', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (resp.ok) {
            alert('Tournoi créé!');
            // Reset formulaire
            if ($('tName')) $('tName').value = '';
            if ($('tDesc')) $('tDesc').value = '';
            if ($('tVariant')) $('tVariant').value = 'holdem';
            if ($('tMax')) $('tMax').value = '100';
            if ($('tMin')) $('tMin').value = '4';
            if ($('tChips')) $('tChips').value = '10000';
            if ($('tPrize')) $('tPrize').value = '0';
            if ($('tItm')) $('tItm').value = '10';
            if ($('tRegStart')) $('tRegStart').value = '';
            if ($('tRegEnd')) $('tRegEnd').value = '';
            if ($('tStart')) $('tStart').value = '';
            loadTournaments();
        } else {
            const e = await resp.json();
            alert(e.detail || 'Erreur');
        }
    } catch (e) {
        alert('Erreur réseau');
    }
}

async function pauseTournament(tid) {
    try {
        const resp = await fetch(`/api/admin/tournaments/${tid}/pause`, { method: 'POST' });
        if (!resp.ok) {
            const e = await resp.json().catch(() => ({}));
            alert(e.detail || `Erreur pause (${resp.status})`);
        }
    } catch (e) {
        alert('Erreur réseau');
    }
    loadTournaments();
}

async function resumeTournament(tid) {
    try {
        const resp = await fetch(`/api/admin/tournaments/${tid}/resume`, { method: 'POST' });
        if (!resp.ok) {
            const e = await resp.json().catch(() => ({}));
            alert(e.detail || `Erreur reprise (${resp.status})`);
        }
    } catch (e) {
        alert('Erreur réseau');
    }
    loadTournaments();
}

async function deleteTournament(tid) {
    if (!confirm('Supprimer ce tournoi?')) return;
    try {
        const resp = await fetch(`/api/admin/tournaments/${tid}`, { method: 'DELETE' });
        if (!resp.ok) {
            const e = await resp.json().catch(() => ({}));
            alert(e.detail || `Erreur suppression (${resp.status})`);
        }
    } catch (e) {
        alert('Erreur réseau');
    }
    loadTournaments();
}

async function showTournamentPlayers(tid) {
    // ── Nettoyage des modales existantes ──
    document.querySelectorAll('.modal').forEach(m => m.remove());

    try {
        const resp = await fetch(`/api/tournaments/${tid}`);
        if (!resp.ok) {
            alert('Impossible de charger les joueurs');
            return;
        }
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
                        ? `<button class="action-btn-sm success" onclick="unmute('${esc(tid)}','${esc(p.user_id)}')">🔊 Unmute</button>`
                        : `<button class="action-btn-sm warn" onclick="mute('${esc(tid)}','${esc(p.user_id)}')">🔇 Mute</button>`
                    }
                    ${p.status !== 'eliminated'
                        ? `<button class="action-btn-sm danger" onclick="exclude('${esc(tid)}','${esc(p.user_id)}')">❌ Exclure</button>`
                        : ''
                    }
                </td>
            </tr>`).join('')}</tbody></table>`;

        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.style.display = 'flex';
        modal.innerHTML = `<div class="modal-content" style="max-width:700px">${html}<br><button class="btn-secondary" onclick="this.closest('.modal').remove()">Fermer</button></div>`;
        document.body.appendChild(modal);
    } catch (e) {
        console.error('showTournamentPlayers:', e);
        alert('Erreur chargement joueurs');
    }
}

async function mute(tid, uid) {
    try {
        const resp = await fetch(`/api/admin/tournaments/${tid}/mute`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: uid }),
        });
        if (!resp.ok) {
            const e = await resp.json().catch(() => ({}));
            alert(e.detail || 'Erreur mute');
        }
    } catch (e) {
        alert('Erreur réseau');
    }
    document.querySelectorAll('.modal').forEach(m => m.remove());
    showTournamentPlayers(tid);
}

async function unmute(tid, uid) {
    try {
        const resp = await fetch(`/api/admin/tournaments/${tid}/unmute`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: uid }),
        });
        if (!resp.ok) {
            const e = await resp.json().catch(() => ({}));
            alert(e.detail || 'Erreur unmute');
        }
    } catch (e) {
        alert('Erreur réseau');
    }
    document.querySelectorAll('.modal').forEach(m => m.remove());
    showTournamentPlayers(tid);
}

async function exclude(tid, uid) {
    const reason = prompt("Raison de l'exclusion:");
    if (reason === null) return;
    try {
        const resp = await fetch(`/api/admin/tournaments/${tid}/exclude`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: uid, reason }),
        });
        if (!resp.ok) {
            const e = await resp.json().catch(() => ({}));
            alert(e.detail || 'Erreur exclusion');
        }
    } catch (e) {
        alert('Erreur réseau');
    }
    document.querySelectorAll('.modal').forEach(m => m.remove());
    showTournamentPlayers(tid);
}

// ── Users ────────────────────────────────────────────────────────────────
async function loadUsers() {
    try {
        const resp = await fetch('/api/admin/users');
        if (!resp.ok) {
            console.error('loadUsers: HTTP', resp.status);
            return;
        }
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
    } catch (e) {
        console.error('loadUsers:', e);
    }
}

// ── Appearance ───────────────────────────────────────────────────────────
function saveAppearance() {
    const theme = $('adminTheme')?.value || 'dark';
    alert(`Thème "${theme}" sauvegardé (côté serveur à implémenter)`);
}

// ── Utils ────────────────────────────────────────────────────────────────
function esc(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
}

document.addEventListener('DOMContentLoaded', init);
