// frontend/js/lobby.js - Version avec authentification
let refreshInterval = null;
let currentUser = null;
let isGuest = false;

async function init() {
    console.log('Initializing lobby...');
    
    // Vérifier l'authentification
    await checkAuth();
    
    // Charger les tables
    await loadTables();
    await updateStats();
    
    // Rafraîchir toutes les 3 secondes
    if (refreshInterval) clearInterval(refreshInterval);
    refreshInterval = setInterval(() => {
        loadTables();
        updateStats();
    }, 3000);
    
    // Event listeners
    const quickJoinBtn = document.getElementById('quickJoinBtn');
    const optionsBtn = document.getElementById('optionsBtn');
    const loginBtn = document.getElementById('loginBtn');
    const registerBtn = document.getElementById('registerBtn');
    const logoutBtn = document.getElementById('logoutBtn');
    
    if (quickJoinBtn) quickJoinBtn.addEventListener('click', quickJoin);
    if (optionsBtn) optionsBtn.addEventListener('click', showOptionsModal);
    if (loginBtn) loginBtn.addEventListener('click', showLoginModal);
    if (registerBtn) registerBtn.addEventListener('click', showRegisterModal);
    if (logoutBtn) logoutBtn.addEventListener('click', logout);
    
    setupAuthModals();
    setupOptionsModal();
}

async function checkAuth() {
    try {
        const response = await fetch('/api/auth/me');
        if (response.ok) {
            currentUser = await response.json();
            isGuest = false;
            updateUserDisplay();
            document.getElementById('guestWarning')?.classList.add('hidden');
        } else {
            // Mode invité
            isGuest = true;
            currentUser = { username: 'Guest', chips: 0 };
            updateUserDisplay();
            document.getElementById('guestWarning')?.classList.remove('hidden');
        }
    } catch (error) {
        console.error('Auth check failed:', error);
        isGuest = true;
        currentUser = { username: 'Guest', chips: 0 };
        updateUserDisplay();
    }
}

function updateUserDisplay() {
    const usernameSpan = document.getElementById('username');
    const chipsSpan = document.getElementById('chips');
    const loginBtn = document.getElementById('loginBtn');
    const registerBtn = document.getElementById('registerBtn');
    const logoutBtn = document.getElementById('logoutBtn');
    const userActions = document.getElementById('userActions');
    
    if (currentUser && !isGuest) {
        if (usernameSpan) usernameSpan.textContent = currentUser.username;
        if (chipsSpan) chipsSpan.textContent = `${currentUser.chips} chips`;
        if (loginBtn) loginBtn.style.display = 'none';
        if (registerBtn) registerBtn.style.display = 'none';
        if (logoutBtn) logoutBtn.style.display = 'block';
        if (userActions) userActions.classList.add('authenticated');
    } else {
        if (usernameSpan) usernameSpan.textContent = 'Guest';
        if (chipsSpan) chipsSpan.textContent = '0 chips (Spectator)';
        if (loginBtn) loginBtn.style.display = 'block';
        if (registerBtn) registerBtn.style.display = 'block';
        if (logoutBtn) logoutBtn.style.display = 'none';
        if (userActions) userActions.classList.remove('authenticated');
    }
}

async function joinTable(tableId) {
    if (!currentUser || isGuest) {
        alert('Please login or register to join a table');
        showLoginModal();
        return;
    }
    
    const buyInInput = document.getElementById('buyInAmount');
    const buyIn = buyInInput ? parseInt(buyInInput.value) : 100;
    
    if (buyIn < 100 || buyIn > 1000) {
        alert('Buy-in must be between 100 and 1000 chips');
        return;
    }
    
    if (currentUser.chips < buyIn) {
        alert(`You only have ${currentUser.chips} chips. Need ${buyIn}`);
        return;
    }
    
    try {
        const response = await fetch(`/api/tables/${tableId}/join`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: currentUser.id, buy_in: buyIn })
        });
        
        if (response.ok) {
            window.location.href = `/table/${tableId}`;
        } else {
            const error = await response.json();
            alert(error.detail || 'Failed to join table');
        }
    } catch (error) {
        console.error('Error joining table:', error);
        alert('Failed to join table');
    }
}

async function quickJoin() {
    if (!currentUser || isGuest) {
        alert('Please login or register to join a table');
        showLoginModal();
        return;
    }
    
    const buyIn = parseInt(document.getElementById('buyInAmount').value);
    
    try {
        const response = await fetch(`/api/quick-join?user_id=${currentUser.id}&buy_in=${buyIn}`, {
            method: 'POST'
        });
        
        if (response.ok) {
            const data = await response.json();
            window.location.href = `/table/${data.table_id}`;
        } else {
            alert('No available tables. Please try again later.');
        }
    } catch (error) {
        console.error('Error in quick join:', error);
        alert('Failed to join table');
    }
}

