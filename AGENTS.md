# vllm-metrics — AGENTS.md

## Архитектура

```
vllm-metrics (CLI entry point: vllm_metrics.cli:cli)
├── vllm_metrics/__init__.py       → __version__ = "0.1.0"
├── vllm_metrics/config.py         → load_config() — .env + os.environ
├── vllm_metrics/metrics_parser.py → PrometheusParser, MetricSample
├── vllm_metrics/dashboard.py      → MetricsCollector, Dashboard + 12 панелей
└── vllm_metrics/cli.py            → parse_args(), cli() — Rich Live loop
```

**pip-пакет** с `src/` layout. Установка: `pip install -e ".[dev]"`.

## Панели дашборда (12 штук, 3 секции)

### REAL-TIME (зелёная рамка, обновляется каждые N сек)
1. **Server Info** — модель, uptime, engine state, `vllm:kv_cache_usage_perc`, `vllm:estimated_flops_per_gpu_total` (rate)
2. **VLLM Stats** — avg prompt/gen throughput, swapped requests, PPU update time
3. **Live Requests** — running/waiting requests, success rate
4. **Live Throughput** — prompt/gen token rates
5. **Live Process** — virt/res mem, CPU rate, open/max FDs

### LIFETIME (синяя рамка, накопительные)
6. **Total Requests** — success by reason (stop/length/error), preemptions
7. **Total Tokens** — prompt/gen/cached tokens, cache hit rate, prefix hit rate
8. **Cache Details** — prefix/ext-prefix/mm cache queries/hits + hit rate, KV usage
9. **HTTP** — requests by method+status, latency percentiles (p50/p95/p99)
10. **Python GC** — collections by generation (0/1/2)

### PERCENTILES (фиолетовая рамка, кумулятивные)
11. **Latency** — 8 метрик (TTFT, inter-token, e2e, prefill, decode, queue, inference, time-per-output-token), p50/p90/p99
12. **Throughput Details** — 6 histogram метрик (prompt tokens, gen tokens, iteration tokens, KV computed, max gen tokens, params max tokens), avg/p50/p95

## Ключевые детали

- **Метрики названы как в Prometheus** — `vllm:kv_cache_usage_perc`, не "KV Cache"
- **Нет эмодзи** — чистый текстовый интерфейс
- **Нет plotext/графиков** — только Rich Tables + Panels
- **`_rate()`** — вычисляет delta/T для counter-метрик между опросами
- **`kv_color()`** — green (<0.7), yellow (0.7-0.9), red (>0.9) для KV cache usage
- **Config priority**: env vars > `.env` file > defaults
- **`.env` ищется** через `Path(__file__).parent.parent.parent / ".env"` (корень проекта)

## Тестовая стратегия (risk-based)

| Уровень | Файл | Что тестирует | Почему |
|---|---|---|---|
| Unit | test_parser.py | Парсинг Prometheus, histogram, percentiles | Парсинг — основа всего |
| Unit | test_config.py | Приоритет env > .env > default | Неправильный приоритет = недоступный сервер |
| Unit | test_utils.py | Форматирование, rate calc, kv_color | Математика, division by zero |
| Integration | test_collector.py | HTTP fetch, API key, error handling | Сетевое взаимодействие |
| Integration | test_dashboard.py | Пустые/нулевые данные → не краш | UI resilience |
| E2E | test_cli.py | `--help`, недоступный URL | Запуск приложения |

**Результаты:** 54 теста, 76% покрытие.

## Запуск

```bash
source .venv
vllm-metrics                          # из .env
vllm-metrics --url ... --interval 1   # с параметрами
vllm-metrics --all-metrics            # + сырые метрики
python -m vllm_metrics.cli            # альтернативный запуск
```

## Тестирование

```bash
source .venv
python -m pytest tests/ -v --cov=vllm_metrics --cov-report=term-missing
```
