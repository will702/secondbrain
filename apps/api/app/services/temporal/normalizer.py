"""Deterministic temporal normalization (DATA_MODEL.md §5, AI_SYSTEM.md §8).

The LLM extracts raw date expressions verbatim; THIS module owns turning them
into timestamps. Deterministic by design: same input + reference → same output,
fully unit-tested. The LLM never writes a normalized timestamp.

Confidence policy:
  >= 0.75  explicit, plainly stated date          → may auto-confirm
  0.4-0.75 relative but computable (weekday, tomorrow, in N days)
  <  0.4   vague/anchored-to-unknown-event        → review item, never confirmed
"""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from dateutil import parser as dateutil_parser

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

CONFIRM_THRESHOLD = 0.75

_RE_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{1,2}):(\d{2}))?")
_MONTH_ALTS = "|".join(sorted(MONTHS, key=len, reverse=True))
_RE_MONTH_DAY = re.compile(
    rf"(?:({_MONTH_ALTS})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?)"
    rf"|(?:(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_ALTS})\.?)",
    re.IGNORECASE,
)
_RE_TIME = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b|\b(\d{1,2}):(\d{2})\b", re.IGNORECASE)
_RE_IN_N = re.compile(r"\bin\s+(\d+)\s+(day|week|month)s?\b", re.IGNORECASE)
_RE_WEEKDAY = re.compile(
    r"\b(this|next|by|on|before)?\s*(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.IGNORECASE,
)
_RE_RECURRENCE = re.compile(
    r"\b(every|each)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday|week|day)\b|"
    r"\bweekly\b|\bdaily\b|\bmonthly\b",
    re.IGNORECASE,
)
_RE_WEEK_N = re.compile(r"\bweek\s+(\d{1,2})\b", re.IGNORECASE)

# Expressions anchored to events/periods we cannot resolve from text alone.
_VAGUE_PATTERNS = [
    (re.compile(r"sometime", re.I), "vague time expression"),
    (re.compile(r"end of (the )?(semester|term|month|year)", re.I), "anchored to period end"),
    (
        re.compile(r"before the midterm|after submission|after the exam|before class starts", re.I),
        "anchored to another event",
    ),
    (re.compile(r"next (month|year)", re.I), "no unambiguous date"),
]


@dataclass
class NormalizedDate:
    normalized_at: datetime | None
    date_is_exact: bool
    has_time: bool
    confidence: float
    explicit: bool
    is_recurrence: bool = False
    note: str = ""

    @property
    def needs_review(self) -> bool:
        return self.confidence < CONFIRM_THRESHOLD and not self.is_recurrence


def _combine(d: date, t: time, tz: ZoneInfo) -> datetime:
    return datetime.combine(d, t, tzinfo=tz)


