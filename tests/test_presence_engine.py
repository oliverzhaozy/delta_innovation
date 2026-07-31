from datetime import date
from types import SimpleNamespace

from app.domain import presence
from app.domain.presence import PresenceState, Resolution
from app.domain.types import DayPart, Service

D = date(2026, 7, 10)


# --- fakes (duck-typed rows; the engine returns the caller's own objects) ---

def person(stay_out=False, service=Service.NSF):
    return SimpleNamespace(stay_out=stay_out, service=service)


def absence(start=D, end=D, day_part=DayPart.FULL, kind="leave"):
    """Leave-shaped row: dates + day_part, always out of camp."""
    return SimpleNamespace(start_date=start, end_date=end, day_part=day_part, kind=kind)


def status(start=D, end=D, day_part=DayPart.FULL, in_camp=False, kind="mc"):
    return SimpleNamespace(
        start_date=start, end_date=end, day_part=day_part, in_camp=in_camp, kind=kind
    )


def duty(start=D, end=D):
    return SimpleNamespace(start_date=start, end_date=end)


# --- covers (criterion 6) ------------------------------------------------

def test_covers_inclusive_boundaries():
    r = absence(start=date(2026, 7, 10), end=date(2026, 7, 12))
    assert presence.covers(r, date(2026, 7, 10))  # start day
    assert presence.covers(r, date(2026, 7, 11))  # inside
    assert presence.covers(r, date(2026, 7, 12))  # end day
    assert not presence.covers(r, date(2026, 7, 9))   # day before
    assert not presence.covers(r, date(2026, 7, 13))  # day after


def test_covers_single_day():
    r = absence(start=D, end=D)
    assert presence.covers(r, D)
    assert not presence.covers(r, date(2026, 7, 9))


def test_non_covering_rows_appear_nowhere():
    before = absence(start=date(2026, 7, 1), end=date(2026, 7, 5))
    after = status(start=date(2026, 7, 20), end=date(2026, 7, 25), in_camp=True)
    res = presence.resolve(person(stay_out=True), D, leaves=[before], statuses=[after])
    assert res.state is PresenceState.STAY_OUT
    assert res.row is None
    assert res.partial_rows == ()
    assert res.in_camp_rows == ()
    assert res.conflicts == ()


# --- absent_for_day (criterion 7) ----------------------------------------

def test_absent_for_day_full_and_am_absent_pm_present():
    # Decision (i): FULL/AM count absent for the day; PM stays present.
    assert presence.absent_for_day(DayPart.FULL) is True
    assert presence.absent_for_day(DayPart.AM) is True
    assert presence.absent_for_day(DayPart.PM) is False


# --- adjacent precedence pairs (criterion 1) -----------------------------

def test_leave_beats_out_of_camp_status():
    lv = absence(kind="leave")
    st = status(in_camp=False, kind="mc")
    res = presence.resolve(person(), D, leaves=[lv], statuses=[st])
    assert res.state is PresenceState.ABSENT
    assert res.row is lv
    assert res.conflicts == (st,)


def test_first_of_two_covering_leaves_wins_and_the_other_is_a_conflict():
    # Within one tier the input order decides: absent_making[0] is the winner,
    # the rest are conflicts. Nothing a covering row says is ever dropped.
    first = absence(kind="leave")
    second = absence(kind="off")
    res = presence.resolve(person(), D, leaves=[first, second])
    assert res.state is PresenceState.ABSENT
    assert res.row is first
    assert res.conflicts == (second,)


def test_out_of_camp_status_beats_duty():
    st = status(in_camp=False)
    res = presence.resolve(person(), D, statuses=[st], duties=[duty()])
    assert res.state is PresenceState.ABSENT
    assert res.row is st


def test_duty_beats_stay_out():
    res = presence.resolve(person(stay_out=True), D, duties=[duty()])
    assert res.state is PresenceState.DUTY
    assert res.row is None


def test_duty_beats_present():
    res = presence.resolve(person(), D, duties=[duty()])
    assert res.state is PresenceState.DUTY


def test_stay_out_beats_present():
    res = presence.resolve(person(stay_out=True), D)
    assert res.state is PresenceState.STAY_OUT


# --- AM / PM day-part semantics (criterion 2) ----------------------------

def test_am_leave_makes_absent():
    lv = absence(day_part=DayPart.AM)
    res = presence.resolve(person(), D, leaves=[lv])
    assert res.state is PresenceState.ABSENT
    assert res.row is lv
    assert res.partial_rows == ()


def test_pm_leave_is_present_partial():
    lv = absence(day_part=DayPart.PM)
    res = presence.resolve(person(), D, leaves=[lv])
    assert res.state is PresenceState.PRESENT
    assert res.row is None
    assert res.partial_rows == (lv,)
    assert res.conflicts == ()


