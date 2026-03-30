/**
 * table.js — Logique principale de la table de poker
 * v3 : positions fixes, PLO 4 cartes, tournament info, timer progress,
 *       side pots, animations
 */
const tableId = window.tableId;
let ws = null, currentUser = null, gameState = null, isSpectator = false;
let showStacksInBB = false, reconnectAttempts = 0, reconnectTimer = null;
let currentQuickBets = [], tournamentInfo = null;
const $ = (id) => document.getElementById(id);

// ── Seat positions fixes (% autour de la table) ─────────────────────────
const SEAT_POSITIONS = {
    2: [{top:'90%',left:'35%'},{top:'10%',left:'65%'}],
    3: [{top:'88%',left:'50%'},{top:'15%',left:'15%'},{top:'15%',left:'85%'}],
    4: [{top:'88%',left:'35%'},{top:'50%',left:'2%'},{top:'12%',left:'35%'},{top:'50%',left:'98%'}],
    5: [{top:'88%',left:'50%'},{top:'70%',left:'2%'},{top:'15%',left:'15%'},{top:'15%',left:'85%'},{top:'70%',left:'98%'}],
    6: [{top:'88%',left:'35%'},{top:'88%',left:'65%'},{top:'50%',left:'2%'},{top:'12%',left:'35%'},{top:'12%',left:'65%'},{top:'50%',left:'98%'}],
    7: [{top:'88%',left:'50%'},{top:'78%',left:'5%'},{top:'35%',left:'2%'},{top:'10%',left:'25%'},{top:'10%',left:'75%'},{top:'35%',left:'98%'},{top:'78%',left:'95%'}],
    8: [{top:'88%',left:'35%'},{top:'88%',left:'65%'},{top:'65%',left:'2%'},{top:'25%',left:'2%'},{top:'10%',left:'35%'},{top:'10%',left:'65%'},{top:'25%',left:'98%'},{top:'65%',left:'98%'}],
    9: [{top:'88%',left:'50%'},{top:'82%',left:'10%'},{top:'55%',left:'2%'},{top:'22%',left:'5%'},{top:'10%',left:'30%'},{top:'10%',left:'70%'},{top:'22%',left:'95%'},{top:'55%',left:'98%'},{top:'82%',left:'90%'}],
};
function getPositions(count) {
    const key = Math.min(Math.max(count, 2), 9);
    const pos = SEAT_POSITIONS[key] || SEAT_POSITIONS[9];
    return Array.from({length: count}, (_, i) => pos[i % pos.length]);
}

// ── Init ─────────────────────────────────────────────────────────────────
async function init() {
    await loadUser(); loadPreferences(); setupActions(); setupQuickBets();
    setupChat(); setupThemeModal(); setupKeyboardShortcuts(); connectWS();
    loadTournamentInfo();
    if (typeof SoundManager !== 'undefined') SoundManager.init();
}
async function loadUser() {
    try { const r = await fetch('/api/auth/me'); if(r.ok){const d=await r.json(); if(d?.user?.id){currentUser=d.user;return;}} } catch(e){}
    currentUser = null;
}
function loadPreferences() {
    try { const p = JSON.parse(localStorage.getItem('poker_table_prefs')||'{}'); showStacksInBB = p.showStacksInBB||false;
        const t=$('stackDisplayToggle'); if(t){t.checked=showStacksInBB; t.addEventListener('change',()=>{showStacksInBB=t.checked;savePreferences();if(gameState)render(gameState);});}
    } catch(e){}
}
function savePreferences() { try{localStorage.setItem('poker_table_prefs',JSON.stringify({showStacksInBB}));}catch(e){} }

