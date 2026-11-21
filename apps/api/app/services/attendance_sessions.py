"""Working-session and loss-of-pay arithmetic for the IST attendance clock."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class SessionCoverage:
    morning: bool
    afternoon: bool
    minutes_worked: int
    late: bool
    early_exit: bool


def midnight_after(day: date) -> datetime:
    return datetime.combine(day + timedelta(days=1), time.min, IST)


def late_login(day: date, check_in: datetime) -> bool:
    return check_in >= datetime.combine(day, time(9, 46), IST)


def session_coverage(day: date, check_in: datetime, check_out: datetime) -> SessionCoverage:
    morning_start = datetime.combine(day, time(9, 30), IST)
    morning_end = datetime.combine(day, time(13, 30), IST)
    afternoon_start = datetime.combine(day, time(14, 30), IST)
    afternoon_end = datetime.combine(day, time(18, 30), IST)

    def minutes_in(start: datetime, end: datetime) -> int:
        overlap = min(end, check_out) - max(start, check_in)
        return max(0, int(overlap.total_seconds() // 60))

    return SessionCoverage(
        morning=check_in <= datetime.combine(day, time(11, 30), IST) and check_out >= morning_end,
        afternoon=check_in <= afternoon_start and check_out >= afternoon_end,
        minutes_worked=minutes_in(morning_start, morning_end)
        + minutes_in(afternoon_start, afternoon_end),
        late=late_login(day, check_in),
        early_exit=afternoon_start <= check_out < afternoon_end,
    )


def late_penalty_units(ordinal: int) -> int:
    if ordinal <= 3:
        return 0
    if ordinal == 4:
        return 4
    if ordinal == 5:
        return 2
    return 1
