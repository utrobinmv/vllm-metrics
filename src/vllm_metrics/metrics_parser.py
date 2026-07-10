"""vllm-metrics — Парсер Prometheus-формата метрик.

Разбирает текстовый формат Prometheus (text/plain; version=0.0.4)
в структурированные данные: gauge, counter, histogram.
"""

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MetricSample:
    """Одно значение метрики с лейблами."""
    name: str
    value: float
    labels: dict = field(default_factory=dict)
    help_text: str = ""
    metric_type: str = "gauge"  # gauge | counter | histogram


class PrometheusParser:
    """Парсит Prometheus text exposition format."""

    # Игнорируем служебные метрики Python/Prometheus client
    SKIP_PREFIXES = (
        "python_",
        "process_",
        "http_request",
        "http_response",
    )

    def __init__(self, skip_system: bool = True):
        self.skip_system = skip_system
        self._help_texts: dict[str, str] = {}
        self._metric_types: dict[str, str] = {}

    def parse(self, text: str) -> list[MetricSample]:
        """Полный парсинг текста метрик."""
        self._help_texts.clear()
        self._metric_types.clear()
        samples: list[MetricSample] = []

        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue

            # HELP
            if line.startswith("# HELP "):
                parts = line[7:].split(" ", 1)
                if len(parts) == 2:
                    self._help_texts[parts[0]] = parts[1]
                continue

            # TYPE
            if line.startswith("# TYPE "):
                parts = line[7:].split()
                if len(parts) >= 2:
                    self._metric_types[parts[0]] = parts[1]
                continue

            # Comment
            if line.startswith("#"):
                continue

            # Data line: metric_name{labels} value  or  metric_name value
            sample = self._parse_line(line)
            if sample is not None:
                if self.skip_system and any(
                    sample.name.startswith(p) for p in self.SKIP_PREFIXES
                ):
                    continue
                samples.append(sample)

        return samples

    def _parse_line(self, line: str) -> Optional[MetricSample]:
        """Парсит одну строку данных."""
        # metric_name{label="value",...} value
        match = re.match(
            r'^([a-zA-Z_:][a-zA-Z0-9_:]*)'   # name
            r'(?:\{(.*)\})?'                   # optional labels
            r'\s+([\d.eE+\-]+)$',              # value
            line,
        )
        if not match:
            return None

        name = match.group(1)
        labels_str = match.group(2) or ""
        value = float(match.group(3))

        labels = {}
        if labels_str:
            for lm in re.finditer(r'(\w+)="([^"]*)"', labels_str):
                labels[lm.group(1)] = lm.group(2)

        return MetricSample(
            name=name,
            value=value,
            labels=labels,
            help_text=self._help_texts.get(name, ""),
            metric_type=self._metric_types.get(name, "gauge"),
        )

    @staticmethod
    def parse_histogram(samples: list[MetricSample]) -> dict[str, dict]:
        """
        Группирует histogram-образцы по базовому имени.
        Возвращает {base_name: {"buckets": [(le, count), ...], "sum": float, "count": float, "labels": {}}}
        """
        histograms: dict[str, dict] = {}

        for s in samples:
            if s.name.endswith("_bucket"):
                base = s.name[: -len("_bucket")]
            elif s.name.endswith("_sum"):
                base = s.name[: -len("_sum")]
            elif s.name.endswith("_count"):
                base = s.name[: -len("_count")]
            else:
                continue

            if base not in histograms:
                histograms[base] = {
                    "buckets": [],
                    "sum": None,
                    "count": None,
                    "labels": {},
                    "help": s.help_text,
                }

            if s.name.endswith("_bucket"):
                le = float(s.labels.get("le", "inf"))
                histograms[base]["buckets"].append((le, s.value))
            elif s.name.endswith("_sum"):
                histograms[base]["sum"] = s.value
            elif s.name.endswith("_count"):
                histograms[base]["count"] = s.value

            # Сохраняем лейблы (engine, model_name) из первого образца
            for k, v in s.labels.items():
                if k not in ("le",):
                    histograms[base]["labels"][k] = v

        # Сортируем бакеты
        for h in histograms.values():
            h["buckets"].sort(key=lambda x: x[0])

        return histograms

    @staticmethod
    def percentile_from_histogram(buckets: list[tuple[float, float]], pct: float) -> float:
        """
        Оценивает перцентиль из histogram бакетов.
        buckets: [(le, cumulative_count), ...]
        pct: 0.0–1.0
        Возвращает float. Если перцентиль попадает в +Inf бакет, возвращает
        предыдущий конечный бакет.
        """
        if not buckets:
            return 0.0
        total = buckets[-1][1]
        if total == 0:
            return 0.0
        target = pct * total
        result = 0.0
        for le, count in buckets:
            if count >= target:
                result = le
                break
        # Если попали в +Inf, возвращаем предыдущий бакет
        import math
        if math.isinf(result):
            # Ищем последний конечный бакет
            for le, _ in reversed(buckets):
                if not math.isinf(le):
                    return le
            return 0.0
        return result
