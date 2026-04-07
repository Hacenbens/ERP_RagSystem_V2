"""
Unit tests for the observability module — Sprint 1 DoD gate.

Coverage targets (>= 80%):
    src/observability/__init__.py
    src/observability/prometheus_metrics.py
    src/observability/structured_logger.py

Also covers integration of /metrics route (admin.py) with the middleware stack.

Run:
    pytest src/tests/unit/test_observability.py -v --cov=src/observability
"""
from __future__ import annotations

import json
import logging
import io
from contextvars import copy_context

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from src.observability.structured_logger import (
    StructuredLogger,
    _JSONFormatter,
    get_logger,
    get_trace_id,
    get_user_id,
    set_trace_context,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _capture_logger(name: str) -> tuple[StructuredLogger, io.StringIO]:
    """Return a StructuredLogger wired to an in-memory buffer."""
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(_JSONFormatter())
    log = logging.getLogger(name)
    log.addHandler(handler)
    log.setLevel(logging.DEBUG)
    return get_logger(name), buf


def _fresh_registry():
    """Return a fresh CollectorRegistry to avoid cross-test metric pollution."""
    from prometheus_client import CollectorRegistry
    return CollectorRegistry()


# ---------------------------------------------------------------------------
# structured_logger — basic emission
# ---------------------------------------------------------------------------

class TestStructuredLoggerEmission:
    """Logger emits valid JSON with all required fields."""

    def test_info_emits_valid_json(self):
        logger, buf = _capture_logger("test.info_json")
        logger.info("test.event", component="unit_test")
        line = buf.getvalue().strip()
        parsed = json.loads(line)
        assert parsed["event"] == "test.event"
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test.info_json"
        assert "timestamp" in parsed

    def test_debug_level(self):
        logger, buf = _capture_logger("test.debug")
        logger.debug("test.debug_event", detail="low_level")
        parsed = json.loads(buf.getvalue().strip())
        assert parsed["level"] == "DEBUG"
        assert parsed["detail"] == "low_level"

    def test_warning_level(self):
        logger, buf = _capture_logger("test.warning")
        logger.warning("test.warn_event")
        parsed = json.loads(buf.getvalue().strip())
        assert parsed["level"] == "WARNING"

    def test_error_level(self):
        logger, buf = _capture_logger("test.error")
        logger.error("test.error_event", error="something broke")
        parsed = json.loads(buf.getvalue().strip())
        assert parsed["level"] == "ERROR"
        assert parsed["error"] == "something broke"

    def test_critical_level(self):
        logger, buf = _capture_logger("test.critical")
        logger.critical("test.critical_event")
        parsed = json.loads(buf.getvalue().strip())
        assert parsed["level"] == "CRITICAL"

    def test_extra_keyword_fields_merged(self):
        logger, buf = _capture_logger("test.extras")
        logger.info("test.extras_event", user_count=42, status_code=200, flag=True)
        parsed = json.loads(buf.getvalue().strip())
        assert parsed["user_count"] == 42
        assert parsed["status_code"] == 200
        assert parsed["flag"] is True

    def test_required_fields_always_present(self):
        logger, buf = _capture_logger("test.required_fields")
        logger.info("test.required")
        parsed = json.loads(buf.getvalue().strip())
        for field in ("timestamp", "level", "logger", "event", "trace_id", "user_id"):
            assert field in parsed, f"Missing required field: {field}"

    def test_get_logger_returns_same_instance(self):
        a = get_logger("test.singleton")
        b = get_logger("test.singleton")
        assert a is b

    def test_get_logger_different_names_are_distinct(self):
        a = get_logger("test.name_a")
        b = get_logger("test.name_b")
        assert a is not b


# ---------------------------------------------------------------------------
# structured_logger — trace_id / user_id context propagation
# ---------------------------------------------------------------------------

class TestTraceContextPropagation:
    """trace_id and user_id propagate via contextvars."""

    def test_empty_context_by_default(self):
        # Run in a fresh context to avoid bleed from other tests
        def _check():
            assert get_trace_id() == ""
            assert get_user_id() == ""
        copy_context().run(_check)

    def test_set_trace_context_binds_values(self):
        def _check():
            set_trace_context(trace_id="abc-123", user_id="user-42")
            assert get_trace_id() == "abc-123"
            assert get_user_id() == "user-42"
        copy_context().run(_check)

    def test_log_line_includes_trace_id(self):
        logger, buf = _capture_logger("test.trace_in_log")

        def _emit():
            set_trace_context(trace_id="trace-xyz", user_id="user-7")
            logger.info("test.traced_event", latency_ms=10, status=200)

        copy_context().run(_emit)
        parsed = json.loads(buf.getvalue().strip())
        assert parsed["trace_id"] == "trace-xyz"
        assert parsed["user_id"] == "user-7"
        assert parsed["latency_ms"] == 10
        assert parsed["status"] == 200

    def test_trace_id_does_not_bleed_across_contexts(self):
        logger, buf = _capture_logger("test.no_bleed")

        def _ctx_a():
            set_trace_context(trace_id="ctx-a", user_id="")
            logger.info("test.ctx_a")

        def _ctx_b():
            # ctx_b never calls set_trace_context — should see empty string
            logger.info("test.ctx_b")

        copy_context().run(_ctx_a)
        copy_context().run(_ctx_b)

        lines = [json.loads(raw) for raw in buf.getvalue().strip().splitlines() if raw]
        ctx_a_line = next(rec for rec in lines if rec["event"] == "test.ctx_a")
        ctx_b_line = next(rec for rec in lines if rec["event"] == "test.ctx_b")
        assert ctx_a_line["trace_id"] == "ctx-a"
        assert ctx_b_line["trace_id"] == ""


# ---------------------------------------------------------------------------
# prometheus_metrics — counter increments
# ---------------------------------------------------------------------------

class TestPrometheusCounters:
    """All Sprint 1 required counters increment correctly."""

    def test_auth_failure_rate_increments(self):
        from src.observability.prometheus_metrics import AUTH_FAILURE_RATE
        from prometheus_client import REGISTRY

        before = self._sample_value(
            REGISTRY, "erp_rag_auth_failures_total", {"reason": "expired"}
        )
        AUTH_FAILURE_RATE.labels(reason="expired").inc()
        after = self._sample_value(
            REGISTRY, "erp_rag_auth_failures_total", {"reason": "expired"}
        )
        assert after - before == pytest.approx(1.0)

    def test_auth_failure_rate_distinct_labels(self):
        from src.observability.prometheus_metrics import AUTH_FAILURE_RATE
        from prometheus_client import REGISTRY

        AUTH_FAILURE_RATE.labels(reason="tampered").inc(3)
        val = self._sample_value(
            REGISTRY, "erp_rag_auth_failures_total", {"reason": "tampered"}
        )
        assert val >= 3.0

    def test_rbac_violation_rate_increments(self):
        from src.observability.prometheus_metrics import RBAC_VIOLATION_RATE
        from prometheus_client import REGISTRY

        before = self._sample_value(
            REGISTRY, "erp_rag_rbac_violations_total",
            {"role": "ANALYST", "resource": "/admin"},
        )
        RBAC_VIOLATION_RATE.labels(role="ANALYST", resource="/admin").inc()
        after = self._sample_value(
            REGISTRY, "erp_rag_rbac_violations_total",
            {"role": "ANALYST", "resource": "/admin"},
        )
        assert after - before == pytest.approx(1.0)

    def test_pii_detection_rate_increments(self):
        from src.observability.prometheus_metrics import PII_DETECTION_RATE
        from prometheus_client import REGISTRY

        before = self._sample_value(
            REGISTRY, "erp_rag_pii_detections_total", {"entity_type": "email"}
        )
        PII_DETECTION_RATE.labels(entity_type="email").inc(2)
        after = self._sample_value(
            REGISTRY, "erp_rag_pii_detections_total", {"entity_type": "email"}
        )
        assert after - before == pytest.approx(2.0)

    def test_request_count_increments(self):
        from src.observability.prometheus_metrics import REQUEST_COUNT
        from prometheus_client import REGISTRY

        before = self._sample_value(
            REGISTRY, "erp_rag_requests_total",
            {"method": "GET", "endpoint": "/test", "status_code": "200"},
        )
        REQUEST_COUNT.labels(method="GET", endpoint="/test", status_code="200").inc()
        after = self._sample_value(
            REGISTRY, "erp_rag_requests_total",
            {"method": "GET", "endpoint": "/test", "status_code": "200"},
        )
        assert after - before == pytest.approx(1.0)

    # ------------------------------------------------------------------
    # helper
    # ------------------------------------------------------------------

    @staticmethod
    def _sample_value(registry, metric_name: str, labels: dict) -> float:
        """Look up a single sample value by metric name + label set."""
        for metric in registry.collect():
            for sample in metric.samples:
                if sample.name == metric_name and sample.labels == labels:
                    return sample.value
        return 0.0


# ---------------------------------------------------------------------------
# prometheus_metrics — histogram observe
# ---------------------------------------------------------------------------

class TestPrometheusHistogram:
    """REQUEST_LATENCY histogram records observations correctly."""

    def test_request_latency_observe(self):
        from src.observability.prometheus_metrics import REQUEST_LATENCY
        from prometheus_client import REGISTRY

        REQUEST_LATENCY.labels(
            method="POST", endpoint="/api/erp/query", status_code="200"
        ).observe(0.123)

        # Find the _sum sample — should be > 0 after observe()
        for metric in REGISTRY.collect():
            for sample in metric.samples:
                if (
                    sample.name == "erp_rag_request_latency_seconds_sum"
                    and sample.labels.get("endpoint") == "/api/erp/query"
                ):
                    assert sample.value > 0
                    return
        pytest.fail("erp_rag_request_latency_seconds_sum sample not found")

    def test_request_latency_count_increments(self):
        from src.observability.prometheus_metrics import REQUEST_LATENCY
        from prometheus_client import REGISTRY

        before = self._count(REGISTRY, "DELETE", "/test_hist", "404")
        REQUEST_LATENCY.labels(
            method="DELETE", endpoint="/test_hist", status_code="404"
        ).observe(0.05)
        after = self._count(REGISTRY, "DELETE", "/test_hist", "404")
        assert after - before == pytest.approx(1.0)

    @staticmethod
    def _count(registry, method, endpoint, status_code) -> float:
        for metric in registry.collect():
            for sample in metric.samples:
                if (
                    sample.name == "erp_rag_request_latency_seconds_count"
                    and sample.labels.get("method") == method
                    and sample.labels.get("endpoint") == endpoint
                ):
                    return sample.value
        return 0.0


# ---------------------------------------------------------------------------
# GET /metrics endpoint — Sprint 1 DoD gate
# ---------------------------------------------------------------------------

class TestMetricsEndpoint:
    """GET /metrics returns 200 with valid Prometheus text format."""

    @pytest.fixture()
    def client(self) -> TestClient:
        from src.routes.admin import router
        from src.middleware.AuthMiddleware import AuthMiddleware

        app = FastAPI()
        app.add_middleware(AuthMiddleware)
        app.include_router(router)
        return TestClient(app, raise_server_exceptions=True)

    def test_metrics_returns_200(self, client: TestClient):
        r = client.get("/metrics")
        assert r.status_code == 200

    def test_metrics_content_type(self, client: TestClient):
        from prometheus_client import CONTENT_TYPE_LATEST
        r = client.get("/metrics")
        assert r.headers["content-type"] == CONTENT_TYPE_LATEST

    def test_metrics_contains_help_and_type_lines(self, client: TestClient):
        r = client.get("/metrics")
        lines = r.text.splitlines()
        assert any(line.startswith("# HELP") for line in lines)
        assert any(line.startswith("# TYPE") for line in lines)

    def test_metrics_contains_erp_rag_metrics(self, client: TestClient):
        r = client.get("/metrics")
        erp_lines = [line for line in r.text.splitlines() if line.startswith("erp_rag_")]
        assert len(erp_lines) > 0, "No erp_rag_* metrics found in /metrics output"

    def test_metrics_accessible_without_auth_token(self, client: TestClient):
        """DoD: Prometheus scraper must not need a Bearer token."""
        r = client.get("/metrics")   # no Authorization header
        assert r.status_code == 200

    def test_metrics_body_is_text_not_json(self, client: TestClient):
        r = client.get("/metrics")
        # Must NOT be JSON — Prometheus expects plain text
        with pytest.raises(Exception):
            json.loads(r.text)


# ---------------------------------------------------------------------------
# observability __init__ — public API
# ---------------------------------------------------------------------------

class TestObservabilityPackage:
    """Package exposes __version__ and get_logger via __init__."""

    def test_version_defined(self):
        import src.observability as obs
        assert hasattr(obs, "__version__")
        assert isinstance(obs.__version__, str)

    def test_all_defined(self):
        import src.observability as obs
        assert hasattr(obs, "__all__")
        assert "get_logger" in obs.__all__

    def test_get_logger_via_package(self):
        import src.observability as obs
        logger = obs.get_logger("test.via_package")
        assert isinstance(logger, StructuredLogger)