// ── Tournament Info Bar ──────────────────────────────────────────────────
async function loadTournamentInfo() {
    try {
        const r = await fetch(`/api/tables/${tableId}`); if(!r.ok) return;
        const t = await r.json(); if(!t.tournament_id) return;
        const tr = await fetch(`/api/tournaments/${t.tournament_id}`); if(!tr.ok) return;
        tournamentInfo = await tr.json(); updateTournamentBar();
    } catch(e){}
}
function updateTournamentBar() {
    const bar=$('tournamentInfo'); if(!bar||!tournamentInfo){if(bar)bar.style.display='none';return;}
    bar.style.display='flex';
    const b=tournamentInfo.current_blinds||{}, lv=(tournamentInfo.current_level||0)+1;
    const nl=tournamentInfo.seconds_until_next_level, nlS=nl!=null?`${Math.floor(nl/60)}:${String(nl%60).padStart(2,'0')}`:'—';
    const v=tournamentInfo.game_variant==='plo'?'PLO':"Hold'em";
    const pl=`${tournamentInfo.players_count||'?'}/${tournamentInfo.max_players||'?'}`;
    const pr=tournamentInfo.prize_pool>0?`💰 ${tournamentInfo.prize_pool}`:'🆓 Freeroll';
    const pa=tournamentInfo.status==='paused'?'<span style="color:var(--warning);font-weight:bold">⏸ PAUSE</span>':'';
    bar.innerHTML=`<span>🏆 <strong>${esc(tournamentInfo.name)}</strong></span><span>🎮 ${v}</span><span>📊 Niv ${lv} — ${b.small_blind||'?'}/${b.big_blind||'?'}</span><span>⏱ ${nlS}</span><span>👥 ${pl}</span><span>${pr}</span>${pa}`;
}
setInterval(()=>{if(tournamentInfo&&tournamentInfo.seconds_until_next_level>0){tournamentInfo.seconds_until_next_level-=10;updateTournamentBar();}},10000);
setInterval(loadTournamentInfo, 30000);

// ── WebSocket ────────────────────────────────────────────────────────────
function connectWS() {
    if(ws&&(ws.readyState===0||ws.readyState===1)) return;
    const proto=location.protocol==='https:'?'wss:':'ws:';
    ws = new WebSocket(`${proto}//${location.host}/ws/${tableId}/${currentUser?.id||'spectator'}`);
    ws.onopen=()=>{reconnectAttempts=0;if(!isSpectator)toast('Connecté','success');};
    ws.onmessage=(e)=>{try{onMessage(JSON.parse(e.data));}catch(err){console.error('WS:',err);}};
    ws.onclose=()=>{if(!isSpectator)toast('Déconnecté','error');reconnect();};
    ws.onerror=()=>{};
}
function reconnect(){if(reconnectTimer)clearTimeout(reconnectTimer);if(reconnectAttempts>=10){toast('Connexion perdue','error');return;}reconnectTimer=setTimeout(connectWS,Math.min(1000*Math.pow(2,reconnectAttempts++),30000));}
function sendWS(d){if(ws&&ws.readyState===WebSocket.OPEN)ws.send(JSON.stringify(d));}

