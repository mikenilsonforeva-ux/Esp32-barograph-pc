"""Пути к конфигурации/данным и хранение настроек приложения (кроссплатформенно)."""
import json
import os
from pathlib import Path

APP_DIR_NAME = "ESP32Barograph"


def config_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    d = base / APP_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    d = base / APP_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_export_dir() -> Path:
    docs = Path.home() / "Documents"
    return docs if docs.is_dir() else Path.home()


class Config:
    """Простое JSON-хранилище настроек."""

    def __init__(self, path=None):
        self.path = Path(path) if path else config_dir() / "config.json"
        self.values = {
            "host": "esp32-barograf.local",
            "port": 80,
            "last_ip": "",                       # запоминается после успешного подключения
            "db_path": str(data_dir() / "barograph.db"),
            "auto_refresh": True,
            "refresh_s": 5,
            "auto_sync": False,
            "sync_minutes": 30,
            "tz_auto": True,                     # часовой пояс брать у устройства
            "tz_offset_s": 3 * 3600,             # время устройства: Москва, UTC+3
            "pressure_unit": "mmHg",             # mmHg | hPa | kPa
            "export_dir": str(default_export_dir()),
        }
        self.load()

    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self.values.update({k: v for k, v in data.items() if k in self.values})
        except (OSError, ValueError):
            pass          # нет файла или он повреждён - работаем с умолчаниями

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.values, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def __getitem__(self, key):
        return self.values[key]

    def __setitem__(self, key, value):
        self.values[key] = value

    def get(self, key, default=None):
        return self.values.get(key, default)
