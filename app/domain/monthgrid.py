"""Month-grid geometry (UI-23): the arithmetic that turns day-ranges into the
spanning bars a Google-Calendar-style month grid draws.

Pure — stdlib only, so pytest exercises every boundary (run merging, week
segmentation, lane packing) without HTTP or a database. The service layer owns
the queries; everything about WHICH cell a bar starts in, how wide it is, and
which lane it sits on lives here so the template stays a dumb renderer.
"""
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class OffRun:
    """One person's unbroken stretch of identical OFF/LEAVE days.

    `row` is the source row of the run's FIRST day; the merge key guarantees
    every day in [start, end] carries the same person, label and day-part, so
    that one row speaks for the whole run when the bar is rendered.
    """

    row: object
    start: date
    end: date


@dataclass(frozen=True)
class Segment:
    """One week-row's slice of an interval: where its bar starts, how many
    columns it spans, and whether it continues past the days shown here."""

    col: int
    span: int
    clip_left: bool
    clip_right: bool

    @property
    def col_span(self):
        """The (col, span) pair `pack_lanes` packs on."""
        return self.col, self.span


def merge_off_runs(rows_by_day):
    """Merge per-day OFF/LEAVE rows into runs of consecutive DATES.

    `rows_by_day` maps a date to that day's rows (already deduped to one per
    person, in parade order). A run continues only into the immediately next
    calendar day with the same (person_id, label, day_part): a gap day, a label
    change or a day-part change all start a new run. Runs come back in
    first-appearance order, so the input's parade order survives the merge.
    """
    runs = []  # working [row, start, end] triples, in first-appearance order
    previous_day = None
    previous = {}
    for day in sorted(rows_by_day):
        current = {}
        continues = previous_day is not None and day == previous_day + timedelta(days=1)
        for row in rows_by_day[day]:
            key = (row.person_id, row.label, row.day_part)
            working = previous.get(key) if continues else None
            if working is None:
                working = [row, day, day]
                runs.append(working)
            else:
                working[2] = day
            current[key] = working
        previous_day = day
        previous = current
    return [OffRun(row=row, start=start, end=end) for row, start, end in runs]


def week_segment(*, start, end, week_days):
    """The bar for interval [start, end] on one week row, or None if it misses.

    `week_days` is that row's 7 `(date, in_month)` pairs. Only IN-MONTH days can
    carry a bar — adjacent-month padding cells stay empty, so a bar clips at the
    month edge and the neighbouring month draws its own (TECH_PLAN cut). The
    clip flags say the interval runs past the days shown HERE (a week boundary
    or the month edge) and are the template's continuation cue.
    """
    columns = [
        column
        for column, (day, in_month) in enumerate(week_days, start=1)
        if in_month and start <= day <= end
    ]
    if not columns:
        return None
    col, last_col = columns[0], columns[-1]
    return Segment(
        col=col,
        span=last_col - col + 1,
        clip_left=start < week_days[col - 1][0],
        clip_right=end > week_days[last_col - 1][0],
    )


def pack_lanes(placements):
    """Lane (0-based row within a band) for each `(col, span)` placement.

    Greedy interval packing: widest-first at each starting column, each bar
    taking the lowest lane whose columns are still free. Returns a list parallel
    to `placements`, so the caller keeps its own ordering. The sort is stable,
    so equal (col, span) bars keep input order and the lanes are deterministic.
    """
    order = sorted(range(len(placements)), key=lambda i: (placements[i][0], -placements[i][1]))
    lanes = [0] * len(placements)
    taken = []
    for index in order:
        col, span = placements[index]
        columns = set(range(col, col + span))
        lane = 0
        while lane < len(taken) and taken[lane] & columns:
            lane += 1
        if lane == len(taken):
            taken.append(set())
        taken[lane] |= columns
        lanes[index] = lane
    return lanes


def overflow_by_column(placements, lanes, *, lane_limit):
    """Per-column count of the placements pushed past `lane_limit` lanes.

    A capped band drops those bars and shows a "+N more" chip on each DAY they
    covered, so a dropped 3-day run is counted once in each of its 3 columns —
    the reader still learns how many people that day is hiding.
    """
    counts = {}
    for (col, span), lane in zip(placements, lanes):
        if lane < lane_limit:
            continue
        for column in range(col, col + span):
            counts[column] = counts.get(column, 0) + 1
    return counts
