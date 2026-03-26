// frontend/js/settings.js
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
    
    static get(key) {
        const settings = this.load();
        return settings[key];
    }
    
    static set(key, value) {
        const settings = this.load();
        settings[key] = value;
        this.save(settings);
    }
}

// Initialiser les settings
window.settings = SettingsManager;

// Dans lobby.js, ajouter:
function setupOptionsModal() {
    const optionsBtn = document.getElementById('optionsBtn');
    const optionsModal = document.getElementById('optionsModal');
    const closeBtn = optionsModal.querySelector('.close');
    const saveBtn = document.getElementById('saveSettings');
    
    optionsBtn.onclick = () => {
        // Charger les settings actuels
        const settings = SettingsManager.load();
        document.getElementById('soundSetting').value = settings.sound;
        document.getElementById('animationSpeed').value = settings.animationSpeed;
        document.getElementById('cardDisplay').value = settings.cardDisplay;
        document.getElementById('autoAction').value = settings.autoAction;
        document.getElementById('showHistory').value = settings.showHistory;
        optionsModal.style.display = 'block';
    };
    
    closeBtn.onclick = () => optionsModal.style.display = 'none';
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
    
    window.onclick = (event) => {
        if (event.target === optionsModal) {
            optionsModal.style.display = 'none';
        }
    };
}
