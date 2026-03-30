#!/bin/bash
# ЛогоперРадар — запуск приложения
# Использование: ./run.sh [--dev]

set -e
cd "$(dirname "$0")/backend"

# Активировать виртуальное окружение если есть
if [ -f "../venv/bin/activate" ]; then
  source ../venv/bin/activate
fi

if [ "$1" = "--dev" ]; then
  echo "Запуск в режиме разработки..."
  uvicorn main:app --host 0.0.0.0 --port 8000 --reload
else
  echo "Запуск в production-режиме..."
  uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
fi
