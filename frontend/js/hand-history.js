/**
 * hand-history.js — Module d'historique des mains
 * Stocke et affiche l'historique des mains jouées
 */
'use strict';

const HandHistoryModule = (() => {
    const MAX_HISTORY = 50;
    let _history = [];
    let _currentHand = null;
    
    /**
     * Structure d'une main dans l'historique
     */
    function createHandRecord(handNumber, data) {
        return {
            handNumber: handNumber,
            timestamp: new Date().toISOString(),
            players: data.players || [],
            communityCards: data.communityCards || [],
            pot: data.pot || 0,
            winner: data.winner || null,
            winningHand: data.winningHand || null,
            actions: [],
            myCards: data.myCards || [],
            result: data.result || null // 'win', 'lose', null
        };
    }
    
    /**
     * Démarre l'enregistrement d'une nouvelle main
     */
    function startHand(handNumber, players, myCards) {
        _currentHand = createHandRecord(handNumber, {
            players: players.map(p => ({
                id: p.user_id,
                name: p.username,
                position: p.position,
                chips: p.chips || p.stack
            })),
            myCards: myCards || []
        });
        return _currentHand;
    }
    
    /**
     * Ajoute une action à la main courante
     */
    function addAction(playerId, action, amount = 0, street = 'preflop') {
        if (!_currentHand) return;
        
        _currentHand.actions.push({
            playerId,
            action,
            amount,
            street,
            timestamp: Date.now()
        });
    }
    
    /**
     * Met à jour les cartes communes
     */
    function updateCommunityCards(cards) {
        if (!_currentHand) return;
        _currentHand.communityCards = cards || [];
    }
    
    /**
     * Termine la main courante
     */
    function endHand(winner, winningHand, pot, myResult) {
        if (!_currentHand) return;
        
        _currentHand.winner = winner;
        _currentHand.winningHand = winningHand;
        _currentHand.pot = pot;
        _currentHand.result = myResult;
        _currentHand.endTime = new Date().toISOString();
        
        // Ajouter à l'historique
        _history.unshift(_currentHand);
        
        // Limiter la taille
        if (_history.length > MAX_HISTORY) {
            _history = _history.slice(0, MAX_HISTORY);
        }
        
        const completedHand = _currentHand;
        _currentHand = null;
        
        return completedHand;
    }
    
    /**
     * Génère le HTML pour une entrée d'historique
     */
    function renderHistoryEntry(hand) {
        const cards = hand.communityCards.length > 0 
            ? hand.communityCards.map(c => formatCardShort(c)).join(' ')
            : '—';
        
        const winnerName = hand.winner?.username || hand.winner?.name || '?';
        const resultClass = hand.result === 'win' ? 'win' : 
                           hand.result === 'lose' ? 'lose' : '';
        
        const myCardsHtml = hand.myCards.length > 0
            ? `<span class="history-my-cards">[${hand.myCards.map(c => formatCardShort(c)).join(' ')}]</span>`
            : '';
        
        return `
            <div class="history-entry ${resultClass}" data-hand="${hand.handNumber}">
                <div class="history-header">
                    <span class="history-hand-number">#${hand.handNumber}</span>
                    ${myCardsHtml}
                    <span class="history-pot">${formatChips(hand.pot)}</span>
                </div>
                <div class="history-details">
                    <span class="history-cards">${cards}</span>
                    <span class="history-winner">→ ${winnerName}</span>
                </div>
                ${hand.winningHand ? `<div class="history-winning-hand">${hand.winningHand}</div>` : ''}
            </div>
        `;
    }
    
    /**
     * Met à jour l'affichage de l'historique
     */
    function updateDisplay(container) {
        if (!container) return;
        
        if (_history.length === 0) {
            container.innerHTML = `
                <div class="history-empty">
                    <span>Aucune main jouée</span>
                </div>
            `;
            return;
        }
        
        container.innerHTML = _history
            .slice(0, 20) // Afficher les 20 dernières
            .map(hand => renderHistoryEntry(hand))
            .join('');
        
        // Ajouter les événements de clic pour voir les détails
        container.querySelectorAll('.history-entry').forEach(entry => {
            entry.addEventListener('click', () => {
                const handNum = parseInt(entry.dataset.hand);
                const hand = _history.find(h => h.handNumber === handNum);
                if (hand) {
                    showHandDetails(hand);
                }
            });
        });
    }
    
    /**
     * Affiche les détails d'une main (modal ou tooltip)
     */
    function showHandDetails(hand) {
        // Pour l'instant, juste un console.log
        // Peut être étendu avec un modal
        console.log('Hand details:', hand);
        
        // Créer un toast avec les détails
        const message = `Main #${hand.handNumber}: ${hand.winner?.username || '?'} gagne ${formatChips(hand.pot)}`;
        if (window.toast) {
            window.toast(message, 'info');
        }
    }
    
    /**
     * Formate une carte en version courte
     */
    function formatCardShort(cardStr) {
        if (!cardStr || cardStr === 'back') return '??';
        
        const suitSymbols = { 's': '♠', 'h': '♥', 'd': '♦', 'c': '♣' };
        const suit = cardStr.slice(-1).toLowerCase();
        const rank = cardStr.slice(0, -1);
        
        return rank + (suitSymbols[suit] || suit);
    }
    
    /**
     * Formate les jetons
     */
    function formatChips(amount, inBB = false, bigBlind = 20) {
        if (amount === null || amount === undefined) return '0';
        
        if (inBB && bigBlind > 0) {
            const bb = (amount / bigBlind).toFixed(1);
            return `${bb} BB`;
        }
        
        return amount.toLocaleString();
    }
    
    /**
     * Récupère l'historique complet
     */
    function getHistory() {
        return [..._history];
    }
    
    /**
     * Récupère la main courante
     */
    function getCurrentHand() {
        return _currentHand;
    }
    
    /**
     * Efface l'historique
     */
    function clear() {
        _history = [];
        _currentHand = null;
    }
    
    /**
     * Charge l'historique depuis le localStorage
     */
    function loadFromStorage(tableId) {
        try {
            const key = `poker_history_${tableId}`;
            const data = localStorage.getItem(key);
            if (data) {
                _history = JSON.parse(data);
            }
        } catch (e) {
            console.error('Error loading hand history:', e);
        }
    }
    
    /**
     * Sauvegarde l'historique dans le localStorage
     */
    function saveToStorage(tableId) {
        try {
            const key = `poker_history_${tableId}`;
            localStorage.setItem(key, JSON.stringify(_history.slice(0, MAX_HISTORY)));
        } catch (e) {
            console.error('Error saving hand history:', e);
        }
    }
    
    // API publique
    return {
        startHand,
        addAction,
        updateCommunityCards,
        endHand,
        renderHistoryEntry,
        updateDisplay,
        showHandDetails,
        formatCardShort,
        formatChips,
        getHistory,
        getCurrentHand,
        clear,
        loadFromStorage,
        saveToStorage
    };
})();

// Export global
window.HandHistoryModule = HandHistoryModule;