function onMessage(msg) {
    switch(msg.type) {
        case 'game_update': case 'game_state':
            if(msg.is_spectator!==undefined)isSpectator=msg.is_spectator;
            gameState=msg.data||msg; if(msg.quick_bets)currentQuickBets=msg.quick_bets;
            render(gameState); break;
        case 'hole_cards':
            if(gameState){const me=gameState.players?.find(p=>p.user_id===currentUser?.id); if(me)me.hole_cards=msg.cards; updateMyCards();} break;
        case 'community_cards':
            if(gameState)gameState.community_cards=msg.cards; updateCommunityCards(msg.cards);
            if(typeof SoundManager!=='undefined')SoundManager.play('flip'); break;
        case 'player_action':
            if(typeof SoundManager!=='undefined'){
                if(['call','raise','all-in'].includes(msg.action))SoundManager.play('bet');
                else if(msg.action==='fold')SoundManager.play('fold');
                else if(msg.action==='check')SoundManager.play('check');
            } break;
        case 'hand_result': handleHandResult(msg); break;
        case 'deck_commitment': if($('deckStatus'))$('deckStatus').textContent='🔒 Committed'; break;
        case 'deck_reveal': if($('deckStatus'))$('deckStatus').textContent='✅ Verified'; break;
        case 'connected': break;
        case 'reconnected': toast('Reconnecté!','success'); break;
        case 'tournament_level_change':
            toast(`📊 Niveau ${msg.level}: Blinds ${msg.small_blind}/${msg.big_blind}`,'info');
            if(typeof SoundManager!=='undefined')SoundManager.play('turn'); loadTournamentInfo(); break;
        case 'tournament_paused': toast('⏸ Tournoi en pause…','info'); loadTournamentInfo(); break;
        case 'tournament_finished':
            const winnerName = msg.winner?.username || '?';
            toast(`🏆 Tournoi terminé! Gagnant: ${winnerName}`, 'success');
            setTimeout(() => { window.location.href = msg.results_url || '/lobby'; }, 5000);
            break;
        case 'tournament_player_eliminated':
            toast(`💀 ${msg.username||'?'} éliminé — #${msg.rank}`,'info');
            if(msg.user_id===currentUser?.id)toast('Vous avez été éliminé!','error');
            loadTournamentInfo(); break;
        case 'table_chat': appendChatMessage(msg.username,msg.message); break;
        case 'table_change':
            toast(`🔄 ${msg.message||'Changement de table'}`, 'info');
            setTimeout(() => { window.location.href = `/table/${msg.new_table_id}`; }, 2000);
            break;
        case 'player_moved':
            toast(`🔄 ${msg.username} déplacé vers une autre table`, 'info');
            break;
        case 'ping': sendWS({type:'pong'}); break;
        case 'error': toast(msg.message||'Erreur','error'); break;
    }
}

// ── Render ────────────────────────────────────────────────────────────────
function render(state) {
    if(!state) return; gameState=state;
    renderPlayers(state); updateCommunityCards(state.community_cards||[]);
    updatePot(state.pot||0, state.side_pots); updateGameInfo(state);
    updateActions(state); updateMyCards(); updateActionTimer(state); updateQuickBetsUI(state);
    const b=$('spectatorBanner'); if(b)b.style.display=isSpectator?'block':'none';
}

function renderPlayers(state) {
    const container=$('playersContainer'); if(!container)return;
    container.innerHTML='';
    const players=state.players||[], positions=getPositions(players.length);
    const numHole=state.game_variant==='plo'?4:2;

    players.forEach((p,i)=>{
        const el=document.createElement('div');
        el.className=`player-seat ${p.status||''} ${p.user_id===state.current_actor?'active-player':''}`;
        const pos=positions[i]||{top:'50%',left:'50%'}; el.style.top=pos.top; el.style.left=pos.left;

        const stack=formatStack(p.chips||p.stack||0);
        const betDisplay=p.current_bet>0?`<div class="player-bet-chip">${p.current_bet.toLocaleString()}</div>`:'';
        const roleTag=p.is_dealer?'<span class="role-tag dealer">D</span>':p.is_small_blind?'<span class="role-tag sb">SB</span>':p.is_big_blind?'<span class="role-tag bb">BB</span>':'';

        let cardsHtml='';
        if(p.hole_cards&&p.hole_cards.length>0){
            cardsHtml=p.hole_cards.map(c=>typeof CardsModule!=='undefined'?CardsModule.renderCard(c,false):`<div class="mini-card">${c}</div>`).join('');
        } else if(['active','all_in'].includes(p.status)){
            cardsHtml=Array(numHole).fill('<div class="mini-card back"></div>').join('');
        }
        const lastAct=p.last_action?`<div class="last-action">${p.last_action}</div>`:'';

        el.innerHTML=`<div class="player-avatar"><img src="${p.avatar||'/assets/avatars/default.svg'}" alt="${esc(p.username)}" onerror="this.src='/assets/avatars/default.svg'">${roleTag}</div><div class="player-name">${esc(p.username)}</div><div class="player-stack">${stack}</div><div class="player-cards">${cardsHtml}</div>${betDisplay}${lastAct}`;
        container.appendChild(el);
    });
}

