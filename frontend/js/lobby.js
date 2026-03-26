/**
 * lobby.js — Page principale du lobby pokerndpasse
 *
 * Dépendances (charger avant ce fichier) :
 *   /js/sound_manager.js
 *   /js/theme_manager.js
 *   /js/settings_manager.js
 *
 * Structure :
 *   1.  État global
 *   2.  Utilitaires DOM / formatage
 *   3.  Gestionnaire de clocks live
 *   4.  Auth (checkAuth, login, register, logout)
 *   5.  Affichage utilisateur
 *   6.  Chargement & rendu des tournois
 *   7.  Détails du tournoi (modal)
 *   8.  Actions tournoi (inscription / désinscription)
 *   9.  Tables de spectating
 *  10.  Chat WebSocket
 *  11.  Options / paramètres
 *  12.  Heure serveur
 *  13.  Initialisation
 */

'use strict';

// ═════════════════════════════════════════════════════════════════════════════
// 1. État global
// ═════════════════════════════════════════════════════════════════════════════

let currentUser     = null;
let isGuest         = false;
let chatWs          = null;
let _refreshInterval = null;

// Registre des setInterval actifs (clocks live)
const _clocks = {};

// ═════════════════════════════════════════════════════════════════════════════
// 2. Utilitaires DOM / formatage
// ═════════════════════════════════════════════════════════════════════════════

/** Échappe les caractères HTML dangereux */
function escapeHtml(text) {
    const d = document.createElement('div');
    d.textContent = text ?? '';
    return d.innerHTML;
}

/** Formate un timestamp ISO en locale string */
function formatDate(isoStr) {
    if (!isoStr) return 'N/A';
    try { return new Date(isoStr).toLocaleString(); }
    catch (_) { return isoStr; }
}

/** Formate un compte à rebours en secondes → chaîne lisible */
function formatCountdown(secs, short = false) {
    if (secs === null || secs === undefined || secs < 0) return '—';
    secs = Math.floor(secs);
    const h = Math.floor(secs / 3600);
    const m = Math.floor((secs % 3600) / 60);
    const s = secs % 60;
    if (short) {
        if (h > 0) return `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
        return `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
    }
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
}

/** Suffixe ordinal (1st, 2nd, 3rd…) */
function getOrdinal(n) {
    const s = ['th','st','nd','rd'], v = n % 100;
    return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

/** Timestamp UTC courant en secondes */
function nowUTC() { return Date.now() / 1000; }

/** Parse une chaîne ISO → timestamp UTC secondes */
function isoToSec(iso) {
    if (!iso) return null;
    try { return new Date(iso).getTime() / 1000; }
    catch (_) { return null; }
}

/** Affiche une notification toast */
function showToast(message, type = 'info') {
    SoundManager.play(type === 'success' ? 'toast_success' : type === 'error' ? 'toast_error' : 'notify');
    const el = document.getElementById('toast');
    if (!el) return;
    el.textContent = message;
    el.className   = `toast ${type} show`;
    clearTimeout(el._hideTimer);
    el._hideTimer = setTimeout(() => el.classList.remove('show'), 3200);
}

/** Ferme un modal par son ID */
function closeModal(id) {
    const el = document.getElementById(id);
    if (el) el.style.display = 'none';
}

// ═════════════════════════════════════════════════════════════════════════════
// 3. Gestionnaire de clocks live
// ═════════════════════════════════════════════════════════════════════════════

function _clearClock(key) {
    if (_clocks[key]) { clearInterval(_clocks[key]); delete _clocks[key]; }
}

function _clearClocksBy(prefix) {
    Object.keys(_clocks).filter(k => k.startsWith(prefix)).forEach(_clearClock);
}

/** Démarre un interval nommé (arrête l'ancien s'il existe) */
function _startClock(key, fn, ms = 1000) {
    _clearClock(key);
    fn();  // exécution immédiate
    _clocks[key] = setInterval(fn, ms);
}

// ═════════════════════════════════════════════════════════════════════════════
// 4. Auth
// ═════════════════════════════════════════════════════════════════════════════

async function checkAuth() {
    try {
        const res = await fetch('/api/auth/me');
        if (res.ok) {
            currentUser = await res.json();
            isGuest     = false;
        } else {
            _setGuest();
        }
    } catch (_) {
        _setGuest();
    }
    updateUserDisplay();
}

function _setGuest() {
    isGuest     = true;
    currentUser = { username: 'Guest', id: null, avatar: null, is_admin: false };
}

async function login(username, password, remember = false) {
    try {
        const res = await fetch('/api/auth/login', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ username, password, remember_me: remember }),
        });
        if (res.ok) {
            currentUser = await res.json();
            isGuest     = false;
            updateUserDisplay();
            closeModal('loginModal');
            showToast(`Bienvenue, ${currentUser.username} !`, 'success');
            SoundManager.play('connect');
            await loadTournaments();
            if (chatWs) chatWs.close();
            initChat();
        } else {
            const err = await res.json().catch(() => ({}));
            showToast(err.detail || 'Connexion échouée', 'error');
        }
    } catch (_) {
        showToast('Erreur de connexion', 'error');
    }
}

