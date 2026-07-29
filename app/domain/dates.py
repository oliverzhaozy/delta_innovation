"""Date arithmetic pinned to Singapore time. Pure: holidays come in as a set,
never from the DB, so everything here is testable without an app.
"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

SGT = ZoneInfo("Asia/Singapore")


def today_sgt() -> date:
    # Never trust client-local 'today'; a user on OL abroad must not shift dates.
    return datetime.now(SGT).date()


def now_sgt() -> datetime:
    # Stored naive per plan: this app never leaves Singapore time.
    return datetime.now(SGT).replace(tzinfo=None, microsecond=0)


def parse_ym(raw) -> tuple:
    """(year, month) from a raw `?ym=YYYY-MM` query string. "" or an
    unparseable value falls back to today's month — every month grid falls
    back, never 404s (the parade pages' bad-?date= convention).
    """
    if raw:
        try:
            year_str, month_str = raw.split("-")
            year, month = int(year_str), int(month_str)
            date(year, month, 1)  # rejects month 13 / year 0 before a grid is built
            return year, month
        except ValueError:
            pass
    today = today_sgt()
    return today.year, today.month


def adjacent_ym(year: int, month: int, delta: int) -> tuple:
    # delta is +-1 month; only ever called with |delta| == 1 so no general
    # modular-arithmetic case is needed.
    if delta == 1:
        return (year + 1, 1) if month == 12 else (year, month + 1)
    return (year - 1, 12) if month == 1 else (year, month - 1)


def iter_days(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def is_working_day(d: date, holidays: frozenset = frozenset()) -> bool:
    return d.weekday() < 5 and d not in holidays


def next_weekday(d: date) -> date:
    """The first Mon-Fri date strictly after `d`. Weekend-only by design: the RO
    exists for public holidays too, so no holidays parameter (unlike working_days).
    """
    d += timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def prev_weekday(d: date) -> date:
    """The last Mon-Fri date strictly before `d`."""
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def working_days(start: date, end: date, holidays: frozenset = frozenset()) -> int:
    """Working days in [start, end] — the only days that consume OFF/OIL balance."""
    return sum(1 for d in iter_days(start, end) if is_working_day(d, holidays))


def format_ddmmyy(d: date) -> str:
    # DDMMYY is the one date format every generated parade document uses (PARADE_FORMATS.md).
    return d.strftime("%d%m%y")


def format_ddmmyy_range(start: date, end: date) -> str:
    # Parade-line suffix rule (owner 2026-07-27): a one-day range collapses to the
    # single date; the " - " separator matches the manning header's.
    if start == end:
        return format_ddmmyy(start)
    return f"{format_ddmmyy(start)} - {format_ddmmyy(end)}"
