"""Unit tests for telemetry.metrics module."""

from unittest.mock import Mock, patch

from telemetry.metrics import (
    _Instruments,
    _get_instance,
    _get_meter,
    _initialize_instruments,
    record_latency_operation_a,
    increment_http_request_handled,
    register_asynchronous_gauge,
)


def test_record_latency_operation_a() -> None:
    """Test recording latency operation."""
    with patch("telemetry.metrics._get_instance") as mock_get_instance:
        mock_instruments = Mock()
        mock_histogram = Mock()
        mock_instruments.latency_operation_a = mock_histogram
        mock_get_instance.return_value = mock_instruments

        record_latency_operation_a(150, "test_resource")

        mock_histogram.record.assert_called_once_with(150, attributes={"resource": "test_resource"})


def test_increment_http_request_handled() -> None:
    """Test incrementing HTTP request counter."""
    with patch("telemetry.metrics._get_instance") as mock_get_instance:
        mock_instruments = Mock()
        mock_counter = Mock()
        mock_instruments.http_request_handled = mock_counter
        mock_get_instance.return_value = mock_instruments

        increment_http_request_handled("GET", 200)

        mock_counter.add.assert_called_once_with(1, attributes={"http.resource": "request", "http.method": "GET", "http.status_code": 200})


def test_register_asynchronous_gauge() -> None:
    """Test registering an asynchronous gauge."""
    with patch("telemetry.metrics._get_meter") as mock_get_meter:
        mock_meter = Mock()
        mock_gauge = Mock()
        mock_meter.create_observable_gauge.return_value = mock_gauge
        mock_get_meter.return_value = mock_meter

        def get_value() -> int:
            return 42

        register_asynchronous_gauge(
            name="test_gauge", description="A test gauge", unit="count", get_current_value=get_value, attributes={"environment": "test"}
        )

        mock_meter.create_observable_gauge.assert_called_once()


# Tests for internal functions and classes


def test_instruments_class() -> None:
    """Test _Instruments class initialization."""
    instruments = _Instruments()

    assert instruments.latency_operation_a is None
    assert instruments.memory_server is None
    assert instruments.http_request_handled is None


def test_get_instance_singleton() -> None:
    """Test that _get_instance returns a singleton."""
    # Reset the global instance
    import telemetry.metrics

    telemetry.metrics._instance = None

    instance1 = _get_instance()
    instance2 = _get_instance()

    assert instance1 is instance2
    assert isinstance(instance1, _Instruments)


@patch("telemetry.metrics._initialize_instruments")
def test_get_instance_calls_initialize(mock_init: Mock) -> None:
    """Test that _get_instance calls _initialize_instruments."""
    # Reset the global instance
    import telemetry.metrics

    telemetry.metrics._instance = None

    _get_instance()

    mock_init.assert_called_once()


@patch("telemetry.metrics.metrics.get_meter")
def test_get_meter_with_env_var(mock_get_meter: Mock) -> None:
    """Test _get_meter uses APPLICATION environment variable."""
    import os

    mock_meter = Mock()
    mock_get_meter.return_value = mock_meter

    with patch.dict(os.environ, {"APPLICATION": "test-app"}):
        result = _get_meter()

    mock_get_meter.assert_called_once_with("test-app")
    assert result is mock_meter


@patch("telemetry.metrics.metrics.get_meter")
def test_get_meter_default_name(mock_get_meter: Mock) -> None:
    """Test _get_meter uses default name when APPLICATION not set."""
    import os

    mock_meter = Mock()
    mock_get_meter.return_value = mock_meter

    with patch.dict(os.environ, {}, clear=True):
        result = _get_meter()

    mock_get_meter.assert_called_once_with("local-app")
    assert result is mock_meter


@patch("telemetry.metrics._get_meter")
def test_initialize_instruments_creates_all_instruments(mock_get_meter: Mock) -> None:
    """Test that _initialize_instruments creates all required instruments."""
    mock_meter = Mock()
    mock_histogram = Mock()
    mock_counter = Mock()

    mock_meter.create_histogram.return_value = mock_histogram
    mock_meter.create_counter.return_value = mock_counter
    mock_get_meter.return_value = mock_meter

    instruments = _Instruments()
    _initialize_instruments(instruments)

    # Verify histogram creation
    mock_meter.create_histogram.assert_called_once_with(
        name="latency_operation_a", description="The latency of the processed operation named A", unit="ms"
    )

    # Verify counter creation
    mock_meter.create_counter.assert_called_once_with(name="http_requests_total", description="The total number of HTTP requests")

    # Verify instruments are set
    assert instruments.latency_operation_a is mock_histogram
    assert instruments.http_request_handled is mock_counter
