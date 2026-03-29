/**
 * timer.js — Timer d'action avec callback
 */
const TimerModule = (() => {
    let _interval = null;
    let _remaining = 0;

    function start(seconds, total, callback) {
        stop();
        _remaining = seconds;
        callback(_remaining, _remaining / total);
        _interval = setInterval(() => {
            _remaining = Math.max(0, _remaining - 1);
            callback(_remaining, _remaining / total);
            if (_remaining <= 0) stop();
        }, 1000);
    }

    function stop() {
        if (_interval) { clearInterval(_interval); _interval = null; }
    }

    return { start, stop };
})();

window.TimerModule = TimerModule;
