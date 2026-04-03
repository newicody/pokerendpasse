// ══════════════════════════════════════════════════════════════════════════════
// ORGANISER — Logique complète
// ══════════════════════════════════════════════════════════════════════════════
//
// Intégration : AJOUTER ce code à la fin de frontend/js/lobby.js
//               OU créer un fichier séparé frontend/js/organiser.js
//               et l'inclure dans lobby.html après lobby.js
//
// Si fichier séparé, s'assurer que $ et currentUser sont accessibles (globaux).
//
// ══════════════════════════════════════════════════════════════════════════════

// ── Setup (appeler dans init()) ─────────────────────────────────────────────
// AJOUTER dans la fonction init() de lobby.js :
//     setupOrganiser();

function setupOrganiser() {
    const organizeBtn = $('organizeBtn');
    const modal = $('organizeModal');
    if (!organizeBtn || !modal) return;

    // Afficher le bouton Organiser quand connecté
    // (Appeler cette logique AUSSI dans updateAuthUI)
    if (currentUser) {
        organizeBtn.style.display = '';
    }

    // Ouverture de la modale
    organizeBtn.addEventListener('click', () => {
        modal.style.display = 'flex';
        updateOrganiseSummary();
        loadMyTournaments();
    });

    // Fermeture
    modal.querySelector('.close')?.addEventListener('click', () => modal.style.display = 'none');
    modal.addEventListener('click', (e) => { if (e.target === modal) modal.style.display = 'none'; });

    // Onglets
    const tabs = modal.querySelectorAll('.organize-tab');
    const contents = modal.querySelectorAll('.organize-tab-content');
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const target = tab.dataset.otab;
            tabs.forEach(t => t.classList.remove('active'));
            contents.forEach(c => c.classList.remove('active'));
            tab.classList.add('active');
            const tabEl = document.getElementById(
                target === 'create' ? 'organizeCreateTab' : 'organizeMyTournamentsTab'
            );
            if (tabEl) tabEl.classList.add('active');

            if (target === 'myTournaments') loadMyTournaments();
        });
    });

    // Mise à jour du résumé en live
    ['orgBlindPreset', 'orgRegDuration', 'orgStartDelay', 'orgVariant', 'orgMaxPlayers', 'orgChips']
        .forEach(id => {
            const el = $(id);
            if (el) el.addEventListener('change', updateOrganiseSummary);
        });

    // Bouton créer
    $('orgCreateBtn')?.addEventListener('click', createOrganisedTournament);
}

// ── Mise à jour updateAuthUI ────────────────────────────────────────────────
// AJOUTER dans updateAuthUI() de lobby.js, dans le bloc if (currentUser) :
//     const organizeBtn = $('organizeBtn');
//     if (organizeBtn) organizeBtn.style.display = currentUser ? '' : 'none';
//
// Et dans le else (pas connecté) :
//     if (organizeBtn) organizeBtn.style.display = 'none';


// ── Résumé live ─────────────────────────────────────────────────────────────

function updateOrganiseSummary() {
    const regMinutes = parseInt($('orgRegDuration')?.value || 30);
    const startMinutes = parseInt($('orgStartDelay')?.value || 45);
    const preset = $('orgBlindPreset')?.value || 'standard';
    const chips = parseInt($('orgChips')?.value || 10000);

    const now = new Date();
    const regEnd = new Date(now.getTime() + regMinutes * 60000);
    let startTime = new Date(now.getTime() + startMinutes * 60000);
    if (startTime <= regEnd) startTime = new Date(regEnd.getTime() + 5 * 60000);

    const fmt = (d) => d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });

    const sumRegEnd = $('orgSumRegEnd');
    const sumStart = $('orgSumStart');
    const sumStructure = $('orgSumStructure');

    if (sumRegEnd) sumRegEnd.textContent = fmt(regEnd);
    if (sumStart) sumStart.textContent = fmt(startTime);
    if (sumStructure) {
        const presetLabels = {
            'standard': `Standard · ${chips.toLocaleString()} chips`,
            'turbo': `Turbo · ${chips.toLocaleString()} chips`,
            'deepstack': `Deepstack · ${chips.toLocaleString()} chips`,
        };
        sumStructure.textContent = presetLabels[preset] || preset;
    }
}


