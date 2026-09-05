from datetime import date, time

from app.processing import RecurringRule, expand_recurring_rules


def test_recurring_summary_explains_actual_semester_bounds():
    rule = RecurringRule(
        title="Homework", event_type="assignment", rule_kind="weekly_fixed",
        weekday="wednesday", end_time=time(23, 59), is_all_day=False,
        source_quote="Homework is due every Wednesday at 11:59 PM.", source_page=1,
        confidence="medium",
    )
    series, events = expand_recurring_rules(
        anchors=[], rules=[rule], semester_start=date(2025, 9, 1),
        semester_end=date(2025, 12, 16), explicit_events=[], extraction_model=None,
    )
    assert len(series) == 1
    summary = series[0].rule_summary
    assert "2025-09-01" in summary and "2025-12-16" in summary
    assert "semester" in summary.lower()
    assert "None" not in summary
    assert all(event.derivation_summary == summary for event in events)
    assert rule.boundary_start is None and rule.boundary_end is None
