/**
 * lobby.js — Lobby principal poker (freeroll tournaments)
 * Features: auth, tournois, chat, auto-redirect joueur, spectate par pseudo
 */
'use strict';

let currentUser = null, isGuest = false, chatWs = null, _refreshInterval = null;
const _clocks = {};
let chatHideJoinMessages = false, chatAutoConvertSmileys = true;

// ══════════ UTILS ═══════════════════════════════════════════════════════════
function esc(t) { const d = document.createElement('div'); d.textContent = t ?? ''; return d.innerHTML; }
function fmtDate(iso) { if (!iso) return 'N/A'; try { return new Date(iso).toLocaleString(); } catch(_) { return iso; } }
function fmtCountdown(s, short=false) {
    if (s == null || s < 0) return '—'; s = Math.floor(s);
    const h=Math.floor(s/3600), m=Math.floor((s%3600)/60), sec=s%60;
    if (short) return h>0?`${h}:${String(m).padStart(2,'0')}:${String(sec).padStart(2,'0')}`:`${String(m).padStart(2,'0')}:${String(sec).padStart(2,'0')}`;
    if (h>0) return `${h}h ${m}m`; if (m>0) return `${m}m ${sec}s`; return `${sec}s`;
}
function getOrdinal(n) { const s=['th','st','nd','rd'],v=n%100; return n+(s[(v-20)%10]||s[v]||s[0]); }
function nowUTC() { return Date.now()/1000; }
function isoToSec(iso) { if (!iso) return null; try { return new Date(iso).getTime()/1000; } catch(_) { return null; } }

function showToast(msg, type='info') {
    if (typeof SoundManager !== 'undefined') SoundManager.play(type==='success'?'toast_success':type==='error'?'toast_error':'tick');
    let t = document.getElementById('toast');
    if (!t) { t = document.createElement('div'); t.id='toast'; t.className='toast'; document.body.appendChild(t); }
    t.textContent = msg; t.className = `toast ${type} show`;
    setTimeout(() => t.classList.remove('show'), 3000);
}

function _startClock(k, fn) { _clearClock(k); fn(); _clocks[k] = setInterval(fn, 1000); }
function _clearClock(k) { if (_clocks[k]) { clearInterval(_clocks[k]); delete _clocks[k]; } }
function _clearClocksBy(pfx) { Object.keys(_clocks).filter(k=>k.startsWith(pfx)).forEach(_clearClock); }
function closeModal(id) { const m=document.getElementById(id); if(m) m.style.display='none'; }
window.closeModal = closeModal;
window.showLoginModal = () => { const m=document.getElementById('loginModal'); if(m) m.style.display='flex'; };
window.showRegisterModal = () => { const m=document.getElementById('registerModal'); if(m) m.style.display='flex'; };

// ══════════ AUTH ════════════════════════════════════════════════════════════
async function checkAuth() {
    try {
        const r = await fetch('/api/auth/me');
        if (r.ok) { const d = await r.json(); if (d?.id) { currentUser=d; isGuest=false; window.currentUser=d; updateUserDisplay(); document.getElementById('guestWarning')?.classList.add('hidden'); return; } }
    } catch(_) {}
    isGuest=true; currentUser=null; window.currentUser=null; updateUserDisplay();
    document.getElementById('guestWarning')?.classList.remove('hidden');
}

function updateUserDisplay() {
    const u=document.getElementById('username'), st=document.getElementById('userStatus');
    const lb=document.getElementById('loginBtn'), rb=document.getElementById('registerBtn'), lo=document.getElementById('logoutBtn');
    const pl=document.getElementById('profileLink'), ab=document.getElementById('adminBtn'), av=document.getElementById('userAvatar');
    if (currentUser && !isGuest) {
        if(u) u.textContent=currentUser.username; if(st) st.textContent='Connected';
        if(lb) lb.style.display='none'; if(rb) rb.style.display='none'; if(lo) lo.style.display='block';
        if(pl) pl.style.display='inline-block'; if(ab) ab.style.display=currentUser.is_admin?'inline-block':'none';
        if(av) { const src=currentUser.avatar?.startsWith('/uploads/')?currentUser.avatar:`/assets/images/avatars/${currentUser.avatar||'default'}.svg`; av.innerHTML=`<img src="${src}" style="width:40px;height:40px;border-radius:50%">`; }
    } else {
        if(u) u.textContent='Guest'; if(st) st.textContent='Spectator';
        if(lb) lb.style.display='block'; if(rb) rb.style.display='block'; if(lo) lo.style.display='none';
        if(pl) pl.style.display='none'; if(ab) ab.style.display='none';
        if(av) av.innerHTML='<div style="width:40px;height:40px;border-radius:50%;background:#555;display:flex;align-items:center;justify-content:center">👤</div>';
    }
}

