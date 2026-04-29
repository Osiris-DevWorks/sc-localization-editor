"""Tests for src.utils.perf.timed decorator."""

import logging

import pytest
from src.utils.perf import timed

pytestmark = pytest.mark.unit


def test_function_called_when_debug_disabled():
    call_count = []

    @timed
    def add(a, b):
        call_count.append(1)
        return a + b

    result = add(2, 3)
    assert result == 5
    assert call_count == [1]


def test_preserves_function_name():
    @timed
    def my_special_func():
        pass

    assert my_special_func.__name__ == "my_special_func"


def test_with_debug_enabled_logs_timing(caplog):
    @timed
    def multiply(a, b):
        return a * b

    with caplog.at_level(logging.DEBUG, logger="src.utils.perf"):
        result = multiply(3, 4)

    assert result == 12
    assert any("multiply" in r.message for r in caplog.records)


def test_reraises_exception_with_debug_enabled(caplog):
    @timed
    def explode():
        raise ValueError("bang")

    with caplog.at_level(logging.DEBUG, logger="src.utils.perf"):
        with pytest.raises(ValueError, match="bang"):
            explode()

    assert any("raised" in r.message for r in caplog.records)


def test_reraises_exception_without_debug():
    @timed
    def explode():
        raise TypeError("no debug")

    with pytest.raises(TypeError, match="no debug"):
        explode()
