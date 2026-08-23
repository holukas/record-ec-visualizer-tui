"""The breath race, from a single sample to a finished race.

The scoring rules are what these assert on, because every one of them is a
choice that a plausible-looking alternative would quietly break: an integral
rather than a peak, a hysteresis rather than one threshold, and nothing counted
across a dropout.
"""
import math

import pytest

from record_ec_visualizer_tui.game import (
    GOAL_BREATHS,
    MAX_PLAYERS,
    MAX_PUFF_SECONDS,
    MIN_PUFF_SCORE,
    THRESHOLD_PPM,
    BreathRace,
    PuffDetector,
)


def _blow(detector, start=0.0, level=2000.0, seconds=2.0, rate=20.0, ambient=420.0, tail=1.0):
    """Feed a square breath at ``level`` followed by a return to ``ambient``."""
    step = 1.0 / rate
    elapsed = start
    # One quiet sample first, as a running stream always has: the score is an
    # integral over the steps between samples, so a breath that begins on the
    # very first record the detector ever sees is one step short.
    detector.feed(elapsed, ambient)
    elapsed += step
    samples = int(seconds * rate)
    for _ in range(samples):
        detector.feed(elapsed, level)
        elapsed += step
    for _ in range(int(tail * rate)):
        detector.feed(elapsed, ambient)
        elapsed += step
    return elapsed


class TestPuffDetector:
    def test_quiet_air_is_never_a_breath(self):
        detector = PuffDetector()
        elapsed = 0.0
        for _ in range(200):
            detector.feed(elapsed, 430.0 + 20.0 * math.sin(elapsed))
            elapsed += 0.05
        assert detector.active is None
        assert detector.pop_completed() == []

    def test_the_score_is_the_area_above_the_threshold(self):
        """Two seconds at 2000 is 1000 ppm over the line, so 2000 ppm*s.

        Measured above the threshold rather than above ambient, so that a blow
        which barely crosses scores nearly nothing instead of jumping to
        several hundred, and so that the background drifting between afternoon
        and night cannot hand out points.
        """
        detector = PuffDetector()
        _blow(detector, level=2000.0, seconds=2.0)
        (puff,) = detector.pop_completed()
        assert puff.score == pytest.approx(2000.0, rel=0.02)
        assert puff.peak == 2000.0

    def test_a_saturated_breath_still_ranks_by_how_long_it_lasts(self):
        """The reason the score is an integral at all.

        An open-path head stops at about 3000 umol mol-1 and breath is far
        above that, so two blows that both pin the reading have identical
        peaks. What still separates them is duration, and the score has to see
        it.
        """
        short, long = PuffDetector(), PuffDetector()
        _blow(short, level=3000.0, seconds=1.0)
        _blow(long, level=3000.0, seconds=3.0)
        (brief,), (sustained,) = short.pop_completed(), long.pop_completed()
        assert brief.peak == sustained.peak
        assert sustained.score > brief.score * 2.5

    def test_a_noisy_falling_flank_is_one_breath_not_five(self):
        """The hysteresis, which is the difference between one turn and five."""
        detector = PuffDetector()
        elapsed = 0.0
        for value in [2500.0] * 20 + [1100.0, 900.0, 1200.0, 850.0, 1050.0, 800.0]:
            detector.feed(elapsed, value)
            elapsed += 0.05
        for _ in range(40):
            detector.feed(elapsed, 430.0)
            elapsed += 0.05
        assert len(detector.pop_completed()) == 1

    def test_a_dropout_is_not_scored_as_if_the_value_had_held(self):
        """The analyzer stops, and the missing seconds must not earn points."""
        scored, gapped = PuffDetector(), PuffDetector()
        elapsed = 0.0
        for _ in range(20):
            scored.feed(elapsed, 3000.0)
            gapped.feed(elapsed, 3000.0)
            elapsed += 0.05
        # One stream keeps delivering; the other goes quiet for two seconds and
        # comes back at the same value.
        quiet = elapsed
        for _ in range(40):
            scored.feed(elapsed, 3000.0)
            elapsed += 0.05
        gapped.feed(elapsed, 3000.0)
        assert gapped.active.score < scored.active.score / 2
        assert quiet < elapsed  # the hole really was in the middle

    def test_a_breath_cannot_run_forever(self):
        """A bag over the head is not a lung, and this is what says so."""
        detector = PuffDetector()
        elapsed = 0.0
        while elapsed < MAX_PUFF_SECONDS * 2:
            detector.feed(elapsed, 3000.0)
            elapsed += 0.05
        (puff,) = detector.pop_completed()
        assert puff.duration <= MAX_PUFF_SECONDS + 0.1

    def test_a_sample_nicking_the_threshold_does_not_end_a_turn(self):
        detector = PuffDetector()
        elapsed = 0.0
        for value in [430.0, 1010.0, 430.0, 430.0, 430.0]:
            detector.feed(elapsed, value)
            elapsed += 0.05
        assert detector.pop_completed() == []

    def test_the_threshold_carries_its_hysteresis_with_it(self):
        """A site raising the threshold keeps the gap that stops the chopping."""
        detector = PuffDetector(threshold=5000.0)
        assert detector.threshold > detector.release > 0.0

    def test_ambient_follows_the_quiet_air_only(self):
        detector = PuffDetector()
        elapsed = 0.0
        for _ in range(200):
            detector.feed(elapsed, 500.0)
            elapsed += 0.05
        assert detector.ambient == pytest.approx(500.0, abs=1.0)
        _blow(detector, start=elapsed, level=3000.0, seconds=2.0, ambient=500.0, tail=0.0)
        # The breath itself never enters the average.
        assert detector.ambient == pytest.approx(500.0, abs=1.0)


