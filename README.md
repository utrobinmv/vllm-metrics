# vllm-metrics

Real-time консольный дашборд для мониторинга vLLM сервера.

Забирает метрики с `/metrics` endpoint (Prometheus format) и отображает их в терминале с автоматическим обновлением.

## Установка

```bash
# Из репозитория
pip install git+https://github.com/krapotkin/vllm-metrics.git

# Или локально (разработка)
pip install -e ".[dev]"
```

## Использование

```bash
# Запуск (читает .env)
vllm-metrics

# С параметрами
vllm-metrics --url http://192.168.45.10:30000/metrics --interval 1
vllm-metrics --all-metrics    # + сырые метрики
```

## Настройка

Файл `.env` в корне проекта:

```ini
VLLM_METRICS_URL=http://192.168.45.10:30000/metrics
VLLM_BASE_URL=http://192.168.45.10:30000/v1
VLLM_API_KEY=sk-vllm-...
VLLM_MODEL=Qwen3.6-27B-FP8
REFRESH_INTERVAL=2
```

Приоритет: env-переменные > `.env` файл > значения по умолчанию.

## Что мониторит

### REAL-TIME (зелёная рамка) — обновляется каждые N сек

- **Server Info** — модель, uptime, engine state, `vllm:kv_cache_usage_perc`, `vllm:estimated_flops_per_gpu_total` (rate)
- **VLLM Stats** — `vllm:avg_prompt_throughput_toks_per_s`, `vllm:avg_generation_throughput_toks_per_s`, `vllm:num_requests_swapped`, `vllm:time_since_last_ppu_update`
- **Live Requests** — `vllm:num_requests_running`, `vllm:num_requests_waiting`, `vllm:request_success_total` (rate)
- **Live Throughput** — `vllm:prompt_tokens_total` (rate), `vllm:generation_tokens_total` (rate)
- **Live Process** — `process_virtual_memory_bytes`, `process_resident_memory_bytes`, `process_cpu_seconds_total` (rate), `process_open_fds`

### LIFETIME (синяя рамка) — накопительные счётчики

- **Total Requests** — `vllm:request_success_total` по reason (stop/length/error), `vllm:num_preemptions_total`
- **Total Tokens** — prompt/generation/cached токены, cache hit rate, prefix hit rate
- **Cache Details** — prefix/external prefix/mm cache queries/hits + hit rate, `vllm:kv_cache_usage_perc`
- **HTTP** — `http_requests_total` по method+status, latency percentiles (p50/p95/p99)
- **Python GC** — `python_gc_collections_total` по generation (0/1/2)

### PERCENTILES (фиолетовая рамка) — кумулятивные гистограммы

- **Latency** — TTFT, inter-token, e2e, prefill, decode, queue, inference, time-per-output-token (p50/p90/p99)
- **Throughput Details** — prompt tokens, generation tokens, iteration tokens, KV computed, max gen tokens, params max tokens (avg/p50/p95)

## Тестирование

```bash
pip install -e ".[dev]"
pytest tests/ -v --cov=vllm_metrics --cov-report=term-missing
```

Результаты: **54 теста, 76% покрытие**.

## Архитектура

```
vllm-metrics (CLI)
├── vllm_metrics.config      → .env + os.environ
├── vllm_metrics.metrics_parser  → Prometheus text format parser
├── vllm_metrics.dashboard   → MetricsCollector + Dashboard (Rich panels)
└── vllm_metrics.cli         → CLI entry point + Live loop
```

## Лицензия

MIT
