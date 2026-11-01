"""Immutable values indexed by the five card attributes."""
from __future__ import annotations
from dataclasses import dataclass
import math

ATTRIBUTE_NAMES = ('fire', 'water', 'wind', 'light', 'dark')


@dataclass(frozen=True)
class AttributeValues:
    fire: float
    water: float
    wind: float
    light: float
    dark: float

    def __post_init__(self) -> None:
        for name in ATTRIBUTE_NAMES:
            _number(getattr(self, name))

    @classmethod
    def filled(cls, value: float) -> AttributeValues:
        return cls(value, value, value, value, value)

    def for_attribute(self, attribute: int) -> float:
        if type(attribute) is not int or attribute not in range(1, 6):
            raise ValueError('属性必须为1至5')
        return getattr(self, ATTRIBUTE_NAMES[attribute - 1])


def _number(value: float, *, positive: bool = False) -> float:
    try:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError
        result = float(value)
        if not math.isfinite(result) or result < 0 or (positive and result == 0):
            raise ValueError
    except (ValueError, OverflowError):
        raise ValueError('属性加成必须为有限正数' if positive else '属性加成必须为有限非负数') from None
    return result


def attribute_value(value: AttributeValues | float, attribute: int, *, positive: bool = False) -> float:
    """Resolve only the action's attribute; legacy scalars apply to all five."""
    if type(attribute) is not int or attribute not in range(1, 6):
        raise ValueError('属性必须为1至5')
    selected = value.for_attribute(attribute) if isinstance(value, AttributeValues) else value
    return _number(selected, positive=positive)
