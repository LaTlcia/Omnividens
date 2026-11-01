"""Exact leading-score probabilities after the specified core captures."""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product


@dataclass(frozen=True)
class CoreWinRate:
    wins: int
    ties: int
    total: int

    @property
    def probability(self) -> float:
        """Strict wins only; a tied score is not a win for either side."""
        return self.wins / self.total


def calculate_core_winrate(a: int, b: int, order: str) -> CoreWinRate:
    """Return the LAST capturing side's chance of finishing ahead.

    A/B refer to the displayed left/right teams. Each capture independently
    transfers floor(victim_points * r / 100), with r uniform over integers
    15..30 (Toolbox Lacrymira's transfer model). AB means A then B, evaluated
    from B's perspective; BA is B then A, evaluated from A's perspective.
    The second capture uses the first capture's resulting scores. Enumerating
    16 or 256 outcomes avoids sampling noise and keeps all point math integral.
    This conditional score comparison excludes damage points and core interest.
    """
    if any(type(value) is not int or value < 0 for value in (a, b)):
        raise ValueError('比分必须是非负整数')
    if order not in ('A', 'B', 'AB', 'BA'):
        raise ValueError('进核顺序必须为A、B、AB或BA')
    wins = ties = total = 0
    for rates in product(range(15, 31), repeat=len(order)):
        left, right = a, b
        for side, rate in zip(order, rates):
            if side == 'A':
                transfer = right * rate // 100
                left, right = left + transfer, right - transfer
            else:
                transfer = left * rate // 100
                left, right = left - transfer, right + transfer
        wins += (left > right) if order[-1] == 'A' else (right > left)
        ties += left == right
        total += 1
    return CoreWinRate(wins, ties, total)