async function login(user, pass, remember=false) {
    try {
        const r=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:user,password:pass,remember_me:remember})});
        if(r.ok){const d=await r.json();currentUser=d.user;isGuest=false;window.currentUser=d.user;updateUserDisplay();closeModal('loginModal');showToast('Login OK!','success');document.getElementById('guestWarning')?.classList.add('hidden');initChat();await loadTournaments();}
        else{const e=await r.json().catch(()=>({}));showToast(e.detail||'Login failed','error');}
    }catch(_){showToast('Network error','error');}
}

async function register(user, pass, email) {
    try {
        const r=await fetch('/api/auth/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:user,password:pass,email})});
        if(r.ok){const d=await r.json();currentUser=d.user;isGuest=false;window.currentUser=d.user;updateUserDisplay();closeModal('registerModal');showToast('Registered!','success');document.getElementById('guestWarning')?.classList.add('hidden');initChat();await loadTournaments();}
        else{const e=await r.json().catch(()=>({}));showToast(e.detail||'Registration failed','error');}
    }catch(_){showToast('Network error','error');}
}

async function logout() {
    try{await fetch('/api/auth/logout',{method:'POST'});}catch(_){}
    currentUser=null;isGuest=true;window.currentUser=null;updateUserDisplay();
    document.getElementById('guestWarning')?.classList.remove('hidden');
    if(chatWs){chatWs.close();chatWs=null;} showToast('Logged out','info');
}

// ══════════ TOURNAMENTS ════════════════════════════════════════════════════
async function loadTournaments() {
    try {
        const r=await fetch('/api/tournaments'); if(!r.ok) throw 0;
        const all=await r.json();
        renderActiveTournaments(all.filter(t=>t.status==='in_progress'));
        renderUpcomingTournaments(all.filter(t=>t.status==='registration'||t.status==='starting'));
        renderFinishedTournaments(all.filter(t=>t.status==='finished').slice(0,5));
    } catch(e) { console.error('loadTournaments:', e); }
}

function renderActiveTournaments(tournaments) {
    const grid=document.getElementById('activeTournamentsGrid'); if(!grid) return;
    _clearClocksBy('active_');
    if (!tournaments.length) { grid.innerHTML='<div class="empty-state">No active tournaments</div>'; return; }
    grid.innerHTML = tournaments.map(t => {
        // Est-ce que JE suis inscrit dans ce tournoi actif ?
        const myPlayer = currentUser ? (t.registered_players||t.players||[]).find(p=>p.user_id===currentUser.id && p.status==='registered') : null;
        const myTableBtn = myPlayer?.table_id
            ? `<button class="join-btn" onclick="event.stopPropagation(); window.goToMyTable('${t.id}')">🎮 Go to my table</button>`
            : '';
        return `
        <div class="tournament-card tournament-card--active" onclick="showTournamentDetails('${t.id}')">
            <div class="tournament-header">
                <span class="tournament-name">🏆 ${esc(t.name)}</span>
                <span class="tournament-status in_progress">🎲 In Progress</span>
            </div>
            <div class="tournament-details">
                <div><span class="label">Players:</span><span class="value">${t.players_count}</span></div>
                <div><span class="label">Level:</span><span class="value">${(t.current_level||0)+1}</span></div>
                <div><span class="label">Blinds:</span><span class="value">${t.current_blinds?.small_blind??'?'}/${t.current_blinds?.big_blind??'?'}</span></div>
                <div><span class="label">Prize:</span><span class="value">${(t.prize_pool||0).toLocaleString()}</span></div>
            </div>
            <div class="clock-bar"><span>⏱ Next level: </span><span id="blind-clock-${t.id}">—</span></div>
            ${myTableBtn}
            <button class="spectate-btn" onclick="event.stopPropagation(); window.showTournamentTables('${t.id}')">👁 Watch Tables</button>
        </div>`;
    }).join('');
    tournaments.forEach(t => {
        let secs = t.seconds_until_next_level ?? null;
        _startClock(`active_${t.id}`, () => {
            const el=document.getElementById(`blind-clock-${t.id}`); if(!el){_clearClock(`active_${t.id}`);return;}
            if(secs===null){el.textContent='—';return;}
            el.textContent=fmtCountdown(secs,true); el.style.color=secs<=30?'#e74c3c':secs<=60?'#ff9800':'#27ae60';
            secs=Math.max(0,secs-1);
        });
    });
}

function renderUpcomingTournaments(tournaments) {
    const grid=document.getElementById('upcomingTournamentsGrid'); if(!grid) return;
    _clearClocksBy('upcoming_');
    if (!tournaments.length) { grid.innerHTML='<div class="empty-state">No upcoming tournaments</div>'; return; }
    grid.innerHTML = tournaments.map(t => {
        const isReg = currentUser && !isGuest && (t.registered_players||[]).some(p=>p.user_id===currentUser.id);
        return `
        <div class="tournament-card" onclick="showTournamentDetails('${t.id}')">
            <div class="tournament-header">
                <span class="tournament-name">📅 ${esc(t.name)}</span>
                <span class="tournament-status registration">📝 Registration</span>
            </div>
            <div class="tournament-details">
                <div><span class="label">Players:</span><span class="value">${t.players_count}/${t.max_players}</span></div>
                <div><span class="label">Start:</span><span class="value">${fmtDate(t.start_time)}</span></div>
                <div><span class="label">Prize Pool:</span><span class="value">${(t.prize_pool||0).toLocaleString()} (Freeroll)</span></div>
            </div>
            <div class="clock-bar"><span>⏰ Starts in: </span><span id="start-clock-${t.id}">—</span></div>
            ${isReg
                ? `<button class="join-btn" style="background:#e74c3c" onclick="event.stopPropagation();window.unregisterFromTournament('${t.id}')">❌ Cancel</button>`
                : t.can_register
                    ? `<button class="join-btn" onclick="event.stopPropagation();window.registerForTournament('${t.id}')">✅ Register (Free)</button>`
                    : '<div style="text-align:center;padding:8px;opacity:0.6">Registration closed</div>'
            }
        </div>`;
    }).join('');
    tournaments.forEach(t => {
        const startSec=isoToSec(t.start_time);
        _startClock(`upcoming_${t.id}`, () => {
            const el=document.getElementById(`start-clock-${t.id}`); if(!el){_clearClock(`upcoming_${t.id}`);return;}
            if(!startSec){el.textContent='—';return;} const d=startSec-nowUTC();
            el.textContent=d>0?fmtCountdown(d):'Starting...'; el.style.color=d<60?'#e74c3c':d<300?'#ff9800':'#27ae60';
        });
    });
}

function renderFinishedTournaments(tournaments) {
    const grid=document.getElementById('finishedTournamentsGrid'); if(!grid) return;
    if (!tournaments.length) { grid.innerHTML='<div class="empty-state">No finished tournaments</div>'; return; }
    grid.innerHTML = tournaments.map(t => `
        <div class="tournament-card" onclick="showTournamentDetails('${t.id}')" style="opacity:0.7">
            <div class="tournament-header">
                <span class="tournament-name">🏁 ${esc(t.name)}</span>
                <span class="tournament-status" style="background:rgba(150,150,150,0.3);color:#aaa">Finished</span>
            </div>
            <div class="tournament-details">
                <div><span class="label">Players:</span><span class="value">${t.total_players||t.players_count}</span></div>
                <div><span class="label">Prize:</span><span class="value">${(t.prize_pool||0).toLocaleString()}</span></div>
            </div>
        </div>`).join('');
}

// ══════════ GO TO MY TABLE (joueur inscrit) ═════════════════════════════════
window.goToMyTable = async function(tournamentId) {
    if (!currentUser || isGuest) { window.showLoginModal(); return; }
    try {
        const r = await fetch(`/api/tournaments/${tournamentId}/my-table`);
        if (r.ok) {
            const data = await r.json();
            // Ouvrir en mode JOUEUR (pas spectateur !)
            window.location.href = `/table/${data.table_id}`;
        } else {
            showToast('Table not found', 'error');
        }
    } catch(_) { showToast('Network error', 'error'); }
};

// ══════════ SPECTATE A SPECIFIC PLAYER ══════════════════════════════════════
window.spectatePlayer = async function(tournamentId, userId) {
    try {
        const r = await fetch(`/api/tournaments/${tournamentId}/player-table/${userId}`);
        if (r.ok) {
            const data = await r.json();
            // Ouvrir dans un NOUVEL ONGLET en mode spectateur
            window.open(`/table/${data.table_id}?spectate=true`, '_blank');
        } else {
            showToast('Player table not found', 'error');
        }
    } catch(_) { showToast('Network error', 'error'); }
};

// ══════════ TOURNAMENT DETAILS MODAL ═════════════════════════════════════════
window.showTournamentDetails = async function(tournamentId) {
    const modal=document.getElementById('tournamentModal'), detailsDiv=document.getElementById('tournamentDetails');
    if(!modal||!detailsDiv) return;
    detailsDiv.innerHTML='<div class="loading">Loading...</div>'; modal.style.display='flex';

    try {
        const r=await fetch(`/api/tournaments/${tournamentId}`); if(!r.ok) throw 0;
        const t=await r.json();
        const isRegistered = currentUser ? (t.registered_players||t.players||[]).some(p=>p.user_id===currentUser.id && p.status==='registered') : false;

        const blindsHtml = (t.blind_structure||[]).map((b,i) => `
            <div class="blind-level-item" ${i===t.current_level?'style="background:rgba(255,215,0,0.15);font-weight:bold"':''}>
                <span class="level-num">${b.level||i+1}</span><span>${b.small_blind}/${b.big_blind}</span><span>${b.duration||10} min</span>
            </div>`).join('') || '<div style="opacity:0.5">Default structure</div>';

        // Joueurs avec lien spectate
        const playersHtml = (t.registered_players||[]).map((p,i) => `
            <div class="player-item" style="cursor:pointer" onclick="window.spectatePlayer('${t.id}','${p.user_id}')" title="Click to spectate ${esc(p.username)}">
                <span>#${i+1} ${esc(p.username)} ${p.user_id===currentUser?.id?'(you)':''}</span>
                <small>${p.chips ? p.chips.toLocaleString()+' chips' : ''} ${t.status==='in_progress'?'👁':''}  </small>
            </div>`).join('') || '<div style="opacity:0.5">No players yet</div>';

        const prizesHtml = (t.prizes||[]).map(p => `
            <div class="prize-item"><span>${getOrdinal(p.rank)}</span><span>${p.amount?.toLocaleString()||0} (${p.percentage}%)</span></div>
        `).join('') || '<div style="opacity:0.5">No prizes configured</div>';

        const statusLabels = { registration:'📝 Registration', starting:'⚡ Starting...', in_progress:'🎲 In Progress', finished:'🏁 Finished', cancelled:'❌ Cancelled' };

        // Action button
        let actionHtml = '';
        if (t.status === 'registration') {
            if (isRegistered) actionHtml = `<button class="unregister-tournament-btn" onclick="window.unregisterFromTournament('${t.id}')">❌ Cancel Registration</button>`;
            else if (t.can_register) actionHtml = `<button class="register-tournament-btn" onclick="window.registerForTournament('${t.id}')">✅ Register (Free Entry)</button>`;
            else actionHtml = '<div class="status-message">Registration not available</div>';
        } else if (t.status === 'in_progress') {
            const myTableBtn = isRegistered ? `<button class="register-tournament-btn" onclick="window.goToMyTable('${t.id}')">🎮 Go to my table</button>` : '';
            actionHtml = `${myTableBtn}<button class="spectate-tournament-btn" onclick="window.showTournamentTables('${t.id}')">👁 Watch Tables</button>`;
        } else if (t.status === 'finished') {
            actionHtml = '<div class="status-message">🏁 Tournament finished</div>';
        }

        detailsDiv.innerHTML = `
            <div class="tournament-info-header"><h2>🏆 ${esc(t.name)}</h2><span class="tournament-status ${t.status}">${statusLabels[t.status]??t.status}</span></div>
            ${t.description?`<p style="opacity:0.8;margin-bottom:15px">${esc(t.description)}</p>`:''}
            <div class="tournament-timeline" style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:20px">
                <div><span style="opacity:0.6">Registration:</span><br>${fmtDate(t.registration_start)} — ${fmtDate(t.registration_end)}</div>
                <div><span style="opacity:0.6">Start:</span><br>${fmtDate(t.start_time)}</div>
                <div><span style="opacity:0.6">Players:</span><br>${t.players_count}/${t.max_players}</div>
                <div><span style="opacity:0.6">Prize Pool:</span><br>${(t.prize_pool||0).toLocaleString()} (Freeroll)</div>
            </div>
            <div class="tournament-tabs" style="display:flex;gap:5px;border-bottom:1px solid rgba(255,215,0,0.3);margin-bottom:15px">
                <button class="tab-btn active" data-tab="blinds">Blinds</button>
                <button class="tab-btn" data-tab="players">Players (${t.players_count})</button>
                <button class="tab-btn" data-tab="prizes">Prizes</button>
            </div>
            <div class="tournament-tab-content active" data-tab-content="blinds"><div class="blind-structure"><h4>Blind Structure</h4><div class="blind-structure-list">${blindsHtml}</div></div></div>
            <div class="tournament-tab-content" data-tab-content="players"><div class="registered-players"><h4>Players ${t.status==='in_progress'?'<small>(click to spectate)</small>':''}</h4><div class="players-list">${playersHtml}</div></div></div>
            <div class="tournament-tab-content" data-tab-content="prizes"><div class="prize-structure"><h4>Prize Structure (Freeroll)</h4><div class="prize-list">${prizesHtml}</div></div></div>
            <div style="margin-top:20px">${actionHtml}</div>`;

        // Bind tabs
        const btns=detailsDiv.querySelectorAll('.tab-btn'), panes=detailsDiv.querySelectorAll('.tournament-tab-content');
        btns.forEach(b=>{b.onclick=()=>{const id=b.dataset.tab;btns.forEach(x=>x.classList.toggle('active',x.dataset.tab===id));panes.forEach(p=>p.classList.toggle('active',p.dataset.tabContent===id));};});
    } catch(e) { detailsDiv.innerHTML='<div class="error">Failed to load details</div>'; }
};

// ══════════ TOURNAMENT ACTIONS ═══════════════════════════════════════════════
window.registerForTournament = async function(id) {
    if(!currentUser||isGuest){window.showLoginModal();return;}
    try{const r=await fetch(`/api/tournaments/${id}/register`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({user_id:currentUser.id})});
    if(r.ok){showToast('Registered!','success');closeModal('tournamentModal');await loadTournaments();}
    else{const e=await r.json().catch(()=>({}));showToast(e.detail||'Failed','error');}}
    catch(_){showToast('Network error','error');}
};

