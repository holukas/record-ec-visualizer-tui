"""The Eddy Derby: a game played through the gas analyzer's own inlet.

Breathe at an open-path analyzer and the CO2 reading jumps from a few hundred
umol mol-1 to thousands, in a fraction of a second. That is a game waiting to
happen, and at an open day it is the shortest route from "this box measures
air" to "I can move that with my lungs". Everything here is state derived from
values that already arrive: it reads the stream and never touches it.

**The score is the area under the peak**, ``sum (c - threshold) dt`` over the
samples above the threshold, in ppm*s. The obvious score is the peak value,
and it does not work: an open-path head measures over a range ending around
3000 umol mol-1, exhaled breath is more than ten times that, and anyone who
gets close to the inlet pins the reading. Peaks would tie at the top of the
scale and the winner would be whoever leaned in furthest. An integral keeps
discriminating after the sensor saturates, because what is left to vary is how
long the breath holds it there -- which is the thing worth measuring anyway. It
is also the same operation the flux processing performs, over one breath
instead of half an hour, which is the sentence this whole feature exists to
earn.

The excess is measured **above the threshold rather than above ambient**, so
the score is continuous where a breath begins: a blow that barely crosses the
line scores nearly nothing rather than jumping straight to several hundred
ppm*s. It also makes the game independent of the background, which is not
constant -- it drifts by more than a hundred umol mol-1 between a windy
afternoon and a still night inside a canopy, and a score measured against
ambient would quietly hand out points for the time of day.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

#: What a sample has to exceed to count towards a score, umol mol-1. Ambient
#: air is 400-450 and a canopy at night can reach 600, so this sits far enough
#: above anything the atmosphere does to be unambiguously somebody's lungs.
THRESHOLD_PPM = 1000.0

#: Where a breath is judged to be over, as a fraction of the threshold. Below
#: it, not at it: the signal is noisy on the falling flank and a single
#: boundary would chop one blow into a handful of puffs, passing the turn
#: several times over. A fraction rather than a second figure in umol mol-1,
#: so that a site which raises the threshold keeps its hysteresis.
RELEASE_FRACTION = 0.7

#: How long the reading has to stay below the release level before the breath
#: is closed. Slack in the same direction as the hysteresis, for the case where
#: someone snatches a quick second breath mid-blow.
RELEASE_HOLD_S = 0.5

#: The longest a single breath may score for. Nobody exhales for ten seconds;
#: what does is a bag or a hand cupped over the head, and this is what stops
#: that from being an unbeatable move.
MAX_PUFF_SECONDS = 10.0

#: A breath scoring less than this is discarded rather than counted. Without
#: it a single sample nicking the threshold would end somebody's turn.
MIN_PUFF_SCORE = 100.0

#: The longest sample-to-sample step that is integrated across. The analyzer
#: stream drops out, and a gap must not be scored as if the last value had
#: held throughout it.
MAX_SAMPLE_GAP_S = 0.5

#: Breaths the finish line is set to when it is calibrated from the first one.
GOAL_BREATHS = 5

#: The shortest derby an auto-calibrated goal may set, ppm*s. A first breath
#: that barely registered would otherwise put the finish line within reach of
#: a cough.
MIN_GOAL = 500.0

#: One-line ASCII racers. ASCII on purpose: the logging host's display is a
#: Linux virtual console with a 256- or 512-glyph font, the same limitation
#: that makes braille plots unreadable there, so anything pictorial would
#: arrive as a row of replacement boxes on the one screen this is meant for.
ANIMALS: tuple[tuple[str, str], ...] = (
    ("snail", "@_/"),
    ("fish", "><>"),
    ("cat", "=^.^="),
    ("crab", "V(oo)V"),
    ("worm", "~~~o"),
    ("bird", "-<v>-"),
)

#: Lane colours, from the 16 ANSI colours for the reason the ``classic``
#: palette leads the plot palettes: they are the set that survives a terminal
#: that has only those.
LANE_COLORS: tuple[str, ...] = (
    "bright_cyan",
    "bright_magenta",
    "bright_yellow",
    "bright_green",
    "bright_blue",
    "bright_red",
)

MAX_PLAYERS = len(ANIMALS)


@dataclass
class Puff:
    """One breath, from the first sample above the threshold to the last."""

    started: float
    peak: float
    #: ppm*s above the threshold so far. Accumulates while the breath is open.
    score: float = 0.0
    #: When the last sample of this breath arrived, so a breath in progress can
    #: still report how long it has been going.
    last: float = 0.0
    ended: float | None = None

    @property
    def duration(self) -> float:
        return max(0.0, (self.ended if self.ended is not None else self.last) - self.started)

    @property
    def is_open(self) -> bool:
        return self.ended is None


class PuffDetector:
    """Turns a stream of CO2 samples into breaths and their scores.

    Fed one value per analyzer record -- 20 Hz at a typical site -- rather than
    once per frame, because the score is an integral and sampling it at the
    display rate would throw most of it away.
    """

    def __init__(
        self,
        threshold: float = THRESHOLD_PPM,
        release: float | None = None,
        release_hold: float = RELEASE_HOLD_S,
        max_seconds: float = MAX_PUFF_SECONDS,
        max_gap: float = MAX_SAMPLE_GAP_S,
        min_score: float = MIN_PUFF_SCORE,
    ) -> None:
        self.threshold = threshold
        self.release = threshold * RELEASE_FRACTION if release is None else min(release, threshold)
        self._release_hold = release_hold
        self._max_seconds = max_seconds
        self._max_gap = max_gap
        self._min_score = min_score
        self._active: Puff | None = None
        self._completed: list[Puff] = []
        self._last_seen: float | None = None
        self._below_since: float | None = None
        self._ambient = math.nan

    @property
    def active(self) -> Puff | None:
        """The breath in progress, or ``None``."""
        return self._active

    @property
    def ambient(self) -> float:
        """A slow average of the quiet air between breaths, umol mol-1.

        For display only -- the score deliberately does not depend on it. An
        exponential average rather than a median over a window, because it is
        updated on every record of a 20 Hz stream and re-sorting a minute of
        those on each one would cost more than the game is worth.
        """
        return self._ambient

    def feed(self, elapsed: float, value: float | None) -> None:
        """Take one CO2 sample, at ``elapsed`` seconds on the app's clock."""
        previous, self._last_seen = self._last_seen, elapsed

        if value is None or math.isnan(value):
            # A dropout. Nothing is integrated across the hole, and the next
            # real sample must not integrate across it either, so the step
            # clock restarts. A breath left open when the stream died still
            # times out rather than staying open forever.
            self._last_seen = None
            self._expire(elapsed)
            return

        step = 0.0 if previous is None else elapsed - previous
        if step <= 0.0 or step > self._max_gap:
            step = 0.0

        if value > self.threshold:
            puff = self._active
            if puff is None:
                puff = self._active = Puff(started=elapsed, peak=value, last=elapsed)
            puff.score += (value - self.threshold) * step
            puff.peak = max(puff.peak, value)
            puff.last = elapsed
            self._below_since = None
        elif self._active is not None:
            self._active.last = elapsed
            if value > self.release:
                # On the way down, but not clear of the breath yet.
                self._below_since = None
            elif self._below_since is None:
                self._below_since = elapsed
            elif elapsed - self._below_since >= self._release_hold:
                self._close(elapsed)
        elif value <= self.release:
            self._ambient = (
                value if math.isnan(self._ambient) else self._ambient + 0.05 * (value - self._ambient)
            )

        self._expire(elapsed)

    def _expire(self, elapsed: float) -> None:
        puff = self._active
        if puff is not None and elapsed - puff.started >= self._max_seconds:
            self._close(elapsed)

    def _close(self, elapsed: float) -> None:
        puff = self._active
        self._active = None
        self._below_since = None
        if puff is None:  # pragma: no cover - guarded by the callers
            return
        puff.ended = elapsed
        if puff.score >= self._min_score:
            self._completed.append(puff)

    def pop_completed(self) -> list[Puff]:
        """Breaths finished since the last call, and forget them."""
        finished, self._completed = self._completed, []
        return finished

    def reset(self) -> None:
        self._active = None
        self._completed = []
        self._last_seen = None
        self._below_since = None


