"""`media/probe.py`: só a conta pura de `creation_time` (o resto de `probe()` é ffprobe de verdade,
coberto pela integração)."""

from __future__ import annotations

from datetime import UTC, datetime

from dmaker.media.probe import _creation_time


def test_creation_time_parses_utc_iso8601_with_z_suffix():
    moment = _creation_time({"tags": {"creation_time": "2024-03-10T14:30:00.000000Z"}})
    assert moment == datetime(2024, 3, 10, 14, 30, 0, tzinfo=UTC).timestamp()


def test_creation_time_assumes_utc_without_timezone():
    moment = _creation_time({"tags": {"creation_time": "2024-03-10T14:30:00"}})
    assert moment == datetime(2024, 3, 10, 14, 30, 0, tzinfo=UTC).timestamp()


def test_creation_time_missing_or_invalid_is_none():
    assert _creation_time({}) is None
    assert _creation_time({"tags": {}}) is None
    assert _creation_time({"tags": {"creation_time": "não é uma data"}}) is None
