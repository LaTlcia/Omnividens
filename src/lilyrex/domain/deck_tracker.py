"""Deck knowledge and cycle tracking; no I/O."""
from __future__ import annotations
from collections import defaultdict

DECK_MAX = 25

class DeckTracker:
    """Which memoria of each player's deck were used in the current cycle.

    A deck holds ≤DECK_MAX distinct memoria and each is used once per cycle — played
    (skill_exec) or fed into NeunWelt (neun_welt_charge); once all are used the deck
    refreshes. gvg_change_deck refreshes too. Card lists are kept per deckDataId, so
    switching back to a deck shows the cards already known for it.

    Joining mid-battle, a player's first cycle has an unknown start (cards used before we
    connected are invisible). Every later cycle is exactly `size` uses of distinct cards, so the
    uses seen since joining pin down where cycles break; once only one split fits, tracking is
    exact again (_use_unsynced). Deck sizes are only inferred from cycles seen from their start.
    """

    def __init__(self):
        self.deck_id = {}                  # uid -> current deckDataId (None right after a change)
        self.cards = {}                    # (uid, deckDataId) -> {cardMstId: last skillMstId}, first-seen order
        self.size = {}                     # (uid, deckDataId) -> deck size once a full cycle was seen
        self.used = defaultdict(set)       # uid -> cards used this cycle
        self.cycle = defaultdict(lambda: 1)
        self.last = {}                     # uid -> most recently used cardMstId
        self.clean = {}                    # uid -> the current cycle's start was observed
        self.exact = {}                    # uid -> cycle numbers count from the deck's first cycle
        self.fresh = False                 # joined before the battle: everyone's first cycle is clean
        self.seq = defaultdict(list)       # uid -> uses since joining, while the cycle phase is unknown

    def _key(self, uid):
        return uid, self.deck_id.get(uid)

    def set_deck(self, uid, deck_id):
        """From schedule_info each frame; adopts cards seen while the id was unknown."""
        if deck_id is None or self.deck_id.get(uid) == deck_id:
            return False
        had_id = uid in self.deck_id
        self.deck_id[uid] = deck_id
        pending = self.cards.pop((uid, None), None)
        if pending:
            self.cards.setdefault((uid, deck_id), {}).update(pending)
        return had_id or bool(pending)

    def change_deck(self, uid):
        self.used[uid].clear()
        self.cycle[uid] = 1
        self.clean[uid] = self.exact[uid] = True
        self.seq.pop(uid, None)
        self.last.pop(uid, None)
        self.deck_id[uid] = None           # the next frame carries the new deckDataId

    def use(self, uid, card, skill):
        key = self._key(uid)
        cards = self.cards.setdefault(key, {})
        if skill or card not in cards:
            cards[card] = skill or cards.get(card, 0)
        self.last[uid] = card
        self.exact.setdefault(uid, self.fresh)
        if not self.clean.get(uid, self.fresh):
            self._use_unsynced(uid, key, card)
            return
        used = self.used[uid]
        if card in used:                   # used twice -> the deck refreshed: a whole cycle was seen,
            self.size.setdefault(key, len(used))      # so this deck has fewer than DECK_MAX cards
            used.clear()
            self.cycle[uid] += 1
        used.add(card)
        size = self.size.get(key) or (DECK_MAX if len(cards) >= DECK_MAX else None)
        if size and len(used) >= size:     # whole deck used -> refreshed right away
            used.clear()
            self.cycle[uid] += 1

    def _use_unsynced(self, uid, key, card):
        """Joined mid-cycle: seq = b uses finishing the unseen cycle, then blocks of `size` distinct
        cards. Keep the splits b that fit; when one is left, the current cycle is known."""
        seq, used = self.seq[uid], self.used[uid]
        seq.append(card)
        if card in used:                   # best guess for display meanwhile
            used.clear()
        used.add(card)
        size = self.size.get(key) or DECK_MAX

        def fits(b):
            return len(set(seq[:b])) == b and all(
                len(set(seq[i:i + size])) == len(seq[i:i + size]) for i in range(b, len(seq), size))

        splits = [b for b in range(min(size - 1, len(seq)) + 1) if fits(b)]
        if len(splits) == 1:
            b = splits[0]
            start = b + (len(seq) - b) // size * size
            used.clear()
            used.update(seq[start:])
            self.clean[uid] = True
            del self.seq[uid]
        elif not splits:                   # doesn't fit (deck not DECK_MAX?): start over from here
            seq[:] = [card]

    def view(self, uid):
        """(cards {card: skill}, used set, deck size or None, cycle or None if unknown, last card,
        whether this cycle's start was seen)"""
        key = self._key(uid)
        cycle = self.cycle[uid] if self.exact.get(uid, self.fresh) else None
        return (self.cards.get(key, {}), self.used[uid], self.size.get(key), cycle, self.last.get(uid),
                self.clean.get(uid, self.fresh))
