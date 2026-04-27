from services.english_service.core.metrics import Metrics


def test_metrics_increment_and_reset():
    Metrics.reset()
    Metrics.inc("semantic_rejections")
    Metrics.inc("semantic_rejections", 2)

    snapshot = Metrics.snapshot()

    assert snapshot["semantic_rejections"] == 3

    Metrics.reset()
    assert Metrics.snapshot()["semantic_rejections"] == 0