async function register(username, password, email) {
    try {
        const res = await fetch('/api/auth/register', {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ username, password, email: email || null }),
        });
        if (res.ok) {
            closeModal('registerModal');
            showToast('Inscription réussie ! Connectez-vous.', 'success');
            showLoginModal();
        } else {
            const err = await res.json().catch(() => ({}));
            showToast(err.detail || 'Inscription échouée', 'error');
        }
    } catch (_) {
        showToast("Erreur d'inscription", 'error');
    }
}

async function logout() {
    try { await fetch('/api/auth/logout', { method: 'POST' }); } catch (_) {}
    if (chatWs) { chatWs.close(); chatWs = null; }
    _setGuest();
    updateUserDisplay();
    showToast('Déconnexion réussie', 'info');
    SoundManager.play('disconnect');
    await loadTournaments();
}

// ═════════════════════════════════════════════════════════════════════════════
// 5. Affichage utilisateur
// ═════════════════════════════════════════════════════════════════════════════

const PREDEFINED_AVATARS = ['default','panda','tiger','dragon','phoenix'];

function updateUserDisplay() {
    _q('username',    el => el.textContent = currentUser?.username ?? 'Guest');
    _q('chips',       el => el.textContent = currentUser?.chips
                                             ? `${Number(currentUser.chips).toLocaleString()} chips`
                                             : '');
    _q('loginBtn',    el => el.style.display    = isGuest ? 'block' : 'none');
    _q('registerBtn', el => el.style.display    = isGuest ? 'block' : 'none');
    _q('logoutBtn',   el => el.style.display    = isGuest ? 'none'  : 'block');
    _q('profileLink', el => el.style.display    = isGuest ? 'none'  : 'inline-block');
    _q('adminBtn',    el => el.style.display    = (!isGuest && currentUser?.is_admin) ? 'inline-block' : 'none');
    _q('guestWarning',el => el.classList.toggle('hidden', !isGuest));

    const avatar = document.getElementById('userAvatar');
    if (avatar) {
        if (!isGuest && currentUser?.avatar) {
            const url = PREDEFINED_AVATARS.includes(currentUser.avatar)
                ? `/assets/images/avatars/${currentUser.avatar}.svg`
                : currentUser.avatar;
            Object.assign(avatar.style, {
                backgroundImage:    `url('${url}')`,
                backgroundSize:     'cover',
                backgroundPosition: 'center',
                backgroundColor:    'transparent',
            });
        } else {
            avatar.style.backgroundImage = '';
        }
    }
}

/** Raccourci getElementById sécurisé */
function _q(id, fn) {
    const el = document.getElementById(id);
    if (el) fn(el);
}

// ═════════════════════════════════════════════════════════════════════════════
// 6. Chargement & rendu des tournois
// ═════════════════════════════════════════════════════════════════════════════

async function loadTournaments() {
    try {
        const res  = await fetch('/api/tournaments');
        if (!res.ok) throw new Error('API error');
        const all  = await res.json();

        const active   = all.filter(t => t.status === 'in_progress');
        const upcoming = all.filter(t => t.status === 'registration' || t.status === 'starting');
        const finished = all.filter(t => t.status === 'finished').slice(0, 5);

        renderActiveTournaments(active);
        renderUpcomingTournaments(upcoming);
        renderFinishedTournaments(finished);
    } catch (e) {
        console.error('loadTournaments error:', e);
    }
}

// ── Tournois actifs ──────────────────────────────────────────────────────────

