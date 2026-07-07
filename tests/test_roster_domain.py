"""P4.3 — pure domain/roster.py: greedy monthly duty generator + violations.

Hard constraints (eligibility via pre-filtered pools, availability) are never
violated — an unfillable day is left blank and flagged, never rule-broken.
Soft constraints (spread max-min <= 1 per duty, no adjacent duty days incl.
Fri->following-Mon) are prefer-avoided by the pick key and REPORTED by the
standalone violations() — never solved, never refused (plan's own scope cut).
No solver, no randomness: same inputs, same roster, forever.
"""
from datetime import date
from types import SimpleNamespace

from app.domain.roster import adjacent_duty_days, generate, violations
from app.domain.types import Duty

# September 2026: Tue 1st; first Friday the 4th, following Monday the 7th.
SEP = lambda d: date(2026, 9, d)


def person(id):
    return SimpleNamespace(id=id)


def always(p, day):
    return True


# --- adjacent_duty_days --------------------------------------------------------

def test_calendar_adjacent_days():
    assert adjacent_duty_days(SEP(3), SEP(4))
    assert adjacent_duty_days(SEP(4), SEP(3))  # symmetric
    assert not adjacent_duty_days(SEP(3), SEP(5))
    assert not adjacent_duty_days(SEP(3), SEP(3))  # same day is not "adjacent"


def test_friday_to_following_monday_counts_adjacent():
    assert adjacent_duty_days(SEP(4), SEP(7))   # Fri -> Mon (assumption 11)
    assert adjacent_duty_days(SEP(7), SEP(4))   # symmetric
    assert not adjacent_duty_days(SEP(4), SEP(6))   # Fri -> Sun (2 days, not the pair)
    assert not adjacent_duty_days(SEP(4), SEP(14))  # Fri -> Mon-after-next
    assert not adjacent_duty_days(SEP(7), SEP(11))  # Mon -> Fri same week: no


# --- generate: hard constraints ------------------------------------------------

def test_empty_pool_leaves_every_day_blank_and_flagged():
    days = [SEP(1), SEP(2)]
    pools = {Duty.COS: [], Duty.CDOS: [person(1)]}
    got = generate(days, pools, always)
    assert got[(SEP(1), Duty.COS)] is None
    assert got[(SEP(2), Duty.COS)] is None
    report = violations(got, pools)
    assert (SEP(1), Duty.COS) in report.blanks
    assert (SEP(2), Duty.COS) in report.blanks


def test_unavailable_candidates_are_never_auto_picked_even_if_sole_option():
    # Decision (d): auto-pick SKIPS anyone with any off/leave; the manual-
    # assign-with-warning path (P4.6) is the only way over that line.
    days = [SEP(1)]
    pools = {Duty.COS: [person(1)]}
    got = generate(days, pools, lambda p, day: False)
    assert got[(SEP(1), Duty.COS)] is None


def test_deterministic_for_identical_inputs():
    days = [SEP(d) for d in range(1, 31)]
    pools = {Duty.COS: [person(1), person(2), person(3)],
             Duty.CDOS: [person(4), person(5)]}
    a = generate(days, pools, always)
    b = generate(days, pools, always)
    assert a == b


# --- generate: soft constraints steer, never refuse ----------------------------

def test_unavoidable_adjacency_still_fills_and_is_flagged():
    days = [SEP(1), SEP(2), SEP(3)]
    pools = {Duty.COS: [person(1)]}          # one man: adjacency is unavoidable
    got = generate(days, pools, always)
    assert all(got[(d, Duty.COS)] == 1 for d in days)   # filled, never refused
    report = violations(got, pools)
    assert (1, SEP(1), SEP(2)) in report.adjacency
    assert (1, SEP(2), SEP(3)) in report.adjacency