def test_am_status_makes_absent():
    st = status(day_part=DayPart.AM, in_camp=False)
    res = presence.resolve(person(), D, statuses=[st])
    assert res.state is PresenceState.ABSENT
    assert res.row is st


def test_pm_status_is_present_partial():
    st = status(day_part=DayPart.PM, in_camp=False)
    res = presence.resolve(person(), D, statuses=[st])
    assert res.state is PresenceState.PRESENT
    assert res.partial_rows == (st,)


# --- stay-out / present defaults (criterion 3) ---------------------------

def test_regular_without_flag_is_present():
    # The stay_out flag is the ONE source of stay-out (owner 2026-07-31);
    # service no longer forces it — an unflagged regular parades PRESENT.
    res = presence.resolve(person(service=Service.REGULAR), D)
    assert res.state is PresenceState.PRESENT


def test_regular_stay_out_flag_stays_out():
    res = presence.resolve(person(service=Service.REGULAR, stay_out=True), D)
    assert res.state is PresenceState.STAY_OUT


def test_nsf_stay_out_flag_stays_out():
    res = presence.resolve(person(service=Service.NSF, stay_out=True), D)
    assert res.state is PresenceState.STAY_OUT


def test_nsf_default_present():
    res = presence.resolve(person(service=Service.NSF, stay_out=False), D)
    assert res.state is PresenceState.PRESENT


# --- in-camp statuses are annotations, never absences (criterion 4) ------

def test_stay_out_regular_with_in_camp_briefing_still_stay_out():
    # Subtle case: night documents show STAY OUT; the briefing surfaces only as
    # an in-camp annotation (morning parade OTHERS IN CAMP), never an absence.
    p = person(service=Service.REGULAR, stay_out=True)  # flagged stay-out regular
    briefing = status(in_camp=True, kind="briefing")
    res = presence.resolve(p, D, statuses=[briefing])
    assert res.state is PresenceState.STAY_OUT
    assert res.in_camp_rows == (briefing,)
    assert res.conflicts == ()
    assert res.partial_rows == ()
    assert res.row is None


def test_in_camp_status_alone_is_present_annotation():
    briefing = status(in_camp=True, kind="briefing")
    res = presence.resolve(person(), D, statuses=[briefing])
    assert res.state is PresenceState.PRESENT
    assert res.in_camp_rows == (briefing,)
    assert res.row is None
    assert res.conflicts == ()
    assert res.partial_rows == ()


def test_in_camp_status_collected_even_when_absent():
    lv = absence()
    briefing = status(in_camp=True, kind="briefing")
    res = presence.resolve(person(), D, leaves=[lv], statuses=[briefing])
    assert res.state is PresenceState.ABSENT
    assert res.row is lv
    assert res.in_camp_rows == (briefing,)
    assert briefing not in res.conflicts


def test_in_camp_pm_status_is_annotation_not_partial():
    briefing = status(in_camp=True, day_part=DayPart.PM, kind="briefing")
    res = presence.resolve(person(), D, statuses=[briefing])
    assert res.in_camp_rows == (briefing,)
    assert res.partial_rows == ()


# --- MC while on leave (criterion 5) -------------------------------------

def test_mc_while_on_leave_surfaces_conflict():
    lv = absence(kind="leave")
    mc = status(in_camp=False, kind="mc")
    res = presence.resolve(person(), D, leaves=[lv], statuses=[mc])
    assert res.state is PresenceState.ABSENT
    assert res.row is lv
    assert res.conflicts == (mc,)


# --- conflict ordering ---------------------------------------------------

def test_conflicts_preserve_precedence_order():
    lv = absence(kind="leave")
    off = absence(kind="off")
    mc = status(in_camp=False, kind="mc")
    res = presence.resolve(person(), D, leaves=[lv, off], statuses=[mc])
    assert res.row is lv
    # Leave wins; the other leave-tier row keeps its input position, and the
    # out-of-camp status ranks after the whole leave tier.
    assert res.conflicts == (off, mc)


def test_duty_state_still_collects_partials():
    pm_off = absence(day_part=DayPart.PM, kind="off")
    res = presence.resolve(person(), D, duties=[duty()], leaves=[pm_off])
    assert res.state is PresenceState.DUTY
    assert res.partial_rows == (pm_off,)


# --- Resolution shape ----------------------------------------------------

def test_resolution_is_frozen():
    res = presence.resolve(person(), D)
    assert isinstance(res, Resolution)
    try:
        res.state = PresenceState.ABSENT
    except Exception as exc:  # frozen dataclass raises FrozenInstanceError
        assert exc.__class__.__name__ == "FrozenInstanceError"
    else:
        raise AssertionError("Resolution should be immutable")