window.unregisterFromTournament = async function(id) {
    if(!confirm('Cancel registration?')) return;
    try{const r=await fetch(`/api/tournaments/${id}/unregister`,{method:'POST',headers:{'Content-Type':'application/json'}});
    if(r.ok){showToast('Cancelled','info');closeModal('tournamentModal');await loadTournaments();}
    else showToast('Failed','error');}catch(_){showToast('Network error','error');}
};

window.showTournamentTables = async function(id) {
    try{const r=await fetch(`/api/tournaments/${id}/tables`);if(!r.ok)throw 0;const tables=await r.json();
    const modal=document.getElementById('tournamentTablesModal'),list=document.getElementById('tournamentTablesList');
    if(!modal||!list) return;
    list.innerHTML = tables.length ? tables.map(tb=>`<div class="table-item"><div><strong>🎲 ${esc(tb.name)}</strong><small>${tb.current_players}/${tb.max_players} players</small></div><button class="watch-table-btn" onclick="window.open('/table/${tb.id}?spectate=true','_blank')">👁 Watch</button></div>`).join('')
        : '<div class="empty-state">No tables</div>';
    modal.style.display='flex';}catch(_){showToast('Could not load tables','error');}
};

// ══════════ CHAT ════════════════════════════════════════════════════════════
function initChat() {
    if(!currentUser||isGuest||chatWs?.readyState===WebSocket.OPEN) return;
    const url=`${location.protocol==='https:'?'wss:':'ws:'}//${location.host}/ws/chat`;
    try{
        chatWs=new WebSocket(url);
        chatWs.onopen=()=>{chatWs.send(JSON.stringify({type:'join',user_id:currentUser.id,username:currentUser.username}));const i=document.getElementById('chatInput'),b=document.getElementById('chatSendBtn');if(i)i.disabled=false;if(b)b.disabled=false;};
        chatWs.onmessage=e=>{try{const m=JSON.parse(e.data);handleChatMsg(m);}catch(_){}};
        chatWs.onclose=()=>{const i=document.getElementById('chatInput'),b=document.getElementById('chatSendBtn');if(i)i.disabled=true;if(b)b.disabled=true;setTimeout(()=>{if(currentUser&&!isGuest)initChat();},5000);};
    }catch(_){}
}