def test_adjacency_avoidance_beats_count_evenness():
    # Day 2: person 1 did day 1 (adjacent); person 2 already has a higher month
    # count but is NOT adjacent — the pick key puts adjacency first.
    days = [SEP(1), SEP(2)]
    pools = {Duty.COS: [person(1), person(2)]}
    # Force person 1 onto day 1 by making 2 unavailable that day only.
    avail = lambda p, day: not (p.id == 2 and day == SEP(1))
    got = generate(days, pools, avail)
    assert got[(SEP(1), Duty.COS)] == 1
    assert got[(SEP(2), Duty.COS)] == 2   # not 1, despite equal-or-lower count


def test_friday_monday_adjacency_avoided_across_the_weekend():
    # Person 1 holds Friday; for the following Monday the generator prefers
    # person 2 even though counts tie.
    days = [SEP(4), SEP(7)]                # Fri, following Mon
    pools = {Duty.COS: [person(1), person(2)]}
    avail = lambda p, day: not (p.id == 2 and day == SEP(4))
    got = generate(days, pools, avail)
    assert got[(SEP(4), Duty.COS)] == 1
    assert got[(SEP(7), Duty.COS)] == 2


def test_even_spread_two_people_four_days():
    days = [SEP(1), SEP(3), SEP(9), SEP(11)]   # spaced: adjacency never bites
    pools = {Duty.COS: [person(1), person(2)]}
    got = generate(days, pools, always)
    picks = [got[(d, Duty.COS)] for d in days]
    assert picks.count(1) == 2 and picks.count(2) == 2
    assert not violations(got, pools).spread


def test_spread_breach_is_reported_by_violations():
    # Person 2 available ONLY on day 1 (when person 1 is out) -> 2 takes day 1,
    # person 1 takes the other 3: spread 3-1 breaches max-min <= 1.
    days = [SEP(1), SEP(9), SEP(16), SEP(23)]
    pools = {Duty.COS: [person(1), person(2)]}
    avail = lambda p, day: (p.id == 2) == (day == SEP(1))
    got = generate(days, pools, avail)
    report = violations(got, pools)
    assert report.spread[Duty.COS] == (1, 3)


def test_carry_over_breaks_an_otherwise_equal_tie():
    # Both fresh this month, both non-adjacent: the one who did FEWER last
    # month goes first. Tie-breaker only — nothing else consults history.
    days = [SEP(9)]
    pools = {Duty.COS: [person(1), person(2)]}
    prior_counts = {Duty.COS: {1: 4, 2: 2}}
    got = generate(days, pools, always, prior_counts=prior_counts)
    assert got[(SEP(9), Duty.COS)] == 2


def test_prior_tail_makes_cross_month_adjacency_visible():
    # Person 1 held the last day of August; September 1st prefers person 2,
    # and violations() with the tail reports the pair if forced anyway.
    days = [SEP(1)]
    pools = {Duty.COS: [person(1), person(2)]}
    tail = [(date(2026, 8, 31), Duty.COS, 1)]
    got = generate(days, pools, always, prior_tail=tail)
    assert got[(SEP(1), Duty.COS)] == 2

    forced = {(SEP(1), Duty.COS): 1}
    report = violations(forced, pools, prior_tail=tail)
    assert (1, date(2026, 8, 31), SEP(1)) in report.adjacency


def test_first_ever_month_empty_tail_and_counts_is_defined_not_crashed():
    days = [SEP(1)]
    pools = {Duty.COS: [person(1)]}
    got = generate(days, pools, always, prior_counts={}, prior_tail=())
    assert got[(SEP(1), Duty.COS)] == 1


def test_violations_reflags_after_manual_edits_not_only_after_generation():
    # violations() is standalone: hand it any assignment map (e.g. after a P4.6
    # manual replace) and it re-reports — the page re-flags on every render.
    pools = {Duty.COS: [person(1), person(2)]}
    manual = {(SEP(1), Duty.COS): 1, (SEP(2), Duty.COS): 1, (SEP(3), Duty.COS): None}
    report = violations(manual, pools)
    assert (1, SEP(1), SEP(2)) in report.adjacency
    assert (SEP(3), Duty.COS) in report.blanks
