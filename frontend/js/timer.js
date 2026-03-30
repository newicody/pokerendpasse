/**
 * timer.js — Timer d'action avec callback (secs, percentage)
 */
const TimerModule = (() => {
    let _interval = null;
    let _remaining = 0;
    let _total = 0;

    function start(seconds, total, callback) {
        stop();
        _remaining = seconds;
        _total = total || seconds;
        callback(_remaining, _remaining / _total);
        _interval = setInterval(() => {
            _remaining = Math.max(0, _remaining - 1);
            callback(_remaining, _total > 0 ? _remaining / _total : 0);
            if (_remaining <= 0) stop();
        }, 1000);
    }

    function stop() {
        if (_interval) { clearInterval(_interval); _interval = null; }
    }

    function getRemaining() { return _remaining; }

    return { start, stop, getRemaining };
})();

window.TimerModule = TimerModule;
