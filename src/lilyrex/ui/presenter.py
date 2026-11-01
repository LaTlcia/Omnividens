"""Translate session state into an explicit, copied UI contract."""
from __future__ import annotations
from typing import Any, Mapping
from .view_models import BattleView, PlayerView


def _pick(value: Mapping[str, Any], fields: tuple[str, ...]) -> dict:
    return {key: value[key] for key in fields if key in value}


class BattlePresenter:
    def __init__(self, session, watcher_user_id: int = 0):
        self.session = session
        self.watcher_user_id = watcher_user_id

    def view(self) -> BattleView | None:
        history = self.session.latest_history
        if not history:
            return None
        players: list[PlayerView] = []
        for user in history.get("gvgUserData", ()):
            if user.get("userId") == self.watcher_user_id:
                continue
            row = {key: user[key] for key in PlayerView.__annotations__ if key in user}
            for key in ("userId", "guildDataId", "memberRank", "characterJobMstId", "hp", "sp"):
                row.setdefault(key, 0)
            row.setdefault("name", f"#{row['memberRank']}")
            row.setdefault("partySequence", 0)
            for key in ("attributeAttackEffectLevel", "attributeDefenseEffectLevel"):
                row[key] = [_pick(x, ("attribute", "effectLevel")) for x in row.get(key, ())]
            players.append(row)
        guilds = tuple({"guildDataId": int(g.get("guildDataId", 0)), "point": int(g.get("point", 0))}
                       for g in history.get("guildData", ()))
        stacks = {"buff": [_pick(x, ("userId", "stackType", "stackNum"))
                            for x in history.get("gvgStackSkillData", {}).get("buff", ())]}
        orders = tuple(_pick(x, ("tacticsMstId", "guildDataId", "startTime", "endTime",
                                "dualTacticsEffectMstId", "dualTacticsStatus"))
                       for x in history.get("gvgTacticsData", ()))
        pending = tuple(_pick(x, ("guildDataId", "effectNum"))
                        for x in history.get("gvgStackTacticsData", ()))
        ball = history.get("neunWelt") or {}
        ball_view = {"startTime": ball.get("startTime", 0),
                     "cardTypeList": [_pick(x, ("cardType",)) for x in ball.get("cardTypeList", ())]}
        return BattleView(guilds, tuple(players), stacks, orders, pending, ball_view,
                          self.session.snapshot.elapsed_seconds, self.session.snapshot.timestamp,
                          self.session.revision,
                          getattr(self.session, "display_elapsed_seconds", None))