function handleChatMsg(m) {
    if(m.type==='system'){if(chatHideJoinMessages&&(m.message?.includes('joined')||m.message?.includes('left')))return;addChat(null,m.message,'system');if(m.user_count!==undefined){const e=document.getElementById('chatUserCount');if(e)e.textContent=`${m.user_count} online`;}}
    else if(m.type==='message') addChat(m.username,m.message,m.user_id===currentUser?.id?'self':'user');
}

function addChat(user, msg, type='user') {
    const c=document.getElementById('chatMessages'); if(!c) return;
    const d=document.createElement('div'); d.className=`chat-message ${type}`;
    const time=new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
    if(type==='system') d.innerHTML=`<span class="time">[${time}]</span> ${esc(msg)}`;
    else { let text=esc(msg); if(chatAutoConvertSmileys) text=text.replace(/:\)/g,'😊').replace(/;\)/g,'😉').replace(/:D/g,'😃').replace(/:\(/g,'😢').replace(/:P/g,'😛').replace(/<3/g,'❤️');
        d.innerHTML=`<span class="username">${esc(user)}</span><span class="time">[${time}]</span><span class="message-text">${text}</span>`; }
    c.appendChild(d); d.scrollIntoView({behavior:'smooth'});
    while(c.children.length>200) c.removeChild(c.firstChild);
}

