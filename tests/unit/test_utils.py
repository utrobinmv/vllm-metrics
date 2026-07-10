"""Unit-тесты для утилит dashboard.py.

Риски: Математические ошибки, деление на ноль, отрицательные числа.
"""

import time
import pytest

from vllm_metrics.dashboard import fmt_bytes, fmt_tokens, fmt_time, fmt_uptime, kv_color, Dashboard


class TestFormatting:
    """Тесты функций форматирования."""

    def test_fmt_bytes_negative(self):
        """fmt_bytes: отрицательное число → 'N/A'."""
        assert fmt_bytes(-1) == "N/A"

    def test_fmt_bytes_ranges(self):
        """fmt_bytes: B, KB, MB, GB, TB."""
        assert fmt_bytes(500) == "500.0B"
        assert fmt_bytes(1500) == "1.5KB"
        assert fmt_bytes(1_500_000) == "1.4MB"
        assert fmt_bytes(1_500_000_000) == "1.4GB"
        assert fmt_bytes(1_500_000_000_000) == "1.4TB"

    def test_fmt_tokens_ranges(self):
        """fmt_tokens: < 1K, 1K–1M, 1M–1B, 1B+."""
        assert fmt_tokens(500) == "500"
        assert fmt_tokens(1500) == "1.5K"
        assert fmt_tokens(1_500_000) == "1.50M"
        assert fmt_tokens(1_500_000_000) == "1.50B"

    def test_fmt_time_boundaries(self):
        """fmt_time: переходы границ µs → ms → s → min."""
        assert "us" in fmt_time(0.0005)
        assert "ms" in fmt_time(0.05)
        assert "s" in fmt_time(5.5)
        assert "m" in fmt_time(120.0)

    def test_fmt_uptime_boundaries(self):
        """fmt_uptime: переходы min → hours → days."""
        assert fmt_uptime(300) == "5m"
        assert "h" in fmt_uptime(3700)
        assert "d" in fmt_uptime(90000)


class TestRateCalculation:
    """Тесты Dashboard._rate()."""

    def _make_dashboard(self):
        return Dashboard(config={"metrics_url": "http://test", "model": "test"})

    def test_first_call_returns_zero(self):
        """First Call: нет предыдущего значения → rate = 0."""
        d = self._make_dashboard()
        rate = d._rate("test", 100)
        assert rate == 0

    def test_normal_rate(self):
        """Normal: рост за время T → rate = delta / T."""
        d = self._make_dashboard()
        d._rate("test", 100)  # first call
        time.sleep(0.1)
        rate = d._rate("test", 110)  # delta=10, time≈0.1
        assert rate > 80  # ~100 tok/s

    def test_no_change_rate_is_zero(self):
        """No Change: counter не вырос → rate = 0."""
        d = self._make_dashboard()
        d._rate("test", 100)
        time.sleep(0.05)
        rate = d._rate("test", 100)
        assert rate == 0

    def test_counter_reset_rate_is_zero(self):
        """Counter Reset: counter уменьшился → rate = 0 (не отрицательное!)."""
        d = self._make_dashboard()
        d._rate("test", 100)
        time.sleep(0.05)
        rate = d._rate("test", 50)  # сброс
        assert rate == 0


class TestKvColor:
    """Тесты kv_color()."""

    def test_green(self):
        assert kv_color(0.5) == "green"

    def test_yellow(self):
        assert kv_color(0.75) == "yellow"

    def test_red(self):
        assert kv_color(0.95) == "red"

    def test_boundary_07(self):
        # 0.7 — граница: > 0.7 → yellow, == 0.7 → green
        assert kv_color(0.7) == "green"
        assert kv_color(0.71) == "yellow"

    def test_boundary_09(self):
        # 0.9 — граница: > 0.9 → red, == 0.9 → yellow
        assert kv_color(0.9) == "yellow"
        assert kv_color(0.91) == "red"
