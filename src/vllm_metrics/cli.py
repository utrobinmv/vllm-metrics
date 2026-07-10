"""vllm-metrics — CLI entry point.

Real-time консольный мониторинг vLLM сервера.
Забирает метрики с /metrics endpoint в формате Prometheus,
парсит их и отображает в Rich Live-дашборде.

Использование:
    vllm-metrics                          # использует .env
    vllm-metrics --url http://host:port/metrics
    vllm-metrics --interval 1             # обновлять каждую секунду
    vllm-metrics --all-metrics            # показать все сырые метрики
"""

import argparse
import signal
import sys
import time

from rich.live import Live
from rich.console import Console

from .config import load_config
from .metrics_parser import PrometheusParser
from .dashboard import Dashboard, MetricsCollector


def parse_args():
    parser = argparse.ArgumentParser(
        prog="vllm-metrics",
        description="vLLM Metrics — real-time console monitoring dashboard",
    )
    parser.add_argument(
        "--url",
        help="URL метрик (по умолчанию из .env: VLLM_METRICS_URL)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        help="Интервал обновления в секундах (по умолчанию из .env: REFRESH_INTERVAL)",
    )
    parser.add_argument(
        "--all-metrics",
        action="store_true",
        help="Показать все сырые метрики внизу дашборда",
    )
    return parser.parse_args()


def cli():
    """CLI entry point."""
    args = parse_args()
    config = load_config()

    metrics_url = args.url or config["metrics_url"]
    refresh_interval = args.interval or config["refresh_interval"]
    show_all = args.all_metrics

    console = Console()

    # Проверяем доступность сервера
    console.print(f"\n[bold cyan]vLLM Metrics[/] — connecting to [link={metrics_url}]{metrics_url}[/]...")
    console.print(f"Refresh interval: [bold]{refresh_interval}s[/]\n")

    collector = MetricsCollector(
        metrics_url=metrics_url,
        api_key=config.get("api_key", ""),
    )
    dashboard = Dashboard(config=config)

    # Флаг остановки
    stop = False

    def handle_signal(signum, frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Первая попытка подключения
    try:
        metrics = collector.collect()
    except Exception as e:
        console.print(f"[bold red]ERROR:[/] Cannot connect to {metrics_url}")
        console.print(f"[dim]{e}[/]")
        sys.exit(1)

    console.print("[bold green]Connected![/] Starting dashboard...\n")

    def update():
        try:
            metrics = collector.collect()
        except Exception as e:
            error_panel = f"[bold red]CONNECTION ERROR:[/] {e}"
            return error_panel

        group = dashboard.build(metrics)

        if show_all:
            from rich.panel import Panel
            from rich.console import Group as RichGroup
            all_panel = dashboard._all_metrics_panel(metrics)
            return RichGroup(group, all_panel)

        return group

    try:
        with Live(
            update(),
            console=console,
            refresh_per_second=1.0 / refresh_interval,
            screen=True,
            transient=False,
        ) as live:
            while not stop:
                try:
                    metrics = collector.collect()
                except Exception as e:
                    live.update(f"[bold red]CONNECTION ERROR:[/] {e}\n[dim]Retrying in {refresh_interval}s...[/]")
                    time.sleep(refresh_interval)
                    continue

                group = dashboard.build(metrics)
                if show_all:
                    from rich.console import Group as RichGroup
                    all_panel = dashboard._all_metrics_panel(metrics)
                    group = RichGroup(group, all_panel)

                live.update(group)
                time.sleep(refresh_interval)
    except KeyboardInterrupt:
        pass

    console.print("\n[bold yellow]Dashboard stopped.[/]\n")


if __name__ == "__main__":
    cli()
