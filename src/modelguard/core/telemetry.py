"""Prometheus and bounded-dimension AWS EMF telemetry boundaries."""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable, Iterable
from enum import StrEnum
from typing import ClassVar, Literal, Protocol

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram
from prometheus_client.exposition import generate_latest

from modelguard.core.config import ApiAccessMode, AppEnvironment, Settings

DecisionLabel = Literal["low_risk", "high_risk"]
ModelLoadOutcome = Literal["success", "failure"]
EventSinkOutcome = Literal["success", "timeout", "failure"]


class ErrorKind(StrEnum):
    """Closed, low-cardinality error categories."""

    AUTH = "auth"
    BODY_TOO_LARGE = "body_too_large"
    CONCURRENCY = "concurrency"
    EVENT_SINK = "event_sink"
    MODEL_LOAD = "model_load"
    NOT_READY = "not_ready"
    PREDICTION = "prediction"
    TRANSPORT = "transport"
    VALIDATION = "validation"


class Telemetry(Protocol):
    """Signals used by the API without coupling routes to a telemetry backend."""

    @property
    def prometheus_content_type(self) -> str:
        """Return the Prometheus exposition media type."""

    def record_http_request(
        self,
        *,
        method: str,
        route: str,
        status_code: int,
        latency_seconds: float,
    ) -> None:
        """Record one completed HTTP request."""

    def record_prediction(self, decision: DecisionLabel) -> None:
        """Record one successfully scored decision."""

    def record_model_load(self, outcome: ModelLoadOutcome, latency_seconds: float) -> None:
        """Record one startup model-load attempt."""

    def record_error(self, kind: ErrorKind) -> None:
        """Record one error using a closed category."""

    def record_event_sink(self, outcome: EventSinkOutcome, latency_seconds: float) -> None:
        """Record one bounded event-sink operation."""

    def render_prometheus(self) -> bytes:
        """Render the local/test Prometheus surface."""