function updateCommunityCards(cards) {
    const c=$('communityCards'); if(!c)return; c.innerHTML='';
    if(!cards?.length) return;
    cards.forEach(card=>{
        if(typeof CardsModule!=='undefined') c.innerHTML+=CardsModule.renderCard(card,false);
        else { const el=document.createElement('div'); el.className='community-card'; el.textContent=card; c.appendChild(el); }
    });
}

function updatePot(pot, sidePots) {
    const el=$('potDisplay'); if(!el)return;
    if(sidePots&&sidePots.length>1){
        const parts=sidePots.map((sp,i)=>`P${i+1}:${sp.amount.toLocaleString()}`).join(' · ');
        el.innerHTML=`<span class="pot-main">Pot: ${pot.toLocaleString()}</span> <span class="pot-side">(${parts})</span>`;
    } else { el.textContent=`Pot: ${pot.toLocaleString()}`; }
}

function updateMyCards() {
    const c=$('myCardsContainer'); if(!c||!currentUser)return;
    const me=gameState?.players?.find(p=>p.user_id===currentUser.id);
    if(!me?.hole_cards?.length){c.classList.add('hidden');return;}
    c.classList.remove('hidden');
    c.innerHTML=me.hole_cards.map(card=>typeof CardsModule!=='undefined'?CardsModule.renderCard(card,false):`<div class="my-card">${card}</div>`).join('');
}

function updateGameInfo(state) {
    const set=(id,t)=>{const el=$(id);if(el)el.textContent=t;};
    set('handNumber',`#${state.round||0}`);
    set('gameVariant',state.game_variant==='plo'?'PLO':"Hold'em");
    const streets={preflop:'Preflop',flop:'Flop',turn:'Turn',river:'River',showdown:'Showdown'};
    set('bettingRound',streets[state.betting_round]||state.betting_round||'');
    set('gameBlinds',`${state.small_blind}/${state.big_blind}`);
    const alive=state.players?.filter(p=>!['folded','eliminated'].includes(p.status)).length||0;
    set('playersAlive',String(alive));
    const me=state.players?.find(p=>p.user_id===currentUser?.id);
    set('myChipsInfo',me?formatStack(me.chips||me.stack||0):'—');
}

// ── Actions ──────────────────────────────────────────────────────────────
function setupActions(){
    $('foldBtn')?.addEventListener('click',()=>doAction('fold'));
    $('checkBtn')?.addEventListener('click',()=>doAction('check'));
    $('callBtn')?.addEventListener('click',()=>doAction('call'));
    $('raiseBtn')?.addEventListener('click',()=>showRaiseSlider());
    $('confirmRaise')?.addEventListener('click',confirmRaise);
    $('cancelRaise')?.addEventListener('click',hideRaiseSlider);
    const sl=$('raiseAmount'),inp=$('raiseValue');
    if(sl&&inp){sl.addEventListener('input',()=>{inp.value=sl.value;});inp.addEventListener('input',()=>{sl.value=inp.value;});}
}

function updateActions(state) {
    const myTurn=state.current_actor===currentUser?.id, me=state.players?.find(p=>p.user_id===currentUser?.id);
    $('foldBtn').disabled=!myTurn; $('checkBtn').disabled=!myTurn; $('raiseBtn').disabled=!myTurn;
    const tableBet=state.current_bet||0;
    if(me&&tableBet>(me.current_bet||0)){
        $('checkBtn').style.display='none'; $('callBtn').style.display=''; $('callBtn').disabled=!myTurn;
        const toCall=Math.min(tableBet-(me.current_bet||0),me.chips||0);
        $('callBtn').textContent=`Call ${toCall.toLocaleString()} (C)`;
    } else { $('checkBtn').style.display=''; $('callBtn').style.display='none'; }
    if(me&&myTurn){const sl=$('raiseAmount');if(sl){sl.min=state.min_raise||state.big_blind||10;sl.max=me.chips||1000;sl.value=Math.max(+sl.min,+sl.value);}}
}

