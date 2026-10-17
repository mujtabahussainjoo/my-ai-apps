"""Exposure accounting.

Tracks total, per-symbol, and correlated exposure. Correlation matters because
five BTC-long positions are one position with extra steps, and a limit that
counts them as five understates real risk by the full correlation.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.schemas.portfolio import Position


@dataclass(slots=True)
class ExposureReport:
    total_usd: float
    exposure_pct: float
    by_symbol: dict[str, float]
    open_positions: int
    correlated_usd: float
    effective_positions: float

    @property
    def largest_symbol_usd(self) -> float:
        return max(self.by_symbol.values(), default=0.0)


class ExposureTracker:
    """Computes exposure from a set of positions."""

    def __init__(
        self,
        *,
        max_total_exposure_pct: float,
        max_open_positions: int,
        per_symbol_cap_pct: float | None = None,
        correlation_threshold: float = 0.8,
    ) -> None:
        self.max_total_exposure_pct = max_total_exposure_pct
        self.max_open_positions = max_open_positions
        self.per_symbol_cap_pct = per_symbol_cap_pct or max_total_exposure_pct / 2
        self.correlation_threshold = correlation_threshold

    def compute(
        self,
        positions: list[Position],
        equity_usd: float,
        correlations: dict[str, float] | None = None,
    ) -> ExposureReport:
        by_symbol: dict[str, float] = {}
        for position in positions:
            price = position.current_price or position.entry_price
            by_symbol[position.symbol] = by_symbol.get(position.symbol, 0.0) + (position.quantity * price)

        total = sum(by_symbol.values())
        correlations = correlations or {}

        # Cluster symbols that are highly correlated with the largest holding.
        correlated_usd = 0.0
        effective = float(len(by_symbol))
        if by_symbol:
            dominant = max(by_symbol, key=lambda k: by_symbol[k])
            for symbol, value in by_symbol.items():
                if symbol == dominant:
                    continue
                rho = abs(correlations.get(f"{dominant}:{symbol}", correlations.get(symbol, 0.0)))
                if rho >= self.correlation_threshold:
                    correlated_usd += value
                    # A correlated position adds no independent diversification.
                    effective += max(0.0, value / max(by_symbol[dominant], 1e-9) - 1.0)

        return ExposureReport(
            total_usd=total,
            exposure_pct=(total / equity_usd * 100) if equity_usd > 0 else 0.0,
            by_symbol=by_symbol,
            open_positions=len(positions),
            correlated_usd=correlated_usd,
            effective_positions=effective,
        )

    def remaining_capacity_usd(self, equity_usd: float, positions: list[Position]) -> float:
        report = self.compute(positions, equity_usd)
        limit_usd = equity_usd * self.max_total_exposure_pct / 100
        return max(0.0, limit_usd - report.total_usd)

    def check(
        self,
        *,
        symbol: str,
        additional_notional_usd: float,
        positions: list[Position],
        equity_usd: float,
        correlations: dict[str, float] | None = None,
    ) -> tuple[bool, str]:
        """Would adding this notional breach the exposure limits?"""
        report = self.compute(positions, equity_usd, correlations)
        limit_usd = equity_usd * self.max_total_exposure_pct / 100

        if report.open_positions >= self.max_open_positions:
            return False, (f"max open positions reached: {report.open_positions}/{self.max_open_positions}")

        new_total = report.total_usd + additional_notional_usd
        if new_total > limit_usd:
            return False, (
                f"total exposure would be {new_total / equity_usd * 100:.2f}% of equity, "
                f"limit {self.max_total_exposure_pct}% "
                f"(${new_total:,.0f} > ${limit_usd:,.0f})"
            )

        new_symbol_total = report.by_symbol.get(symbol, 0.0) + additional_notional_usd
        symbol_limit_usd = equity_usd * self.per_symbol_cap_pct / 100
        if new_symbol_total > symbol_limit_usd:
            return False, (
                f"per-symbol exposure for {symbol} would be "
                f"{new_symbol_total / equity_usd * 100:.2f}%, "
                f"limit {self.per_symbol_cap_pct}%"
            )

        return True, ""
