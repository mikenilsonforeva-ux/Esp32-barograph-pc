#!/usr/bin/env bash
# ESP32 Barograph PC - запуск на Ubuntu/Linux (первый запуск создаёт окружение и ставит библиотеки)
cd "$(dirname "$0")" || exit 1
if ! python3 -c "import tkinter" 2>/dev/null; then
    echo "Нет tkinter. Установите:  sudo apt install python3-tk python3-venv" >&2
    exit 1
fi
if [ ! -x .venv/bin/python ]; then
    echo "Создаю виртуальное окружение..."
    python3 -m venv .venv || { echo "Установите:  sudo apt install python3-venv" >&2; exit 1; }
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/python -m pip install -r requirements.txt || exit 1
fi
exec .venv/bin/python barograph_app.py "$@"
