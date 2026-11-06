"""Новое API прошивки (/api/range, /api/history?from&to, /api/export/full.csv), выгрузка CSV с устройства и
график по CSV-файлу за произвольный период - против имитатора ESP32.
Запуск:  python -m unittest discover -s tests -v
"""
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import matplotlib
matplotlib.use("Agg")

from barograph import cli, exporters, service
from barograph.api_client import BarographClient, DeviceError, parse_csv_text
from barograph.csvdata import CsvDataset, CsvFormatError, parse_csv_flexible
from barograph.storage import Storage
from barograph.timeutil import tz_from_offset
from mock_esp32 import start_mock

TZ = tz_from_offset(10800)


class DeviceCsvTests(unittest.TestCase):
    """Устройство с SD-картой: 72 ч в ОЗУ и 240 ч в CSV на карте."""

    @classmethod
    def setUpClass(cls):
        cls.srv, cls.port, cls.dev = start_mock(0, hours=72, sd_hours=240)
        cls.srv2, cls.port2, cls.dev2 = start_mock(0, hours=72, sd_hours=240, sd=False)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.client = BarographClient("127.0.0.1", cls.port, timeout=10)
        cls.client_nosd = BarographClient("127.0.0.1", cls.port2, timeout=10)
        cls.all = cls.dev.sd_rows()

    @classmethod
    def tearDownClass(cls):
        for srv in (cls.srv, cls.srv2):
            srv.shutdown()
            srv.server_close()
        cls.tmp.cleanup()

    def path(self, name):
        return os.path.join(self.tmp.name, name)

    # ---------------- /api/range
    def test_01_range(self):
        r = self.client.range()
        self.assertTrue(r["has_data"])
        self.assertEqual((r["first"], r["last"]), (self.all[0][0], self.all[-1][0]))
        self.assertEqual(r["source"], "sd")
        r2 = self.client_nosd.range()                    # без карты - только буфер ОЗУ (72 ч)
        self.assertEqual(r2["source"], "ram")
        self.assertEqual(r2["first"], self.dev2.records[0][0])
        self.assertGreater(r2["first"], r["first"])

    # ---------------- /api/history?from&to
    def test_02_history_range(self):
        first, last = self.all[0][0], self.all[-1][0]
        a, b = first + 10 * 3600, first + 100 * 3600
        h = self.client.history_range(a, b, max_points=200)
        self.assertEqual(h["source"], "sd")
        self.assertLessEqual(h["count"], 200)
        self.assertEqual(h["raw_count"], sum(1 for r in self.all if a <= r[0] <= b))
        self.assertGreaterEqual(h["data"][0]["timestamp"], a)
        self.assertLessEqual(h["data"][-1]["timestamp"], b)
        # только from - до конца данных, только to - с начала данных
        self.assertEqual(self.client.history_range(start=last - 3600, max_points=100)["to"], last)
        self.assertEqual(self.client.history_range(end=first + 3600, max_points=100)["from"], first)
        # период шире данных обрезается по данным
        wide = self.client.history_range(first - 99999, last + 99999, max_points=100)
        self.assertEqual((wide["from"], wide["to"]), (first, last))

    def test_03_history_range_errors_and_empty(self):
        first, last = self.all[0][0], self.all[-1][0]
        for kwargs, code in (({"start": last, "end": first}, "invalid_range"),
                             ({"start": first, "end": first}, "invalid_range")):
            with self.assertRaises(DeviceError) as cm:
                self.client.history_range(**kwargs)
            self.assertEqual(cm.exception.error, code)
        with self.assertRaises(DeviceError) as cm:
            self.client.get_json("/api/history", {"from": "abc"})
        self.assertEqual(cm.exception.error, "invalid_from")
        empty = self.client.history_range(last + 1000, last + 5000)       # периода нет в данных
        self.assertEqual((empty["count"], empty["data"]), (0, []))

    # ---------------- /api/export/full.csv
    def test_10_download_full(self):
        dest = self.path("full.csv")
        seen = []
        res = self.client.download_csv(dest, progress=seen.append)
        self.assertEqual(res["source"], "sd")
        self.assertEqual(res["rows"], len(self.all))
        self.assertEqual(res["bytes"], os.path.getsize(dest))
        self.assertTrue(seen and seen[-1] == res["bytes"])
        with open(dest, encoding="utf-8") as f:
            self.assertEqual([r[0] for r in parse_csv_text(f.read())], [r[0] for r in self.all])
        self.assertFalse(os.path.exists(dest + ".part"))

    def test_11_download_period_inclusive(self):
        a, b = self.all[1000][0], self.all[2000][0]
        dest = self.path("period.csv")
        res = self.client.download_csv(dest, a, b)
        self.assertEqual(res["source"], "sd")
        self.assertEqual(res["rows"], 1001)                  # границы включаются
        ds = CsvDataset.from_file(dest)
        self.assertEqual(ds.bounds(), (a, b))

    def test_12_download_without_sd_falls_back_to_ram(self):
        a = self.dev2.records[100][0]
        b = self.dev2.records[200][0]
        dest = self.path("ram.csv")
        res = self.client_nosd.download_csv(dest, a, b)
        self.assertEqual(res["source"], "ram")
        self.assertEqual(res["rows"], 101)
        self.assertEqual(CsvDataset.from_file(dest).bounds(), (a, b))
        full = self.client_nosd.download_csv(self.path("ram_all.csv"))    # без периода - весь буфер ОЗУ
        self.assertEqual(full["rows"], len(self.dev2.records))

    def test_13_download_empty_period(self):
        last = self.all[-1][0]
        dest = self.path("empty.csv")
        res = self.client.download_csv(dest, last + 1000, last + 2000)
        self.assertEqual(res["rows"], 0)                      # только заголовок
        with open(dest, encoding="utf-8") as f:
            self.assertEqual(len(f.read().splitlines()), 1)

    def test_14_download_errors_leave_no_files(self):
        dest = self.path("bad.csv")
        with self.assertRaises(DeviceError) as cm:
            self.client.download_csv(dest, 2000, 1000)
        self.assertEqual(cm.exception.error, "invalid_range")
        dead = BarographClient("127.0.0.1", 1, timeout=1)
        with self.assertRaises(DeviceError):
            dead.download_csv(dest)
        self.assertFalse(os.path.exists(dest))
        self.assertFalse(os.path.exists(dest + ".part"))

    def test_15_download_does_not_replace_existing_file_on_error(self):
        dest = self.path("keep.csv")
        with open(dest, "w") as f:
            f.write("old")
        with self.assertRaises(DeviceError):
            self.client.download_csv(dest, 2000, 1000)
        with open(dest) as f:
            self.assertEqual(f.read(), "old")

    # ---------------- период для запросов
    def test_20_device_period_params(self):
        now = 1_800_000_000
        self.assertEqual(service.device_period_params(("all",), TZ, now), (None, None))
        self.assertEqual(service.device_period_params(("hours", 6), TZ, now), (now - 6 * 3600, None))
        s, e = service.device_period_params(("custom", "01.11.2026 10:00", "02.11.2026"), TZ, now)
        self.assertEqual(e - s, 14 * 3600 + 86399 - 0)       # 02.11 до 23:59:59, начало 01.11 10:00
        self.assertEqual(service.device_period_params(("custom", "", "02.11.2026"), TZ, now)[0], None)
        with self.assertRaises(ValueError):
            service.device_period_params(("custom", "02.11.2026", "01.11.2026"), TZ, now)

    def test_21_service_download(self):
        dest = self.path("svc.csv")
        res = service.download_device_csv(self.client, dest, ("hours", 24), TZ)
        self.assertEqual(res["source"], "sd")
        self.assertIsNotNone(res["start"])
        self.assertIsNone(res["end"])
        self.assertAlmostEqual(res["rows"], 24 * 60, delta=2)


class CsvDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv, cls.port, cls.dev = start_mock(0, hours=72, sd_hours=240)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.rows = cls.dev.sd_rows()
        cls.csv = os.path.join(cls.tmp.name, "data.csv")
        BarographClient("127.0.0.1", cls.port).download_csv(cls.csv)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def path(self, name):
        return os.path.join(self.tmp.name, name)

    def test_01_loads_device_file(self):
        ds = CsvDataset.from_file(self.csv)
        self.assertEqual(ds.count(), len(self.rows))
        self.assertEqual(ds.bounds(), (self.rows[0][0], self.rows[-1][0]))
        self.assertEqual(ds.skipped, 0)

    def test_02_same_results_as_storage(self):
        ds = CsvDataset.from_file(self.csv)
        st = Storage(self.path("parity.db"))
        st.insert_many(self.rows)
        a, b = self.rows[500][0], self.rows[9000][0]
        self.assertEqual(ds.count(a, b), st.count(a, b))
        self.assertEqual(ds.bounds(), st.bounds())
        self.assertEqual(ds.query(a, b), st.query(a, b))
        self.assertEqual(ds.query(a, b, bucket_s=300), st.query(a, b, bucket_s=300))
        self.assertEqual(ds.query(max_points=500), st.query(max_points=500))
        s1, s2 = ds.stats(a, b), st.stats(a, b)
        for key in ("count", "first_ts", "last_ts"):
            self.assertEqual(s1[key], s2[key])
        for name in ("pressure", "temperature", "humidity"):
            for k in ("min", "max", "avg"):
                self.assertAlmostEqual(s1[name][k], s2[name][k], places=6, msg=f"{name}.{k}")
        self.assertAlmostEqual(s1["pressure"]["change"], s2["pressure"]["change"], places=6)

    def test_03_empty_period_and_bmp_without_humidity(self):
        ds = CsvDataset.from_file(self.csv)
        last = ds.bounds()[1]
        self.assertEqual(ds.query(last + 10, last + 100), [])
        st = ds.stats(last + 10, last + 100)
        self.assertEqual((st["count"], st["pressure"]["min"]), (0, None))
        bmp = CsvDataset([(r[0], r[1], r[2], None) for r in self.rows[:100]])
        self.assertIsNone(bmp.stats()["humidity"]["avg"])
        self.assertIsNone(bmp.query(bucket_s=600)[0][3])

    def test_04_period_relative_to_data(self):
        ds = CsvDataset.from_file(self.csv)
        last = ds.bounds()[1]
        old = CsvDataset([(r[0] - 400 * 86400, r[1], r[2], r[3]) for r in self.rows])      # файл «давнишний»
        a, b = service.resolve_period(("hours", 24), TZ, old, relative_to_data=True)
        self.assertEqual(b - a, 24 * 3600)
        self.assertEqual(b, old.bounds()[1])
        self.assertGreater(old.count(a, b), 1000)
        self.assertEqual(old.count(*service.resolve_period(("hours", 24), TZ, old)), 0)    # от «сейчас» пусто
        a, b = service.resolve_period(("custom", "", ""), TZ, ds, relative_to_data=True)
        self.assertEqual(b, last)

    def test_05_flexible_parser_formats(self):
        rows = self.rows[:50]
        for unit, ru in (("mmHg", False), ("hPa", False), ("kPa", True), ("hPa", True)):
            p = self.path(f"app_{unit}_{ru}.csv")
            exporters.export_csv(rows, p, TZ, unit, ru)
            ds = CsvDataset.from_file(p)
            self.assertEqual(ds.count(), 50)
            for got, want in zip(ds.rows, rows):
                self.assertEqual(got[0], want[0])
                self.assertAlmostEqual(got[1], want[1], delta=0.02)      # округление при экспорте в гПа/кПа
                self.assertAlmostEqual(got[2], want[2], delta=0.05)

    def test_06_flexible_parser_dirty_data(self):
        text = ("﻿timestamp,date,time,pressure_mmHg,temperature_c,humidity\n"
                "1800000300,2027-01-15,10:05:00,750.50,20.1,40.0\n"
                "1800000000,2027-01-15,10:00:00,751.00,20.0,\n"       # раньше предыдущей, влажности нет
                "1800000000,2027-01-15,10:00:00,760.00,20.0,\n"       # дубль метки - берётся первая
                "1800000600,2027-01-15,10:10:00,not_a_number,20.0,\n"
                "1800000900,2027-01-15,10:15:00,2000.0,20.0,\n"       # давление вне диапазона
                "18000012\n"                                          # оборванная строка
                "\n"
                "1800000900,2027-01-15,10:15:00,749.00,19.8,41.5\n")
        rows, skipped = parse_csv_flexible(text)
        self.assertEqual([r[0] for r in rows], [1800000000, 1800000300, 1800000900])
        self.assertEqual(rows[0][1], 751.0)
        self.assertIsNone(rows[0][3])
        self.assertEqual(skipped, 3)
        # пустой файл или не тот формат
        for bad in ("", "hello world\nfoo,bar\n", "timestamp,date,time,pressure_mmHg,temperature_c,humidity\n"):
            p = self.path("bad.csv")
            with open(p, "w", encoding="utf-8") as f:
                f.write(bad)
            with self.assertRaises(CsvFormatError):
                CsvDataset.from_file(p)

    def test_07_png_from_csv(self):
        ds = CsvDataset.from_file(self.csv)
        a, b = self.rows[100][0], self.rows[3000][0]
        out = self.path("g.png")
        n = service.export_data(ds, "png", out, a, b, TZ, "hPa", metrics=("pressure", "temperature"))
        self.assertGreater(n, 0)
        with open(out, "rb") as f:
            self.assertEqual(f.read(8), b"\x89PNG\r\n\x1a\n")
        with self.assertRaises(exporters.ExportError):             # период без данных
            service.export_data(ds, "png", self.path("e.png"), 10, 20, TZ)

    # ---------------- командная строка
    def test_10_cli(self):
        base = ["--host", "127.0.0.1", "--port", str(self.port), "--db", self.path("cli.db")]
        self.assertEqual(cli.main(base + ["device-range"]), 0)
        out = self.path("cli_dl.csv")
        self.assertEqual(cli.main(base + ["download-csv", "--out", out, "--hours", "12", "--import"]), 0)
        self.assertAlmostEqual(CsvDataset.from_file(out).count(), 12 * 60, delta=2)
        self.assertEqual(Storage(self.path("cli.db")).count(), CsvDataset.from_file(out).count())
        a = time.strftime("%d.%m.%Y %H:%M", time.gmtime(self.rows[100][0] + 10800))
        b = time.strftime("%d.%m.%Y %H:%M", time.gmtime(self.rows[3000][0] + 10800))
        png = self.path("cli.png")
        self.assertEqual(cli.main(base + ["export", "--csv", self.csv, "--format", "png", "--out", png,
                                          "--from", a, "--to", b]), 0)
        self.assertGreater(os.path.getsize(png), 1000)
        self.assertEqual(cli.main(base + ["stats", "--csv", self.csv, "--hours", "24"]), 0)   # от конца данных файла
        self.assertEqual(cli.main(base + ["export", "--csv", self.csv, "--format", "sqlite",
                                          "--out", self.path("x.sqlite")]), 2)
        self.assertEqual(cli.main(base + ["stats", "--csv", self.path("no_such.csv")]), 2)
        # период без записей: файл сохраняется (только заголовок), код возврата 1
        last = self.rows[-1][0]
        future = time.strftime("%d.%m.%Y %H:%M", time.gmtime(last + 86400 + 10800))
        self.assertEqual(cli.main(base + ["download-csv", "--out", self.path("none.csv"), "--from", future]), 1)


if __name__ == "__main__":
    unittest.main()