function renderActiveTournaments(tournaments) {
    const grid = document.getElementById('activeTournamentsGrid');
    if (!grid) return;

    _clearClocksBy('active_');

    if (!tournaments.length) {
        grid.innerHTML = '<div class="empty-state">Aucun tournoi en cours</div>';
        return;
    }

    grid.innerHTML = tournaments.map(t => `
        <div class="tournament-card tournament-card--active" id="acard-${t.id}">
            <div class="tournament-card__header">
                <span class="tournament-card__name">🏆 ${escapeHtml(t.name)}</span>
                <span class="badge badge--progress">🎲 En cours</span>
            </div>
            <div class="tournament-card__info">
                <div><span class="label">Joueurs :</span>
                     <span class="value">${t.players_count}</span></div>
                <div><span class="label">Niveau :</span>
                     <span class="value">${t.current_level}</span></div>
                <div><span class="label">Blinds :</span>
                     <span class="value">${t.current_blinds?.small_blind ?? '?'}/${t.current_blinds?.big_blind ?? '?'}</span></div>
            </div>
            <div class="clock-bar">
                <span class="clock-bar__label">⏱ Prochain niveau :</span>
                <span class="clock-bar__value" id="blind-clock-${t.id}">—</span>
            </div>
            <button class="btn-spectate"
                onclick="event.stopPropagation(); window.showTournamentTables('${t.id}')">
                👁 Voir les tables
            </button>
        </div>
    `).join('');

    // Clock par tournoi
    tournaments.forEach(t => {
        let secs = t.seconds_until_next_level ?? null;
        _startClock(`active_${t.id}`, () => {
            const el = document.getElementById(`blind-clock-${t.id}`);
            if (!el) { _clearClock(`active_${t.id}`); return; }
            if (secs === null) { el.textContent = '—'; return; }
            el.textContent  = formatCountdown(secs, true);
            el.style.color  = secs <= 30 ? 'var(--color-danger)' : secs <= 60 ? 'var(--color-warn)' : 'var(--color-ok)';
            if (secs === 30) SoundManager.play('tick_urgent');
            else if (secs > 0 && secs <= 10) SoundManager.play('tick');
            if (secs === 0) SoundManager.play('blind_up');
            secs = Math.max(0, secs - 1);
        });
    });
}

// ── Tournois à venir ─────────────────────────────────────────────────────────

function renderUpcomingTournaments(tournaments) {
    const grid = document.getElementById('upcomingTournamentsGrid');
    if (!grid) return;

    _clearClocksBy('upcoming_');

    if (!tournaments.length) {
        grid.innerHTML = '<div class="empty-state">Aucun tournoi programmé</div>';
        return;
    }

    grid.innerHTML = tournaments.map(t => `
        <div class="tournament-card" id="ucard-${t.id}">
            <div class="tournament-card__header">
                <span class="tournament-card__name">📅 ${escapeHtml(t.name)}</span>
                <span class="badge" id="ubadge-${t.id}">…</span>
            </div>
            <div class="tournament-card__info">
                <div><span class="label">Départ :</span>
                     <span class="value">${formatDate(t.start_time)}</span></div>
                <div><span class="label">Inscr. :</span>
                     <span class="value">${formatDate(t.registration_end)}</span></div>
                <div><span class="label">Joueurs :</span>
                     <span class="value">${t.players_count}/${t.max_players}</span></div>
                ${t.prize_pool ? `<div><span class="label">Prize :</span>
                     <span class="value">💰 ${Number(t.prize_pool).toLocaleString()}</span></div>` : ''}
            </div>
            <div class="clock-bar">
                <span class="clock-bar__label" id="uclabel-${t.id}">…</span>
                <span class="clock-bar__value" id="uclock-${t.id}">—</span>
            </div>
            <button class="btn-register" onclick="window.showTournamentDetails('${t.id}')">
                Voir / S'inscrire
            </button>
        </div>
    `).join('');

    tournaments.forEach(t => {
        const regStartSec = isoToSec(t.registration_start);
        const regEndSec   = isoToSec(t.registration_end);
        const startSec    = isoToSec(t.start_time);

        _startClock(`upcoming_${t.id}`, () => {
            const now      = nowUTC();
            const clockEl  = document.getElementById(`uclock-${t.id}`);
            const labelEl  = document.getElementById(`uclabel-${t.id}`);
            const badgeEl  = document.getElementById(`ubadge-${t.id}`);
            if (!clockEl) { _clearClock(`upcoming_${t.id}`); return; }

            if (now < regStartSec) {
                const d = regStartSec - now;
                labelEl.textContent = '🕐 Inscriptions dans :';
                clockEl.textContent = formatCountdown(d);
                clockEl.style.color = 'var(--color-ok)';
                badgeEl.textContent = '📅 Bientôt';
                badgeEl.className   = 'badge badge--soon';
            } else if (now < regEndSec) {
                const d = regEndSec - now;
                labelEl.textContent = '✅ Ferme dans :';
                clockEl.textContent = formatCountdown(d);
                clockEl.style.color = d < 300 ? 'var(--color-danger)' : 'var(--color-ok)';
                badgeEl.textContent = '✅ Ouvert';
                badgeEl.className   = 'badge badge--open';
            } else if (now < startSec) {
                const d = startSec - now;
                labelEl.textContent = '🎯 Départ dans :';
                clockEl.textContent = formatCountdown(d);
                clockEl.style.color = d < 120 ? 'var(--color-danger)' : 'var(--color-warn)';
                badgeEl.textContent = '⏰ Fermé';
                badgeEl.className   = 'badge badge--closed';
            } else {
                labelEl.textContent = '';
                clockEl.textContent = '🚀 En cours !';
                badgeEl.textContent = '🎲 En jeu';
                badgeEl.className   = 'badge badge--progress';
            }
        });
    });
}