class PrometheusTelemetry:
    """Per-application Prometheus collectors to avoid mutable global registries."""

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry(auto_describe=True)
        self._http_requests = Counter(
            "modelguard_api_requests_total",
            "Completed API requests.",
            ("method", "route", "status_class"),
            registry=self.registry,
        )
        self._http_latency = Histogram(
            "modelguard_api_request_latency_seconds",
            "API request latency in seconds.",
            ("method", "route"),
            buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
            registry=self.registry,
        )
        self._predictions = Counter(
            "modelguard_predictions_total",
            "Successful predictions by locked decision.",
            ("decision",),
            registry=self.registry,
        )
        self._model_loads = Counter(
            "modelguard_model_load_total",
            "Startup model-load attempts.",
            ("outcome",),
            registry=self.registry,
        )
        self._model_load_latency = Histogram(
            "modelguard_model_load_duration_seconds",
            "Model verification and load duration in seconds.",
            ("outcome",),
            buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
            registry=self.registry,
        )
        self._errors = Counter(
            "modelguard_errors_total",
            "Application errors by closed category.",
            ("kind",),
            registry=self.registry,
        )
        self._event_sink = Counter(
            "modelguard_event_sink_operations_total",
            "Prediction event-sink outcomes.",
            ("outcome",),
            registry=self.registry,
        )
        self._event_sink_latency = Histogram(
            "modelguard_event_sink_duration_seconds",
            "Prediction event-sink duration in seconds.",
            ("outcome",),
            buckets=(0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
            registry=self.registry,
        )

    @property
    def prometheus_content_type(self) -> str:
        return CONTENT_TYPE_LATEST

    def record_http_request(
        self,
        *,
        method: str,
        route: str,
        status_code: int,
        latency_seconds: float,
    ) -> None:
        status_class = f"{min(max(status_code, 100), 599) // 100}xx"
        self._http_requests.labels(method=method, route=route, status_class=status_class).inc()
        self._http_latency.labels(method=method, route=route).observe(max(latency_seconds, 0.0))

    def record_prediction(self, decision: DecisionLabel) -> None:
        self._predictions.labels(decision=decision).inc()

    def record_model_load(self, outcome: ModelLoadOutcome, latency_seconds: float) -> None:
        self._model_loads.labels(outcome=outcome).inc()
        self._model_load_latency.labels(outcome=outcome).observe(max(latency_seconds, 0.0))

    def record_error(self, kind: ErrorKind) -> None:
        self._errors.labels(kind=kind.value).inc()

    def record_event_sink(self, outcome: EventSinkOutcome, latency_seconds: float) -> None:
        self._event_sink.labels(outcome=outcome).inc()
        self._event_sink_latency.labels(outcome=outcome).observe(max(latency_seconds, 0.0))

    def render_prometheus(self) -> bytes:
        return generate_latest(self.registry)


EmfWriter = Callable[[str], None]


def _write_stdout(line: str) -> None:
    sys.stdout.write(f"{line}\n")
    sys.stdout.flush()


class EmfTelemetry:
    """Emit EMF events with only three fixed, bounded dimensions."""

    _ERROR_METRIC_NAMES: ClassVar[dict[ErrorKind, str]] = {
        ErrorKind.AUTH: "AuthErrors",
        ErrorKind.BODY_TOO_LARGE: "BodyTooLargeErrors",
        ErrorKind.CONCURRENCY: "ConcurrencyRejections",
        ErrorKind.EVENT_SINK: "EventSinkErrors",
        ErrorKind.MODEL_LOAD: "ModelLoadErrors",
        ErrorKind.NOT_READY: "NotReadyErrors",
        ErrorKind.PREDICTION: "PredictionErrors",
        ErrorKind.TRANSPORT: "TransportErrors",
        ErrorKind.VALIDATION: "ValidationErrors",
    }

    def __init__(
        self,
        *,
        environment: AppEnvironment,
        access_mode: ApiAccessMode,
        writer: EmfWriter = _write_stdout,
        epoch_milliseconds: Callable[[], int] | None = None,
    ) -> None:
        self._dimensions = {
            "Service": "api",
            "Environment": environment.value,
            "AccessMode": access_mode.value,
        }
        self._writer = writer
        self._epoch_milliseconds = epoch_milliseconds or (lambda: time.time_ns() // 1_000_000)

    @property
    def prometheus_content_type(self) -> str:
        return CONTENT_TYPE_LATEST

    def _emit(self, metrics: dict[str, tuple[float, str]]) -> None:
        definitions = [{"Name": name, "Unit": unit} for name, (_, unit) in metrics.items()]
        payload: dict[str, object] = {
            "_aws": {
                "Timestamp": self._epoch_milliseconds(),
                "CloudWatchMetrics": [
                    {
                        "Namespace": "ModelGuardAI",
                        "Dimensions": [["Service", "Environment", "AccessMode"]],
                        "Metrics": definitions,
                    }
                ],
            },
            **self._dimensions,
        }
        payload.update({name: value for name, (value, _) in metrics.items()})
        self._writer(json.dumps(payload, allow_nan=False, separators=(",", ":"), sort_keys=True))

    def record_http_request(
        self,
        *,
        method: str,
        route: str,
        status_code: int,
        latency_seconds: float,
    ) -> None:
        del method, route
        metrics: dict[str, tuple[float, str]] = {
            "ApiRequests": (1.0, "Count"),
            "ApiLatency": (max(latency_seconds, 0.0) * 1_000.0, "Milliseconds"),
        }
        if status_code >= 500:
            metrics["Api5xxErrors"] = (1.0, "Count")
        elif status_code >= 400:
            metrics["Api4xxErrors"] = (1.0, "Count")
        self._emit(metrics)

    def record_prediction(self, decision: DecisionLabel) -> None:
        decision_metric = {
            "low_risk": "LowRiskPredictions",
            "high_risk": "HighRiskPredictions",
        }[decision]
        self._emit({"Predictions": (1.0, "Count"), decision_metric: (1.0, "Count")})

    def record_model_load(self, outcome: ModelLoadOutcome, latency_seconds: float) -> None:
        outcome_metric = {
            "success": "ModelLoadSuccess",
            "failure": "ModelLoadFailure",
        }[outcome]
        self._emit(
            {
                outcome_metric: (1.0, "Count"),
                "ModelLoadLatency": (max(latency_seconds, 0.0) * 1_000.0, "Milliseconds"),
            }
        )

    def record_error(self, kind: ErrorKind) -> None:
        self._emit(
            {
                "ApplicationErrors": (1.0, "Count"),
                self._ERROR_METRIC_NAMES[kind]: (1.0, "Count"),
            }
        )

    def record_event_sink(self, outcome: EventSinkOutcome, latency_seconds: float) -> None:
        outcome_metric = {
            "success": "EventSinkSuccess",
            "timeout": "EventSinkTimeout",
            "failure": "EventSinkFailure",
        }[outcome]
        self._emit(
            {
                outcome_metric: (1.0, "Count"),
                "EventSinkLatency": (max(latency_seconds, 0.0) * 1_000.0, "Milliseconds"),
            }
        )

    def render_prometheus(self) -> bytes:
        return b""


class CompositeTelemetry:
    """Fan out signals while retaining one canonical Prometheus renderer."""

    def __init__(
        self,
        prometheus: PrometheusTelemetry,
        additional_sinks: Iterable[Telemetry] = (),
    ) -> None:
        self._prometheus = prometheus
        self._sinks: tuple[Telemetry, ...] = (prometheus, *tuple(additional_sinks))

    @property
    def prometheus_content_type(self) -> str:
        return self._prometheus.prometheus_content_type

    def record_http_request(
        self,
        *,
        method: str,
        route: str,
        status_code: int,
        latency_seconds: float,
    ) -> None:
        for sink in self._sinks:
            sink.record_http_request(
                method=method,
                route=route,
                status_code=status_code,
                latency_seconds=latency_seconds,
            )

    def record_prediction(self, decision: DecisionLabel) -> None:
        for sink in self._sinks:
            sink.record_prediction(decision)

    def record_model_load(self, outcome: ModelLoadOutcome, latency_seconds: float) -> None:
        for sink in self._sinks:
            sink.record_model_load(outcome, latency_seconds)

    def record_error(self, kind: ErrorKind) -> None:
        for sink in self._sinks:
            sink.record_error(kind)

    def record_event_sink(self, outcome: EventSinkOutcome, latency_seconds: float) -> None:
        for sink in self._sinks:
            sink.record_event_sink(outcome, latency_seconds)

    def render_prometheus(self) -> bytes:
        return self._prometheus.render_prometheus()


def build_telemetry(
    settings: Settings,
    *,
    emf_writer: EmfWriter = _write_stdout,
) -> CompositeTelemetry:
    """Build Prometheus in every mode and add EMF only in AWS mode."""

    prometheus = PrometheusTelemetry()
    additional: tuple[Telemetry, ...] = ()
    if settings.app_env is AppEnvironment.AWS:
        additional = (
            EmfTelemetry(
                environment=settings.app_env,
                access_mode=settings.api_access_mode,
                writer=emf_writer,
            ),
        )
    return CompositeTelemetry(prometheus, additional)
