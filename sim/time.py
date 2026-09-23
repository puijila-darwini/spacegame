"""Time: discrete day-tick stepping over the same core the daemon will drive.

Daemon default: 1 game-day per real minute. Offline progress on load is capped
so a month away doesn't spiral the game; the ledger still shows what happened.
Long advances tick markets day-by-day so production/consumption stay honest.
"""
from __future__ import annotations

from . import contracts, markets, ships
from .state import Game

DAY_PER_SEC = 1.0 / 60.0  # daemon rate: game-days per real second
CATCHUP_CAP_D = 30.0  # offline progress cap, game-days


def advance(game: Game, days: float) -> list:
    """Advance `days` (may be fractional) and settle arrivals.

    Games with markets step day-by-day so the daily prod/cons tick is exact;
    marketless games jump in one go (same result, cheaper). Contract expiry
    sweeps on every advance.
    """
    if not getattr(game, "markets", None):
        game.t += days
        reports = ships.update(game)
        contracts.sweep(game)
        return reports
    reports: list = []
    left = days
    while left > 1e-9:
        step = min(1.0, left)
        game.t += step
        left -= step
        markets.tick(game)
        reports += ships.update(game)
        contracts.sweep(game)
    return reports


def advance_to(game: Game, t: float) -> list:
    if t < game.t:
        raise ValueError("cannot go back in time")
    return advance(game, t - game.t)


def offline_days(saved_wall: float, now: float, rate: float = DAY_PER_SEC) -> float:
    """Game-days owed for wall-clock absence between two timestamps."""
    return max(0.0, (now - saved_wall) * rate)


def catch_up(game: Game, elapsed_days: float, cap_days: float = CATCHUP_CAP_D) -> tuple:
    """Apply capped offline progress. Returns (advanced_days, arrival_reports)."""
    owed = min(max(elapsed_days, 0.0), cap_days)
    reports = advance(game, owed) if owed > 0 else []
    return (owed, reports)
