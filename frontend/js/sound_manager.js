/**
 * sound_manager.js — Sons procéduraux via Web Audio API
 */
const SoundManager = (() => {
    let _ctx = null;
    let _enabled = true;
    let _volume = 0.5;
    let _initialized = false;

    function _getCtx() {
        if (!_ctx) {
            try { _ctx = new (window.AudioContext || window.webkitAudioContext)(); }
            catch (e) { return null; }
        }
        if (_ctx.state === 'suspended') _ctx.resume().catch(() => {});
        return _ctx;
    }

    function _gain(vol) {
        const ctx = _getCtx();
        if (!ctx) return null;
        const g = ctx.createGain();
        g.gain.value = vol;
        g.connect(ctx.destination);
        return g;
    }

    function _beep(freq, duration, type = 'sine', vol = _volume * 0.3) {
        const ctx = _getCtx();
        if (!ctx || !_enabled) return;
        try {
            const osc = ctx.createOscillator();
            const g = _gain(vol);
            if (!g) return;
            osc.type = type;
            osc.frequency.value = freq;
            g.gain.setValueAtTime(vol, ctx.currentTime);
            g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + duration);
            osc.connect(g);
            osc.start(ctx.currentTime);
            osc.stop(ctx.currentTime + duration);
        } catch (e) {}
    }

    function _noise(duration, vol = _volume * 0.3) {
        const ctx = _getCtx();
        if (!ctx || !_enabled) return;
        try {
            const buf = ctx.createBuffer(1, ctx.sampleRate * duration, ctx.sampleRate);
            const data = buf.getChannelData(0);
            for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;
            const src = ctx.createBufferSource();
            src.buffer = buf;
            const g = _gain(vol);
            if (!g) return;
            g.gain.setValueAtTime(vol, ctx.currentTime);
            g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + duration);
            src.connect(g);
            src.start(ctx.currentTime);
        } catch (e) {}
    }

    const _sounds = {
        chip:  () => { _noise(0.08, _volume * 0.4); _beep(800, 0.06, 'square', _volume * 0.15); },
        bet:   () => { for (let i = 0; i < 3; i++) setTimeout(() => _noise(0.07, _volume * 0.35), i * 40); },
        deal:  () => { _noise(0.12, _volume * 0.25); _beep(600, 0.08, 'triangle', _volume * 0.1); },
        flip:  () => { _beep(900, 0.05, 'triangle', _volume * 0.2); _noise(0.06, _volume * 0.15); },
        fold:  () => { _beep(300, 0.15, 'sine', _volume * 0.1); },
        check: () => { _beep(500, 0.05, 'square', _volume * 0.1); },
        win:   () => { [523, 659, 784].forEach((f, i) => setTimeout(() => _beep(f, 0.2, 'sine', _volume * 0.25), i * 120)); },
        turn:  () => { _beep(440, 0.1, 'triangle', _volume * 0.3); },
        timer: () => { _beep(880, 0.05, 'square', _volume * 0.4); },
        error: () => { _beep(200, 0.3, 'sawtooth', _volume * 0.2); },
    };

    return {
        play(name) { if (_enabled && _sounds[name]) _sounds[name](); },
        toggle()   { _enabled = !_enabled; return _enabled; },
        isEnabled(){ return _enabled; },
        setVolume(v) { _volume = Math.min(1, Math.max(0, v)); },
        getVolume()  { return _volume; },
        loadPreferences() {
            try {
                const s = JSON.parse(localStorage.getItem('poker_settings') || '{}');
                _enabled = (s.sound !== 'off');
                _volume = parseFloat(s.soundVolume ?? 0.5);
            } catch (e) {}
        },
        list() { return Object.keys(_sounds); },
        init() {
            if (_initialized) return;
            _initialized = true;
            this.loadPreferences();
            const wake = () => { _getCtx(); document.removeEventListener('click', wake); };
            document.addEventListener('click', wake);
        },
    };
})();

window.SoundManager = SoundManager;
