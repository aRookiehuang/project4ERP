from backend.app.reports import report_html


def test_untrusted_report_text_is_escaped():
    payload = {
        "question": '<script>alert("x")</script>',
        "answer": '<img src="https://evil.example">',
        "columns": [{"key": "name", "label": "<b>客户</b>", "unit": ""}],
        "rows": [{"name": "<iframe>"}],
        "time_range": {"start": "2026-09-01", "end": "2026-10-01"},
        "metric_definitions": {},
        "assumptions": [],
        "data_coverage": ["2024-11-01", "2026-11-01"],
        "versions": {"data": "v1"},
        "snapshot_at": "2026-10-14",
        "query_id": "test",
        "truncated": False,
        "sql_display": "SELECT <unsafe>",
    }
    rendered = report_html(payload, True)
    assert "<script>" not in rendered and "<iframe>" not in rendered and '<img src="https' not in rendered
    assert "&lt;script&gt;" in rendered and "&lt;unsafe&gt;" in rendered
