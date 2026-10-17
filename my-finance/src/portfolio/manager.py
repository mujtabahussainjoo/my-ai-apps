"""Synchronise spot account balances without inventing exchange capital."""

from src.core.enums import TradingMode
from src.database.repositories import PortfolioRepository
from src.schemas.portfolio import Position


class PortfolioManager:
    def __init__(self, session, broker):
        self.session = session
        self.broker = broker
        self.repository = PortfolioRepository(session)

    def sync(self):
        client = self.broker._client
        raw = client.fetch_balance()
        mode = self.broker.mode.value
        total, free, used = raw.get("total", {}), raw.get("free", {}), raw.get("used", {})
        # Assets absent from a fresh response have a zero balance, never a stale holding.
        from sqlalchemy import select

        from src.database.models.trading import Balance

        for balance in self.session.scalars(select(Balance).where(Balance.mode == mode)):
            if balance.asset not in total:
                self.repository.set_balance(balance.asset, mode, 0)
        holdings = set()
        for asset, quantity in total.items():
            quantity = float(quantity or 0)
            if quantity < 0:
                raise ValueError("spot account returned a negative balance")
            self.repository.set_balance(
                asset, mode, float(free.get(asset, 0) or 0), float(used.get(asset, 0) or 0)
            )
            if quantity == 0 or asset in ("USD", "USDT", "USDC"):
                continue
            symbol = asset + "/USDT"
            quote = client.fetch_ticker(symbol)
            price = float(quote.get("last") or 0)
            if price <= 0:
                raise ValueError("cannot value an exchange holding")
            holdings.add(symbol)
            position = self.repository.get_position(symbol, mode)
            if position:
                position = position.model_copy(update={"quantity": quantity, "current_price": price})
            else:
                position = Position(
                    symbol=symbol,
                    quantity=quantity,
                    entry_price=price,
                    current_price=price,
                    mode=TradingMode(mode),
                )
            self.repository.upsert_position(position)
        for position in self.repository.get_positions(mode):
            if position.symbol not in holdings:
                self.repository.close_position(position.symbol, mode)
        snapshot = self.repository.build_snapshot(mode)
        self.repository.record_snapshot(snapshot)
        self.session.commit()
        return snapshot