// ── Création de tournoi ─────────────────────────────────────────────────────

async function createOrganisedTournament() {
    const name = $('orgName')?.value?.trim();
    if (!name) {
        showToast('Nom du tournoi requis', 'error');
        $('orgName')?.focus();
        return;
    }

    const btn = $('orgCreateBtn');
    if (btn) { btn.disabled = true; btn.textContent = 'Création…'; }

    const data = {
        name: name,
        description: $('orgDesc')?.value?.trim() || '',
        game_variant: $('orgVariant')?.value || 'holdem',
        max_players: parseInt($('orgMaxPlayers')?.value || 50),
        min_players_to_start: parseInt($('orgMinPlayers')?.value || 3),
        starting_chips: parseInt($('orgChips')?.value || 10000),
        registration_duration_minutes: parseInt($('orgRegDuration')?.value || 30),
        start_delay_minutes: parseInt($('orgStartDelay')?.value || 45),
        blind_preset: $('orgBlindPreset')?.value || 'standard',
    };

    try {
        const resp = await fetch('/api/organize/create', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });

        if (resp.ok) {
            const result = await resp.json();
            showToast(`Tournoi "${name}" créé ! Inscriptions ouvertes.`, 'success');

            // Reset le formulaire
            if ($('orgName')) $('orgName').value = '';
            if ($('orgDesc')) $('orgDesc').value = '';

            // Basculer vers l'onglet "Mes tournois"
            const tabs = document.querySelectorAll('.organize-tab');
            const contents = document.querySelectorAll('.organize-tab-content');
            tabs.forEach(t => t.classList.remove('active'));
            contents.forEach(c => c.classList.remove('active'));
            tabs[1]?.classList.add('active');
            $('organizeMyTournamentsTab')?.classList.add('active');
            await loadMyTournaments();

            // Rafraîchir la liste des tournois du lobby
            if (typeof loadTournaments === 'function') await loadTournaments();
        } else {
            const err = await resp.json();
            showToast(err.detail || 'Erreur lors de la création', 'error');
        }
    } catch (e) {
        console.error('Create tournament error:', e);
        showToast('Erreur réseau', 'error');
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = 'Créer le tournoi'; }
    }
}


// ── Charger mes tournois ────────────────────────────────────────────────────

