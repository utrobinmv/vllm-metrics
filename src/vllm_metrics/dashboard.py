"""vllm-metrics — Real-time консольный дашборд для мониторинга vLLM сервера.

Использует Rich Live Display.
Забирает метрики с /metrics endpoint в формате Prometheus.

Секции:
  1. REAL-TIME (зелёная рамка) — меняется каждые N сек
     Server Info, VLLM Stats, Live Requests, Live Throughput, Live Process
  2. LIFETIME (синяя рамка) — накопительные счётчики
     Total Requests, Total Tokens, Cache Details, HTTP, GC
  3. PERCENTILES (фиолетовая рамка) — кумулятивные гистограммы
     Latency, Throughput Details
"""

import time
import requests
from datetime import datetime

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.columns import Columns
from rich.console import Group as RichGroup

from .metrics_parser import PrometheusParser


# ─── Утилиты форматирования ─────────────────────────────────────────

def fmt_bytes(n: float) -> str:
    """Форматирует байты в читаемый вид."""
    if n < 0:
        return "N/A"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}PB"


def fmt_tokens(n: float) -> str:
    """Форматирует число токенов."""
    if n >= 1e9:
        return f"{n/1e9:.2f}B"
    if n >= 1e6:
        return f"{n/1e6:.2f}M"
    if n >= 1e3:
        return f"{n/1e3:.1f}K"
    return f"{n:.0f}"


def fmt_time(s: float) -> str:
    """Форматирует секунды."""
    if s < 0.001:
        return f"{s*1e6:.0f}us"
    if s < 1:
        return f"{s*1000:.1f}ms"
    if s < 60:
        return f"{s:.2f}s"
    return f"{s/60:.1f}m"


