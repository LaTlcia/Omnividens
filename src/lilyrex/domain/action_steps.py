"""Pure classification of ordered battle actions for viewing navigation."""
from __future__ import annotations
from dataclasses import dataclass
from .events import BattleEvent

_PREFIX = 'response:gvg_'
_ACTION_LABELS = {
    'skill_exec_player': '出牌/技能',
    'rare_skill_exec_player': '稀有技能',
    'tactics_prepare': 'Order准备',
    'change_deck': '更换卡组',
    'change_member': '队员换位',
    'attack_siege': '攻城',
    'buffer_siege_player': '攻城支援',
    'recovery_player': '回复',
    'neun_welt_charge': '球蓄力',
    'neun_welt_pass': '球传递',
    'neun_welt_invoke': '球发动',
}
_STATE_EVENTS = frozenset(('system_schedule_info', 'set_target_member_rank',
                           'change_is_sp_recovery_mode', 'out_time'))


@dataclass(frozen=True)
class ActionMarker:
    ordinal: int
    label: str


def action_label(event: BattleEvent) -> str | None:
    """Keep a complete broadcast atomic, including all of its influence rows.

    Only explicit synchronization events are excluded inside the GVG namespace;
    future battle events remain visible as individual steps until classified.
    """
    if not event.name.startswith(_PREFIX):
        return None
    suffix = event.name[len(_PREFIX):]
    if suffix in _STATE_EVENTS:
        return None
    return _ACTION_LABELS.get(suffix, '其他战斗动作')