// ── Tournois terminés ─────────────────────────────────────────────────────────

function renderFinishedTournaments(tournaments) {
    const grid = document.getElementById('finishedTournamentsGrid');
    if (!grid) return;
    if (!tournaments.length) {
        grid.innerHTML = '<div class="empty-state">Aucun tournoi terminé récemment</div>';
        return;
    }
    grid.innerHTML = tournaments.map(t => `
        <div class="tournament-card tournament-card--finished">
            <div class="tournament-card__header">
                <span class="tournament-card__name">🏁 ${escapeHtml(t.name)}</span>
                <span class="badge badge--finished">Terminé</span>
            </div>
            <div class="tournament-card__info">
                <div><span class="label">Joueurs :</span> <span class="value">${t.total_players}</span></div>
                <div><span class="label">Débuté :</span> <span class="value">${formatDate(t.start_time)}</span></div>
            </div>
            <button class="btn-secondary btn-sm"
                onclick="window.showTournamentDetails('${t.id}')">Résultats</button>
        </div>
    `).join('');
}

// ═════════════════════════════════════════════════════════════════════════════
// 7. Détails du tournoi (modal)
// ═════════════════════════════════════════════════════════════════════════════

window.showTournamentDetails = async function(tournamentId) {
    // Arrêter les clocks modales précédentes
    _clearClocksBy('modal_');
    SoundManager.play('flip');

    try {
        const [tRes, regRes] = await Promise.all([
            fetch(`/api/tournaments/${tournamentId}`),
            (!isGuest && currentUser?.id)
                ? fetch(`/api/tournaments/${tournamentId}/registered/${currentUser.id}`)
                : Promise.resolve(null),
        ]);

        if (!tRes.ok) throw new Error('Tournoi introuvable');
        const t = await tRes.json();

        let isRegistered = false;
        if (regRes?.ok) {
            const rd = await regRes.json();
            isRegistered = rd.registered;
        }

        const modal      = document.getElementById('tournamentModal');
        const detailsDiv = document.getElementById('tournamentDetails');
        if (!modal || !detailsDiv) return;

        // ── Prix ──────────────────────────────────────────────────────────────
        const prizesHtml = t.prizes?.length
            ? t.prizes.map(p => `
                <div class="prize-item ${p.rank <= 3 ? 'prize-item--top' : ''}">
                    <span>🏆 ${getOrdinal(p.rank)}</span>
                    <span>💰 ${p.amount.toLocaleString()} chips (${p.percentage}%)</span>
                </div>`).join('')
            : '<div class="empty-state">Pas de prize pool — classement seul</div>';

        // ── Joueurs ───────────────────────────────────────────────────────────
        const playersHtml = t.registered_players?.length
            ? t.registered_players.map(p => `
                <div class="player-item">
                    <span>👤 ${escapeHtml(p.username)}</span>
                    <small>${formatDate(p.registered_at)}</small>
                </div>`).join('')
            : '<div class="empty-state">Aucun joueur inscrit</div>';

        // ── Blinds ────────────────────────────────────────────────────────────
        const currentLvl = t.current_level ?? 1;
        const blindsHtml = t.blind_structure?.length
            ? t.blind_structure.map(lv => `
                <div class="blind-level-item ${lv.level === currentLvl ? 'blind-level-item--current' : ''}">
                    <span class="level-num">${lv.level === currentLvl ? '▶ ' : ''}Niv. ${lv.level}</span>
                    <span>${lv.small_blind}/${lv.big_blind}</span>
                    <span>⏱ ${lv.duration} min</span>
                </div>`).join('')
            : '<div class="empty-state">Structure non définie</div>';

        // ── Classement (tournoi en cours) ─────────────────────────────────────
        const rankingHtml = t.ranking?.length
            ? t.ranking.slice(0,20).map((p, i) => `
                <div class="player-item ${p.status === 'eliminated' ? 'player-item--out' : ''}">
                    <span>#${i+1} ${p.sit_out ? '💤 ' : ''}${escapeHtml(p.username)}</span>
                    <span class="badge ${p.status === 'eliminated' ? 'badge--out' : 'badge--open'}">${p.status}</span>
                </div>`).join('')
            : '<div class="empty-state">Aucun classement</div>';

        // ── Timeline avec placeholders pour clocks ────────────────────────────
        const infoHtml = `
            <div class="tournament-description">
                ${t.description ? escapeHtml(t.description) : '<em>Pas de description</em>'}
            </div>
            <div class="timeline">
                <div class="timeline__item">
                    <span class="timeline__icon">📅</span>
                    <div><strong>Inscriptions ouvrent</strong><br>${formatDate(t.registration_start)}</div>
                </div>
                <div class="timeline__item">
                    <span class="timeline__icon">⏰</span>
                    <div>
                        <strong>Inscriptions ferment</strong><br>${formatDate(t.registration_end)}
                        <span class="clock-inline" id="modal-regEnd-clock"></span>
                    </div>
                </div>
                <div class="timeline__item">
                    <span class="timeline__icon">🎯</span>
                    <div>
                        <strong>Départ</strong><br>${formatDate(t.start_time)}
                        <span class="clock-inline" id="modal-start-clock"></span>
                    </div>
                </div>
                ${t.status === 'in_progress' ? `
                <div class="timeline__item timeline__item--highlight">
                    <span class="timeline__icon">🎲</span>
                    <div>
                        <strong>Niveau actuel : ${currentLvl}
                            — Blinds ${t.current_blinds?.small_blind}/${t.current_blinds?.big_blind}</strong>
                        <br>Prochain niveau : <span class="clock-inline" id="modal-blind-clock">—</span>
                    </div>
                </div>` : ''}
            </div>
            <div class="stats-row">
                <div class="stat-mini"><div class="stat-mini__val">${t.players_count}/${t.max_players}</div><div class="stat-mini__lbl">Joueurs</div></div>
                <div class="stat-mini"><div class="stat-mini__val">💰 ${Number(t.prize_pool).toLocaleString()}</div><div class="stat-mini__lbl">Prize Pool</div></div>
                <div class="stat-mini"><div class="stat-mini__val">${t.itm_percentage}%</div><div class="stat-mini__lbl">ITM</div></div>
            </div>
        `;

        // ── Onglets ───────────────────────────────────────────────────────────
        const tabs = [
            { id: 'info',    icon: '📋', label: 'Infos',   html: infoHtml   },
            { id: 'prizes',  icon: '🏆', label: 'Prix',    html: `<div class="prize-structure"><h4>Répartition</h4><div class="prize-list">${prizesHtml}</div></div>` },
            { id: 'blinds',  icon: '🎲', label: 'Blinds',  html: `<div class="blind-structure"><h4>Niveaux</h4><div class="blind-list">${blindsHtml}</div></div>` },
            { id: 'players', icon: '👥', label: 'Joueurs', html: `<div class="registered-players"><h4>Inscrits (${t.players_count})</h4><div class="players-list">${playersHtml}</div></div>` },
            ...(t.status === 'in_progress' ? [{ id: 'ranking', icon: '📊', label: 'Classement', html: `<div class="ranking"><h4>Classement en direct</h4><div class="players-list">${rankingHtml}</div></div>` }] : []),
        ];

        const tabsHtml = `
            <div class="tab-nav">${tabs.map((tab, i) => `
                <button class="tab-nav__btn ${i === 0 ? 'tab-nav__btn--active' : ''}"
                    data-tab="${tab.id}">${tab.icon} ${tab.label}</button>`).join('')}
            </div>
            ${tabs.map((tab, i) => `
                <div class="tab-pane ${i === 0 ? 'tab-pane--active' : ''}" id="tp-${tab.id}">
                    ${tab.html}
                </div>`).join('')}
        `;

        // ── Bouton d'action ────────────────────────────────────────────────────
        const actionHtml = _buildTournamentActionBtn(t, isRegistered);

        // ── Statut badge ──────────────────────────────────────────────────────
        const statusLabels = {
            registration: '📝 Inscriptions',
            starting:     '⚡ Démarrage…',
            in_progress:  '🎲 En cours',
            finished:     '🏁 Terminé',
            cancelled:    '❌ Annulé',
        };

        detailsDiv.innerHTML = `
            <div class="tournament-modal__header">
                <h2>🏆 ${escapeHtml(t.name)}</h2>
                <span class="badge status-badge--${t.status}">${statusLabels[t.status] ?? t.status}</span>
            </div>
            ${tabsHtml}
            <div class="tournament-modal__action">${actionHtml}</div>
        `;

        // Activer les onglets
        _bindTabs(detailsDiv);

        modal.style.display = 'flex';

        // ── Clocks modales ─────────────────────────────────────────────────────
        const regEndSec = isoToSec(t.registration_end);
        const startSec  = isoToSec(t.start_time);

        _startClock('modal_regEnd', () => {
            const el = document.getElementById('modal-regEnd-clock');
            if (!el) { _clearClock('modal_regEnd'); return; }
            const d = regEndSec - nowUTC();
            el.textContent = d > 0 ? `(ferme dans ${formatCountdown(d)})` : '(fermées)';
            el.style.color = d < 300 ? 'var(--color-danger)' : 'var(--color-ok)';
        });

        _startClock('modal_start', () => {
            const el = document.getElementById('modal-start-clock');
            if (!el) { _clearClock('modal_start'); return; }
            const d = startSec - nowUTC();
            el.textContent = d > 0 ? `(dans ${formatCountdown(d)})` : '(démarré)';
            el.style.color = d < 60 ? 'var(--color-danger)' : d < 300 ? 'var(--color-warn)' : 'var(--color-ok)';
        });

        if (t.status === 'in_progress') {
            let blindSecs = t.seconds_until_next_level ?? null;
            _startClock('modal_blind', () => {
                const el = document.getElementById('modal-blind-clock');
                if (!el) { _clearClock('modal_blind'); return; }
                if (blindSecs === null) { el.textContent = '—'; return; }
                el.textContent = formatCountdown(blindSecs, true);
                el.style.color = blindSecs <= 30 ? 'var(--color-danger)' : blindSecs <= 60 ? 'var(--color-warn)' : 'var(--color-ok)';
                blindSecs = Math.max(0, blindSecs - 1);
            });
        }

    } catch (e) {
        console.error('showTournamentDetails:', e);
        showToast('Impossible de charger le tournoi', 'error');
    }
};

