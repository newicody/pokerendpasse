// frontend/js/sound_manager.js
/**
 * sound_manager.js — Sons procéduraux via Web Audio API
 */

const SoundManager = (() => {
    let _ctx = null;
    let _enabled = true;
    let _volume = 0.5;
    let _initialized = false;
let _options = {
    soundOnWin: true,
    soundOnChat: true,
    soundOnDeal: true,
    soundOnTimer: true,
};
let _customUrl = null;

function setOption(key, value) {
    _options[key] = value;
}

function getOption(key) {
    return _options[key];
}

function setCustomUrl(url) {
    _customUrl = url;
    // Vous pourriez implémenter le chargement du son personnalisé ici
}
    function _getCtx() {
        if (!_ctx) {
            try {
                _ctx = new (window.AudioContext || window.webkitAudioContext)();
            } catch (e) {
                console.warn('Web Audio API not supported');
                return null;
            }
        }
        return _ctx;
    }

    function _beep(freq, duration, type = 'sine', vol = _volume * 0.3) {
        const ctx = _getCtx();
        if (!ctx || !_enabled) return;
        try {
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            gain.gain.value = vol;
            osc.type = type;
            osc.frequency.value = freq;
            osc.connect(gain);
            gain.connect(ctx.destination);
            gain.gain.setValueAtTime(vol, ctx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + duration);
            osc.start(ctx.currentTime);
            osc.stop(ctx.currentTime + duration);
        } catch (e) {}
    }

    function _noise(duration, vol = _volume * 0.3) {
        const ctx = _getCtx();
        if (!ctx || !_enabled) return;
        try {
            const bufferSize = ctx.sampleRate * duration;
            const buffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
            const data = buffer.getChannelData(0);
            for (let i = 0; i < bufferSize; i++) {
                data[i] = Math.random() * 2 - 1;
            }
            const source = ctx.createBufferSource();
            source.buffer = buffer;
            const gain = ctx.createGain();
            gain.gain.value = vol;
            source.connect(gain);
            gain.connect(ctx.destination);
            gain.gain.setValueAtTime(vol, ctx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + duration);
            source.start(ctx.currentTime);
        } catch (e) {}
    }

    const _sounds = {
        chip: () => {
            _noise(0.08, _volume * 0.4);
            _beep(800, 0.06, 'square', _volume * 0.15);
        },
        bet: () => {
            for (let i = 0; i < 3; i++) {
                setTimeout(() => _noise(0.07, _volume * 0.35), i * 40);
            }
        },
        deal: () => {
            _noise(0.12, _volume * 0.25);
            _beep(600, 0.08, 'triangle', _volume * 0.1);
        },
        flip: () => {
            _beep(900, 0.05, 'triangle', _volume * 0.2);
            _noise(0.06, _volume * 0.15);
        },
        fold: () => {
            _beep(300, 0.15, 'sine', _volume * 0.1);
        },
        check: () => {
            _beep(500, 0.05, 'square', _volume * 0.1);
        },
        win: () => {
            [523, 659, 784].forEach((f, i) => {
                setTimeout(() => _beep(f, 0.2, 'sine', _volume * 0.25), i * 120);
            });
        },
        turn: () => {
            _beep(440, 0.1, 'triangle', _volume * 0.3);
        },
        timer: () => {
            _beep(880, 0.05, 'square', _volume * 0.4);
        },
        error: () => {
            _beep(200, 0.3, 'sawtooth', _volume * 0.2);
        },
    };

    function _resumeContext() {
        const ctx = _getCtx();
        if (ctx && ctx.state === 'suspended') {
            ctx.resume().catch(e => console.warn('AudioContext resume failed', e));
        }
    }

    function init() {
        if (_initialized) return;
        _initialized = true;
        const unlock = () => {
            const ctx = _getCtx();
            if (ctx && ctx.state === 'suspended') {
                ctx.resume().then(() => console.log('AudioContext resumed')).catch(e => console.warn('AudioContext resume error', e));
            }
            document.removeEventListener('click', unlock);
            document.removeEventListener('touchstart', unlock);
            document.removeEventListener('keydown', unlock);
        };
        document.addEventListener('click', unlock);
        document.addEventListener('touchstart', unlock);
        document.addEventListener('keydown', unlock);
        this.loadPreferences();
    }

    function play(name) {
        if (!_enabled) return;
if (name === 'win' && !_options.soundOnWin) return;
    if (name === 'chat' && !_options.soundOnChat) return;
    if (name === 'flip' && !_options.soundOnDeal) return;
    if (name === 'timer' && !_options.soundOnTimer) return;

        if (!_ctx) {
            _getCtx();
            _resumeContext();
        }
        if (_sounds[name]) {
            _sounds[name]();
        } else {
            console.warn(`Sound not found: ${name}`);
        }
    }

    function enable() {
        _enabled = true;
        _resumeContext();
    }

    function disable() {
        _enabled = false;
    }

    function toggle() {
        _enabled = !_enabled;
        if (_enabled) _resumeContext();
        return _enabled;
    }

    function setVolume(vol) {
        _volume = Math.min(1, Math.max(0, vol));
    }

    function getVolume() {
        return _volume;
    }

    function isEnabled() {
        return _enabled;
    }

    function loadPreferences() {
        try {
            if (typeof SettingsManager !== 'undefined') {
                const s = SettingsManager.get();
                _enabled = (s.sound !== 'off');
                _volume = parseFloat(s.soundVolume) || 0.5;
            } else {
                const stored = localStorage.getItem('poker_settings');
                if (stored) {
                    const s = JSON.parse(stored);
                    _enabled = (s.sound !== 'off');
                    _volume = parseFloat(s.soundVolume) || 0.5;
                }
            }
        } catch (e) {
            console.warn('Failed to load sound preferences', e);
        }
    }

    function savePreferences() {
        if (typeof SettingsManager !== 'undefined') {
            SettingsManager.set('sound', _enabled ? 'on' : 'off');
            SettingsManager.set('soundVolume', _volume);
        } else {
            try {
                const stored = localStorage.getItem('poker_settings');
                const s = stored ? JSON.parse(stored) : {};
                s.sound = _enabled ? 'on' : 'off';
                s.soundVolume = _volume;
                localStorage.setItem('poker_settings', JSON.stringify(s));
            } catch (e) {}
        }
    }

    function list() {
        return Object.keys(_sounds);
    }

    return {
        init,
        play,
        enable,
        disable,
        toggle,
        setVolume,
        getVolume,
        isEnabled,
        loadPreferences,
        savePreferences,
        list,
setOption, 
getOption, 
setCustomUrl
    };
})();

window.SoundManager = SoundManager;