function doAction(action,amount=0){sendWS({type:'action',action,amount});hideRaiseSlider();if(typeof SoundManager!=='undefined')SoundManager.play('chip');}
function showRaiseSlider(){const el=$('raiseSlider');if(el)el.style.display='flex';}
function hideRaiseSlider(){const el=$('raiseSlider');if(el)el.style.display='none';}
function confirmRaise(){const a=parseInt($('raiseValue')?.value||$('raiseAmount')?.value||0);if(a>0)doAction('raise',a);}

// ── Quick Bets ───────────────────────────────────────────────────────────
function setupQuickBets(){
    document.querySelectorAll('.qb-btn').forEach(btn=>{
        btn.addEventListener('click',()=>{const key=btn.dataset.key,bet=currentQuickBets.find(b=>b.key===key);
            if(bet){key==='allin'?doAction('all_in',bet.amount):doAction('raise',bet.amount);}});
    });
}
function updateQuickBetsUI(state){
    const c=$('quickBets');if(!c)return;
    const myTurn=state.current_actor===currentUser?.id; c.style.display=myTurn?'flex':'none';
    if(!myTurn||!currentQuickBets?.length)return;
    document.querySelectorAll('.qb-btn').forEach(btn=>{const key=btn.dataset.key,bet=currentQuickBets.find(b=>b.key===key);
        if(bet){btn.style.display='';btn.textContent=`${bet.label} (${bet.amount.toLocaleString()})`;}else{btn.style.display='none';}});
}

// ── Timer (avec barre de progression) ────────────────────────────────────
function updateActionTimer(state) {
    const el=$('actionTimer');
    if(!state.current_actor||state.action_timer==null){if(el)el.classList.add('hidden');if(typeof TimerModule!=='undefined')TimerModule.stop();return;}
    if(el)el.classList.remove('hidden');
    const total=state.action_timeout_total||20, remaining=state.action_timer;
    if(typeof TimerModule!=='undefined'){
        TimerModule.start(remaining,total,(secs,pct)=>{
            if(el){
                const color=pct>0.5?'var(--success)':pct>0.2?'var(--warning)':'var(--danger)';
                el.innerHTML=`<div class="timer-bar-bg"><div class="timer-bar-fill" style="width:${pct*100}%;background:${color}"></div></div><span class="timer-text">⏱ ${secs}s</span>`;
            }
            if(secs===5&&state.current_actor===currentUser?.id&&typeof SoundManager!=='undefined')SoundManager.play('timer');
        });
    } else if(el){ el.textContent=`⏱ ${remaining}s`; }
}

// ── Hand Result ──────────────────────────────────────────────────────────
function handleHandResult(msg) {
    if(typeof SoundManager!=='undefined')SoundManager.play('win');
    const winners=msg.winners||[];
    toast(`🏆 ${winners.map(w=>`${w.username} +${w.amount?.toLocaleString()||0} (${w.hand||'?'})`).join(', ')}`,'success');
    if(msg.side_pots&&msg.side_pots.length>1) toast(msg.side_pots.map((sp,i)=>`Pot ${i+1}: ${sp.amount.toLocaleString()}`).join(' | '),'info');
    if(msg.showdown){msg.showdown.forEach(p=>{if(gameState?.players){const gp=gameState.players.find(x=>x.user_id===p.user_id);if(gp)gp.hole_cards=p.hole_cards;}});if(gameState)render(gameState);}
    if(typeof HandHistory!=='undefined') HandHistory.add({round:gameState?.round||0,winners,pot:msg.pot,community:msg.community_cards||[]});
}

