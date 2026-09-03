from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.temporal.normalizer import CONFIRM_THRESHOLD, normalize_when

TZ = "Asia/Jakarta"
# Reference: Wednesday, 2026-09-02 (user's "today")
REF = datetime(2026, 9, 2, 10, 0, tzinfo=ZoneInfo(TZ))


def norm(text: str):
    return normalize_when(text, reference=REF, tz_name=TZ)


def test_explicit_date_with_time():
    result = norm("11:59 PM on September 12")
    assert result.normalized_at is not None
    assert result.normalized_at.day == 12 and result.normalized_at.month == 9
    assert result.normalized_at.hour == 23 and result.normalized_at.minute == 59
    assert result.explicit and result.confidence >= CONFIRM_THRESHOLD
    assert result.date_is_exact and result.has_time


def test_month_day_eod():
    result = norm("October 13")
    assert result.normalized_at is not None
    assert (result.normalized_at.year, result.normalized_at.month, result.normalized_at.day) == (
        2026,
        10,
        13,
    )
    assert result.normalized_at.hour == 23  # date-only deadlines default to end of day
    assert result.confidence >= CONFIRM_THRESHOLD and result.explicit


def test_month_day_with_24h_time():
    result = norm("Oct 13 at 23:59")
    assert result.normalized_at.hour == 23 and result.normalized_at.minute == 59
    assert result.has_time


def test_day_month_order():
    result = norm("13 October")
    assert result.normalized_at is not None
    assert (result.normalized_at.month, result.normalized_at.day) == (10, 13)


def test_iso_date():
    result = norm("2026-10-20")
    assert (result.normalized_at.month, result.normalized_at.day) == (10, 20)
    assert result.confidence == 0.95


def test_iso_datetime():
    result = norm("2026-10-20T13:00")
    assert result.normalized_at.hour == 13 and result.has_time


def test_next_friday():
    result = norm("next Friday")
    assert result.normalized_at is not None
    # Reference Wed 2026-09-02 → next week's Friday = 2026-09-11
    assert (result.normalized_at.month, result.normalized_at.day) == (9, 11)
    assert not result.explicit
    assert result.confidence < CONFIRM_THRESHOLD and result.needs_review


def test_bare_weekday_coming_friday():
    result = norm("Friday")
    # Reference Wed → the coming Friday = 2026-09-04
    assert (result.normalized_at.month, result.normalized_at.day) == (9, 4)


def test_tomorrow():
    result = norm("tomorrow")
    assert result.normalized_at.day == 3
    assert result.confidence < CONFIRM_THRESHOLD


def test_in_n_days():
    result = norm("in 3 days")
    assert result.normalized_at.day == 5


def test_vague_never_resolves():
    result = norm("sometime next week")
    assert result.normalized_at is None
    assert result.confidence < 0.4 and result.needs_review


def test_event_anchored_never_resolves():
    result = norm("before the midterm")
    assert result.normalized_at is None and result.needs_review


def test_end_of_semester_review():
    result = norm("end of semester")
    assert result.normalized_at is None and result.needs_review


def test_week_number_needs_course_anchor():
    result = norm("week 7")
    assert result.normalized_at is None and result.needs_review
    assert "course" in result.note


def test_recurrence_detected():
    result = norm("every Monday")
    assert result.is_recurrence
    assert not result.needs_review  # handled as recurrence, not uncertainty
    assert result.normalized_at is None


def test_past_date_rolls_to_next_year():
    result = norm("January 5")  # 2026-01-05 is long past the reference
    assert result.normalized_at.year == 2027


def test_invalid_calendar_date():
    result = norm("February 30")
    assert result.normalized_at is None and result.confidence <= 0.2


def test_garbage_low_confidence():
    result = norm("whenever really")
    assert result.normalized_at is None and result.needs_review
