"""Unit-тесты для metrics_parser.py.

Риски: Неправильный парсинг ломает всё. Гистограммы — самая сложная часть.
"""

import math
import pytest

from vllm_metrics.metrics_parser import PrometheusParser, MetricSample


# ─── Парсинг строк ─────────────────────────────────────────────────


class TestParseLines:
    """Тесты PrometheusParser.parse()."""

    def test_malformed_input_ignored(self, malformed_metrics_text):
        """Malformed Input: строка без значения, без имени, с мусором → игнорируется."""
        parser = PrometheusParser(skip_system=False)
        samples = parser.parse(malformed_metrics_text)
        # Только валидные метрики должны пройти
        names = [s.name for s in samples]
        assert "valid_metric" in names
        assert "sci_metric" in names
        assert "negative_metric" in names

    def test_labels_parsed(self):
        """Labels: метрика {label="val"} → лейбл сохранён."""
        parser = PrometheusParser(skip_system=False)
        samples = parser.parse('test{foo="bar",num="42"} 1.5')
        assert len(samples) == 1
        assert samples[0].labels == {"foo": "bar", "num": "42"}

    def test_types_assigned(self):
        """Types: # TYPE gauge/counter/histogram → тип присвоен."""
        text = (
            "# TYPE g gauge\n"
            "g 1\n"
            "# TYPE c counter\n"
            "c 2\n"
            "# TYPE h histogram\n"
            "h 3\n"
        )
        parser = PrometheusParser(skip_system=False)
        samples = parser.parse(text)
        types = {s.name: s.metric_type for s in samples}
        assert types == {"g": "gauge", "c": "counter", "h": "histogram"}

    def test_default_type_is_gauge(self):
        """Метрика без TYPE → по умолчанию gauge."""
        parser = PrometheusParser(skip_system=False)
        samples = parser.parse("no_type_metric 42")
        assert samples[0].metric_type == "gauge"

    def test_skip_system_true(self):
        """skip_system=True → python_, process_ отфильтрованы."""
        text = (
            "vllm:test 1\n"
            "python_gc 2\n"
            "process_cpu 3\n"
            "http_requests 4\n"
        )
        parser = PrometheusParser(skip_system=True)
        samples = parser.parse(text)
        names = [s.name for s in samples]
        assert "vllm:test" in names
        assert "python_gc" not in names
        assert "process_cpu" not in names
        assert "http_requests" not in names

    def test_skip_system_false(self):
        """skip_system=False → все метрики проходят."""
        text = (
            "vllm:test 1\n"
            "python_gc 2\n"
            "process_cpu 3\n"
        )
        parser = PrometheusParser(skip_system=False)
        samples = parser.parse(text)
        names = [s.name for s in samples]
        assert "python_gc" in names
        assert "process_cpu" in names

    def test_scientific_notation(self):
        """Значение с научной нотацией (1.5e10)."""
        parser = PrometheusParser(skip_system=False)
        samples = parser.parse("sci 1.5e10")
        assert samples[0].value == 1.5e10

    def test_negative_value(self):
        """Отрицательное значение."""
        parser = PrometheusParser(skip_system=False)
        samples = parser.parse("neg -3.14")
        assert samples[0].value == -3.14

    def test_help_text_saved(self):
        """HELP-текст сохраняется в sample.help_text."""
        text = '# HELP test Help text\ntest 1'
        parser = PrometheusParser(skip_system=False)
        samples = parser.parse(text)
        assert samples[0].help_text == "Help text"


# ─── Гистограммы ───────────────────────────────────────────────────