async function loadMyTournaments() {
    const container = $('myTournamentsList');
    if (!container) return;

    container.innerHTML = '<div class="loading">Chargement…</div>';

    try {
        const resp = await fetch('/api/organize/my-tournaments');
        if (!resp.ok) {
            container.innerHTML = '<div class="loading" style="color:var(--danger)">Erreur de chargement</div>';
            return;
        }

        const tournaments = await resp.json();

        if (!tournaments.length) {
            container.innerHTML = `
                <div class="loading" style="color:var(--text-muted)">
                    Vous n'avez pas encore organisé de tournoi.<br>
                    Créez-en un depuis l'onglet "Créer" !
                </div>`;
            return;
        }

        container.innerHTML = tournaments.map(t => {
            const statusLabels = {
                'registration': '📝 Inscriptions',
                'in_progress': '🔄 En cours',
                'paused': '⏸ Pause',
                'finished': '🏆 Terminé',
                'cancelled': '❌ Annulé',
            };
            const statusText = statusLabels[t.status] || t.status;
            const statusClass = `status-${t.status}`;

            const regEnd = t.registration_end ? new Date(t.registration_end).toLocaleString('fr-FR', {
                day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'
            }) : '—';
            const startTime = t.start_time ? new Date(t.start_time).toLocaleString('fr-FR', {
                day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'
            }) : '—';
            const variant = t.game_variant === 'plo' ? 'PLO' : "Hold'em";

            // Actions selon le statut
            let actions = '';
            if (t.status === 'registration') {
                actions = `
                    <button class="btn-sm btn-cancel" onclick="cancelMyTournament('${t.id}')">Annuler</button>
                    <button class="btn-sm btn-view" onclick="showTournamentDetail('${t.id}')">Détails</button>
                `;
            } else if (t.status === 'in_progress') {
                actions = `
                    <button class="btn-sm btn-pause" onclick="pauseMyTournament('${t.id}')">⏸ Pause</button>
                    <button class="btn-sm btn-cancel" onclick="cancelMyTournament('${t.id}')">Annuler</button>
                    <button class="btn-sm btn-view" onclick="showTournamentDetail('${t.id}')">Détails</button>
                `;
            } else if (t.status === 'paused') {
                actions = `
                    <button class="btn-sm btn-resume" onclick="resumeMyTournament('${t.id}')">▶ Reprendre</button>
                    <button class="btn-sm btn-cancel" onclick="cancelMyTournament('${t.id}')">Annuler</button>
                    <button class="btn-sm btn-view" onclick="showTournamentDetail('${t.id}')">Détails</button>
                `;
            } else if (t.status === 'finished') {
                actions = `
                    <a href="/tournament/${t.id}/results" class="btn-sm btn-view">📊 Résultats</a>
                `;
            } else {
                actions = `<span style="font-size:12px;color:var(--text-muted)">Aucune action</span>`;
            }

            return `
                <div class="my-tournament-card">
                    <div class="mt-header">
                        <span class="mt-name">${escLocal(t.name)}</span>
                        <span class="status-badge ${statusClass}">${statusText}</span>
                    </div>
                    <div class="mt-meta">
                        <span>Variante: <b class="mv">${variant}</b></span>
                        <span>Joueurs: <b class="mv">${t.players_count}/${t.max_players}</b></span>
                        <span>Tables: <b class="mv">${t.tables_count || 0}</b></span>
                        <span>Niveau: <b class="mv">${t.current_level || 0}</b></span>
                        <span>Inscriptions: <b class="mv">${regEnd}</b></span>
                        <span>Début: <b class="mv">${startTime}</b></span>
                    </div>
                    <div class="mt-actions">${actions}</div>
                </div>
            `;
        }).join('');
    } catch (e) {
        console.error('Load my tournaments error:', e);
        container.innerHTML = '<div class="loading" style="color:var(--danger)">Erreur réseau</div>';
    }
}


// ── Actions organisateur ────────────────────────────────────────────────────

async function pauseMyTournament(tid) {
    if (!confirm('Mettre le tournoi en pause ?')) return;
    try {
        const resp = await fetch(`/api/organize/${tid}/pause`, { method: 'POST' });
        if (resp.ok) {
            showToast('Tournoi mis en pause', 'success');
            await loadMyTournaments();
            if (typeof loadTournaments === 'function') await loadTournaments();
        } else {
            const err = await resp.json();
            showToast(err.detail || 'Erreur', 'error');
        }
    } catch (e) { showToast('Erreur réseau', 'error'); }
}

async function resumeMyTournament(tid) {
    try {
        const resp = await fetch(`/api/organize/${tid}/resume`, { method: 'POST' });
        if (resp.ok) {
            showToast('Tournoi repris', 'success');
            await loadMyTournaments();
            if (typeof loadTournaments === 'function') await loadTournaments();
        } else {
            const err = await resp.json();
            showToast(err.detail || 'Erreur', 'error');
        }
    } catch (e) { showToast('Erreur réseau', 'error'); }
}

async function cancelMyTournament(tid) {
    if (!confirm('Annuler ce tournoi ? Cette action est irréversible.')) return;
    try {
        const resp = await fetch(`/api/organize/${tid}/cancel`, { method: 'POST' });
        if (resp.ok) {
            showToast('Tournoi annulé', 'success');
            await loadMyTournaments();
            if (typeof loadTournaments === 'function') await loadTournaments();
        } else {
            const err = await resp.json();
            showToast(err.detail || 'Erreur', 'error');
        }
    } catch (e) { showToast('Erreur réseau', 'error'); }
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function escLocal(t) {
    // Version locale de esc() au cas où pas déjà défini
    if (typeof esc === 'function') return esc(t);
    const d = document.createElement('div');
    d.textContent = t || '';
    return d.innerHTML;
}
