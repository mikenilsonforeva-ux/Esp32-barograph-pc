"""CSV-файл барографа как источник данных для графика (без записи в локальную базу).

Читает файл прошивки (/data/barograph.csv с SD-карты, результат /api/export/full.csv) и файлы, которые
экспортирует само приложение (в т.ч. в гПа/кПа и «для русского Excel»: разделитель «;», десятичная запятая).
Интерфейс выборок (count / bounds / query / stats) совпадает с barograph.storage.Storage, поэтому график и
статистика работают с обоими источниками одинаково."""
import bisect
import math
from itertools import groupby

from .storage import METRIC_COLUMNS
from .units import PRESSURE_UNITS

# множитель перевода давления из единицы заголовка (pressure_mmHg / _hPa / _kPa) в мм рт. ст.
_TO_MMHG = {unit.lower(): 1.0 / spec[0] for unit, spec in PRESSURE_UNITS.items()}


class CsvFormatError(ValueError):
    """Файл не похож на CSV барографа или в нём нет корректных записей."""


def _num(text, decimal_comma):
    text = text.strip()
    if not text:
        return None
    return float(text.replace(",", ".") if decimal_comma else text)


def parse_csv_flexible(text: str):
    """Разбор CSV барографа. Возвращает (записи, пропущено_строк); записи - (ts, мм рт. ст., °C, % или None),
    отсортированы по времени, без повторяющихся меток (берётся первая)."""
    lines = text.lstrip("﻿").splitlines()
    first = next((ln for ln in lines if ln.strip()), "")
    delim = ";" if first.count(";") >= 4 else ","
    decimal_comma = delim == ";"
    factor = 1.0
    if first and not first.strip()[:1].isdigit():
        for name in first.lower().replace(";", ",").split(","):
            name = name.strip()
            if name.startswith("pressure_"):
                factor = _TO_MMHG.get(name[len("pressure_"):], 1.0)

    by_ts = {}
    skipped = 0
    for ln in lines:
        if not ln.strip():
            continue
        parts = ln.split(delim)
        if len(parts) < 5 or not parts[0].strip().isdigit():
            if parts and parts[0].strip().isdigit():
                skipped += 1                                  # оборванная строка; заголовок не считается
            continue
        try:
            ts = int(parts[0])
            p = _num(parts[3], decimal_comma)
            t = _num(parts[4], decimal_comma)
            h = _num(parts[5], decimal_comma) if len(parts) > 5 else None
        except ValueError:
            skipped += 1
            continue
        if p is None or t is None:
            skipped += 1
            continue
        p *= factor
        if ts < 1_000_000_000 or not (300.0 < p < 900.0) or not (-60.0 < t < 100.0):
            skipped += 1
            continue
        by_ts.setdefault(ts, (ts, round(p, 3), t, h))
    return [by_ts[k] for k in sorted(by_ts)], skipped


class CsvDataset:
    def __init__(self, rows, path=None, skipped=0):
        self.rows = list(rows)                                # уже отсортированы по ts
        self.path = path
        self.skipped = skipped
        self._ts = [r[0] for r in self.rows]

    @classmethod
    def from_file(cls, path):
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            text = f.read()
        rows, skipped = parse_csv_flexible(text)
        if not rows:
            raise CsvFormatError(
                "В файле нет корректных записей. Ожидается CSV барографа: "
                "timestamp,date,time,pressure_mmHg,temperature_c,humidity")
        return cls(rows, path, skipped)

    # ------------------------------------------------------------------ выборки (как у Storage)
    def _slice(self, start, end):
        lo = 0 if start is None else bisect.bisect_left(self._ts, int(start))
        hi = len(self.rows) if end is None else bisect.bisect_right(self._ts, int(end))
        return self.rows[lo:hi]

    def count(self, start=None, end=None) -> int:
        return len(self._slice(start, end))

    def bounds(self):
        return (self._ts[0], self._ts[-1]) if self._ts else None

    def query(self, start=None, end=None, bucket_s=0, max_points=None):
        """Строки (ts, давление, температура, влажность). bucket_s > 0 - усреднение по интервалу;
        max_points - автоматическое усреднение, чтобы получилось не больше max_points точек."""
        rows = self._slice(start, end)
        if max_points and not bucket_s and len(rows) > max_points:
            span = max(1, rows[-1][0] - rows[0][0])
            bucket_s = max(1, math.ceil(span / max_points))
        if not (bucket_s and bucket_s > 1):
            return list(rows)
        out = []
        for b, grp in groupby(rows, key=lambda r: r[0] // bucket_s):
            g = list(grp)
            ts = [r[2] for r in g if r[2] is not None]
            hs = [r[3] for r in g if r[3] is not None]
            out.append((b * bucket_s,
                        round(sum(r[1] for r in g) / len(g), 3),
                        round(sum(ts) / len(ts), 2) if ts else None,
                        round(sum(hs) / len(hs), 2) if hs else None))
        return out

    def stats(self, start=None, end=None) -> dict:
        """Мин/макс/среднее по каждому параметру за период (структура как у Storage.stats)."""
        rows = self._slice(start, end)
        out = {"count": len(rows), "first_ts": None, "last_ts": None}
        for name in METRIC_COLUMNS:
            out[name] = {"min": None, "max": None, "avg": None}
        if not rows:
            return out
        out["first_ts"], out["last_ts"] = rows[0][0], rows[-1][0]
        for i, name in enumerate(METRIC_COLUMNS, start=1):
            vals = [r[i] for r in rows if r[i] is not None]
            if vals:
                out[name] = {"min": min(vals), "max": max(vals), "avg": sum(vals) / len(vals)}
        out["pressure"]["change"] = rows[-1][1] - rows[0][1]
        return out
