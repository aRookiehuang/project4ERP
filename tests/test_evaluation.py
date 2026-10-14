from evaluation.run import equivalent, summarize


def test_failed_attempt_stays_in_denominator():
    result = summarize(
        [
            {"correct": True, "completed": True, "http_ms": 100},
            {"correct": False, "completed": False, "http_ms": 10},
        ]
    )
    assert result["accuracy"] == 0.5
    assert result["joint_correct_http_under_3s"] == 0.5
    assert result["http_p95_incomplete"] and result["http_p95_ms"] is None


def test_unordered_result_preserves_duplicates():
    assert not equivalent([{"x": 1}, {"x": 1}], [{"x": 1}], ordered=False)
