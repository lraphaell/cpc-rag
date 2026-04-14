"""
Package telemetry provides helper functions to record service metrics
using the OpenTelemetry Python SDK. The following code is an example of how a healthy metric helper should be implemented
Users may feel free to erase or change it to fit their needs

Quick reference

 1. Instruments should be created only once. Metric names should be attached to instruments and appear in this file exclusively.
  In the example:
    - latency_operation_a   (Histogram): internal operation "a" latency in ms
    - memory_server         (ObservableGauge): memory usage of the server
    - http_request_handled  (Counter): total HTTP requests processed

 2. Usage example:
    from telemetry import record_latency_operation_a, increment_http_request_handled, register_asynchronous_gauge

    # ... business logic ...

    # Histogram
    record_latency_operation_a(1000), "generate_invoice")

    # Counter
    increment_http_request_handled("GET", 200)

    # Observable Gauge with value supplier function
    def get_random_value():
        return random.randint(0, 100)

    register_asynchronous_gauge(
        name="test_observable_gauge",
        description="A custom gauge metric that changes over time",
        unit="ms",
        get_current_value=lambda: get_random_value(),
        attributes={"test": "true"}
    )

 3. Conventions:
    • Instrument names are snake_case and describe *what* is being measured.
    • Attributes/labels use snake_case keys and whenever possible follow the OTel semantic conventions (as shown in the examples)
    • Always use the helper functions provided rather than accessing instruments directly.

To extend:
  - Add a new instrument to the _Instruments class.
  - Instantiate it inside _initialize_instruments() with its corresponding metric name and description.
  - Expose a helper function that records or adds values following the patterns in the examples.
  - Metric attributes should be passed as primitive arguments to the helper functions (as shown in the examples)

More info:

O11y Docs: https://furydocs.io/o11y-docs/latest/guide/#

OTel: https://opentelemetry.io/docs/specs/semconv/general/metrics
"""

import os
import threading
from typing import Optional, Callable, Dict, Any

from opentelemetry import metrics
from opentelemetry.metrics import Meter, Counter, Histogram, ObservableGauge, Observation


class _Instruments:
    """Internal container class to hold metric instruments."""

    def __init__(self) -> None:
        self.latency_operation_a: Optional[Histogram] = None
        self.memory_server: Optional[ObservableGauge] = None
        self.http_request_handled: Optional[Counter] = None


_instance: Optional[_Instruments] = None
_instance_lock = threading.Lock()


def _get_instance() -> _Instruments:
    global _instance

    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = _Instruments()
                _initialize_instruments(_instance)

    return _instance


def _get_meter() -> Meter:
    return metrics.get_meter(os.getenv("APPLICATION", "local-app"))


def _initialize_instruments(instruments: _Instruments) -> None:
    meter = _get_meter()

    # Create latency histogram
    instruments.latency_operation_a = meter.create_histogram(
        name="latency_operation_a", description="The latency of the processed operation named A", unit="ms"
    )
    # Create HTTP request counter
    instruments.http_request_handled = meter.create_counter(name="http_requests_total", description="The total number of HTTP requests")


def record_latency_operation_a(latency_ms: int, resource: str) -> None:
    instruments = _get_instance()
    if instruments.latency_operation_a is not None:
        instruments.latency_operation_a.record(latency_ms, attributes={"resource": resource})


def increment_http_request_handled(http_method: str, status_code: int) -> None:
    instruments = _get_instance()
    if instruments.http_request_handled is not None:
        instruments.http_request_handled.add(
            1, attributes={"http.resource": "request", "http.method": http_method, "http.status_code": status_code}
        )


def register_asynchronous_gauge(
    name: str, description: str, unit: str, get_current_value: Callable[[], int], attributes: Optional[Dict[str, Any]] = None
) -> None:
    """Register an asynchronous gauge that observes values via a callback function.

    Args:
        name: The name of the metric
        description: Description of what the metric measures
        unit: The unit of measurement (e.g., 'bytes', 'ms', 'count')
        get_current_value: Function that returns the current value to observe
        attributes: Optional attributes to include with the metric
    """

    def callback(callback_options: Any) -> list[Observation]:
        try:
            value = get_current_value()
        except Exception:
            return []
        if attributes:
            return [Observation(value, attributes)]
        else:
            return [Observation(value)]

    meter = _get_meter()
    meter.create_observable_gauge(name=name, description=description, unit=unit, callbacks=[callback])
