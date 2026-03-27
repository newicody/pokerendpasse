/* ═══════════════════════════════════════════════════════════════════════════
   table.css — Poker Table — Design professionnel
   Table ovale proportionnée, 9 sièges fixes, avatars, cartes stylisées
   ═══════════════════════════════════════════════════════════════════════════ */

@import url('https://fonts.googleapis.com/css2?family=Oswald:wght@400;600&family=Fira+Mono&display=swap');

:root {
    --felt-green: #1b5e20;
    --felt-dark: #0d3010;
    --rail-brown: #5d3a1a;
    --rail-light: #8b6914;
    --gold: #ffd700;
    --card-white: #f5f5f0;
    --danger: #e74c3c;
    --success: #27ae60;
}

/* ── Layout ──────────────────────────────────────────────────────────────── */
.poker-room {
    display: flex;
    gap: 16px;
    max-width: 1400px;
    margin: 0 auto;
    padding: 12px;
    min-height: 100vh;
    font-family: 'Oswald', sans-serif;
    background: linear-gradient(160deg, #0a1f0d 0%, #0d2818 40%, #071210 100%);
}

/* ── Table container ─────────────────────────────────────────────────────── */
.table-container {
    flex: 3;
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 600px;
}

.poker-table {
    position: relative;
    width: 820px;
    height: 440px;
    /* Rail extérieur */
    background:
        radial-gradient(ellipse 95% 90% at 50% 50%, var(--felt-green) 0%, var(--felt-dark) 85%, transparent 86%),
        radial-gradient(ellipse 100% 96% at 50% 50%, var(--rail-brown) 0%, #3a2210 90%, transparent 91%);
    border-radius: 220px;
    box-shadow:
        0 0 0 8px #2a1a0a,
        0 0 0 12px #1a100a,
        0 8px 40px rgba(0,0,0,0.7),
        inset 0 0 80px rgba(0,0,0,0.3);
}

/* Feutre intérieur */
.poker-table::before {
    content: '';
    position: absolute;
    top: 16px; left: 16px; right: 16px; bottom: 16px;
    border-radius: 200px;
    background: radial-gradient(ellipse 80% 75% at 45% 40%, #2e7d32 0%, #1b5e20 40%, #0d3010 100%);
    box-shadow: inset 0 0 60px rgba(0,0,0,0.4);
    z-index: 0;
}

/* Liseré or */
.poker-table::after {
    content: '';
    position: absolute;
    top: 14px; left: 14px; right: 14px; bottom: 14px;
    border-radius: 210px;
    border: 1.5px solid rgba(255,215,0,0.15);
    z-index: 1;
    pointer-events: none;
}

/* ── Community cards ─────────────────────────────────────────────────────── */
.community-cards {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -55%);
    display: flex;
    gap: 8px;
    z-index: 10;
    background: rgba(0,0,0,0.25);
    padding: 10px 16px;
    border-radius: 16px;
}

.community-cards .card {
    width: 56px;
    height: 80px;
    border-radius: 6px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: 'Fira Mono', monospace;
    font-size: 22px;
    font-weight: bold;
    box-shadow: 0 2px 8px rgba(0,0,0,0.4);
    transition: transform 0.25s;
    position: relative;
}

.community-cards .card.back {
    background: linear-gradient(135deg, #1a237e, #0d47a1);
    border: 1.5px solid #1565c0;
}
.community-cards .card.back::after {
    content: '🂠';
    font-size: 28px;
    opacity: 0.3;
}

.community-cards .card:not(.back) {
    background: var(--card-white);
    border: 1px solid #ccc;
    color: #222;
}

.community-cards .card:hover {
    transform: translateY(-6px);
}

.card-face { line-height: 1; }
.card-face.heart, .card-face.diamond { color: #c62828; }
.card-face.club, .card-face.spade { color: #1a1a1a; }

/* ── Pot ──────────────────────────────────────────────────────────────────── */
.pot {
    position: absolute;
    top: 58%;
    left: 50%;
    transform: translateX(-50%);
    font-family: 'Fira Mono', monospace;
    font-size: 16px;
    font-weight: bold;
    color: var(--gold);
    text-shadow: 0 1px 4px rgba(0,0,0,0.7);
    background: rgba(0,0,0,0.55);
    padding: 5px 18px;
    border-radius: 20px;
    border: 1px solid rgba(255,215,0,0.25);
    z-index: 10;
    white-space: nowrap;
}

/* ── Players container (9 seats) ─────────────────────────────────────────── */
.players-container {
    position: absolute;
    top: 0; left: 0;
    width: 100%; height: 100%;
    z-index: 5;
}

/* ── Seat (player or empty) ──────────────────────────────────────────────── */
.player-seat {
    position: absolute;
    transform: translate(-50%, -50%);
    text-align: center;
    width: 110px;
    transition: all 0.3s;
    z-index: 5;
}

/* Positions fixes pour 9 sièges autour de l'ovale */
.player-seat[data-seat="0"] { bottom: -35px; left: 50%;  top: auto; transform: translateX(-50%); }
.player-seat[data-seat="1"] { bottom: 5%;    left: 10%;  top: auto; transform: none; }
.player-seat[data-seat="2"] { top: 25%;      left: -2%;  transform: none; }
.player-seat[data-seat="3"] { top: -10%;     left: 18%;  transform: none; }
.player-seat[data-seat="4"] { top: -10%;     left: 50%;  transform: translateX(-50%); }
.player-seat[data-seat="5"] { top: -10%;     right: 18%; left: auto; transform: none; }
.player-seat[data-seat="6"] { top: 25%;      right: -2%; left: auto; transform: none; }
.player-seat[data-seat="7"] { bottom: 5%;    right: 10%; left: auto; top: auto; transform: none; }
.player-seat[data-seat="8"] { bottom: -35px; left: 72%;  top: auto; transform: translateX(-50%); }

/* ── Avatar ──────────────────────────────────────────────────────────────── */
.seat-avatar {
    width: 54px;
    height: 54px;
    border-radius: 50%;
    margin: 0 auto 4px;
    background: #1a1a1a;
    border: 3px solid #444;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 24px;
    overflow: hidden;
    transition: border-color 0.3s, box-shadow 0.3s;
}

.seat-avatar img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    border-radius: 50%;
}

/* État connecté */
.player-seat.occupied .seat-avatar {
    border-color: var(--success);
    box-shadow: 0 0 10px rgba(39,174,96,0.4);
}

/* État absent / sit-out */
.player-seat.absent .seat-avatar {
    border-color: #666;
    opacity: 0.55;
    filter: grayscale(60%);
}

/* Tour actif */
.player-seat.active-turn .seat-avatar {
    border-color: var(--gold);
    box-shadow: 0 0 16px rgba(255,215,0,0.6), 0 0 30px rgba(255,215,0,0.2);
    animation: pulse-glow 1.2s ease-in-out infinite;
}

@keyframes pulse-glow {
    0%, 100% { box-shadow: 0 0 12px rgba(255,215,0,0.5); }
    50%      { box-shadow: 0 0 24px rgba(255,215,0,0.8); }
}

/* Mon siège */
.player-seat.me .seat-avatar {
    border-color: #42a5f5;
    box-shadow: 0 0 12px rgba(66,165,245,0.5);
}

/* Foldé */
.player-seat.folded {
    opacity: 0.45;
}

/* ── Name + chips box ────────────────────────────────────────────────────── */
.seat-info {
    background: rgba(0,0,0,0.75);
    border-radius: 8px;
    padding: 3px 8px;
    font-size: 11px;
    line-height: 1.3;
    min-width: 80px;
    backdrop-filter: blur(4px);
}

.seat-name {
    color: #fff;
    font-weight: 600;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 100px;
}

.seat-chips {
    color: var(--gold);
    font-family: 'Fira Mono', monospace;
    font-size: 10px;
}

/* Siège vide */
.player-seat.empty .seat-info {
    opacity: 0.3;
}
.player-seat.empty .seat-name {
    color: #666;
}
.player-seat.empty .seat-avatar {
    border-color: #333;
    border-style: dashed;
}

/* ── Cartes du joueur ────────────────────────────────────────────────────── */
.seat-cards {
    display: flex;
    justify-content: center;
    gap: 3px;
    margin-top: 3px;
}

.mini-card {
    width: 32px;
    height: 44px;
    border-radius: 4px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: 'Fira Mono', monospace;
    font-size: 14px;
    font-weight: bold;
    box-shadow: 0 1px 4px rgba(0,0,0,0.4);
}

.mini-card:not(.back) {
    background: var(--card-white);
    border: 1px solid #bbb;
}

.mini-card.back {
    background: linear-gradient(135deg, #1a237e, #0d47a1);
    border: 1px solid #1565c0;
}

.mini-card.heart, .mini-card.diamond { color: #c62828; }
.mini-card.club, .mini-card.spade { color: #1a1a1a; }

/* ── Bet chip ────────────────────────────────────────────────────────────── */
.seat-bet {
    font-family: 'Fira Mono', monospace;
    font-size: 10px;
    color: var(--gold);
    background: rgba(0,0,0,0.7);
    padding: 2px 6px;
    border-radius: 10px;
    display: inline-block;
    margin-top: 2px;
    border: 1px solid rgba(255,215,0,0.3);
}

/* ── Markers (Dealer, SB, BB) ────────────────────────────────────────────── */
.marker-row {
    display: flex;
    justify-content: center;
    gap: 3px;
    margin-top: 2px;
}

.marker {
    width: 22px;
    height: 22px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 9px;
    font-weight: 700;
    line-height: 1;
}

.marker-d {
    background: var(--gold);
    color: #000;
    box-shadow: 0 1px 4px rgba(0,0,0,0.4);
}

.marker-sb {
    background: #2196f3;
    color: #fff;
}

.marker-bb {
    background: #f44336;
    color: #fff;
}

.marker-allin {
    background: var(--danger);
    color: #fff;
    border-radius: 6px;
    width: auto;
    padding: 1px 6px;
    font-size: 8px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

/* ── Spectator banner ────────────────────────────────────────────────────── */
.spectator-banner {
    position: fixed;
    top: 12px;
    left: 50%;
    transform: translateX(-50%);
    background: rgba(0,0,0,0.85);
    color: var(--gold);
    padding: 8px 24px;
    border-radius: 24px;
    font-size: 13px;
    z-index: 100;
    border: 1px solid rgba(255,215,0,0.3);
    backdrop-filter: blur(8px);
}

/* ── Action panel ────────────────────────────────────────────────────────── */
.action-panel {
    position: fixed;
    bottom: 0;
    left: 0; right: 0;
    background: rgba(0,0,0,0.92);
    backdrop-filter: blur(10px);
    padding: 12px 20px;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
    z-index: 50;
    border-top: 1px solid rgba(255,215,0,0.2);
}

.action-buttons {
    display: flex;
    gap: 10px;
}

.action-btn {
    padding: 10px 24px;
    border: none;
    border-radius: 10px;
    font-family: 'Oswald', sans-serif;
    font-size: 15px;
    font-weight: 600;
    cursor: pointer;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    transition: transform 0.15s, filter 0.15s;
}

.action-btn:hover:not(:disabled) {
    transform: translateY(-2px);
    filter: brightness(1.15);
}

.action-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
}

.action-btn.fold  { background: #616161; color: #fff; }
.action-btn.check { background: #1976d2; color: #fff; }
.action-btn.call  { background: var(--success); color: #fff; }
.action-btn.raise { background: var(--gold); color: #1a1a1a; }

.raise-slider {
    display: flex;
    align-items: center;
    gap: 10px;
    background: rgba(255,255,255,0.05);
    padding: 8px 14px;
    border-radius: 10px;
}

.raise-slider input[type="range"] {
    width: 160px;
    accent-color: var(--gold);
}

.raise-controls {
    display: flex;
    align-items: center;
    gap: 8px;
    font-family: 'Fira Mono', monospace;
    font-size: 14px;
    color: var(--gold);
}

.player-info {
    font-family: 'Fira Mono', monospace;
    font-size: 13px;
    color: rgba(255,255,255,0.7);
    display: flex;
    gap: 16px;
}

.player-info #playerChips { color: var(--gold); font-weight: 600; }
.player-info #playerBet   { color: #90caf9; }

/* ── Info panel ──────────────────────────────────────────────────────────── */
.info-panel {
    flex: 1;
    min-width: 260px;
    max-width: 320px;
    background: rgba(0,0,0,0.85);
    backdrop-filter: blur(10px);
    border-radius: 16px;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 14px;
    border: 1px solid rgba(255,215,0,0.15);
    font-family: 'Oswald', sans-serif;
    max-height: 100vh;
    overflow-y: auto;
}

.game-info {
    background: rgba(0,0,0,0.4);
    border-radius: 10px;
    padding: 12px;
}

.info-row {
    display: flex;
    justify-content: space-between;
    padding: 5px 0;
    font-size: 13px;
    border-bottom: 1px solid rgba(255,255,255,0.06);
}
.info-row:last-child { border-bottom: none; }
.info-row .label { opacity: 0.55; font-weight: 400; }
.info-row .value { color: var(--gold); font-weight: 600; }

.hand-history h3 {
    font-size: 14px;
    color: var(--gold);
    margin-bottom: 8px;
}

.history-list {
    max-height: 250px;
    overflow-y: auto;
    font-family: 'Fira Mono', monospace;
    font-size: 11px;
}

.history-entry {
    padding: 5px 0;
    border-bottom: 1px solid rgba(255,255,255,0.05);
}

.leave-btn {
    margin-top: auto;
    padding: 10px;
    background: linear-gradient(135deg, #c62828, #b71c1c);
    color: white;
    border: none;
    border-radius: 10px;
    cursor: pointer;
    font-family: 'Oswald', sans-serif;
    font-weight: 600;
    font-size: 14px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
.leave-btn:hover {
    filter: brightness(1.15);
    transform: translateY(-1px);
}

/* ── Toast ────────────────────────────────────────────────────────────────── */
.toast {
    position: fixed;
    bottom: 80px;
    right: 20px;
    background: rgba(0,0,0,0.92);
    color: white;
    padding: 10px 20px;
    border-radius: 10px;
    z-index: 200;
    transform: translateX(400px);
    transition: transform 0.3s;
    font-size: 13px;
    border-left: 3px solid var(--gold);
}
.toast.show    { transform: translateX(0); }
.toast.success { border-left-color: var(--success); }
.toast.error   { border-left-color: var(--danger); }

/* ── Responsive ──────────────────────────────────────────────────────────── */
@media (max-width: 1100px) {
    .poker-room { flex-direction: column; }
    .poker-table { width: 100%; max-width: 820px; height: auto; aspect-ratio: 1.86 / 1; margin: 0 auto; }
    .info-panel { max-width: 100%; flex-direction: row; flex-wrap: wrap; max-height: none; }
    .action-panel { padding: 8px 10px; }
}

@media (max-width: 700px) {
    .poker-table { height: 300px; }
    .community-cards .card { width: 40px; height: 56px; font-size: 16px; }
    .seat-avatar { width: 36px; height: 36px; font-size: 16px; }
    .seat-info { font-size: 9px; min-width: 60px; }
    .player-seat { width: 80px; }
    .action-btn { padding: 8px 14px; font-size: 12px; }
}
