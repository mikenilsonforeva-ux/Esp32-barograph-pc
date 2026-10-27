#!/usr/bin/env python3
"""Имитатор барографа ESP32 (тот же REST API, что в прошивке) - для проверки приложения без железа.

    python tools/mock_esp32.py --port 8080 [--bmp] [--hours 72]
затем в приложении: хост 127.0.0.1, порт 8080.
"""
import argparse
import json
import math
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

TZ_OFFSET = 10800


class MockDevice:
    def __init__(self, hours=72, has_humidity=True, ntp=True, record_interval=60):
        self.lock = threading.Lock()
        self.has_humidity = has_humidity
        self.ntp = ntp
        self.time_set_by_client = False
        self.record_interval = record_interval
        self.measure_interval = 10
        self.ssid = "MiWiFi"
        self.password_set = True
        self.scan_started = 0.0
        self.t0 = time.time()
        now = int(time.time()) // record_interval * record_interval
        n = int(hours * 3600 / record_interval)
        rnd = random.Random(42)
        self.records = []
        for i in range(n):
            ts = now - (n - 1 - i) * record_interval
            self.records.append(self._make(ts, rnd))

    def _make(self, ts, rnd=None):
        rnd = rnd or random
        x = ts / 3600.0
        p = 755.0 + 4.0 * math.sin(x / 9.0) + 1.5 * math.sin(x / 2.3) + rnd.uniform(-0.05, 0.05)
        t = 18.0 + 3.0 * math.sin((x - 8) / 24.0 * 2 * math.pi) + rnd.uniform(-0.05, 0.05)
        h = 55.0 + 10.0 * math.sin(x / 6.0) + rnd.uniform(-0.2, 0.2) if self.has_humidity else None
        return (ts, round(p, 2), round(t, 1), None if h is None else round(h, 1))

    def sample(self):
        return self._make(int(time.time()))


def iso(ts):
    off = TZ_OFFSET
    t = time.gmtime(ts + off)
    return time.strftime("%Y-%m-%dT%H:%M:%S", t) + "+03:00"


