"""Клиент REST API барографа ESP32 (только стандартная библиотека)."""
import csv
import io
import json
import time
import urllib.error
import urllib.parse
import urllib.request

Record = tuple  # (ts:int, pressure_mmHg:float, temperature:float, humidity:float|None)


class DeviceError(Exception):
    """Ошибка связи с устройством или ответ с ошибкой."""


def normalize_host(host: str) -> str:
    host = (host or "").strip().rstrip("/")
    if host.startswith("http://"):
        host = host[7:]
    elif host.startswith("https://"):
        host = host[8:]
    return host


class BarographClient:
    def __init__(self, host: str, port: int = 80, timeout: float = 8.0, fallback_hosts=None):
        self.host = normalize_host(host)
        self.port = int(port or 80)
        self.timeout = timeout
        self.fallback_hosts = [normalize_host(h) for h in (fallback_hosts or []) if h]
        self.active_host = self.host            # хост, по которому реально ответило устройство

    # ------------------------------------------------------------------ низкий уровень
    def _base(self, host: str) -> str:
        return f"http://{host}" if self.port == 80 else f"http://{host}:{self.port}"

    def _request(self, method: str, path: str, params=None, data=None, timeout=None) -> bytes:
        hosts = [self.active_host] + [h for h in [self.host] + self.fallback_hosts if h != self.active_host]
        url_path = path
        if params:
            url_path += "?" + urllib.parse.urlencode(params)
        body = urllib.parse.urlencode(data).encode("utf-8") if data is not None else None
        last_exc = None
        for host in hosts:
            req = urllib.request.Request(self._base(host) + url_path, data=body, method=method)
            if body is not None:
                req.add_header("Content-Type", "application/x-www-form-urlencoded")
            try:
                with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                    payload = resp.read()
                self.active_host = host
                return payload
            except urllib.error.HTTPError as e:         # устройство ответило ошибкой - не пробуем другие адреса
                raw = e.read() if hasattr(e, "read") else b""
                msg = f"HTTP {e.code}"
                try:
                    j = json.loads(raw.decode("utf-8"))
                    if isinstance(j, dict) and j.get("error"):
                        msg = f"{j['error']} (HTTP {e.code})"
                except (ValueError, UnicodeDecodeError):
                    pass
                raise DeviceError(msg) from None
            except (urllib.error.URLError, OSError, TimeoutError) as e:
                last_exc = e
                continue
        reason = getattr(last_exc, "reason", last_exc)
        raise DeviceError(f"Нет связи с устройством ({', '.join(hosts)}): {reason}")

    def get_json(self, path: str, params=None, timeout=None) -> dict:
        raw = self._request("GET", path, params=params, timeout=timeout)
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            raise DeviceError(f"Некорректный ответ устройства: {e}") from None

    def post_json(self, path: str, data=None, params=None, timeout=None) -> dict:
        raw = self._request("POST", path, params=params, data=data if data is not None else {}, timeout=timeout)
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            raise DeviceError(f"Некорректный ответ устройства: {e}") from None

    # ------------------------------------------------------------------ API устройства
    def status(self) -> dict:
        return self.get_json("/api/status")

    def current(self) -> dict:
        return self.get_json("/api/current")

    def forecast(self) -> dict:
        return self.get_json("/api/forecast")

    def history(self, hours: float = 1.0, max_points: int = 400) -> dict:
        return self.get_json("/api/history", {"hours": hours, "max": max_points}, timeout=30)

    def measure(self, store: bool = False) -> dict:
        return self.post_json("/api/measure", params={"store": 1} if store else None)

    def get_settings(self) -> dict:
        return self.get_json("/api/settings")

    def set_settings(self, **kwargs) -> dict:
        data = {k: v for k, v in kwargs.items() if v is not None}
        return self.post_json("/api/settings", data)

    def set_time(self, epoch=None) -> dict:
        return self.post_json("/api/time", {"epoch": int(epoch if epoch is not None else time.time())})

    def wifi_scan(self, wait_s: float = 25.0, poll_s: float = 1.0) -> list:
        """Запускает сканирование и ждёт результата. Возвращает список сетей."""
        self.get_json("/api/wifi/scan", {"start": 1})
        deadline = time.time() + wait_s
        while time.time() < deadline:
            time.sleep(poll_s)
            res = self.get_json("/api/wifi/scan")
            if res.get("status") == "done":
                return res.get("networks", [])
            if res.get("status") == "idle":
                break
        return []

    def export_csv_text(self) -> str:
        raw = self._request("GET", "/api/export.csv", timeout=60)
        return raw.decode("utf-8-sig", errors="replace")

    def download_records(self) -> list:
        """Вся история из ОЗУ устройства (до 72 ч) в сыром виде, без усреднения."""
        return parse_csv_text(self.export_csv_text())


# ---------------------------------------------------------------------- разбор CSV
def parse_csv_text(text: str) -> list:
    """CSV прошивки: timestamp,date,time,pressure_mmHg,temperature_c,humidity
    (тот же формат у файла /data/barograph.csv на SD-карте). Повреждённые строки пропускаются."""
    records = []
    reader = csv.reader(io.StringIO(text))
    for row in reader:
        if len(row) < 5:
            continue
        try:
            ts = int(row[0])
            p = float(row[3])
            t = float(row[4])
        except ValueError:
            continue                                     # заголовок или оборванная строка
        if ts < 1_000_000_000 or not (300.0 < p < 900.0) or not (-60.0 < t < 100.0):
            continue
        h = None
        if len(row) > 5 and row[5].strip() != "":
            try:
                h = float(row[5])
            except ValueError:
                h = None
        records.append((ts, p, t, h))
    return records
