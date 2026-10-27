"""Прикладная логика, общая для GUI и командной строки: синхронизация, периоды, экспорт, импорт."""
import os
import time
from dataclasses import dataclass

from . import exporters, plotting
from .api_client import BarographClient, parse_csv_text
from .storage import Storage
from .timeutil import parse_datetime, tz_from_offset

# (подпись, часы) - None = всё время, "custom" = свой период
PERIOD_PRESETS = [
    ("1 час", 1), ("3 часа", 3), ("6 часов", 6), ("12 часов", 12), ("24 часа", 24),
    ("3 суток", 72), ("7 суток", 168), ("30 суток", 720), ("Всё время", None), ("Свой период", "custom"),
]
EXPORT_FORMATS = {
    "CSV": ("csv", ".csv"),
    "Excel (xlsx)": ("xlsx", ".xlsx"),
    "SQLite": ("sqlite", ".sqlite"),
    "JSON": ("json", ".json"),
    "PNG (график)": ("png", ".png"),
}
RESAMPLE_PRESETS = [("Без усреднения", 0), ("1 минута", 60), ("5 минут", 300), ("15 минут", 900),
                    ("1 час", 3600), ("6 часов", 21600), ("1 сутки", 86400)]


@dataclass
class SyncResult:
    downloaded: int
    new: int
    first_ts: int
    last_ts: int
    total_in_db: int


def sync_from_device(client: BarographClient, storage: Storage) -> SyncResult:
    """Скачивает всю историю устройства (до 72 ч, сырые записи) и дописывает в локальную базу без дублей."""
    records = client.download_records()
    new = storage.insert_many(records)
    storage.set_meta("last_sync_ts", int(time.time()))
    return SyncResult(
        downloaded=len(records), new=new,
        first_ts=records[0][0] if records else 0, last_ts=records[-1][0] if records else 0,
        total_in_db=storage.count())


def import_csv_file(storage: Storage, path) -> tuple:
    """Импорт CSV (в т.ч. barograph.csv с SD-карты). Возвращает (разобрано, новых)."""
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        records = parse_csv_text(f.read())
    return len(records), storage.insert_many(records)


def resolve_period(spec, tz, storage: Storage, now=None):
    """spec: ('hours', N) | ('all',) | ('custom', 'начало', 'конец'). Возвращает (start, end) в Unix-времени."""
    now = int(now if now is not None else time.time())
    kind = spec[0]
    if kind == "hours":
        return now - int(float(spec[1]) * 3600), now
    if kind == "all":
        b = storage.bounds()
        return (b[0], b[1]) if b else (0, now)
    if kind == "custom":
        start = parse_datetime(spec[1], tz) if spec[1].strip() else 0
        end = parse_datetime(spec[2], tz, end=True) if spec[2].strip() else now
        if end < start:
            raise ValueError("Конец периода раньше начала")
        return start, end
    raise ValueError(f"Неизвестный тип периода: {kind}")


def export_data(storage: Storage, fmt: str, path, start, end, tz, unit="mmHg",
                resample_s=0, excel_ru=False, metrics=("pressure", "temperature", "humidity")) -> int:
    """Единая точка экспорта. fmt: csv | xlsx | sqlite | json | png. Возвращает число записей."""
    path = str(path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    if fmt == "sqlite":
        if storage.count(start, end) == 0:
            raise exporters.ExportError("Нет данных за выбранный период")
        return storage.export_sqlite(path, start, end, bucket_s=resample_s)
    rows = storage.query(start, end, bucket_s=resample_s)
    if fmt == "csv":
        return exporters.export_csv(rows, path, tz, unit, excel_ru)
    if fmt == "json":
        return exporters.export_json(rows, path, tz, unit)
    if fmt == "xlsx":
        return exporters.export_xlsx(rows, path, tz, unit)
    if fmt == "png":
        if not rows:
            raise exporters.ExportError("Нет данных за выбранный период")
        rows = storage.query(start, end, max_points=4000)
        return plotting.save_png(path, rows, list(metrics), tz, unit)
    raise ValueError(f"Неизвестный формат: {fmt}")


def client_from_config(cfg, host=None, port=None, timeout=8.0) -> BarographClient:
    """Клиент с запасным адресом: последний известный IP устройства (если mDNS-имя не резолвится)."""
    fallback = [cfg.get("last_ip")] if cfg.get("last_ip") else []
    return BarographClient(host or cfg["host"], port or cfg["port"], timeout=timeout, fallback_hosts=fallback)


def refresh_device_info(client: BarographClient, cfg) -> dict:
    """Запрашивает статус и запоминает IP устройства и (если включено) его часовой пояс."""
    st = client.status()
    ip = st.get("ip")
    if ip and ip != "0.0.0.0" and not st.get("ap"):
        cfg["last_ip"] = ip
    if cfg.get("tz_auto", True) and isinstance(st.get("tz_offset_s"), int):
        cfg["tz_offset_s"] = st["tz_offset_s"]
    return st


def tz_from_config(cfg):
    return tz_from_offset(cfg.get("tz_offset_s", 10800))