@dataclass
class Racer:
    """One player's lane."""

    name: str
    animal: str
    color: str
    #: Committed score, ppm*s. A breath in progress is not in here; ask
    #: :meth:`EddyDerby.distance_of` for the figure that includes it.
    distance: float = 0.0
    breaths: int = 0
    best_breath: float = 0.0
    peak: float = 0.0
    #: Finishing position, once across the line.
    place: int | None = None

    @property
    def finished(self) -> bool:
        return self.place is not None


def _goal_from_first_breath(score: float) -> float:
    """The finish line a first breath of ``score`` ppm*s calibrates."""
    return max(MIN_GOAL, score * GOAL_BREATHS)


@dataclass
class EddyDerby:
    """Racers, turns and a finish line, driven by :class:`PuffDetector`.

    Turn-based, because there is one inlet: the players queue at it, one blows,
    that lane moves, and the turn passes when the breath ends. The alternative
    -- every lane live at once -- cannot work with a single sensor, since
    nothing in the stream says whose lungs a peak came from.

    The lane advances **while the breath is happening**, not when it ends. That
    is the whole feel of the thing, and the 20 Hz analyzer stream is what makes
    it possible: the animal runs for as long as you can keep the reading up.
    """

    players: int = 2
    #: Finish line in ppm*s, or ``None`` to take it from the first breath. No
    #: constant is right everywhere -- the score depends on how far the mouth
    #: is from the head, which is a property of the site's mast rather than of
    #: the player -- so by default the first breath of the session sets the
    #: pace and everyone races against that.
    goal: float | None = None
    detector: PuffDetector = field(default_factory=PuffDetector)

    def __post_init__(self) -> None:
        self.racers: list[Racer] = []
        for _ in range(max(1, min(self.players, MAX_PLAYERS))):
            self.add_player()
        self.turn = 0
        self._finished: list[Racer] = []
        self._configured_goal = self.goal

    def add_player(self) -> bool:
        if len(self.racers) >= MAX_PLAYERS:
            return False
        index = len(self.racers)
        animal_name, animal = ANIMALS[index]
        self.racers.append(
            Racer(
                name=f"P{index + 1} {animal_name}",
                animal=animal,
                color=LANE_COLORS[index % len(LANE_COLORS)],
            )
        )
        return True

    def remove_player(self) -> bool:
        if len(self.racers) <= 1:
            return False
        dropped = self.racers.pop()
        if dropped in self._finished:
            self._finished.remove(dropped)
        self.turn = min(self.turn, len(self.racers) - 1)
        return True

    def reset(self) -> None:
        """Start again with the same lanes, and re-open the finish line.

        The goal goes back to whatever was configured, which for the default is
        nothing: a fresh derby calibrates itself from its own first breath
        rather than inheriting the pace of the last one.
        """
        for index, racer in enumerate(self.racers):
            self.racers[index] = Racer(name=racer.name, animal=racer.animal, color=racer.color)
        self.turn = 0
        self._finished = []
        self.goal = self._configured_goal
        self.detector.reset()

    @property
    def active(self) -> Racer | None:
        """Whose turn it is, or ``None`` once everybody has finished."""
        if self.turn < len(self.racers) and not self.racers[self.turn].finished:
            return self.racers[self.turn]
        return None

    @property
    def at_the_inlet(self) -> Racer | None:
        """Whose lane a breath arriving now belongs to.

        Not the same as :attr:`active`, which is empty once a lane has
        finished. A racer crosses the line in the middle of a breath, and until
        that breath ends it is still their breath: attributing it by ``active``
        left the winning animal snapping back to the start line for the second
        or two between crossing and being scored.
        """
        return self.racers[self.turn] if self.turn < len(self.racers) else None

    @property
    def over(self) -> bool:
        return all(racer.finished for racer in self.racers)

    @property
    def standings(self) -> list[Racer]:
        """Everyone across the line, in the order they crossed."""
        return list(self._finished)

    def distance_of(self, racer: Racer) -> float:
        """Committed score plus, for whoever is blowing, the breath in progress."""
        puff = self.detector.active
        if puff is not None and racer is self.at_the_inlet:
            return racer.distance + puff.score
        return racer.distance

    @property
    def effective_goal(self) -> float | None:
        """The finish line to draw the lanes against, or ``None`` before there is one.

        Provisional while the first breath of the session is still going, since
        the committed goal does not exist until that breath is scored. Dividing
        by nothing pinned that one lane to the start line until the player
        stopped blowing, which is exactly the rule this class opens by stating
        that it does not do: every other breath moves its animal live.

        The provisional figure is what :meth:`_commit` will calculate from the
        same breath, so the animal is in the same place the moment before it is
        scored as the moment after. It follows that a first breath runs a fifth
        of the track and then holds there however long it lasts, which is not a
        stall but what calibrating the finish line from it means.
        """
        if self.goal:
            return self.goal
        puff = self.detector.active
        return None if puff is None else _goal_from_first_breath(puff.score)

    def fraction_of(self, racer: Racer) -> float:
        """How far along the track this lane is, 0 to 1."""
        goal = self.effective_goal
        if not goal:
            return 0.0
        return min(1.0, self.distance_of(racer) / goal)

    def feed(self, elapsed: float, value: float | None) -> None:
        """Take one CO2 sample: run the detector, then move the lanes."""
        self.detector.feed(elapsed, value)

        racer = self.active
        if racer is not None and self.goal and self.distance_of(racer) >= self.goal:
            # Crossing is judged live, so the animal stops at the line during
            # the breath that got it there rather than a second later when that
            # breath is finally scored.
            self._finish(racer)

        for puff in self.detector.pop_completed():
            self._commit(puff)

    def _commit(self, puff: Puff) -> None:
        racer = self.racers[self.turn] if self.turn < len(self.racers) else None
        if racer is None:  # pragma: no cover - defensive
            return
        racer.distance += puff.score
        racer.breaths += 1
        racer.best_breath = max(racer.best_breath, puff.score)
        racer.peak = max(racer.peak, puff.peak)

        if self.goal is None:
            self.goal = _goal_from_first_breath(puff.score)
        if not racer.finished and racer.distance >= self.goal:
            self._finish(racer)
        self._next_turn()

    def _finish(self, racer: Racer) -> None:
        racer.place = len(self._finished) + 1
        self._finished.append(racer)

    def _next_turn(self) -> None:
        """Pass to the next lane still in the derby, if there is one."""
        for step in range(1, len(self.racers) + 1):
            candidate = (self.turn + step) % len(self.racers)
            if not self.racers[candidate].finished:
                self.turn = candidate
                return

    def skip_turn(self) -> None:
        """Hand the turn on without a breath, for a player who steps away."""
        self._next_turn()
