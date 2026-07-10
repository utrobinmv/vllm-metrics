# INSTALL.md — Установка vllm-metrics

## Системные требования

- Python 3.11+
- Доступ к vLLM серверу с endpoint `/metrics`

## Пошаговая установка

### 1. Клонирование / навигация

```bash
cd ~/workspace/projects/vllm-metrics
```

### 2. Создание виртуального окружения

```bash
python3 -m venv ~/workspace/venvs/vllm-metrics/default
```

### 3. Активация venv

```bash
source .venv
```

### 4. Установка пакета

```bash
# С основными зависимостями
pip install -e .

# С тестовыми зависимостями
pip install -e ".[dev]"
```

### 5. Настройка подключения

Файл `.env` уже содержит параметры подключения к вашему vLLM серверу:

```ini
VLLM_METRICS_URL=http://192.168.45.10:30000/metrics
VLLM_BASE_URL=http://192.168.45.10:30000/v1
VLLM_API_KEY=sk-vllm-qwen3.5-0.8b
VLLM_MODEL=Qwen3.6-27B-FP8
REFRESH_INTERVAL=2
```

При необходимости отредактируйте `.env` под свой сервер.

### 6. Запуск

```bash
# Через CLI entry point
vllm-metrics

# С параметрами
vllm-metrics --interval 1 --all-metrics
vllm-metrics --url http://host:port/metrics

# Или через модуль
python -m vllm_metrics.cli
```

### 7. Запуск тестов

```bash
source .venv
python -m pytest tests/ -v --cov=vllm_metrics --cov-report=term-missing
```

## Повторное развёртывание с нуля

```bash
# Удаляем старое
rm -rf ~/workspace/venvs/vllm-metrics

# Создаём заново
cd ~/workspace/projects/vllm-metrics
python3 -m venv ~/workspace/venvs/vllm-metrics/default
source .venv
pip install -e ".[dev]"

# Запускаем
vllm-metrics
```

## Установка из GitHub

```bash
pip install git+https://github.com/krapotkin/vllm-metrics.git
```
