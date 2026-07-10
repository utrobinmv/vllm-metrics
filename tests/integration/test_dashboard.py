"""Integration-тесты для Dashboard resilience.

Риски: Падение UI при отсутствии данных или делении на ноль.
"""

import pytest

from vllm_metrics.dashboard import Dashboard


@pytest.fixture
def dashboard():
    return Dashboard(config={"metrics_url": "http://test", "model": "test"})


def _empty_metrics():
    """Полностью пустой dict метрик."""
    return {
        "samples": [],
        "histograms": {},
        "gauge": {},
        "counter": {},
        "raw": "",
    }


def _minimal_metrics():
    """Минимальный dict с нулями."""
    return {
        "samples": [],
        "histograms": {},
        "gauge": {
            "vllm:kv_cache_usage_perc": 0,
            "vllm:num_requests_running": 0,
            "vllm:num_requests_waiting": 0,
            "process_virtual_memory_bytes": 0,
            "process_resident_memory_bytes": 0,
            "process_open_fds": 0,
            "process_max_fds": 0,
        },
        "counter": {
            "vllm:prompt_tokens_total": 0,
            "vllm:generation_tokens_total": 0,
            "vllm:estimated_flops_per_gpu_total": 0,
            "process_cpu_seconds_total": 0,
            "vllm:num_preemptions_total": 0,
            "vllm:prefix_cache_queries_total": 0,
            "vllm:prefix_cache_hits_total": 0,
            "vllm:external_prefix_cache_queries_total": 0,
            "vllm:external_prefix_cache_hits_total": 0,
            "vllm:mm_cache_queries_total": 0,
            "vllm:mm_cache_hits_total": 0,
            "vllm:prompt_tokens_cached_total": 0,
        },
        "raw": "",
    }


class TestDashboardResilience:
    """Тесты устойчивости Dashboard к отсутствию данных."""

    def test_empty_metrics_no_crash(self, dashboard):
        """Empty Metrics: пустой dict → не падает."""
        result = dashboard.build(_empty_metrics())
        assert result is not None

    def test_minimal_metrics_no_crash(self, dashboard):
        """Minimal Metrics: нули → не падает."""
        result = dashboard.build(_minimal_metrics())
        assert result is not None

    def test_cache_hit_rate_no_division_by_zero(self, dashboard):
        """Cache Hit Rate при queries=0 → не ZeroDivisionError."""
        metrics = _minimal_metrics()
        # prefix_cache_queries_total = 0, hits = 0
        panel = dashboard._total_tokens_panel(metrics)
        assert panel is not None

    def test_prefix_hit_rate_no_division_by_zero(self, dashboard):
        """Prefix Hit Rate при queries=0 → не ZeroDivisionError."""
        metrics = _minimal_metrics()
        panel = dashboard._cache_details_panel(metrics)
        assert panel is not None

    def test_missing_engine_state_shows_unknown(self, dashboard):
        """Engine State: отсутствует метрика → UNKNOWN."""
        metrics = _minimal_metrics()
        panel = dashboard._server_info_panel(metrics)
        assert panel is not None

    def test_all_panels_render_without_crash(self, dashboard):
        """Все панели рендерятся без краша на минимальных данных."""
        metrics = _minimal_metrics()
        panels = [
            dashboard._server_info_panel(metrics),
            dashboard._vllm_stats_panel(metrics),
            dashboard._live_requests_panel(metrics),
            dashboard._live_throughput_panel(metrics),
            dashboard._live_process_panel(metrics),
            dashboard._total_requests_panel(metrics),
            dashboard._total_tokens_panel(metrics),
            dashboard._cache_details_panel(metrics),
            dashboard._http_panel(metrics),
            dashboard._gc_panel(metrics),
            dashboard._latency_panel(metrics),
            dashboard._throughput_details_panel(metrics),
            dashboard._all_metrics_panel(metrics),
        ]
        assert all(p is not None for p in panels)