function sendChat() {
    const i=document.getElementById('chatInput'); if(!i||!chatWs||chatWs.readyState!==WebSocket.OPEN) return;
    const t=i.value.trim(); if(!t) return;
    chatWs.send(JSON.stringify({type:'message',message:t})); i.value='';
}

// ══════════ EVENT LISTENERS ═════════════════════════════════════════════════
function setupAuthModals() {
    document.getElementById('loginForm')?.addEventListener('submit',e=>{e.preventDefault();login(document.getElementById('loginUsername').value,document.getElementById('loginPassword').value,document.getElementById('rememberMe')?.checked);});
    document.getElementById('registerForm')?.addEventListener('submit',e=>{e.preventDefault();register(document.getElementById('regUsername').value,document.getElementById('regPassword').value,document.getElementById('regEmail')?.value);});
    document.querySelectorAll('.modal .close').forEach(b=>{b.onclick=()=>b.closest('.modal').style.display='none';});
    window.addEventListener('click',e=>{if(e.target.classList.contains('modal'))e.target.style.display='none';});
}

function setupEventListeners() {
    document.getElementById('loginBtn')?.addEventListener('click',window.showLoginModal);
    document.getElementById('registerBtn')?.addEventListener('click',window.showRegisterModal);
    document.getElementById('logoutBtn')?.addEventListener('click',logout);
    document.getElementById('chatSendBtn')?.addEventListener('click',sendChat);
    document.getElementById('chatInput')?.addEventListener('keydown',e=>{if(e.key==='Enter')sendChat();});

    // Chat settings
    document.getElementById('chatSettingsBtn')?.addEventListener('click',()=>{const m=document.getElementById('chatSettingsModal');if(m){document.getElementById('hideJoinMessages').checked=chatHideJoinMessages;document.getElementById('autoConvertSmileys').checked=chatAutoConvertSmileys;m.style.display='flex';}});
    document.getElementById('saveChatSettings')?.addEventListener('click',()=>{chatHideJoinMessages=document.getElementById('hideJoinMessages')?.checked??false;chatAutoConvertSmileys=document.getElementById('autoConvertSmileys')?.checked??true;try{localStorage.setItem('poker_chat_settings',JSON.stringify({chatHideJoinMessages,chatAutoConvertSmileys}));}catch(_){}closeModal('chatSettingsModal');showToast('Saved','success');});
    try{const s=JSON.parse(localStorage.getItem('poker_chat_settings')||'{}');chatHideJoinMessages=s.chatHideJoinMessages??false;chatAutoConvertSmileys=s.chatAutoConvertSmileys??true;}catch(_){}

    // Smileys
    const sBtn=document.getElementById('smileyBtn'),sDrop=document.getElementById('smileyDropdown');
    if(sBtn&&sDrop){
        const emojis=['😊','😂','🤣','😍','🤔','😎','🙄','😢','😡','🎉','👍','👎','🔥','💰','🃏','♠️','♥️','♣️','♦️','🏆','😏','🤑','😤','🥳','🤯','💀','🎲','🍀','⭐','💎'];
        sDrop.innerHTML=emojis.map(e=>`<span class="emoji-item">${e}</span>`).join('');
        sBtn.addEventListener('click',e=>{e.stopPropagation();sDrop.classList.toggle('visible');});
        sDrop.addEventListener('click',e=>{if(e.target.classList.contains('emoji-item')){const i=document.getElementById('chatInput');if(i){i.value+=e.target.textContent;i.focus();}sDrop.classList.remove('visible');}});
        document.addEventListener('click',e=>{if(!sBtn.contains(e.target)&&!sDrop.contains(e.target))sDrop.classList.remove('visible');});
    }
}

