"""vllm-metrics — Конфигурация подключения к vLLM серверу."""

import os
from pathlib import Path
from dotenv import load_dotenv


def load_config() -> dict:
    """Загружает конфигурацию из .env и переменных окружения."""
    # Ищем .env рядом с файлом конфигурации (в корне проекта)
    env_path = Path(__file__).parent.parent.parent / ".env"
    load_dotenv(env_path)

    return {
        "metrics_url": os.getenv("VLLM_METRICS_URL", "http://localhost:8000/metrics"),
        "base_url": os.getenv("VLLM_BASE_URL", "http://localhost:8000/v1"),
        "api_key": os.getenv("VLLM_API_KEY", ""),
        "model": os.getenv("VLLM_MODEL", "unknown"),
        "refresh_interval": int(os.getenv("REFRESH_INTERVAL", "2")),
    }
