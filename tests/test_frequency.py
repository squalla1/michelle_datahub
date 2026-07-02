from datahub.scheduler.frequency import parse_frequency


def test_realtime_is_interval():
    spec = parse_frequency("实时")
    assert spec.kind == "interval"
    assert spec.seconds and spec.seconds > 0


def test_minute_range_takes_lower_bound():
    spec = parse_frequency("10-15分钟")
    assert spec.kind == "interval"
    assert spec.seconds == 10 * 60


def test_explicit_minutes():
    assert parse_frequency("每5分钟").kind == "interval"


def test_calendar_cadences():
    assert parse_frequency("每日").kind == "cron"
    assert parse_frequency("每周").kind == "cron"
    assert parse_frequency("每月").kind == "cron"


def test_blank_and_irregular_are_manual():
    assert parse_frequency("").kind == "manual"
    assert parse_frequency("不定期").kind == "manual"
    assert parse_frequency("按provider").kind == "manual"