function setupOptionsModal() {
    const ob=document.getElementById('optionsBtn'),om=document.getElementById('optionsModal'),sb=document.getElementById('saveSettings');
    if(ob) ob.onclick=()=>{if(typeof SettingsManager!=='undefined'){const s=SettingsManager.load();['soundSetting','animationSpeed','cardDisplay','autoAction','showHistory'].forEach(id=>{const el=document.getElementById(id);const key=id==='soundSetting'?'sound':id;if(el&&s[key]!==undefined)el.value=s[key];});}if(om)om.style.display='flex';};
    if(sb) sb.onclick=()=>{const ns={sound:document.getElementById('soundSetting')?.value||'on',animationSpeed:document.getElementById('animationSpeed')?.value||'normal',cardDisplay:document.getElementById('cardDisplay')?.value||'standard',autoAction:document.getElementById('autoAction')?.value||'never',showHistory:document.getElementById('showHistory')?.value||'all'};if(typeof SettingsManager!=='undefined')SettingsManager.save(ns);if(typeof SoundManager!=='undefined')SoundManager.loadPreferences();closeModal('optionsModal');showToast('Settings saved!','success');};
}

function _startServerClock() {
    async function u(){try{const r=await fetch('/api/server/time');if(r.ok){const d=await r.json();const e=document.getElementById('serverTime');if(e)e.textContent=d.time||'--:--:--';}}catch(_){}}
    u(); setInterval(u,5000);
}

// ══════════ INIT ════════════════════════════════════════════════════════════
async function init() {
    if(typeof SoundManager!=='undefined') SoundManager.init();
    await checkAuth(); await loadTournaments();
    if(_refreshInterval) clearInterval(_refreshInterval);
    _refreshInterval = setInterval(loadTournaments, 8000);
    setupEventListeners(); setupAuthModals(); setupOptionsModal(); _startServerClock();
    if(!isGuest) initChat();
}

window.initCurrentUser = async function() { await checkAuth(); return window.currentUser; };

if (document.readyState==='loading') document.addEventListener('DOMContentLoaded',init); else init();