class TestBreathRace:
    def test_the_first_breath_sets_the_finish_line(self):
        """No fixed goal suits every mast, so the session calibrates itself."""
        race = BreathRace(players=2)
        assert race.goal is None
        elapsed = _blow(race.detector, level=2000.0, seconds=2.0)
        race.feed(elapsed, 420.0)
        assert race.goal == pytest.approx(2000.0 * GOAL_BREATHS, rel=0.05)

    def test_a_breath_moves_the_lane_whose_turn_it_is_and_then_passes_it(self):
        race = BreathRace(players=2, goal=100_000.0)
        first, second = race.racers
        assert race.active is first

        elapsed = 0.0
        for _ in range(40):
            race.feed(elapsed, 3000.0)
            elapsed += 0.05
        # Moving during the breath is the whole feel of the game.
        assert race.distance_of(first) > 0
        assert first.distance == 0.0
        for _ in range(40):
            race.feed(elapsed, 420.0)
            elapsed += 0.05

        assert first.distance > 0
        assert first.breaths == 1
        assert race.active is second

    def test_crossing_the_line_is_judged_during_the_breath(self):
        """The animal stops at the line, not a second later when it is scored."""
        race = BreathRace(players=1, goal=500.0)
        (racer,) = race.racers
        elapsed = 0.0
        while racer.place is None and elapsed < 5.0:
            race.feed(elapsed, 3000.0)
            elapsed += 0.05
        assert racer.place == 1
        assert race.detector.active is not None  # still blowing
        assert race.fraction_of(racer) == 1.0

    def test_a_finished_lane_is_skipped_and_the_race_ends(self):
        race = BreathRace(players=2, goal=1000.0)
        first, second = race.racers
        elapsed = 0.0
        for _ in range(6):
            elapsed = _blow(race.detector, start=elapsed, level=3000.0, seconds=1.0)
            race.feed(elapsed, 420.0)
            elapsed += 0.05
        assert race.over
        assert [racer.place for racer in (first, second)] == [1, 2]
        assert race.standings == [first, second]
        assert race.active is None

    def test_the_turn_passes_without_a_breath_when_a_player_walks_off(self):
        race = BreathRace(players=3)
        race.skip_turn()
        assert race.active is race.racers[1]

    def test_lanes_can_be_added_and_dropped_within_the_animals_there_are(self):
        race = BreathRace(players=1)
        while race.add_player():
            pass
        assert len(race.racers) == MAX_PLAYERS
        assert len({racer.animal for racer in race.racers}) == MAX_PLAYERS
        while race.remove_player():
            pass
        assert len(race.racers) == 1

    def test_a_reset_reopens_an_auto_calibrated_finish_line(self):
        """A new race calibrates itself rather than inheriting the last pace."""
        race = BreathRace(players=2)
        elapsed = _blow(race.detector, level=2000.0, seconds=2.0)
        race.feed(elapsed, 420.0)
        assert race.goal

        race.reset()
        assert race.goal is None
        assert all(racer.distance == 0 for racer in race.racers)
        assert race.turn == 0

    def test_a_configured_finish_line_survives_a_reset(self):
        race = BreathRace(players=2, goal=4321.0)
        elapsed = _blow(race.detector, level=3000.0, seconds=1.0)
        race.feed(elapsed, 420.0)
        race.reset()
        assert race.goal == 4321.0

    def test_a_breath_too_small_to_count_never_passes_the_turn(self):
        race = BreathRace(players=2)
        first = race.racers[0]
        elapsed = 0.0
        # Just over the line for a moment: less than MIN_PUFF_SCORE of area.
        for value in [1100.0, 1100.0, 420.0, 420.0, 420.0, 420.0, 420.0, 420.0]:
            race.feed(elapsed, value)
            elapsed += 0.05
        assert race.active is first
        assert first.breaths == 0
        assert MIN_PUFF_SCORE > 0


def test_the_default_threshold_clears_anything_the_atmosphere_does():
    """1000 is the point of the rule, so it is worth pinning down.

    Ambient air is 400-450 umol mol-1 and a canopy at night reaches 600, so
    a threshold anywhere near those would score the weather.
    """
    assert THRESHOLD_PPM >= 1000.0