def make_handler(dev: MockDevice):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            pass

        # ---- вспомогательное
        def _cors(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")

        def send_json(self, obj, code=200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)

        def send_chunked(self, text, ctype="text/csv; charset=utf-8"):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Transfer-Encoding", "chunked")
            self._cors()
            self.end_headers()
            data = text.encode("utf-8")
            for i in range(0, len(data), 1000):                 # как sendContent() в прошивке
                chunk = data[i:i + 1000]
                self.wfile.write(f"{len(chunk):X}\r\n".encode() + chunk + b"\r\n")
            self.wfile.write(b"0\r\n\r\n")

        def params(self):
            q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                body = self.rfile.read(length).decode("utf-8")
                q.update({k: v[0] for k, v in parse_qs(body).items()})
            return q

        def err(self, code, msg):
            self.send_json({"success": False, "error": msg}, code)

        # ---- маршруты
        def do_GET(self):
            self.route("GET")

        def do_POST(self):
            self.route("POST")

        def route(self, method):
            path = urlparse(self.path).path
            q = self.params()
            with dev.lock:
                fn = {
                    "/api/current": self.current, "/api/status": self.status, "/api/forecast": self.forecast,
                    "/api/history": self.history, "/api/measure": self.measure, "/api/settings": self.settings,
                    "/api/wifi/scan": self.scan, "/api/time": self.time_api, "/api/export.csv": self.export,
                }.get(path)
                if fn is None:
                    return self.err(404, "not_found")
                fn(method, q)

        def current(self, m, q):
            ts, p, t, h = dev.records[-1]
            self.send_json({"state": "ok", "pressure": p, "pressure_hpa": round(p / 0.750061683, 2),
                            "temperature": t, "humidity": h, "humidity_valid": h is not None,
                            "timestamp": ts, "datetime": iso(ts), "age_s": int(time.time()) - ts,
                            "trend_mmhg_h": -0.42})

        def status(self, m, q):
            ts = int(time.time())
            self.send_json({
                "wifi": True, "wifi_state": "connected", "ssid": dev.ssid, "ip": "127.0.0.1", "rssi": -52, "ap": False,
                "mdns": "esp32-barograf.local", "sd": True, "sd_card_mb": 7580, "csv_bytes": 183450,
                "csv_file": "barograph.csv", "storage": "sd", "flash_ok": True, "flash_records": 0,
                "sensor": "BME280" if dev.has_humidity else "BMP280", "sensor_state": "ok", "sensor_address": "0x76",
                "uptime": int(time.time() - dev.t0), "free_heap": 180000, "history_records": len(dev.records),
                "history_capacity": 4782, "time_synced": True, "ntp_synced": dev.ntp,
                "time_source": "ntp" if dev.ntp else "browser", "epoch": ts, "datetime": iso(ts),
                "tz_offset_s": TZ_OFFSET, "fw_version": "1.0.0"})

        def forecast(self, m, q):
            self.send_json({"valid": True, "data_span_s": 18000, "pressure": dev.records[-1][1], "trend": "falling",
                            "trend_label": "ПАДЕНИЕ", "level": "slow_fall", "rate_mmhg_h": -0.42,
                            "change_3h_mmhg": -1.26,
                            "rates": {"10m": -0.5, "30m": -0.45, "1h": -0.4, "3h": -0.42, "6h": None},
                            "icon": "cloud", "windy": False, "summary": "Вероятно ухудшение погоды",
                            "details": "Давление медленно падает.", "probability_worse": 52, "probability_better": 11})

        def history(self, m, q):
            hours = float(q.get("hours", 1))
            mx = int(q.get("max", 400))
            cutoff = int(time.time() - hours * 3600)
            rows = [r for r in dev.records if r[0] >= cutoff]
            step = max(1, math.ceil(len(rows) / mx)) if rows else 1
            out = []
            for b in range(0, len(rows), step):
                g = rows[b:b + step]
                hs = [r[3] for r in g if r[3] is not None]
                out.append({"timestamp": int(sum(r[0] for r in g) / len(g)),
                            "pressure": round(sum(r[1] for r in g) / len(g), 2),
                            "temperature": round(sum(r[2] for r in g) / len(g), 1),
                            "humidity": round(sum(hs) / len(hs), 1) if hs else None})
            self.send_json({"hours": hours, "record_interval_s": dev.record_interval, "raw_count": len(rows),
                            "step": step, "count": len(out), "data": out})

        def measure(self, m, q):
            s = dev.sample()
            if q.get("store") in ("1", "true"):
                if s[0] > dev.records[-1][0]:
                    dev.records.append(s)
            self.send_json({"success": True, "pressure": s[1], "temperature": s[2], "humidity": s[3],
                            "humidity_valid": s[3] is not None, "timestamp": s[0],
                            "stored": q.get("store") in ("1", "true")})

        def settings(self, m, q):
            changed_wifi = False
            if m == "POST":
                if not any(k in q for k in ("ssid", "password", "measure_interval_s", "record_interval_s")):
                    return self.err(400, "no_parameters")
                m_i, r_i = int(q.get("measure_interval_s", dev.measure_interval)), int(q.get("record_interval_s", dev.record_interval))
                if not (5 <= m_i <= 3600 and 60 <= r_i <= 3600):
                    return self.err(400, "invalid_interval")
                if "password" in q and q["password"] and not (8 <= len(q["password"]) <= 63):
                    return self.err(400, "invalid_password_length_8_63")
                if "ssid" in q and q["ssid"] != dev.ssid:
                    changed_wifi = True
                    dev.ssid = q["ssid"]
                    dev.password_set = bool(q.get("password"))
                dev.measure_interval, dev.record_interval = m_i, r_i
            self.send_json({"success": True, "ssid": dev.ssid, "wifi_password_set": dev.password_set,
                            "measure_interval_s": dev.measure_interval, "record_interval_s": dev.record_interval,
                            "measure_interval_range": [5, 3600], "record_interval_range": [60, 3600],
                            "ap_ssid": "ESP32_barograf", "reconnecting": changed_wifi})

        def scan(self, m, q):
            if q.get("start") == "1":
                dev.scan_started = time.time()
                return self.send_json({"status": "scanning", "networks": []})
            if dev.scan_started == 0:
                return self.send_json({"status": "idle", "networks": []})
            if time.time() - dev.scan_started < 1.2:
                return self.send_json({"status": "scanning", "networks": []})
            dev.scan_started = 0
            self.send_json({"status": "done", "networks": [
                {"ssid": "MiWiFi", "rssi": -42, "channel": 6, "security": "WPA2"},
                {"ssid": "Neighbor", "rssi": -77, "channel": 11, "security": "WPA2"},
                {"ssid": "CafeOpen", "rssi": -81, "channel": 1, "security": "Open"}]})

        def time_api(self, m, q):
            applied = False
            if m == "POST":
                if "epoch" not in q:
                    return self.err(400, "epoch_required")
                applied = not dev.ntp
            ts = int(time.time())
            self.send_json({"success": True, "applied": applied, "synced": True,
                            "source": "ntp" if dev.ntp else "browser", "epoch": ts, "datetime": iso(ts)})

        def export(self, m, q):
            lines = ["timestamp,date,time,pressure_mmHg,temperature_c,humidity"]
            for ts, p, t, h in dev.records:
                tt = time.gmtime(ts + TZ_OFFSET)
                lines.append(f"{ts},{time.strftime('%Y-%m-%d', tt)},{time.strftime('%H:%M:%S', tt)},"
                             f"{p:.2f},{t:.1f},{'' if h is None else f'{h:.1f}'}")
            self.send_chunked("\n".join(lines) + "\n")

    return Handler


def start_mock(port=0, **kwargs):
    """Запуск в фоновом потоке. Возвращает (server, port, device)."""
    dev = MockDevice(**kwargs)
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(dev))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1], dev


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--hours", type=float, default=72)
    ap.add_argument("--bmp", action="store_true", help="датчик без влажности (BMP280)")
    a = ap.parse_args()
    srv, port, _ = start_mock(a.port, hours=a.hours, has_humidity=not a.bmp)
    print(f"Имитатор барографа: http://127.0.0.1:{port}  (Ctrl+C - выход)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        srv.shutdown()
