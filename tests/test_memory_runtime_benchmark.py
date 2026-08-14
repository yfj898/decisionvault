from scripts.benchmark_memory_runtime import _percentile


def test_runtime_benchmark_percentile_is_bounded_and_deterministic():
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert _percentile(values, 0.0) == 10.0
    assert _percentile(values, 0.5) == 30.0
    assert _percentile(values, 0.95) == 50.0
    assert _percentile(values, 1.0) == 50.0
    assert _percentile([], 0.95) == 0.0
