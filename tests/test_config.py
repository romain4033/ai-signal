from datetime import date, datetime, timezone

from ai_signal.config import load_settings


def test_settings_load():
    s = load_settings()
    assert s.models.triage == "claude-haiku-5-5"
    assert s.price_for("claude-sonnet-5-5").output == 10.0
    assert s.web_search_price == 0.01


def test_daily_window():
    s = load_settings()
    start, end = s.window(date(2026, 11, 12))
    assert end == datetime(2026, 11, 12, 8, tzinfo=timezone.utc)
    assert start == datetime(2026, 11, 11, 8, tzinfo=timezone.utc)


def test_weekly_window():
    s = load_settings().model_copy(update={"frequency": "weekly"})
    start, end = s.window(date(2026, 11, 12))
    assert (end - start).days == 7
    assert s.edition_size.max_stories == 15