class TestParseHistogram:
    """Тесты PrometheusParser.parse_histogram()."""

    def test_aggregation(self):
        """_bucket, _sum, _count сгруппированы в один dict."""
        samples = [
            MetricSample("test_bucket", 10, {"le": "1.0"}, metric_type="untyped"),
            MetricSample("test_bucket", 20, {"le": "5.0"}, metric_type="untyped"),
            MetricSample("test_sum", 100.0, metric_type="untyped"),
            MetricSample("test_count", 20, metric_type="untyped"),
        ]
        result = PrometheusParser.parse_histogram(samples)
        assert "test" in result
        assert len(result["test"]["buckets"]) == 2
        assert result["test"]["sum"] == 100.0
        assert result["test"]["count"] == 20

    def test_bucket_sorting(self):
        """Бакеты отсортированы по le."""
        samples = [
            MetricSample("t_bucket", 5, {"le": "5.0"}, metric_type="untyped"),
            MetricSample("t_bucket", 3, {"le": "1.0"}, metric_type="untyped"),
            MetricSample("t_bucket", 10, {"le": "10.0"}, metric_type="untyped"),
        ]
        result = PrometheusParser.parse_histogram(samples)
        les = [le for le, _ in result["t"]["buckets"]]
        assert les == [1.0, 5.0, 10.0]

    def test_inf_label(self):
        """le='+Inf' → float('inf')."""
        samples = [
            MetricSample("t_bucket", 10, {"le": "+Inf"}, metric_type="untyped"),
        ]
        result = PrometheusParser.parse_histogram(samples)
        le, _ = result["t"]["buckets"][0]
        assert math.isinf(le)

    def test_non_histogram_ignored(self):
        """Негистограммные samples пропускаются."""
        samples = [
            MetricSample("plain_gauge", 42, metric_type="gauge"),
        ]
        result = PrometheusParser.parse_histogram(samples)
        assert result == {}

    def test_empty_samples(self):
        """Пустой список samples → пустой dict."""
        result = PrometheusParser.parse_histogram([])
        assert result == {}

    def test_labels_preserved(self):
        """Лейблы (кроме le) сохраняются."""
        samples = [
            MetricSample("t_bucket", 10, {"le": "1.0", "engine": "mp"}, metric_type="untyped"),
        ]
        result = PrometheusParser.parse_histogram(samples)
        assert result["t"]["labels"]["engine"] == "mp"


# ─── Percentiles ───────────────────────────────────────────────────


class TestPercentile:
    """Тесты PrometheusParser.percentile_from_histogram()."""

    def test_normal_p50(self):
        """p50 попадает в средний бакет."""
        buckets = [(1.0, 50.0), (5.0, 100.0), (10.0, 150.0)]
        result = PrometheusParser.percentile_from_histogram(buckets, 0.5)
        assert result == 5.0

    def test_p99_falls_into_inf_returns_last_finite(self):
        """p99 попадает в +Inf → вернуть последний конечный бакет."""
        buckets = [(1.0, 10.0), (5.0, 50.0), (10.0, 90.0), (float("inf"), 100.0)]
        result = PrometheusParser.percentile_from_histogram(buckets, 0.99)
        assert result == 10.0  # Не inf!

    def test_empty_buckets(self):
        """Пустые бакеты → 0.0."""
        result = PrometheusParser.percentile_from_histogram([], 0.5)
        assert result == 0.0

    def test_zero_count(self):
        """total == 0 → 0.0."""
        buckets = [(1.0, 0.0), (5.0, 0.0)]
        result = PrometheusParser.percentile_from_histogram(buckets, 0.5)
        assert result == 0.0

    def test_single_bucket(self):
        """Один бакет → его le."""
        buckets = [(42.0, 100.0)]
        result = PrometheusParser.percentile_from_histogram(buckets, 0.5)
        assert result == 42.0

    def test_p0_returns_first_bucket(self):
        """p0 → первый бакет."""
        buckets = [(1.0, 10.0), (5.0, 50.0), (10.0, 100.0)]
        result = PrometheusParser.percentile_from_histogram(buckets, 0.0)
        assert result == 1.0

    def test_all_inf_buckets(self):
        """Все бакеты +Inf → 0.0."""
        buckets = [(float("inf"), 100.0)]
        result = PrometheusParser.percentile_from_histogram(buckets, 0.99)
        assert result == 0.0
