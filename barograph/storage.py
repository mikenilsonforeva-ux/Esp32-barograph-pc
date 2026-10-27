"""Локальное хранилище измерений (SQLite). Время хранится как Unix UTC, давление - в мм рт. ст."""
import math
import os
import sqlite3
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    ts          INTEGER PRIMARY KEY,
    pressure    REAL NOT NULL,       -- мм рт. ст.
    temperature REAL,
    humidity    REAL
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

METRIC_COLUMNS = ("pressure", "temperature", "humidity")


class Storage:
    def __init__(self, path):
        self.path = str(path)
        d = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(d, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        # отдельное соединение на операцию: безопасно для потоков GUI
        conn = sqlite3.connect(self.path, timeout=30)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------ запись
    def insert_many(self, records) -> int:
        """Добавляет записи (ts, p, t, h); существующие метки времени не затираются. Возвращает число новых."""
        records = list(records)
        if not records:
            return 0
        with self._conn() as c:
            before = c.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
            c.executemany("INSERT OR IGNORE INTO readings(ts,pressure,temperature,humidity) VALUES (?,?,?,?)",
                          records)
            after = c.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
        return after - before

    def set_meta(self, key, value):
        with self._conn() as c:
            c.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      (key, str(value)))

    def get_meta(self, key, default=None):
        with self._conn() as c:
            row = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    # ------------------------------------------------------------------ чтение
    def count(self, start=None, end=None) -> int:
        start, end = self._range(start, end)
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM readings WHERE ts BETWEEN ? AND ?", (start, end)).fetchone()[0]

    def bounds(self):
        """(первая_метка, последняя_метка) или None, если база пуста."""
        with self._conn() as c:
            lo, hi = c.execute("SELECT MIN(ts), MAX(ts) FROM readings").fetchone()
        return None if lo is None else (lo, hi)

    @staticmethod
    def _range(start, end):
        return (0 if start is None else int(start)), (4_000_000_000 if end is None else int(end))

    def query(self, start=None, end=None, bucket_s=0, max_points=None):
        """Строки (ts, pressure, temperature, humidity).
        bucket_s > 0 - усреднение по интервалу; max_points - автоматическое усреднение для графиков."""
        start, end = self._range(start, end)
        if max_points and not bucket_s:
            n = self.count(start, end)
            if n > max_points:
                lo, hi = self.bounds() or (start, end)
                span = max(1, min(end, hi) - max(start, lo))
                bucket_s = max(1, math.ceil(span / max_points))
        with self._conn() as c:
            if bucket_s and bucket_s > 1:
                cur = c.execute(
                    "SELECT (ts/?)*? AS b, AVG(pressure), AVG(temperature), AVG(humidity) "
                    "FROM readings WHERE ts BETWEEN ? AND ? GROUP BY b ORDER BY b",
                    (bucket_s, bucket_s, start, end))
                return [(int(b), round(p, 3), None if t is None else round(t, 2), None if h is None else round(h, 2))
                        for b, p, t, h in cur.fetchall()]
            cur = c.execute("SELECT ts,pressure,temperature,humidity FROM readings "
                            "WHERE ts BETWEEN ? AND ? ORDER BY ts", (start, end))
            return cur.fetchall()

    def stats(self, start=None, end=None) -> dict:
        """Мин/макс/среднее по каждому параметру за период."""
        start, end = self._range(start, end)
        out = {"count": 0, "first_ts": None, "last_ts": None}
        with self._conn() as c:
            row = c.execute(
                "SELECT COUNT(*), MIN(ts), MAX(ts), "
                "MIN(pressure), MAX(pressure), AVG(pressure), "
                "MIN(temperature), MAX(temperature), AVG(temperature), "
                "MIN(humidity), MAX(humidity), AVG(humidity) "
                "FROM readings WHERE ts BETWEEN ? AND ?", (start, end)).fetchone()
            out["count"], out["first_ts"], out["last_ts"] = row[0], row[1], row[2]
            for i, name in enumerate(METRIC_COLUMNS):
                mn, mx, avg = row[3 + i * 3: 6 + i * 3]
                out[name] = {"min": mn, "max": mx, "avg": avg}
            if out["count"]:
                first = c.execute("SELECT pressure FROM readings WHERE ts BETWEEN ? AND ? ORDER BY ts ASC LIMIT 1",
                                  (start, end)).fetchone()[0]
                last = c.execute("SELECT pressure FROM readings WHERE ts BETWEEN ? AND ? ORDER BY ts DESC LIMIT 1",
                                 (start, end)).fetchone()[0]
                out["pressure"]["change"] = last - first
        return out

    # ------------------------------------------------------------------ экспорт в другой SQLite
    def export_sqlite(self, dest_path, start=None, end=None, bucket_s=0) -> int:
        dest_path = os.path.abspath(str(dest_path))
        if os.path.abspath(self.path) == dest_path:
            raise ValueError("Нельзя экспортировать базу саму в себя")
        rows = self.query(start, end, bucket_s=bucket_s)
        if os.path.exists(dest_path):
            os.remove(dest_path)
        conn = sqlite3.connect(dest_path)
        try:
            conn.executescript(SCHEMA)
            conn.executemany("INSERT OR REPLACE INTO readings(ts,pressure,temperature,humidity) VALUES (?,?,?,?)", rows)
            conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('source','esp32-barograph')")
            conn.commit()
        finally:
            conn.close()
        return len(rows)
