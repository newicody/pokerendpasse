// frontend/js/api.js
const API_BASE = '/api';

class PokerAPI {
    static async request(endpoint, options = {}) {
        try {
            const response = await fetch(`${API_BASE}${endpoint}`, {
                headers: {
                    'Content-Type': 'application/json',
                    ...options.headers
                },
                ...options
            });
            
            if (!response.ok) {
                const error = await response.json().catch(() => ({ detail: 'Request failed' }));
                throw new Error(error.detail || `HTTP ${response.status}`);
            }
            
            return response.json();
        } catch (error) {
            console.error('API request failed:', error);
            throw error;
        }
    }
    
    // Users
    static async createUser(username, email = null) {
        return this.request('/users', {
            method: 'POST',
            body: JSON.stringify({ username, email })
        });
    }
    
    static async getUser(userId) {
        return this.request(`/users/${userId}`);
    }
    
    // Tables
    static async getTables() {
        return this.request('/tables');
    }
    
    static async getTable(tableId) {
        return this.request(`/tables/${tableId}`);
    }
    
    static async createTable(data) {
        return this.request('/tables', {
            method: 'POST',
            body: JSON.stringify(data)
        });
    }
    
    static async joinTable(tableId, userId, buyIn) {
        return this.request(`/tables/${tableId}/join`, {
            method: 'POST',
            body: JSON.stringify({ user_id: userId, buy_in: buyIn })
        });
    }
    
    static async leaveTable(tableId, userId) {
        return this.request(`/tables/${tableId}/leave?user_id=${userId}`, {
            method: 'POST'
        });
    }
    
    static async quickJoin(userId, buyIn = 100) {
        return this.request(`/quick-join?user_id=${userId}&buy_in=${buyIn}`, {
            method: 'POST'
        });
    }
    
    static async sendAction(tableId, userId, action, amount = 0) {
        return this.request(`/tables/${tableId}/action`, {
            method: 'POST',
            body: JSON.stringify({ user_id: userId, action, amount })
        });
    }
    
    // Lobby
    static async getLobbyInfo() {
        return this.request('/lobby');
    }
}

// User management - Variables globales
window.currentUser = null;

window.initCurrentUser = async function() {
    const savedUser = localStorage.getItem('poker_user');
    if (savedUser) {
        try {
            const user = JSON.parse(savedUser);
            window.currentUser = await PokerAPI.getUser(user.id);
            console.log('User loaded:', window.currentUser);
        } catch (e) {
            console.log('Error loading user, creating new one');
            await window.createNewUser();
        }
    } else {
        await window.createNewUser();
    }
    return window.currentUser;
};

window.createNewUser = async function() {
    let username = prompt('Enter your name:', `Player${Math.floor(Math.random() * 1000)}`);
    if (!username || username.trim() === '') {
        username = `Player${Math.floor(Math.random() * 1000)}`;
    }
    try {
        window.currentUser = await PokerAPI.createUser(username.trim());
        localStorage.setItem('poker_user', JSON.stringify({ id: window.currentUser.id }));
        console.log('New user created:', window.currentUser);
    } catch (error) {
        console.error('Failed to create user:', error);
        // Fallback user
        window.currentUser = {
            id: 'guest_' + Date.now(),
            username: username,
            chips: 1000
        };
    }
    return window.currentUser;
};

window.showToast = function(message, type = 'info') {
    let toast = document.getElementById('toast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'toast';
        toast.className = 'toast';
        document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.className = `toast ${type} show`;
    setTimeout(() => {
        toast.classList.remove('show');
    }, 3000);
};
