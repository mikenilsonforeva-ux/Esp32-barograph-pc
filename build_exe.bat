@echo off
rem Сборка одного exe-файла для Windows (PyInstaller). Результат: dist\ESP32Barograph.exe
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" call run.bat --version
".venv\Scripts\python.exe" -m pip install pyinstaller
".venv\Scripts\pyinstaller.exe" --noconfirm --onefile --windowed --name ESP32Barograph --collect-submodules matplotlib.backends barograph_app.py
echo.
echo Готово: dist\ESP32Barograph.exe
pause
