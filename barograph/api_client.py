"""Клиент REST API барографа ESP32 (только стандартная библиотека)."""
import csv
import http.client
import io
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

Record = tuple  # (ts:int, pressure_mmHg:float, temperature:float, humidity:float|None)

CSV_HEADER = "timestamp,date,time,pressure_mmHg,temperature_c,humidity"
_CHUNK = 16 * 1024


class DeviceError(Exception):
    """Ошибка связи с устройством или ответ с ошибкой.
    code - HTTP-код ответа устройства, error - его поле "error" (например "sd_offline"); у сетевых ошибок None."""

    def __init__(self, message, code=None, error=None):
        super().__init__(message)
        self.code = code
        self.error = error


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

    def _open(self, method: str, path: str, params=None, data=None, timeout=None):
        """Открывает соединение (пробуя запасные адреса) и возвращает ответ; закрыть должен вызвавший."""
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
                resp = urllib.request.urlopen(req, timeout=timeout or self.timeout)
            except urllib.error.HTTPError as e:         # устройство ответило ошибкой - не пробуем другие адреса
                raw = e.read() if hasattr(e, "read") else b""
                msg, err = f"HTTP {e.code}", None
                try:
                    j = json.loads(raw.decode("utf-8"))
                    if isinstance(j, dict) and j.get("error"):
                        err = str(j["error"])
                        msg = f"{err} (HTTP {e.code})"
                except (ValueError, UnicodeDecodeError):
                    pass
                raise DeviceError(msg, code=e.code, error=err) from None
            except (urllib.error.URLError, OSError, TimeoutError) as e:
                last_exc = e
                continue
            self.active_host = host
            return resp
        reason = getattr(last_exc, "reason", last_exc)
        raise DeviceError(f"Нет связи с устройством ({', '.join(hosts)}): {reason}")

    def _request(self, method: str, path: str, params=None, data=None, timeout=None) -> bytes:
        resp = self._open(method, path, params, data, timeout)
        try:
            with resp:
                return resp.read()
        except (OSError, TimeoutError, http.client.HTTPException) as e:
            raise DeviceError(f"Обрыв связи с устройством: {e}") from None

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

    def range(self) -> dict:
        """GET /api/range: за какой период у устройства есть измерения (has_data, first, last, source sd|ram)."""
        return self.get_json("/api/range")

    def history_range(self, start=None, end=None, max_points: int = 1000) -> dict:
        """GET /api/history?from=&to=: произвольный период (Unix, UTC). С SD-картой читается весь период
        хранения, без неё - только буфер в ОЗУ. Чтение с карты может занять секунды."""
        params = {"max": int(max_points)}
        if start is not None:
            params["from"] = int(start)
        if end is not None:
            params["to"] = int(end)
        return self.get_json("/api/history", params, timeout=120)

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
        """GET /api/export.csv: только буфер в ОЗУ устройства (последние 72 ч и больше)."""
        raw = self._request("GET", "/api/export.csv", timeout=60)
        return raw.decode("utf-8-sig", errors="replace")

    def download_records(self) -> list:
        """Вся история из ОЗУ устройства (до 72 ч) в сыром виде, без усреднения."""
        return parse_csv_text(self.export_csv_text())

    def download_csv(self, dest, start=None, end=None, progress=None) -> dict:
        """Сохраняет CSV с устройства в файл dest.

        Основной путь - GET /api/export/full.csv: полный файл с SD-карты за всё время хранения или только
        период start..end (Unix, UTC, включительно). Если SD-карты нет (503 sd_offline), берётся буфер ОЗУ
        (/api/export.csv, последние ≥72 ч) и отфильтровывается по периоду здесь.
        Файл пишется во временный dest+".part" и переименовывается после успешной загрузки.
        progress(байт_получено) вызывается по ходу загрузки. Возвращает {"source": "sd"|"ram", "rows", "bytes"}."""
        dest = str(dest)
        part = dest + ".part"
        os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
        params = {}
        if start is not None:
            params["from"] = int(start)
        if end is not None:
            params["to"] = int(end)
        try:
            try:
                size, lines = self._stream_to_file("/api/export/full.csv", params, part, progress)
                source = "sd"
            except DeviceError as e:
                if e.error != "sd_offline" and e.code != 404:     # 404 - прошивка старой версии без этого маршрута
                    raise
                size, lines = self._ram_csv_to_file(part, start, end, progress)
                source = "ram"
            if size == 0:
                raise DeviceError("Устройство вернуло пустой файл (SD-карта недоступна?)")
            os.replace(part, dest)
        except BaseException:
            try:
                os.remove(part)
            except OSError:
                pass
            raise
        return {"source": source, "rows": max(0, lines - 1), "bytes": size}

    def _stream_to_file(self, path, params, dest, progress):
        """Потоковая загрузка в файл. Возвращает (байт, число строк)."""
        resp = self._open("GET", path, params, timeout=60)
        size = lines = 0
        try:
            with resp, open(dest, "wb") as f:
                while True:
                    chunk = resp.read(_CHUNK)
                    if not chunk:
                        break
                    f.write(chunk)
                    size += len(chunk)
                    lines += chunk.count(b"\n")
                    if progress:
                        progress(size)
        except (OSError, TimeoutError, http.client.HTTPException) as e:
            raise DeviceError(f"Обрыв связи при загрузке файла: {e}") from None
        return size, lines

    def _ram_csv_to_file(self, dest, start, end, progress):
        text = self.export_csv_text()
        out = [CSV_HEADER]
        for line in text.splitlines():
            head = line.split(",", 1)[0]
            if not head.isdigit():
                continue                                      # заголовок и мусор
            ts = int(head)
            if (start is not None and ts < start) or (end is not None and ts > end):
                continue
            out.append(line)
        data = ("\n".join(out) + "\n").encode("utf-8")
        with open(dest, "wb") as f:
            f.write(data)
        if progress:
            progress(len(data))
        return len(data), len(out)


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
