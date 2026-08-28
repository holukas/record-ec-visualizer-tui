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

#: The finish line, ppm*s, and the length of a derby in one number. Around
#: four or five hard breaths at an inlet a player can get their mouth close
#: to, which is a few minutes for two lanes. It is a fixed figure rather than
#: one taken from the first breath, so every session is the same length and
#: the number can be printed on a sign; the cost is that a mast holding the
#: head well out of reach scores less per breath and makes a longer derby, and
#: ``--derby-goal`` is the answer there.
DEFAULT_GOAL = 20_000.0

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
    #: Which of this lane's own breaths carried it over the line, counting
    #: from 1, or ``None`` while it is still running.
    crossed_on: int | None = None
    #: Finishing position, recomputed by :meth:`EddyDerby._rank` whenever the
    #: order can have changed, so it is not final until the derby is over.
    place: int | None = None

    @property
    def finished(self) -> bool:
        return self.crossed_on is not None


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
    #: Finish line in ppm*s. Set from the start, so the track has a scale
    #: before anybody has blown into it and the first lane moves on the first
    #: breath like every other one.
    goal: float = DEFAULT_GOAL
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

        The goal goes back to whatever was configured, in case something has
        moved it since.
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
        """Everyone across the line, best first. See :meth:`_rank`."""
        return list(self._finished)

    def distance_of(self, racer: Racer) -> float:
        """Committed score plus, for whoever is blowing, the breath in progress."""
        puff = self.detector.active
        if puff is not None and racer is self.at_the_inlet:
            return racer.distance + puff.score
        return racer.distance

    def fraction_of(self, racer: Racer) -> float:
        """How far along the track this lane is, 0 to 1."""
        if not self.goal:
            return 0.0
        return min(1.0, self.distance_of(racer) / self.goal)

    def feed(self, elapsed: float, value: float | None) -> None:
        """Take one CO2 sample: run the detector, then move the lanes."""
        self.detector.feed(elapsed, value)

        racer = self.active
        if racer is not None and self.goal and self.distance_of(racer) >= self.goal:
            # Crossing is judged live, so the animal stops at the line during
            # the breath that got it there rather than a second later when that
            # breath is finally scored. That breath is not counted yet, which
            # is why the number it crossed on is one past the tally.
            self._finish(racer, racer.breaths + 1)

        for puff in self.detector.pop_completed():
            self._commit(puff)

    def _commit(self, puff: Puff) -> None:
        racer = self.racers[self.turn] if self.turn < len(self.racers) else None
        if racer is None:  # pragma: no cover - defensive
            return
        if racer.finished and racer.breaths >= racer.crossed_on:
            # Everybody is across, so the turn had nowhere to pass to and is
            # parked on the last finisher, whose lane would otherwise collect
            # whatever anyone blows at the inlet afterwards. Their own crossing
            # breath is not this one: it is scored the call after the line was
            # judged live, while the tally is still one short of it.
            return
        racer.distance += puff.score
        racer.breaths += 1
        racer.best_breath = max(racer.best_breath, puff.score)
        racer.peak = max(racer.peak, puff.peak)

        if not racer.finished and racer.distance >= self.goal:
            self._finish(racer, racer.breaths)
        else:
            # A lane that crossed mid-breath is across the line already, but
            # the breath that took it there has only now been scored, and the
            # total it adds is what a tie is settled on.
            self._rank()
        self._next_turn()

    def _finish(self, racer: Racer, crossed_on: int) -> None:
        racer.crossed_on = crossed_on
        self._finished.append(racer)
        self._rank()

    def _rank(self) -> None:
        """Order the finishers: fewest breaths first, then the higher total.

        Crossing order alone would hand first place to whoever blows earliest
        in the round, which is a property of the lane they were given rather
        than of how hard they blew: with two players P1 always goes first, so
        P1 took every derby that ended in a shared round. Players who need the
        same number of breaths are level on that count, and the score they
        did it with separates them.

        A lane can therefore be shown a place and then lose it, up until the
        last player of the round has been scored. That is the tie being
        settled, and it is why :attr:`Racer.place` is recomputed rather than
        handed out once at the line.
        """
        self._finished.sort(key=lambda racer: (racer.crossed_on, -racer.distance))
        for position, racer in enumerate(self._finished, start=1):
            racer.place = position

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
