"""Build one hovered card's per-enemy estimate from the latest snapshot."""
from __future__ import annotations

from dataclasses import replace
from typing import Callable, Mapping

from lilyrex.domain.attributes import attribute_value
from lilyrex.domain.buff_scaling import effective_attack, effective_defense
from lilyrex.domain.damage import estimate_damage
from lilyrex.domain.damage_trace import damage_trace
from lilyrex.domain.models import (ActiveOrder, BattleSnapshot, DamageCatalog, DamageEstimate,
                                   EstimateSettings, PreviewResult)
from lilyrex.domain.modifiers import calculate_modifiers
from lilyrex.domain.orders import resolve_orders
from lilyrex.domain.passives import estimate_passives
from lilyrex.domain.passive_models import PassivePoolSettings
from lilyrex.domain.skill_conditions import element_condition
from lilyrex.services.passive_pool import PassivePool


class DamagePreviewService:
    def __init__(self, catalog: DamageCatalog,
                 settings_for: Callable[[int], EstimateSettings] | None = None,
                 passive_settings_for: Callable[[int], PassivePoolSettings | None] | None = None) -> None:
        self.catalog = catalog
        self.settings_for = settings_for or (lambda _: EstimateSettings())
        self.snapshot = BattleSnapshot()
        self.passive_pool = PassivePool()
        self.passive_settings_for = passive_settings_for

    def configure_passives(self, callback: Callable[[int], PassivePoolSettings | None]) -> None:
        self.passive_settings_for = callback

    def update_deck(self, user_id: int, deck_id: int | None, cards: Mapping[int, int],
                    expected_size: int | None = None, complete: bool = False) -> None:
        self.passive_pool.update(user_id, deck_id, cards, expected_size, complete)

    def update(self, snapshot: BattleSnapshot) -> None:
        self.snapshot = snapshot

    def preview(self, user_id: int, card_id: int, skill_id: int,
                *, include_calculation: bool = True) -> PreviewResult:
        skill = self.catalog.skill(card_id, skill_id)
        if skill is None:
            reason = "尚未观察到该牌的攻击技能" if not skill_id else "该牌/技能没有可用的伤害参数"
            return PreviewResult(card_id, skill_id, error=reason)
        base = dict(card_id=card_id, skill_id=skill_id, card_name=skill.card_name,
                    attribute=skill.attribute, attack_label="通常伤害" if skill.attack_type == "physical" else "特殊伤害",
                    targets=(skill.min_targets, skill.max_targets))
        actor = self.snapshot.players.get(user_id)
        if actor is None or actor.stats is None:
            return PreviewResult(**base, error="当前快照缺少攻击者基础面板")
        try:
            condition = element_condition(skill, actor.last_attribute)
        except ValueError:
            return PreviewResult(**base, error='技能属性条件参数无效')
        base['targets'] = condition.targets
        notes = [*self.snapshot.warnings]
        settings = self.settings_for(user_id)
        passive_settings = self.passive_settings_for(user_id) if self.passive_settings_for else None
        passive_settings = passive_settings or PassivePoolSettings(mode='manual' if settings.up_bonus else 'observed')
        try:
            deck, coverage = self.passive_pool.select(user_id, actor.deck_id, passive_settings)
        except ValueError:
            return PreviewResult(**base, error='被动池配置无效')
        notes.append(coverage)
        pairs = []
        for card in deck:
            definition = getattr(self.catalog, 'passives', lambda *_: None)(card.card_id, card.skill_id)
            if definition is None:
                notes.append('部分牌的被动分支未知，未计入')
            else:
                pairs.append((card, definition))
        notes.append(f"基础暴率按配置 {settings.crit_rate:.0%}")
        if actor.hp <= 0:
            notes.append("攻击者已倒地：显示面板理论值")
        candidates = [p for p in self.snapshot.players.values()
                      if p.guild_id != actor.guild_id and p.guild_id > 0 and p.party_sequence == 1]
        locked = next((p for p in candidates if p.rank == actor.enemy_target_rank), None)
        if actor.enemy_target_rank:
            if locked is None:
                notes.append("原锁定目标已离开前排")
            elif locked.hp <= 0:
                notes.append("原锁定目标已倒地，列出其他前排")
        else:
            notes.append("自动选敌：以下为各目标单独命中时估计")
        live = sorted((p for p in candidates if p.hp > 0),
                      key=lambda p: (p is not locked, p.rank, p.user_id))
        if not live:
            return PreviewResult(**base, assumptions=tuple(notes), error="当前没有存活敌前排")
        resolved_orders = []
        for pending in self.snapshot.pending_orders:
            effect = self.catalog.order(pending.effect_id)
            if effect and (effect.preparation_override or effect.enemy_duration_override):
                notes.append('累计Order调整下一次准备/持续时间；当前按广播起止时间，不重复乘伤害')
        for active in self.snapshot.orders:
            effect = self.catalog.order(active.effect_id)
            if effect is None:
                notes.append("部分Order缺少参数，未计入")
            else:
                resolved_orders.append((active, effect))
                if active.dual_effect_id and active.dual_status >= 1 and active.dual_user_id >= 1:
                    additional = self.catalog.order(active.dual_effect_id)
                    if additional is not None:
                        resolved_orders.append((ActiveOrder(active.guild_id, additional.effect_id,
                            active.start, active.end, is_dual=True, parent_effect_id=active.effect_id), additional))
        estimates: list[DamageEstimate] = []
        calculation: list[str] = [
            '当前状态下次使用的预估；不是刚才该次攻击的实伤复算。',
            *condition.notes,
        ] if include_calculation else []
        for target in live:
            if target.stats is None:
                notes.append(f"#{target.rank}缺少防御面板，未估计")
                continue
            try:
                attack = effective_attack(actor.stats, actor.buffs, skill.attack_type, skill.attribute)
                defense = effective_defense(target.stats, target.buffs, skill.attack_type, skill.attribute)
                effective_settings = settings
                if passive_settings.mode != 'manual':
                    theme = attribute_value(settings.theme, skill.attribute, positive=True)
                    order = resolve_orders(skill, actor, target, self.snapshot, tuple(resolved_orders), theme)
                    passive = estimate_passives(skill, tuple(pairs), passive_settings,
                                                order.passive_rate_up, order.passive_rate_down)
                    effective_settings = replace(settings, up_bonus=passive.up,
                                                 crit_rate=min(1.0, settings.crit_rate + passive.crit))
                    notes.extend(passive.notes)
                    notes.append('随机范围固定被动期望乘区')
                factors = calculate_modifiers(skill, actor, target, self.snapshot, tuple(resolved_orders), effective_settings)
                damage = estimate_damage(attack, defense, factors.multiplier, factors.crit_rate,
                                         factors.received_multiplier)
            except ValueError:
                return PreviewResult(**base, assumptions=tuple(dict.fromkeys(notes)), error="面板或乘区参数无效")
            notes.extend(factors.notes)
            estimates.append(DamageEstimate(target.user_id, target.rank, target.name, damage.expected,
                                             damage.minimum, damage.maximum, attack, defense, target is locked))
            if include_calculation:
                calculation.extend(damage_trace(skill, actor, target, attack, defense, factors, damage))
        def priority(note: str) -> int:
            # The compact tooltip truncates its notes: keep the current card's
            # attribute and time-dependent growth visible before longer details.
            if '属性主题×' in note:
                return -2
            if note.startswith('蓄力第') or '蓄力按最低档' in note:
                return -1
            if '：EH ' in note or '：SD ' in note or '：MN ' in note:
                return -1
            if '追加状态' in note or '不匹配' in note:
                return 0
            if '被动池' in note and 'UP' not in note:
                return 1
            if note.startswith('Order'):
                return 2
            if 'UP期望' in note:
                return 3
            if '未计入' in note or '未知' in note:
                return 4
            return 5
        ordered_notes = tuple(sorted(dict.fromkeys(notes), key=priority))
        if include_calculation:
            calculation.extend((
                'A/D含层数估计；各系数为实际代入值。显示至6位小数，内部使用binary64。',
                '0.95 = 伤害随机系数期望；100.5 = RandInt(1,200)期望。'
                'E忽略最后一次向下取整，单此项误差小于1点。',
                '随机上下界固定UP期望，未覆盖所有被动发动组合。',
                '计算依据与未计入项', *ordered_notes,
            ))
        return PreviewResult(**base, estimates=tuple(estimates), assumptions=ordered_notes,
                             error=None if estimates else "敌前排缺少可用防御面板",
                             calculation=tuple(calculation))
