// frontend/js/auth.js
class AuthManager {
    static async register(username, password, email = null) {
        const response = await fetch('/api/auth/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password, email })
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Registration failed');
        }
        
        const data = await response.json();
        this.setSession(data.session_id);
        return data.user;
    }
    
    static async login(username, password, rememberMe = false) {
        const response = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password, remember_me: rememberMe })
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Login failed');
        }
        
        const data = await response.json();
        this.setSession(data.session_id);
        return data.user;
    }
    
    static async logout() {
        const response = await fetch('/api/auth/logout', {
            method: 'POST'
        });
        
        this.clearSession();
        return response.ok;
    }
    
    static async getCurrentUser() {
        try {
            const response = await fetch('/api/auth/me');
            if (!response.ok) return null;
            return await response.json();
        } catch (e) {
            return null;
        }
    }
    
    static async updateProfile(data) {
        const response = await fetch('/api/auth/me', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Update failed');
        }
        
        return response.json();
    }
    
    static async changePassword(currentPassword, newPassword) {
        const response = await fetch('/api/auth/change-password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ current_password: currentPassword, new_password: newPassword })
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Password change failed');
        }
        
        return response.json();
    }
    
    static setSession(sessionId) {
        localStorage.setItem('poker_session', sessionId);
    }
    
    static getSession() {
        return localStorage.getItem('poker_session');
    }
    
    static clearSession() {
        localStorage.removeItem('poker_session');
    }
    
    static isAuthenticated() {
        return !!this.getSession();
    }
}

window.auth = AuthManager;