// ── Chat ─────────────────────────────────────────────────────────────────
function setupChat(){
    const inp=$('tableChatInput'),btn=$('tableChatSend');if(!inp||!btn)return;
    if(currentUser){inp.disabled=false;btn.disabled=false;}
    const send=()=>{const t=inp.value.trim();if(!t)return;sendWS({type:'chat',message:t});inp.value='';};
    btn.addEventListener('click',send); inp.addEventListener('keypress',(e)=>{if(e.key==='Enter')send();});
}
function appendChatMessage(username,message){
    const c=$('tableChatMessages');if(!c)return;
    const d=document.createElement('div');d.className='tchat-msg';
    d.innerHTML=`<strong>${esc(username)}</strong>: ${esc(message)}`;
    c.appendChild(d);c.scrollTop=c.scrollHeight;
    while(c.children.length>100)c.removeChild(c.firstChild);
}

// ── Theme Modal ──────────────────────────────────────────────────────────
function setupThemeModal(){
    const btn=$('themeToggleBtn'),modal=$('themeModal');if(!btn||!modal)return;
    btn.addEventListener('click',()=>{modal.style.display='flex';});
    modal.querySelector('.close')?.addEventListener('click',()=>{modal.style.display='none';});
    modal.addEventListener('click',(e)=>{if(e.target===modal)modal.style.display='none';});
    $('applyTheme')?.addEventListener('click',()=>{
        const theme=$('themeSelect')?.value||'dark',cardDeck=$('cardDeckSelect')?.value||'standard',tableStyle=$('tableStyleSelect')?.value||'felt';
        if(typeof ThemeManager!=='undefined')ThemeManager.setTheme(theme);
        if(typeof CardsModule!=='undefined')CardsModule.setDeck(cardDeck);
        document.body.setAttribute('data-table-style',tableStyle);
        try{localStorage.setItem('poker_visual_prefs',JSON.stringify({theme,cardDeck,tableStyle}));}catch(e){}
        modal.style.display='none'; toast('Thème appliqué','success');
    });
    try{const p=JSON.parse(localStorage.getItem('poker_visual_prefs')||'{}');
        if(p.theme&&typeof ThemeManager!=='undefined')ThemeManager.setTheme(p.theme);
        if(p.cardDeck&&typeof CardsModule!=='undefined')CardsModule.setDeck(p.cardDeck);
        if(p.tableStyle)document.body.setAttribute('data-table-style',p.tableStyle);
        if(p.theme){const el=$('themeSelect');if(el)el.value=p.theme;}
        if(p.cardDeck){const el=$('cardDeckSelect');if(el)el.value=p.cardDeck;}
        if(p.tableStyle){const el=$('tableStyleSelect');if(el)el.value=p.tableStyle;}
    }catch(e){}
}

// ── Keyboard ─────────────────────────────────────────────────────────────
function setupKeyboardShortcuts(){
    document.addEventListener('keydown',(e)=>{
        if(e.target.tagName==='INPUT'||e.target.tagName==='TEXTAREA')return;
        if(gameState?.current_actor!==currentUser?.id)return;
        switch(e.key.toLowerCase()){
            case 'f':doAction('fold');break;
            case 'c':$('callBtn')?.style.display!=='none'?doAction('call'):doAction('check');break;
            case 'r':showRaiseSlider();break;
            case 'a':const al=currentQuickBets.find(b=>b.key==='allin');if(al)doAction('all_in',al.amount);break;
            case 'escape':hideRaiseSlider();break;
        }
    });
}

// ── Utils ────────────────────────────────────────────────────────────────
function formatStack(a){if(a==null)return '0';if(showStacksInBB&&gameState?.big_blind)return `${(a/gameState.big_blind).toFixed(1)} BB`;return a.toLocaleString();}
function esc(t){const d=document.createElement('div');d.textContent=t||'';return d.innerHTML;}
function toast(message,type='info'){
    let c=$('toastContainer')||(()=>{const c=document.createElement('div');c.id='toastContainer';c.className='toast-container';document.body.appendChild(c);return c;})();
    const el=document.createElement('div');el.className=`toast toast-${type}`;el.textContent=message;
    c.appendChild(el);setTimeout(()=>el.classList.add('show'),10);
    setTimeout(()=>{el.classList.remove('show');setTimeout(()=>el.remove(),300);},3000);
}

document.addEventListener('DOMContentLoaded', init);
