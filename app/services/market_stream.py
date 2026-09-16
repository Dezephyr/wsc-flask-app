"""
Alpaca real-time market data stream (IEX feed).
One pooled WebSocket serves all frontend users — browsers never see our keys.
"""
import os
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


def init_market_stream(socketio: SocketIO):
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
    logger.info(f"Market stream started. Subscribed: {LANDING_SYMBOLS}")