async function login(username, password, rememberMe) {
    try {
        const response = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password, remember_me: rememberMe })
        });
        
        if (response.ok) {
            const data = await response.json();
            currentUser = data.user;
            isGuest = false;
            updateUserDisplay();
            closeModal('loginModal');
            alert('Login successful!');
            loadTables(); // Recharger pour afficher les boutons join
        } else {
            const error = await response.json();
            alert(error.detail || 'Login failed');
        }
    } catch (error) {
        console.error('Login error:', error);
        alert('Login failed');
    }
}

async function register(username, password, email) {
    try {
        const response = await fetch('/api/auth/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password, email })
        });
        
        if (response.ok) {
            const data = await response.json();
            currentUser = data.user;
            isGuest = false;
            updateUserDisplay();
            closeModal('registerModal');
            alert('Registration successful!');
        } else {
            const error = await response.json();
            alert(error.detail || 'Registration failed');
        }
    } catch (error) {
        console.error('Registration error:', error);
        alert('Registration failed');
    }
}

async function logout() {
    try {
        await fetch('/api/auth/logout', { method: 'POST' });
        currentUser = null;
        isGuest = true;
        currentUser = { username: 'Guest', chips: 0 };
        updateUserDisplay();
        alert('Logged out successfully');
        loadTables();
    } catch (error) {
        console.error('Logout error:', error);
    }
}

function showLoginModal() {
    const modal = document.getElementById('loginModal');
    if (modal) modal.style.display = 'block';
}

function showRegisterModal() {
    const modal = document.getElementById('registerModal');
    if (modal) modal.style.display = 'block';
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) modal.style.display = 'none';
}

function setupAuthModals() {
    // Login modal
    const loginModal = document.getElementById('loginModal');
    const loginForm = document.getElementById('loginForm');
    if (loginForm) {
        loginForm.onsubmit = (e) => {
            e.preventDefault();
            const username = document.getElementById('loginUsername').value;
            const password = document.getElementById('loginPassword').value;
            const rememberMe = document.getElementById('rememberMe').checked;
            login(username, password, rememberMe);
        };
    }
    
    // Register modal
    const registerModal = document.getElementById('registerModal');
    const registerForm = document.getElementById('registerForm');
    if (registerForm) {
        registerForm.onsubmit = (e) => {
            e.preventDefault();
            const username = document.getElementById('regUsername').value;
            const password = document.getElementById('regPassword').value;
            const email = document.getElementById('regEmail').value;
            register(username, password, email);
        };
    }
    
    // Close buttons
    document.querySelectorAll('.modal .close').forEach(closeBtn => {
        closeBtn.onclick = () => {
            closeBtn.closest('.modal').style.display = 'none';
        };
    });
    
    window.onclick = (event) => {
        if (event.target.classList.contains('modal')) {
            event.target.style.display = 'none';
        }
    };
}

function setupOptionsModal() {
    const optionsModal = document.getElementById('optionsModal');
    const optionsBtn = document.getElementById('optionsBtn');
    const closeBtn = optionsModal?.querySelector('.close');
    const saveBtn = document.getElementById('saveSettings');
    
    if (optionsBtn) {
        optionsBtn.onclick = () => {
            // Charger les settings
            const settings = SettingsManager.load();
            document.getElementById('soundSetting').value = settings.sound;
            document.getElementById('animationSpeed').value = settings.animationSpeed;
            document.getElementById('cardDisplay').value = settings.cardDisplay;
            document.getElementById('autoAction').value = settings.autoAction;
            document.getElementById('showHistory').value = settings.showHistory;
            optionsModal.style.display = 'block';
        };
    }
    
    if (closeBtn) closeBtn.onclick = () => optionsModal.style.display = 'none';
    
    if (saveBtn) {
        saveBtn.onclick = () => {
            SettingsManager.save({
                sound: document.getElementById('soundSetting').value,
                animationSpeed: document.getElementById('animationSpeed').value,
                cardDisplay: document.getElementById('cardDisplay').value,
                autoAction: document.getElementById('autoAction').value,
                showHistory: document.getElementById('showHistory').value
            });
            optionsModal.style.display = 'none';
            alert('Settings saved!');
        };
    }
}

// Settings Manager
class SettingsManager {
    static defaults = {
        sound: 'on',
        animationSpeed: 'normal',
        cardDisplay: 'standard',
        autoAction: 'never',
        showHistory: 'all'
    };
    
    static load() {
        const saved = localStorage.getItem('poker_settings');
        if (saved) {
            return { ...this.defaults, ...JSON.parse(saved) };
        }
        return this.defaults;
    }
    
    static save(settings) {
        localStorage.setItem('poker_settings', JSON.stringify(settings));
    }
}

window.settings = SettingsManager;

// ... (reste du code pour loadTables, renderTables, etc.)

// Start
init();
