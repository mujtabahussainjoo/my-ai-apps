"""MCP stdio server; it never exposes live order placement."""

from src.core.config import get_settings
from src.database.session import session_scope
from src.mcp.tools.service import Tools


def create_server(settings=None):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError('Install MCP support with python -m pip install ".[mcp]"') from exc
    settings = settings or get_settings()
    if not settings.mcp_enabled:
        raise ValueError("MCP is disabled")
    server = FastMCP("my-finance")

    @server.tool()
    def get_price(symbol: str) -> dict:
        """Read the latest stored candle close, with its timestamp."""
        with session_scope() as session:
            return Tools(session, settings).get_price(symbol)

    @server.tool()
    def get_ohlcv(symbol: str, timeframe: str = "1h", limit: int = 200) -> list:
        """Read historical candle data in chronological order."""
        with session_scope() as session:
            return Tools(session, settings).get_ohlcv(symbol, timeframe, limit)

    @server.tool()
    def calculate_indicators(symbol: str, timeframe: str = "1h") -> dict:
        """Compute causal technical indicators from stored candles."""
        with session_scope() as session:
            return Tools(session, settings).calculate_indicators(symbol, timeframe)

    @server.tool()
    def get_portfolio() -> dict:
        """Read the configured environment's portfolio."""
        with session_scope() as session:
            return Tools(session, settings).get_portfolio()

    @server.tool()
    def get_open_positions() -> list:
        """Read the configured environment's open positions."""
        with session_scope() as session:
            return Tools(session, settings).get_open_positions()

    @server.tool()
    def get_strategy_metrics(strategy: str) -> dict:
        """Read performance and qualification evidence without promoting a strategy."""
        with session_scope() as session:
            return Tools(session, settings).get_strategy_metrics(strategy)

    @server.tool()
    def calculate_position_size(entry: float, stop_loss: float) -> dict:
        """Estimate capped size; this does not authorise an order."""
        with session_scope() as session:
            return Tools(session, settings).calculate_position_size(entry, stop_loss)

    @server.tool()
    def run_backtest(strategy: str, symbol: str, timeframe: str = "1h", limit: int = 1500) -> dict:
        """Run a bounded backtest on stored history, without changing qualification."""
        with session_scope() as session:
            return Tools(session, settings).run_backtest(strategy, symbol, timeframe, limit)

    @server.tool()
    def get_paper_pnl() -> dict:
        """Read simulated performance."""
        with session_scope() as session:
            return Tools(session, settings).get_paper_pnl()

    if settings.mcp_allow_order_tools and settings.trading_mode == "paper":

        @server.tool()
        def create_paper_order(signal_id: str) -> dict:
            """Process a recorded signal through AI review, hard risk and paper execution."""
            with session_scope() as session:
                return Tools(session, settings).create_paper_order(signal_id)

    return server


def main():
    import sys

    from src.core.logging import configure_logging

    configure_logging()
    # MCP owns stdout; operational logs belong on stderr.
    from contextlib import redirect_stdout

    with redirect_stdout(sys.stderr):
        server = create_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
