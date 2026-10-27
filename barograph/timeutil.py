"""Время: часовой пояс устройства, разбор и форматирование дат."""
import re
import time
from datetime import datetime, timedelta, timezone

DATE_FMT = "%d.%m.%Y %H:%M:%S"


def tz_from_offset(offset_s: int) -> timezone:
    return timezone(timedelta(seconds=int(offset_s)))


def local_offset_s() -> int:
    """Смещение часового пояса этого компьютера (для кнопки «взять с ПК»)."""
    lt = time.localtime()
    off = getattr(lt, "tm_gmtoff", None)
    return int(off) if off is not None else -time.timezone


def to_dt(ts: float, tz) -> datetime:
    return datetime.fromtimestamp(ts, tz)


def fmt_ts(ts: float, tz, fmt: str = DATE_FMT) -> str:
    return to_dt(ts, tz).strftime(fmt)


_FORMATS = [
    "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y",
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M",
]


def parse_datetime(text: str, tz, end: bool = False) -> int:
    """Разбор даты/времени в Unix-время. Если время не указано и end=True -> конец суток."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Пустая дата")
    for fmt in _FORMATS:
        try:
            dt = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if end and "%H" not in fmt:
            dt = dt.replace(hour=23, minute=59, second=59)
        return int(dt.replace(tzinfo=tz).timestamp())
    raise ValueError(f"Не удалось разобрать дату: «{text}» (формат ДД.ММ.ГГГГ ЧЧ:ММ)")


_DUR = re.compile(r"^(\d+(?:\.\d+)?)\s*([smhdсмчд]?)$")


def parse_duration(text: str) -> int:
    """'300' / '5m' / '1h' / '1d' -> секунды (0 = без усреднения)."""
    text = (text or "").strip().lower()
    if text in ("", "0", "none", "raw", "нет"):
        return 0
    m = _DUR.match(text)
    if not m:
        raise ValueError(f"Неверный интервал: «{text}» (примеры: 300, 5m, 1h, 1d)")
    mult = {"s": 1, "с": 1, "m": 60, "м": 60, "h": 3600, "ч": 3600, "d": 86400, "д": 86400}[m.group(2) or "s"]
    return int(float(m.group(1)) * mult)
