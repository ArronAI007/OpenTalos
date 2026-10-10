from observability.metrics import Metrics


def test_counter_renders_with_type():
    metrics = Metrics()
    metrics.inc("hits_total")
    metrics.inc("hits_total")

    text = metrics.render()
    assert "# TYPE hits_total counter" in text
    assert "hits_total 2" in text


def test_counter_labels_are_sorted_and_escaped():
    metrics = Metrics()
    metrics.inc("calls_total", labels={"tool": "echo", "status": "ok"})

    assert 'calls_total{status="ok",tool="echo"} 1' in metrics.render()


def test_observation_renders_summary_count_and_sum():
    metrics = Metrics()
    metrics.observe("dur_seconds", 0.5)
    metrics.observe("dur_seconds", 1.5)

    text = metrics.render()
    assert "# TYPE dur_seconds summary" in text
    assert "dur_seconds_count 2" in text
    assert "dur_seconds_sum 2" in text


def test_gauge_and_reset():
    metrics = Metrics()
    metrics.set_gauge("open_connections", 3)
    assert "open_connections 3" in metrics.render()

    metrics.reset()
    assert metrics.render() == ""
