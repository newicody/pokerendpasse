// frontend/js/timer.js
/**
 * timer.js — Timer d'action avec barre de progression et son
 * Supporte la configuration via SettingsManager
 */

const TimerModule = (() => {
    let _interval = null;
    let _remaining = 0;
    let _total = 0;
    let _callback = null;
    let _soundPlayed = false; // éviter de jouer le son plusieurs fois

    /**
     * Démarre le timer
     * @param {number} seconds - durée en secondes
     * @param {number} total - durée totale (pourcentage, peut être identique)
     * @param {function} callback - fonction appelée chaque seconde (remaining, percentage)
     */
    function start(seconds, total, callback) {
        stop();
        _remaining = seconds;
        _total = total || seconds;
        _callback = callback;
        _soundPlayed = false;

        // Appel immédiat
        if (_callback) {
            const pct = _total > 0 ? _remaining / _total : 0;
            _callback(_remaining, pct);
        }

        _interval = setInterval(() => {
            _remaining = Math.max(0, _remaining - 1);
            const pct = _total > 0 ? _remaining / _total : 0;
            if (_callback) _callback(_remaining, pct);

            // Jouer un son à 5 secondes s'il reste du temps et que le son n'a pas été joué
            if (_remaining === 5 && !_soundPlayed && typeof SoundManager !== 'undefined') {
                SoundManager.play('timer');
                _soundPlayed = true;
            }

            if (_remaining <= 0) {
                stop();
            }
        }, 1000);
    }

    function stop() {
        if (_interval) {
            clearInterval(_interval);
            _interval = null;
        }
        _remaining = 0;
        _total = 0;
        _callback = null;
        _soundPlayed = false;
    }

    function getRemaining() {
        return _remaining;
    }

    function getTotal() {
        return _total;
    }

    /**
     * Met à jour la durée par défaut (utile si les paramètres changent)
     * @param {number} seconds - nouvelle durée par défaut
     */
    function setDefaultDuration(seconds) {
        // Pour l'instant, on ne stocke pas de durée par défaut au niveau du module,
        // car la durée est passée à start(). On peut cependant l'utiliser si on veut.
        // Laissé pour compatibilité future.
    }

    return {
        start,
        stop,
        getRemaining,
        getTotal,
        setDefaultDuration
    };
})();

// Rendre disponible globalement
window.TimerModule = TimerModule;