function _buildTournamentActionBtn(t, isRegistered) {
    const now      = nowUTC();
    const regStart = isoToSec(t.registration_start);
    const regEnd   = isoToSec(t.registration_end);

    if (t.status === 'registration') {
        if (now >= regStart && now < regEnd) {
            if (isGuest)
                return `<button class="btn-primary" onclick="showLoginModal()">🔐 Connectez-vous pour s'inscrire</button>`;
            return isRegistered
                ? `<button class="btn-danger" onclick="window.unregisterFromTournament('${t.id}')">❌ Annuler l'inscription</button>`
                : `<button class="btn-success" onclick="window.registerForTournament('${t.id}')">✅ S'inscrire</button>`;
        }
        if (now < regStart)
            return `<div class="status-msg">⏰ Inscriptions le ${formatDate(t.registration_start)}</div>`;
        return `<div class="status-msg">📝 Inscriptions fermées</div>`;
    }

    if (t.status === 'in_progress')
        return `<button class="btn-spectate" onclick="window.showTournamentTables('${t.id}')">👁 Voir les tables / Spectate</button>`;

    if (t.status === 'finished')
        return `<div class="status-msg">🏁 Tournoi terminé</div>`;

    if (t.status === 'cancelled')
        return `<div class="status-msg">❌ Tournoi annulé</div>`;

    return '';
}