def _end_of_day(d: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(d, time(23, 59), tzinfo=tz)


def _parse_time(text: str) -> time | None:
    match = _RE_TIME.search(text)
    if match is None:
        return None
    if match.group(3):  # 12-hour clock
        hour = int(match.group(1)) % 12
        if match.group(3).lower() == "pm":
            hour += 12
        minute = int(match.group(2) or 0)
        return time(hour, minute)
    return time(int(match.group(4)), int(match.group(5)))


def _next_weekday(reference: date, weekday: int, force_next_week: bool) -> date:
    if force_next_week:
        monday = reference - timedelta(days=reference.weekday()) + timedelta(days=7)
        return monday + timedelta(days=weekday)
    days_ahead = (weekday - reference.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return reference + timedelta(days=days_ahead)


def normalize_when(when_text: str, *, reference: datetime, tz_name: str) -> NormalizedDate:
    """when_text: verbatim date phrase. reference: anchor for relative phrases."""
    tz = ZoneInfo(tz_name)
    ref_local = reference.astimezone(tz)
    ref_date = ref_local.date()
    text = when_text.strip()
    lowered = text.lower()

    # Recurrences are real information but never a single event.
    if _RE_RECURRENCE.search(lowered):
        return NormalizedDate(
            normalized_at=None,
            date_is_exact=False,
            has_time=False,
            confidence=0.7,
            explicit=True,
            is_recurrence=True,
            note="recurring — schedule as recurrence, not one-off event",
        )

    for pattern, note in _VAGUE_PATTERNS:
        if pattern.search(lowered):
            return NormalizedDate(
                normalized_at=None,
                date_is_exact=False,
                has_time=False,
                confidence=0.2,
                explicit=False,
                note=note,
            )

    if _RE_WEEK_N.search(lowered):
        return NormalizedDate(
            normalized_at=None,
            date_is_exact=False,
            has_time=False,
            confidence=0.25,
            explicit=False,
            note="course week number — needs course start date to resolve",
        )

    if "tomorrow" in lowered:
        t = _parse_time(lowered)
        day = ref_date + timedelta(days=1)
        return NormalizedDate(
            normalized_at=_combine(day, t or time(12, 0), tz),
            date_is_exact=t is not None,
            has_time=t is not None,
            confidence=0.6,
            explicit=False,
        )
    if "today" in lowered or "tonight" in lowered:
        t = _parse_time(lowered) or (time(20, 0) if "tonight" in lowered else time(12, 0))
        return NormalizedDate(
            normalized_at=_combine(ref_date, t, tz),
            date_is_exact=False,
            has_time=True,
            confidence=0.6,
            explicit=False,
        )

    in_n = _RE_IN_N.search(lowered)
    if in_n:
        count, unit = int(in_n.group(1)), in_n.group(2).lower()
        delta = (
            timedelta(days=count)
            if unit == "day"
            else timedelta(weeks=count)
            if unit == "week"
            else timedelta(days=30 * count)
        )
        t = _parse_time(lowered)
        day = ref_date + delta
        return NormalizedDate(
            normalized_at=_combine(day, t or time(12, 0), tz),
            date_is_exact=False,
            has_time=t is not None,
            confidence=0.6,
            explicit=False,
        )

    weekday_match = _RE_WEEKDAY.search(lowered)
    if weekday_match and not _RE_ISO.search(text) and not _has_month(lowered):
        qualifier, weekday_name = weekday_match.group(1), weekday_match.group(2).lower()
        day = _next_weekday(ref_date, WEEKDAYS[weekday_name], qualifier == "next")
        t = _parse_time(lowered)
        return NormalizedDate(
            normalized_at=_combine(day, t or time(12, 0), tz),
            date_is_exact=False,
            has_time=t is not None,
            confidence=0.5,
            explicit=False,
        )

    iso = _RE_ISO.search(text)
    if iso:
        day = date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        t = time(int(iso.group(4)), int(iso.group(5))) if iso.group(4) else _parse_time(lowered)
        return NormalizedDate(
            normalized_at=_combine(day, t or time(23, 59), tz)
            if t or iso.group(4)
            else _end_of_day(day, tz),
            date_is_exact=True,
            has_time=bool(t or iso.group(4)),
            confidence=0.95,
            explicit=True,
        )

    md = _RE_MONTH_DAY.search(text)
    if md and _has_month(lowered):
        if md.group(1):  # "October 13"
            month = MONTHS.get(md.group(1).lower())
            day_num = int(md.group(2))
        else:  # "13 October"
            day_num = int(md.group(3))
            month = MONTHS.get(md.group(4).lower())
        if month:
            year = ref_date.year
            try:
                day = date(year, month, day_num)
            except ValueError:
                return NormalizedDate(
                    normalized_at=None,
                    date_is_exact=False,
                    has_time=False,
                    confidence=0.2,
                    explicit=False,
                    note="invalid calendar date",
                )
            if day < ref_date - timedelta(days=45):  # clearly a past date → next year
                day = date(year + 1, month, day_num)
            t = _parse_time(lowered)
            return NormalizedDate(
                normalized_at=_combine(day, t, tz) if t else _end_of_day(day, tz),
                date_is_exact=True,
                has_time=t is not None,
                confidence=0.9 if t else 0.88,
                explicit=True,
            )

    # Last resort: strict dateutil parse (only clean unambiguous dates pass).
    try:
        parsed = dateutil_parser.parse(text, default=ref_local.replace(tzinfo=None), fuzzy=False)
    except (ValueError, OverflowError):
        parsed = None
    if parsed is not None and parsed.date() != ref_date:
        t = parsed.time() if (parsed.hour or parsed.minute) else None
        return NormalizedDate(
            normalized_at=_combine(parsed.date(), t or time(23, 59), tz),
            date_is_exact=True,
            has_time=t is not None,
            confidence=0.55,
            explicit=True,
        )

    return NormalizedDate(
        normalized_at=None,
        date_is_exact=False,
        has_time=False,
        confidence=0.15,
        explicit=False,
        note="unrecognized date expression",
    )


def _has_month(lowered: str) -> bool:
    return any(name in lowered for name in MONTHS)


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=UTC)
