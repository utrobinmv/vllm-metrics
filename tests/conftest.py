"""Общие фикстуры для всех тестов."""

import pytest
from pathlib import Path


TEST_DATA_DIR = Path(__file__).parent / "test_data"


@pytest.fixture
def full_metrics_text():
    """Полный реалистичный ответ vLLM."""
    return (TEST_DATA_DIR / "full_vllm_metrics.txt").read_text()


@pytest.fixture
def malformed_metrics_text():
    """Повреждённые данные для тестирования устойчивости."""
    return (TEST_DATA_DIR / "malformed_metrics.txt").read_text()