function _bindTabs(container) {
    const btns  = container.querySelectorAll('.tab-nav__btn');
    const panes = container.querySelectorAll('.tab-pane');
    btns.forEach(btn => {
        btn.onclick = () => {
            const id = btn.dataset.tab;
            btns.forEach(b  => b.classList.toggle('tab-nav__btn--active',  b.dataset.tab === id));
            panes.forEach(p => p.classList.toggle('tab-pane--active', p.id === `tp-${id}`));
            SoundManager.play('tick');
        };
    });
}

// ═════════════════════════════════════════════════════════════════════════════
// 8. Actions tournoi
// ═════════════════════════════════════════════════════════════════════════════

window.registerForTournament = async function(tournamentId) {
    if (!currentUser || isGuest) { showLoginModal(); return; }
    try {
        const res = await fetch(`/api/tournaments/${tournamentId}/register`, {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ user_id: currentUser.id }),
        });
        if (res.ok) {
            SoundManager.play('register');
            showToast('Inscription réussie !', 'success');
            closeModal('tournamentModal');
            await loadTournaments();
        } else {
            const err = await res.json().catch(() => ({}));
            showToast(err.detail || 'Inscription échouée', 'error');
        }
    } catch (_) { showToast('Erreur réseau', 'error'); }
};

window.unregisterFromTournament = async function(tournamentId) {
    if (!confirm('Annuler votre inscription ?')) return;
    try {
        const res = await fetch(`/api/tournaments/${tournamentId}/unregister`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });
        if (res.ok) {
            showToast('Inscription annulée', 'info');
            closeModal('tournamentModal');
            await loadTournaments();
        } else {
            showToast('Désinscription impossible', 'error');
        }
    } catch (_) { showToast('Erreur réseau', 'error'); }
};

// ═════════════════════════════════════════════════════════════════════════════
// 9. Tables de spectating
// ═════════════════════════════════════════════════════════════════════════════

window.showTournamentTables = async function(tournamentId) {
    try {
        const res = await fetch(`/api/tournaments/${tournamentId}/tables`);
        if (!res.ok) throw new Error('API error');
        const tables = await res.json();

        const modal   = document.getElementById('tournamentTablesModal');
        const listDiv = document.getElementById('tournamentTablesList');
        if (!modal || !listDiv) return;

        listDiv.innerHTML = tables.length
            ? tables.map(tb => `
                <div class="table-item">
                    <div>
                        <strong>🎲 ${escapeHtml(tb.name)}</strong>
                        <small>${tb.current_players}/${tb.max_players} joueurs</small>
                    </div>
                    <button class="btn-spectate btn-sm"
                        onclick="window.watchTable('${tb.id}')">👁 Regarder</button>
                </div>`).join('')
            : '<div class="empty-state">Aucune table disponible</div>';

        modal.style.display = 'flex';
    } catch (_) { showToast('Impossible de charger les tables', 'error'); }
};