def fmt_uptime(seconds: float) -> str:
    """Форматирует uptime."""
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    mins = int((seconds % 3600) // 60)
    if days > 0:
        return f"{days}d {hours}h {mins}m"
    if hours > 0:
        return f"{hours}h {mins}m"
    return f"{mins}m"


def kv_color(value: float) -> str:
    """Цвет для vllm:kv_cache_usage_perc."""
    if value > 0.9:
        return "red"
    if value > 0.7:
        return "yellow"
    return "green"


# ─── Сборщик метрик ─────────────────────────────────────────────────

class MetricsCollector:
    """Забирает и парсит метрики с vLLM сервера."""

    def __init__(self, metrics_url: str, api_key: str = ""):
        self.metrics_url = metrics_url
        self.headers = {}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"
        self.parser = PrometheusParser(skip_system=False)

    def fetch(self) -> str:
        """Забирает сырые метрики."""
        resp = requests.get(self.metrics_url, headers=self.headers, timeout=10)
        resp.raise_for_status()
        return resp.text

    def collect(self) -> dict:
        """
        Собирает и структурирует все метрики.
        """
        raw = self.fetch()
        samples = self.parser.parse(raw)
        histograms = self.parser.parse_histogram(samples)

        gauge = {}
        counter = {}
        for s in samples:
            if s.metric_type == "gauge":
                gauge[s.name] = s.value
            elif s.metric_type == "counter":
                counter[s.name] = s.value

        return {
            "samples": samples,
            "histograms": histograms,
            "gauge": gauge,
            "counter": counter,
            "raw": raw,
        }


# ─── Панели дашборда ────────────────────────────────────────────────

class Dashboard:
    """Строит Rich-дашборд из собранных метрик."""

    def __init__(self, config: dict):
        self.config = config
        self.start_time = time.time()
        self.prev_counters: dict[str, float] = {}
        self.console = Console()

    def _rate(self, name: str, value: float) -> float:
        """Вычисляет rate (изменение в секунду) для counter-метрик."""
        now = time.time()
        prev_val, prev_time = self.prev_counters.get(name, (value, now))
        rate = (value - prev_val) / max(now - prev_time, 0.001)
        self.prev_counters[name] = (value, now)
        return max(rate, 0)

    # ── REAL-TIME ──────────────────────────────────────────────────

    def _server_info_panel(self, metrics: dict) -> Panel:
        """Верхняя панель: информация о сервере."""
        g = metrics["gauge"]
        c = metrics["counter"]

        model = self.config.get("model", "unknown")
        url = self.config["metrics_url"].replace("/metrics", "")

        uptime = time.time() - self.start_time
        process_start = g.get("process_start_time_seconds", 0)
        server_uptime = time.time() - process_start if process_start > 0 else uptime

        # KV Cache usage — только число
        kv_usage = g.get("vllm:kv_cache_usage_perc", 0)
        kv_text = Text(f"{kv_usage*100:.1f}%", style=f"bold {kv_color(kv_usage)}")

        # Engine state
        engine_awake = engine_offloaded = engine_discard = 0
        for s in metrics["samples"]:
            if s.name == "vllm:engine_sleep_state":
                state = s.labels.get("sleep_state", "")
                if state == "awake":
                    engine_awake = s.value
                elif state == "weights_offloaded":
                    engine_offloaded = s.value
                elif state == "discard_all":
                    engine_discard = s.value

        if engine_awake >= 1:
            engine_status = Text("AWAKE", style="bold green")
        elif engine_offloaded >= 1:
            engine_status = Text("WEIGHTS_OFFLOADED", style="bold yellow")
        elif engine_discard >= 1:
            engine_status = Text("DISCARD_ALL", style="bold red")
        else:
            engine_status = Text("UNKNOWN", style="bold white")

        # GPU FLOPs (rate)
        flops_total = c.get("vllm:estimated_flops_per_gpu_total", 0)
        flops_rate = self._rate("vllm:estimated_flops_per_gpu_total", flops_total)

        content = Table(show_header=False, box=None, padding=(0, 1))
        content.add_column("Metric", style="bold cyan", width=38)
        content.add_column("Value", style="white")

        content.add_row("Server", f"{url}")
        content.add_row("Model", model)
        content.add_row("Uptime", fmt_uptime(server_uptime))
        content.add_row("vllm:engine_sleep_state", engine_status)
        content.add_row("vllm:kv_cache_usage_perc", kv_text)
        content.add_row("vllm:estimated_flops_per_gpu_total (rate)", f"{flops_rate:.2e}" if flops_rate > 0 else "idle")

        title = f" vLLM METRICS  │  {datetime.now().strftime('%H:%M:%S')} "
        return Panel(content, title=title, border_style="bold green", padding=(0, 1))

    def _vllm_stats_panel(self, metrics: dict) -> Panel:
        """Панель: дополнительные gauge-метрики vLLM."""
        g = metrics["gauge"]

        avg_prompt = g.get("vllm:avg_prompt_throughput_toks_per_s", 0)
        avg_gen = g.get("vllm:avg_generation_throughput_toks_per_s", 0)
        swapped = g.get("vllm:num_requests_swapped", 0)
        ppu_time = g.get("vllm:time_since_last_ppu_update", 0)

        content = Table(show_header=False, box=None, padding=(0, 1))
        content.add_column("Metric", style="bold cyan", width=38)
        content.add_column("Value", style="white", justify="right")

        content.add_row("vllm:avg_prompt_throughput_toks_per_s", f"{avg_prompt:.1f}")
        content.add_row("vllm:avg_generation_throughput_toks_per_s", f"{avg_gen:.1f}")
        content.add_row("vllm:num_requests_swapped", f"{swapped:.0f}")
        content.add_row("vllm:time_since_last_ppu_update", fmt_time(ppu_time))

        return Panel(content, title=" VLLM STATS ", border_style="green", padding=(0, 1))

    def _live_requests_panel(self, metrics: dict) -> Panel:
        """Панель: текущие запросы и скорость."""
        g = metrics["gauge"]
        running = g.get("vllm:num_requests_running", 0)
        waiting = g.get("vllm:num_requests_waiting", 0)

        total_success = 0
        for s in metrics["samples"]:
            if s.name == "vllm:request_success_total":
                total_success += s.value
        success_rate = self._rate("vllm:request_success_total", total_success)

        content = Table(show_header=False, box=None, padding=(0, 1))
        content.add_column("Metric", style="bold cyan", width=38)
        content.add_column("Value", style="white", justify="right")

        run_style = "green" if running > 0 else "dim"
        wait_style = "red" if waiting > 3 else ("yellow" if waiting > 0 else "green")

        content.add_row("vllm:num_requests_running", f"[bold {run_style}]{running:.0f}")
        content.add_row("vllm:num_requests_waiting", f"[bold {wait_style}]{waiting:.0f}")
        content.add_row("vllm:request_success_total (rate)", f"{success_rate:.2f}")

        return Panel(content, title=" LIVE REQUESTS ", border_style="green", padding=(0, 1))

    def _live_throughput_panel(self, metrics: dict) -> Panel:
        """Панель: текущая скорость токенов."""
        c = metrics["counter"]
        prompt_total = c.get("vllm:prompt_tokens_total", 0)
        gen_total = c.get("vllm:generation_tokens_total", 0)

        prompt_rate = self._rate("vllm:prompt_tokens_total", prompt_total)
        gen_rate = self._rate("vllm:generation_tokens_total", gen_total)

        content = Table(show_header=False, box=None, padding=(0, 1))
        content.add_column("Metric", style="bold cyan", width=38)
        content.add_column("Value", style="white", justify="right")

        content.add_row("vllm:prompt_tokens_total (rate)", f"[bold green]{prompt_rate:.1f}")
        content.add_row("vllm:generation_tokens_total (rate)", f"[bold green]{gen_rate:.1f}")

        return Panel(content, title=" LIVE THROUGHPUT ", border_style="green", padding=(0, 1))

    def _live_process_panel(self, metrics: dict) -> Panel:
        """Панель: текущие системные метрики."""
        g = metrics["gauge"]
        c = metrics["counter"]

        virt_mem = g.get("process_virtual_memory_bytes", 0)
        res_mem = g.get("process_resident_memory_bytes", 0)
        cpu_sec = c.get("process_cpu_seconds_total", 0)
        open_fds = g.get("process_open_fds", 0)
        max_fds = g.get("process_max_fds", 0)

        cpu_rate = self._rate("process_cpu_seconds_total", cpu_sec)

        content = Table(show_header=False, box=None, padding=(0, 1))
        content.add_column("Metric", style="bold cyan", width=38)
        content.add_column("Value", style="white", justify="right")

        content.add_row("process_virtual_memory_bytes", fmt_bytes(virt_mem))
        content.add_row("process_resident_memory_bytes", fmt_bytes(res_mem))
        content.add_row("process_cpu_seconds_total (rate)", f"{cpu_rate:.2f}")
        content.add_row("process_open_fds", f"{open_fds:.0f} / {max_fds:.0f}")

        return Panel(content, title=" LIVE PROCESS ", border_style="green", padding=(0, 1))

    # ── LIFETIME ───────────────────────────────────────────────────

    def _total_requests_panel(self, metrics: dict) -> Panel:
        """Панель: накопленная статистика запросов."""
        c = metrics["counter"]
        preemptions = c.get("vllm:num_preemptions_total", 0)

        success_stop = success_length = success_error = 0
        for s in metrics["samples"]:
            if s.name == "vllm:request_success_total":
                reason = s.labels.get("finished_reason", "")
                if reason == "stop":
                    success_stop = s.value
                elif reason == "length":
                    success_length = s.value
                elif reason == "error":
                    success_error = s.value

        err_style = "red" if success_error > 0 else "green"

        content = Table(show_header=False, box=None, padding=(0, 1))
        content.add_column("Metric", style="bold cyan", width=40)
        content.add_column("Value", style="white", justify="right")

        content.add_row("vllm:request_success_total{stop}", f"{success_stop:.0f}")
        content.add_row("vllm:request_success_total{length}", f"{success_length:.0f}")
        content.add_row("vllm:request_success_total{error}", f"[bold {err_style}]{success_error:.0f}")
        content.add_row("vllm:num_preemptions_total", f"{preemptions:.0f}")

        return Panel(content, title=" TOTAL REQUESTS ", border_style="blue", padding=(0, 1))

    def _total_tokens_panel(self, metrics: dict) -> Panel:
        """Панель: накопленные токены и hit rates."""
        c = metrics["counter"]
        prompt_total = c.get("vllm:prompt_tokens_total", 0)
        gen_total = c.get("vllm:generation_tokens_total", 0)
        cached_total = c.get("vllm:prompt_tokens_cached_total", 0)

        local_compute = local_cache = 0
        for s in metrics["samples"]:
            if s.name == "vllm:prompt_tokens_by_source_total":
                src = s.labels.get("source", "")
                if src == "local_compute":
                    local_compute = s.value
                elif src == "local_cache_hit":
                    local_cache = s.value

        cache_hit_rate = local_cache / max(local_compute + local_cache, 1) * 100

        prefix_queries = c.get("vllm:prefix_cache_queries_total", 0)
        prefix_hits = c.get("vllm:prefix_cache_hits_total", 0)
        prefix_hit_rate = prefix_hits / max(prefix_queries, 1) * 100

        content = Table(show_header=False, box=None, padding=(0, 1))
        content.add_column("Metric", style="bold cyan", width=40)
        content.add_column("Value", style="white", justify="right")

        content.add_row("vllm:prompt_tokens_total", fmt_tokens(prompt_total))
        content.add_row("vllm:generation_tokens_total", fmt_tokens(gen_total))
        content.add_row("vllm:prompt_tokens_cached_total", fmt_tokens(cached_total))
        content.add_row("")
        content.add_row("vllm:prompt_tokens_by_source_total (hit%)", f"{cache_hit_rate:.1f}%")
        content.add_row("vllm:prefix_cache_hits_total / queries", f"{prefix_hit_rate:.1f}%")

        return Panel(content, title=" TOTAL TOKENS ", border_style="blue", padding=(0, 1))

    def _cache_details_panel(self, metrics: dict) -> Panel:
        """Панель: детализация кэширования."""
        c = metrics["counter"]
        g = metrics["gauge"]

        prefix_queries = c.get("vllm:prefix_cache_queries_total", 0)
        prefix_hits = c.get("vllm:prefix_cache_hits_total", 0)
        ext_queries = c.get("vllm:external_prefix_cache_queries_total", 0)
        ext_hits = c.get("vllm:external_prefix_cache_hits_total", 0)
        mm_queries = c.get("vllm:mm_cache_queries_total", 0)
        mm_hits = c.get("vllm:mm_cache_hits_total", 0)

        kv_usage = g.get("vllm:kv_cache_usage_perc", 0)

        def hit_rate(q, h):
            if q == 0:
                return "N/A"
            return f"{h/q*100:.1f}%"

        kv_text = Text(f"{kv_usage*100:.1f}%", style=f"bold {kv_color(kv_usage)}")

        content = Table(show_header=False, box=None, padding=(0, 1))
        content.add_column("Metric", style="bold cyan", width=40)
        content.add_column("Queries", style="white", justify="right")
        content.add_column("Hits", style="green", justify="right")
        content.add_column("Hit Rate", style="yellow", justify="right")

        content.add_row("vllm:prefix_cache_*_total", fmt_tokens(prefix_queries),
                        fmt_tokens(prefix_hits), hit_rate(prefix_queries, prefix_hits))
        content.add_row("vllm:external_prefix_cache_*_total", fmt_tokens(ext_queries),
                        fmt_tokens(ext_hits), hit_rate(ext_queries, ext_hits))
        content.add_row("vllm:mm_cache_*_total", fmt_tokens(mm_queries),
                        fmt_tokens(mm_hits), hit_rate(mm_queries, mm_hits))
        content.add_row("")
        content.add_row("vllm:kv_cache_usage_perc", kv_text, "", "")

        return Panel(content, title=" CACHE DETAILS ", border_style="blue", padding=(0, 1))

    def _http_panel(self, metrics: dict) -> Panel:
        """Панель: HTTP метрики."""
        h = metrics["histograms"]
        parser = PrometheusParser()

        http_counts: dict[str, float] = {}
        for s in metrics["samples"]:
            if s.name == "http_requests_total":
                method = s.labels.get("method", "")
                status = s.labels.get("status", "")
                key = f"{method} {status}"
                http_counts[key] = s.value

        def http_pct(p: float) -> str:
            hist = h.get("http_request_duration_highr_seconds")
            if not hist or not hist["buckets"]:
                return "N/A"
            return fmt_time(parser.percentile_from_histogram(hist["buckets"], p))

        content = Table(show_header=False, box=None, padding=(0, 1))
        content.add_column("Metric", style="bold cyan", width=40)
        content.add_column("Value", style="white", justify="right")

        for key in sorted(http_counts.keys()):
            content.add_row(f"http_requests_total{{{key}}}", f"{http_counts[key]:.0f}")

        if not http_counts:
            content.add_row("http_requests_total", "No data")

        content.add_row("")
        content.add_row("http_request_duration_highr_seconds p50", f"[green]{http_pct(0.5)}")
        content.add_row("http_request_duration_highr_seconds p95", f"[yellow]{http_pct(0.95)}")
        content.add_row("http_request_duration_highr_seconds p99", f"[red]{http_pct(0.99)}")

        return Panel(content, title=" HTTP ", border_style="blue", padding=(0, 1))

    def _gc_panel(self, metrics: dict) -> Panel:
        """Панель: сборщик мусора Python."""
        gc_0 = gc_1 = gc_2 = 0
        for s in metrics["samples"]:
            if s.name == "python_gc_collections_total":
                gen = s.labels.get("generation", "")
                if gen == "0":
                    gc_0 = s.value
                elif gen == "1":
                    gc_1 = s.value
                elif gen == "2":
                    gc_2 = s.value

        content = Table(show_header=False, box=None, padding=(0, 1))
        content.add_column("Metric", style="bold cyan", width=40)
        content.add_column("Value", style="white", justify="right")

        content.add_row("python_gc_collections_total{gen=0}", f"{gc_0:.0f}")
        content.add_row("python_gc_collections_total{gen=1}", f"{gc_1:.0f}")
        content.add_row("python_gc_collections_total{gen=2}", f"{gc_2:.0f}")

        return Panel(content, title=" PYTHON GC ", border_style="blue", padding=(0, 1))

    # ── PERCENTILES ────────────────────────────────────────────────

    def _latency_panel(self, metrics: dict) -> Panel:
        """Панель: задержки (histograms)."""
        h = metrics["histograms"]
        parser = PrometheusParser()

        def pct(name: str, p: float) -> str:
            hist = h.get(name)
            if not hist or not hist["buckets"]:
                return "N/A"
            val = parser.percentile_from_histogram(hist["buckets"], p)
            return fmt_time(val)

        content = Table(show_header=False, box=None, padding=(0, 1))
        content.add_column("Metric", style="bold cyan", width=40)
        content.add_column("p50", style="green", justify="right")
        content.add_column("p90", style="yellow", justify="right")
        content.add_column("p99", style="red", justify="right")

        content.add_row("vllm:time_to_first_token_seconds", pct("vllm:time_to_first_token_seconds", 0.5),
                        pct("vllm:time_to_first_token_seconds", 0.9),
                        pct("vllm:time_to_first_token_seconds", 0.99))
        content.add_row("vllm:inter_token_latency_seconds", pct("vllm:inter_token_latency_seconds", 0.5),
                        pct("vllm:inter_token_latency_seconds", 0.9),
                        pct("vllm:inter_token_latency_seconds", 0.99))
        content.add_row("vllm:e2e_request_latency_seconds", pct("vllm:e2e_request_latency_seconds", 0.5),
                        pct("vllm:e2e_request_latency_seconds", 0.9),
                        pct("vllm:e2e_request_latency_seconds", 0.99))
        content.add_row("vllm:request_prefill_time_seconds", pct("vllm:request_prefill_time_seconds", 0.5),
                        pct("vllm:request_prefill_time_seconds", 0.9),
                        pct("vllm:request_prefill_time_seconds", 0.99))
        content.add_row("vllm:request_decode_time_seconds", pct("vllm:request_decode_time_seconds", 0.5),
                        pct("vllm:request_decode_time_seconds", 0.9),
                        pct("vllm:request_decode_time_seconds", 0.99))
        content.add_row("vllm:request_queue_time_seconds", pct("vllm:request_queue_time_seconds", 0.5),
                        pct("vllm:request_queue_time_seconds", 0.9),
                        pct("vllm:request_queue_time_seconds", 0.99))
        content.add_row("vllm:request_inference_time_seconds", pct("vllm:request_inference_time_seconds", 0.5),
                        pct("vllm:request_inference_time_seconds", 0.9),
                        pct("vllm:request_inference_time_seconds", 0.99))
        content.add_row("vllm:request_time_per_output_token_seconds", pct("vllm:request_time_per_output_token_seconds", 0.5),
                        pct("vllm:request_time_per_output_token_seconds", 0.9),
                        pct("vllm:request_time_per_output_token_seconds", 0.99))

        return Panel(content, title=" LATENCY (cumulative) ", border_style="magenta", padding=(0, 1))

    def _throughput_details_panel(self, metrics: dict) -> Panel:
        """Панель: детализация пропускной способности."""
        h = metrics["histograms"]
        parser = PrometheusParser()

        def hist_stats(name: str) -> tuple[str, str, str]:
            hist = h.get(name)
            if not hist or hist["count"] is None:
                return "N/A", "N/A", "N/A"
            count = hist["count"]
            if count == 0:
                return "0", "0", "0"
            avg = hist["sum"] / count if hist["sum"] else 0
            p50 = parser.percentile_from_histogram(hist["buckets"], 0.5)
            p95 = parser.percentile_from_histogram(hist["buckets"], 0.95)
            return f"{avg:.1f}", f"{p50:.1f}", f"{p95:.1f}"

        content = Table(show_header=False, box=None, padding=(0, 1))
        content.add_column("Metric", style="bold cyan", width=40)
        content.add_column("Avg", style="green", justify="right")
        content.add_column("p50", style="yellow", justify="right")
        content.add_column("p95", style="red", justify="right")

        avg_tok, p50_tok, p95_tok = hist_stats("vllm:request_prompt_tokens")
        content.add_row("vllm:request_prompt_tokens", avg_tok, p50_tok, p95_tok)

        avg_gen, p50_gen, p95_gen = hist_stats("vllm:request_generation_tokens")
        content.add_row("vllm:request_generation_tokens", avg_gen, p50_gen, p95_gen)

        avg_iter, p50_iter, p95_iter = hist_stats("vllm:iteration_tokens_total")
        content.add_row("vllm:iteration_tokens_total", avg_iter, p50_iter, p95_iter)

        avg_kv, p50_kv, p95_kv = hist_stats("vllm:request_prefill_kv_computed_tokens")
        content.add_row("vllm:request_prefill_kv_computed_tokens", avg_kv, p50_kv, p95_kv)

        avg_max, p50_max, p95_max = hist_stats("vllm:request_max_num_generation_tokens")
        content.add_row("vllm:request_max_num_generation_tokens", avg_max, p50_max, p95_max)

        avg_mt, p50_mt, p95_mt = hist_stats("vllm:request_params_max_tokens")
        content.add_row("vllm:request_params_max_tokens", avg_mt, p50_mt, p95_mt)

        return Panel(content, title=" THROUGHPUT DETAILS (cumulative) ", border_style="magenta", padding=(0, 1))

    def _all_metrics_panel(self, metrics: dict) -> Panel:
        """Панель: полный список всех метрик (для детального анализа)."""
        content = Table(show_header=True, box=None, padding=(0, 1))
        content.add_column("Metric", style="bold cyan", width=42)
        content.add_column("Value", style="white", justify="right")
        content.add_column("Labels", style="dim", width=30)

        for s in sorted(metrics["samples"], key=lambda x: x.name):
            if s.name.endswith("_bucket") or s.name.endswith("_created"):
                continue
            labels = ", ".join(f'{k}={v}' for k, v in s.labels.items()) or "-"
            if s.value >= 1e9:
                val = f"{s.value/1e9:.2f}B"
            elif s.value >= 1e6:
                val = f"{s.value/1e6:.2f}M"
            elif s.value >= 1e3:
                val = f"{s.value/1e3:.1f}K"
            elif s.value == int(s.value):
                val = f"{s.value:.0f}"
            else:
                val = f"{s.value:.4g}"
            content.add_row(s.name, val, labels)

        return Panel(content, title=" ALL METRICS (raw) ", border_style="dim white", padding=(0, 1))

    def build(self, metrics: dict) -> Group:
        """
        Строит полный дашборд.
        Возвращает Rich Group со всеми панелями.
        """
        # REAL-TIME
        server_panel = self._server_info_panel(metrics)
        vllm_stats = self._vllm_stats_panel(metrics)
        live_req = self._live_requests_panel(metrics)
        live_thr = self._live_throughput_panel(metrics)
        live_proc = self._live_process_panel(metrics)

        # LIFETIME
        total_req = self._total_requests_panel(metrics)
        total_tok = self._total_tokens_panel(metrics)
        cache_det = self._cache_details_panel(metrics)
        http_pan = self._http_panel(metrics)
        gc_pan = self._gc_panel(metrics)

        # PERCENTILES
        latency_pan = self._latency_panel(metrics)
        thr_det_pan = self._throughput_details_panel(metrics)

        return Group(
            Columns([server_panel, vllm_stats], equal=True, expand=True),
            Columns([live_req, live_thr, live_proc], equal=True, expand=True),
            Columns([total_req, total_tok, cache_det, http_pan], equal=True, expand=True),
            Columns([gc_pan], expand=True),
            Columns([latency_pan, thr_det_pan], equal=True, expand=True),
        )
