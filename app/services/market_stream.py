"""
Alpaca real-time market data stream (IEX feed).
One pooled WebSocket serves all frontend users — browsers never see our keys.

This version:
  - registers a clean shutdown handler via atexit + signal
  - closes the WebSocket stream when Flask stops
  - prevents "connection limit exceeded" (406) on the next startup
"""
import os
import signal
import atexit
import threading
import logging

from flask_socketio import SocketIO
from alpaca.data.live import StockDataStream
from alpaca.data.enums import DataFeed

logger = logging.getLogger(__name__)

LANDING_SYMBOLS = ["AAPL", "MSFT", "NVDA", "SPY", "QQQ", "TSLA"]

_socketio = None
_stream = None
_stream_thread = None
_shutdown_done = False
_shutdown_lock = threading.Lock()


def _shutdown_stream():
    """Close the Alpaca WebSocket cleanly. Idempotent — safe to call twice."""
    global _shutdown_done, _stream
    with _shutdown_lock:
        if _shutdown_done:
            return
        _shutdown_done = True

    if _stream is None:
        return

    try:
        # alpaca-py's StockDataStream exposes .stop() and .close() on recent
        # versions. Try both — whichever exists, whichever works.
        if hasattr(_stream, "stop"):
            _stream.stop()
            logger.info("Market stream stopped.")
        elif hasattr(_stream, "close"):
            _stream.close()
            logger.info("Market stream closed.")
    except Exception as e:
        logger.warning(f"Error while closing market stream: {e}")


def _install_shutdown_hooks():
    """Register the shutdown handler so Ctrl+C and process exit clean up."""
    atexit.register(_shutdown_stream)

    # SIGINT = Ctrl+C, SIGTERM = kill / system shutdown.
    # Chain to whatever handler was already installed so Flask still exits.
    def _make_handler(sig, prev):
        def _handler(signum, frame):
            _shutdown_stream()
            if callable(prev) and prev not in (signal.SIG_DFL, signal.SIG_IGN):
                prev(signum, frame)
            else:
                # Re-raise with default behavior so the process actually dies
                signal.signal(signum, signal.SIG_DFL)
                os.kill(os.getpid(), signum)
        return _handler

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            prev = signal.getsignal(sig)
            signal.signal(sig, _make_handler(sig, prev))
        except (ValueError, OSError):
            # Not on main thread, or platform doesn't support it — skip
            pass


def init_market_stream(socketio: SocketIO):
    """Start the pooled market data stream. Called once from create_app()."""
    global _socketio, _stream, _stream_thread
    _socketio = socketio

    api_key = os.environ.get("ALPACA_DATA_API_KEY")
    api_secret = os.environ.get("ALPACA_DATA_API_SECRET")

    if not api_key or not api_secret:
        logger.warning(
            "ALPACA_DATA_API_KEY/SECRET not set. Market stream disabled; "
            "landing page will fall back to 'market closed' state."
        )
        return

    _stream = StockDataStream(api_key, api_secret, feed=DataFeed.IEX)

    async def on_trade(trade):
        if _socketio:
            _socketio.emit("market:trade", {
                "symbol": trade.symbol,
                "price": float(trade.price),
                "size": int(trade.size),
                "timestamp": trade.timestamp.isoformat(),
            })

    async def on_bar(bar):
        if _socketio:
            _socketio.emit("market:bar", {
                "symbol": bar.symbol,
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": int(bar.volume),
                "timestamp": bar.timestamp.isoformat(),
            })

    _stream.subscribe_trades(on_trade, *LANDING_SYMBOLS)
    _stream.subscribe_bars(on_bar, *LANDING_SYMBOLS)

    def _run():
        try:
            _stream.run()
        except Exception as e:
            logger.error(f"Market stream exited: {e}")

    _stream_thread = threading.Thread(target=_run, daemon=True)
    _stream_thread.start()

    # Only install shutdown hooks once the stream is actually running
    _install_shutdown_hooks()

    logger.info(f"Market stream started. Subscribed: {LANDING_SYMBOLS}")