window.watchTable = function(tableId) {
    window.location.href = `/table/${tableId}?spectate=true`;
};

// ═════════════════════════════════════════════════════════════════════════════
// 10. Chat WebSocket
// ═════════════════════════════════════════════════════════════════════════════

function initChat() {
    if (!currentUser || isGuest) return;

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    chatWs = new WebSocket(`${protocol}//${location.host}/ws/chat`);

    chatWs.onopen = () => {
        chatWs.send(JSON.stringify({ type: 'join', user_id: currentUser.id, username: currentUser.username }));
        _q('chatInput',   el => el.disabled = false);
        _q('chatSendBtn', el => el.disabled = false);
    };

    chatWs.onmessage = ({ data }) => {
        try {
            const msg = JSON.parse(data);
            _addChatMessage(msg);
            if (msg.user_count) _q('chatUserCount', el => el.textContent = `${msg.user_count} en ligne`);
            if (msg.type === 'message' && SettingsManager.get('chatNotifications') !== 'off') {
                SoundManager.play('chat');
            }
        } catch (_) {}
    };

    chatWs.onclose = () => {
        _q('chatInput',   el => el.disabled = true);
        _q('chatSendBtn', el => el.disabled = true);
        setTimeout(initChat, 4000); // reconnexion automatique
    };

    chatWs.onerror = () => chatWs.close();

    _q('chatSendBtn', el => { el.onclick = sendChatMessage; });
    _q('chatInput',   el => { el.onkeypress = e => { if (e.key === 'Enter') sendChatMessage(); }; });
}

function sendChatMessage() {
    const input = document.getElementById('chatInput');
    if (!input) return;
    const text = input.value.trim();
    if (!text || !chatWs || chatWs.readyState !== WebSocket.OPEN) return;
    chatWs.send(JSON.stringify({ type: 'message', text, user_id: currentUser.id, username: currentUser.username }));
    input.value = '';
}

function _addChatMessage(msg) {
    const box = document.getElementById('chatMessages');
    if (!box) return;

    const el = document.createElement('div');
    el.className = `chat-msg chat-msg--${msg.type || 'message'}`;
    el.innerHTML = msg.type === 'system'
        ? `<em>${escapeHtml(msg.message)}</em>`
        : `<strong>${escapeHtml(msg.username)}:</strong> ${escapeHtml(msg.text || msg.message)}`;

    box.appendChild(el);

    // Garder max 200 messages
    while (box.children.length > 200) box.removeChild(box.firstChild);
    box.scrollTop = box.scrollHeight;
}

// ═════════════════════════════════════════════════════════════════════════════
// 11. Options / paramètres
// ═════════════════════════════════════════════════════════════════════════════

function setupOptionsModal() {
    const modal   = document.getElementById('optionsModal');
    const openBtn = document.getElementById('optionsBtn');
    if (!modal) return;

    if (openBtn) openBtn.onclick = () => _openOptionsModal(modal);

    // Bouton Sauver
    _q('saveSettings', el => {
        el.onclick = () => _saveOptions(modal);
    });

    // Fermeture
    modal.querySelector('.close')?.addEventListener('click', () => closeModal('optionsModal'));
}

function _openOptionsModal(modal) {
    const s = SettingsManager.load();

    // Sons
    _q('soundSetting',      el => el.value   = s.sound);
    _q('soundVolume',       el => el.value   = s.soundVolume ?? 0.5);

    // Thème
    const themeSelect = document.getElementById('themeSelect');
    if (themeSelect) {
        ThemeManager.populateSelect(themeSelect);
        themeSelect.value = s.theme || 'dark';
    }

    // Jeu
    _q('animationSpeed',    el => el.value   = s.animationSpeed);
    _q('cardDisplay',       el => el.value   = s.cardDisplay);
    _q('autoAction',        el => el.value   = s.autoAction);
    _q('chatNotifications', el => el.value   = s.chatNotifications);
    _q('actionTimer',       el => el.value   = s.actionTimer);

    // CSS custom
    _q('customCss',         el => el.value   = s.customCss || '');
    _q('customCssUrl',      el => el.value   = s.customCssUrl || '');

    modal.style.display = 'flex';
}

