@echo off
rem ESP32 Barograph PC - запуск на Windows (первый запуск создаёт окружение и ставит библиотеки)
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Создаю виртуальное окружение...
    py -3 -m venv .venv 2>nul || python -m venv .venv
    if errorlevel 1 (
        echo Не найден Python 3.9+. Установите с https://www.python.org/downloads/ ^(отметьте "Add python.exe to PATH" и "tcl/tk"^)
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo Не удалось установить библиотеки.
        pause
        exit /b 1
    )
)
if "%~1"=="" (
    start "" ".venv\Scripts\pythonw.exe" barograph_app.py
) else (
    ".venv\Scripts\python.exe" barograph_app.py %*
)
