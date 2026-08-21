"""A repeated scan must not repeat an alert."""

from __future__ import annotations

from app.monitor import reminder_list, run_scan
from app.store import store
from conftest import requires_db


def test_second_scan_reports_nothing_new(db_ready, analysis):
    requires_db(db_ready)
    store.purge()

    first = run_scan("test", "vi")
    assert first["new_count"] == len(analysis.findings)
    assert first["suppressed_count"] == 0

    second = run_scan("test", "vi")
    assert second["new_count"] == 0
    assert second["new"] == []
    assert second["suppressed_count"] == len(analysis.findings)

    third = run_scan("schedule", "vi")
    assert third["new_count"] == 0
    assert third["suppressed_count"] == len(analysis.findings)


def test_fingerprints_are_stable_across_reloads(analysis):
    from app.engine import pipeline

    before = sorted(f.fingerprint for f in analysis.findings)
    pipeline.reset_cache()
    after = sorted(f.fingerprint for f in pipeline.cached().findings)
    assert before == after


def test_reminders_are_created_once_per_finding(db_ready):
    requires_db(db_ready)
    store.purge()
    first = run_scan("test", "vi")
    created = first["reminders_created"]
    assert created > 0
    assert run_scan("test", "vi")["reminders_created"] == 0
    assert len(reminder_list()) == created


def test_journal_records_reason_and_confidence(db_ready):
    requires_db(db_ready)
    store.purge()
    run_scan("test", "vi")
    entries = [row for row in store.audit_entries(500)
               if row["event"] == "flag_raised"]
    assert entries
    for row in entries:
        assert row["kind"]
        assert row["label"] in {"recurring_confirmed", "needs_your_confirmation",
                                "insufficient_data"}
        assert row["confidence"] is not None
        assert row["reason"]
        assert "refs=" in row["reason"]


def test_suppression_is_recorded_in_the_journal(db_ready):
    requires_db(db_ready)
    store.purge()
    run_scan("test", "vi")
    run_scan("test", "vi")
    events = [row["event"] for row in store.audit_entries(500)]
    assert "duplicates_suppressed" in events
