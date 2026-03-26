/**
 * sound_manager.js — Gestionnaire de sons poker via Web Audio API
 * Aucune dépendance externe, génération procédurale des sons.
 * Usage : SoundManager.play('chip') / SoundManager.setVolume(0.5)
 */

const SoundManager = (() => {
    let _ctx = null;
    let _volume = 0.5;
    let _enabled = true;
    let _initialized = false;

    function _getCtx() {
        if (!_ctx) {
            try {
                _ctx = new (window.AudioContext || window.webkitAudioContext)();
            } catch (e) {
                console.warn('Web Audio API non disponible');
                return null;
            }
        }
        // Reprendre si suspendu (politique autoplay navigateur)
        if (_ctx.state === 'suspended') _ctx.resume();
        return _ctx;
    }

    function _gain(value = _volume) {
        const ctx = _getCtx();
        if (!ctx) return null;
        const g = ctx.createGain();
        g.gain.value = value;
        g.connect(ctx.destination);
        return g;
    }

    // ── Générateurs de sons ─────────────────────────────────────────────────

    function _beep(freq, duration, type = 'sine', vol = _volume) {
        const ctx = _getCtx();
        if (!ctx || !_enabled) return;
        try {
            const osc = ctx.createOscillator();
            const g   = _gain(vol);
            if (!g) return;
            osc.type = type;
            osc.frequency.setValueAtTime(freq, ctx.currentTime);
            osc.frequency.exponentialRampToValueAtTime(freq * 0.8, ctx.currentTime + duration);
            g.gain.setValueAtTime(vol, ctx.currentTime);
            g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + duration);
            osc.connect(g);
            osc.start(ctx.currentTime);
            osc.stop(ctx.currentTime + duration);
        } catch (e) { /* silencieux */ }
    }

    function _noise(duration, vol = _volume * 0.3) {
        const ctx = _getCtx();
        if (!ctx || !_enabled) return;
        try {
            const bufferSize = ctx.sampleRate * duration;
            const buffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
            const data   = buffer.getChannelData(0);
            for (let i = 0; i < bufferSize; i++) data[i] = Math.random() * 2 - 1;
            const src = ctx.createBufferSource();
            src.buffer = buffer;
            const g = _gain(vol);
            if (!g) return;
            g.gain.setValueAtTime(vol, ctx.currentTime);
            g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + duration);
            src.connect(g);
            src.start(ctx.currentTime);
        } catch (e) { /* silencieux */ }
    }

    // ── Bibliothèque de sons ────────────────────────────────────────────────

    const _sounds = {

        /** Jetons posés sur la table */
        chip: () => {
            _noise(0.08, _volume * 0.4);
            _beep(800, 0.06, 'square', _volume * 0.15);
        },

        /** Mise (plusieurs jetons) */
        bet: () => {
            for (let i = 0; i < 3; i++) {
                setTimeout(() => _noise(0.07, _volume * 0.35), i * 40);
            }
        },

        /** Distribution des cartes */
        deal: () => {
            _noise(0.12, _volume * 0.25);
            _beep(600, 0.08, 'triangle', _volume * 0.1);
        },

        /** Retournement d'une carte (flop/turn/river) */
        flip: () => {
            _beep(900, 0.05, 'triangle', _volume * 0.3);
            setTimeout(() => _beep(1100, 0.05, 'triangle', _volume * 0.2), 50);
        },

        /** Fold */
        fold: () => {
            _beep(300, 0.15, 'sawtooth', _volume * 0.2);
            _noise(0.1, _volume * 0.1);
        },

        /** Check */
        check: () => {
            _beep(1000, 0.08, 'square', _volume * 0.15);
        },

        /** Call */
        call: () => {
            _beep(700, 0.1, 'sine', _volume * 0.25);
            setTimeout(() => _beep(900, 0.08, 'sine', _volume * 0.2), 80);
        },

        /** Raise / All-in */
        raise: () => {
            _beep(600, 0.07, 'square', _volume * 0.3);
            setTimeout(() => _beep(900, 0.07, 'square', _volume * 0.3), 80);
            setTimeout(() => _beep(1200, 0.1, 'square', _volume * 0.25), 160);
            for (let i = 0; i < 5; i++) setTimeout(() => _noise(0.06, _volume * 0.3), i * 30);
        },

        /** Gain du pot */
        win: () => {
            const notes = [523, 659, 784, 1047]; // Do Mi Sol Do
            notes.forEach((f, i) => setTimeout(() => _beep(f, 0.18, 'sine', _volume * 0.4), i * 100));
        },

        /** Elimination */
        eliminate: () => {
            const notes = [400, 300, 200];
            notes.forEach((f, i) => setTimeout(() => _beep(f, 0.2, 'sawtooth', _volume * 0.3), i * 120));
        },

        /** Notification / alerte */
        notify: () => {
            _beep(880, 0.1, 'sine', _volume * 0.3);
            setTimeout(() => _beep(1100, 0.12, 'sine', _volume * 0.35), 120);
        },

        /** Compte à rebours (tic) */
        tick: () => {
            _beep(1200, 0.04, 'square', _volume * 0.2);
        },

        /** Urgence fin de temps */
        tick_urgent: () => {
            _beep(1600, 0.05, 'square', _volume * 0.35);
        },

        /** Changement de niveau de blind */
        blind_up: () => {
            _beep(440, 0.1, 'sine', _volume * 0.3);
            setTimeout(() => _beep(550, 0.1, 'sine', _volume * 0.3), 120);
            setTimeout(() => _beep(660, 0.15, 'sine', _volume * 0.35), 240);
        },

        /** Inscription réussie */
        register: () => {
            _beep(660, 0.1, 'sine', _volume * 0.3);
            setTimeout(() => _beep(880, 0.15, 'sine', _volume * 0.35), 100);
        },

        /** Message chat */
        chat: () => {
            _beep(1000, 0.06, 'sine', _volume * 0.15);
        },

        /** Connexion */
        connect: () => {
            _beep(500, 0.08, 'sine', _volume * 0.2);
            setTimeout(() => _beep(700, 0.08, 'sine', _volume * 0.2), 100);
        },

        /** Déconnexion */
        disconnect: () => {
            _beep(700, 0.08, 'sine', _volume * 0.2);
            setTimeout(() => _beep(500, 0.1, 'sine', _volume * 0.15), 100);
        },

        /** Toast / info */
        toast_success: () => {
            _beep(660, 0.08, 'triangle', _volume * 0.2);
            setTimeout(() => _beep(880, 0.1, 'triangle', _volume * 0.2), 80);
        },

        toast_error: () => {
            _beep(330, 0.12, 'sawtooth', _volume * 0.2);
        },
    };

    // ── API publique ─────────────────────────────────────────────────────────

    return {
        /**
         * Joue un son par nom.
         * @param {string} name - clé de _sounds
         * @param {number} [vol] - volume override 0-1
         */
        play(name, vol) {
            if (!_enabled) return;
            const prev = _volume;
            if (vol !== undefined) _volume = Math.min(1, Math.max(0, vol));
            const fn = _sounds[name];
            if (fn) {
                try { fn(); } catch (e) { console.warn('Sound error:', e); }
            } else {
                console.warn(`Son inconnu : "${name}"`);
            }
            if (vol !== undefined) _volume = prev;
        },

        /** Active/désactive tous les sons */
        setEnabled(v) { _enabled = !!v; },

        isEnabled() { return _enabled; },

        /** Règle le volume global 0–1 */
        setVolume(v) { _volume = Math.min(1, Math.max(0, v)); },

        getVolume() { return _volume; },

        /** Charge les préférences depuis localStorage */
        loadPreferences() {
            try {
                const s = JSON.parse(localStorage.getItem('poker_settings') || '{}');
                _enabled = (s.sound !== 'off');
                _volume  = parseFloat(s.soundVolume ?? 0.5);
            } catch (e) { /* defaults */ }
        },

        /** Liste des sons disponibles */
        list() { return Object.keys(_sounds); },

        /** Init (réveille le contexte audio sur interaction utilisateur) */
        init() {
            if (_initialized) return;
            _initialized = true;
            this.loadPreferences();
            // Réveiller l'AudioContext sur le premier clic
            const wake = () => { _getCtx(); document.removeEventListener('click', wake); };
            document.addEventListener('click', wake);
        },
    };
})();

window.SoundManager = SoundManager;