function _saveOptions(modal) {
    const s = {
        sound:             document.getElementById('soundSetting')?.value      || 'on',
        soundVolume:       parseFloat(document.getElementById('soundVolume')?.value || 0.5),
        theme:             document.getElementById('themeSelect')?.value       || 'dark',
        animationSpeed:    document.getElementById('animationSpeed')?.value    || 'normal',
        cardDisplay:       document.getElementById('cardDisplay')?.value       || 'standard',
        autoAction:        document.getElementById('autoAction')?.value        || 'never',
        chatNotifications: document.getElementById('chatNotifications')?.value || 'on',
        actionTimer:       parseInt(document.getElementById('actionTimer')?.value || 30),
        customCss:         document.getElementById('customCss')?.value         || '',
        customCssUrl:      document.getElementById('customCssUrl')?.value      || '',
    };

    SettingsManager.save(s);

    // Appliquer immédiatement
    SoundManager.setEnabled(s.sound !== 'off');
    SoundManager.setVolume(s.soundVolume);
    ThemeManager.save(s.theme, s.customCss, s.customCssUrl);

    closeModal('optionsModal');
    showToast('Paramètres sauvegardés', 'success');
}

// ═════════════════════════════════════════════════════════════════════════════
// 12. Heure serveur
// ═════════════════════════════════════════════════════════════════════════════

function _startServerClock() {
    _startClock('serverTime', () => {
        const now = new Date();
        const hh  = String(now.getUTCHours()).padStart(2,'0');
        const mm  = String(now.getUTCMinutes()).padStart(2,'0');
        const ss  = String(now.getUTCSeconds()).padStart(2,'0');
        _q('serverTime',      el => el.textContent = `${hh}:${mm}:${ss} UTC`);
        _q('adminServerTime', el => el.textContent = `${hh}:${mm}:${ss} UTC`);
    });
}

// ═════════════════════════════════════════════════════════════════════════════
// 13. Event listeners & modaux auth
// ═════════════════════════════════════════════════════════════════════════════

function setupEventListeners() {
    _qEv('optionsBtn',   'click', () => document.getElementById('optionsModal') && _openOptionsModal(document.getElementById('optionsModal')));
    _qEv('loginBtn',     'click', showLoginModal);
    _qEv('registerBtn',  'click', showRegisterModal);
    _qEv('logoutBtn',    'click', logout);
    _qEv('adminBtn',     'click', () => window.location.href = '/admin');
    _qEv('profileLink',  'click', e => { e.preventDefault(); window.location.href = '/profile'; });
}

function _qEv(id, event, fn) {
    const el = document.getElementById(id);
    if (el) el.addEventListener(event, fn);
}

function showLoginModal()    { _showModal('loginModal'); }
function showRegisterModal() { _showModal('registerModal'); }

function _showModal(id) {
    const el = document.getElementById(id);
    if (el) el.style.display = 'flex';
}

function setupAuthModals() {
    // Login form
    const loginForm = document.getElementById('loginForm');
    if (loginForm) {
        loginForm.onsubmit = e => {
            e.preventDefault();
            const user = document.getElementById('loginUsername')?.value;
            const pass = document.getElementById('loginPassword')?.value;
            const rem  = document.getElementById('rememberMe')?.checked ?? false;
            if (user && pass) login(user, pass, rem);
        };
    }

    // Register form
    const regForm = document.getElementById('registerForm');
    if (regForm) {
        regForm.onsubmit = e => {
            e.preventDefault();
            const user  = document.getElementById('regUsername')?.value;
            const pass  = document.getElementById('regPassword')?.value;
            const email = document.getElementById('regEmail')?.value;
            if (user && pass) register(user, pass, email);
        };
    }

    // Fermeture génériques
    document.querySelectorAll('.modal .close').forEach(btn => {
        btn.onclick = () => {
            const m = btn.closest('.modal');
            if (m) {
                m.style.display = 'none';
                // Stopper les clocks modales si c'est le modal tournoi
                if (m.id === 'tournamentModal') _clearClocksBy('modal_');
            }
        };
    });

    // Clic hors modal
    window.addEventListener('click', e => {
        if (e.target?.classList?.contains('modal')) {
            e.target.style.display = 'none';
            if (e.target.id === 'tournamentModal') _clearClocksBy('modal_');
        }
    });
}

// ═════════════════════════════════════════════════════════════════════════════
// 14. Initialisation
// ═════════════════════════════════════════════════════════════════════════════

async function init() {
    // Charger thème et sons en premier (avant tout rendu)
    ThemeManager.load();
    SoundManager.init();

    await checkAuth();
    await loadTournaments();

    // Rafraîchissement auto des tournois
    if (_refreshInterval) clearInterval(_refreshInterval);
    _refreshInterval = setInterval(loadTournaments, 10_000);

    setupEventListeners();
    setupAuthModals();
    setupOptionsModal();
    _startServerClock();

    // Chat uniquement si connecté
    if (!isGuest) initChat();
}

// ── Démarrage ─────────────────────────────────────────────────────────────────
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
