"""Командная строка: те же возможности без GUI (удобно для планировщика заданий / cron)."""
import argparse
import json
import sys
import time

from . import __version__
from .api_client import DeviceError
from .paths import Config
from .service import (EXPORT_FORMATS, client_from_config, export_data, import_csv_file, refresh_device_info,
                      resolve_period, sync_from_device, tz_from_config)
from .storage import Storage
from .timeutil import fmt_ts, parse_duration
from .units import PRESSURE_UNITS, convert_pressure, pressure_label


def _period_args(p):
    p.add_argument("--hours", type=float, help="последние N часов")
    p.add_argument("--from", dest="start", help="начало периода (ДД.ММ.ГГГГ [ЧЧ:ММ] или ГГГГ-ММ-ДД)")
    p.add_argument("--to", dest="end", help="конец периода")


def build_parser():
    ap = argparse.ArgumentParser(prog="barograph", description="ESP32 Barograph - клиент для ПК")
    ap.add_argument("--host", help="адрес устройства (по умолчанию из настроек)")
    ap.add_argument("--port", type=int, help="порт устройства")
    ap.add_argument("--db", help="путь к базе SQLite")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("gui", help="графический интерфейс (по умолчанию)")
    sub.add_parser("status", help="состояние устройства")
    sub.add_parser("current", help="текущие значения")
    sub.add_parser("forecast", help="прогноз")
    sp = sub.add_parser("sync", help="скачать историю с устройства в локальную базу")
    sp.add_argument("--loop", type=float, metavar="МИН", help="повторять каждые N минут")
    sub.add_parser("set-time", help="установить время устройства с этого компьютера (если нет NTP)")
    sub.add_parser("wifi-scan", help="сканировать Wi-Fi сети устройством")

    sp = sub.add_parser("settings", help="показать/изменить настройки устройства")
    sp.add_argument("--ssid")
    sp.add_argument("--password")
    sp.add_argument("--measure-interval", type=int, metavar="СЕК")
    sp.add_argument("--record-interval", type=int, metavar="СЕК")

    sp = sub.add_parser("stats", help="статистика по локальной базе")
    _period_args(sp)
    sp.add_argument("--unit", choices=sorted(PRESSURE_UNITS))

    sp = sub.add_parser("export", help="экспорт данных из локальной базы")
    sp.add_argument("--format", required=True, choices=[v[0] for v in EXPORT_FORMATS.values()])
    sp.add_argument("--out", required=True, help="выходной файл")
    _period_args(sp)
    sp.add_argument("--resample", default="0", help="усреднение: 0, 300, 5m, 1h, 1d")
    sp.add_argument("--unit", choices=sorted(PRESSURE_UNITS), help="единица давления")
    sp.add_argument("--excel-csv", action="store_true", help="CSV для русского Excel (; и десятичная запятая)")

    sp = sub.add_parser("import-csv", help="импорт CSV (например, barograph.csv с SD-карты)")
    sp.add_argument("file")
    return ap


def _spec(args):
    if args.start or args.end:
        return ("custom", args.start or "", args.end or "")
    if args.hours:
        return ("hours", args.hours)
    return ("all",)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cfg = Config()
    if args.db:
        cfg["db_path"] = args.db
    if args.cmd in (None, "gui"):
        from .gui import run_gui
        return run_gui(cfg)

    tz = tz_from_config(cfg)
    try:
        if args.cmd == "status":
            print(json.dumps(refresh_device_info(client_from_config(cfg, args.host, args.port), cfg),
                             ensure_ascii=False, indent=2))
            cfg.save()
        elif args.cmd == "current":
            print(json.dumps(client_from_config(cfg, args.host, args.port).current(), ensure_ascii=False, indent=2))
        elif args.cmd == "forecast":
            print(json.dumps(client_from_config(cfg, args.host, args.port).forecast(), ensure_ascii=False, indent=2))
        elif args.cmd == "set-time":
            print(json.dumps(client_from_config(cfg, args.host, args.port).set_time(), ensure_ascii=False, indent=2))
        elif args.cmd == "wifi-scan":
            for n in sorted(client_from_config(cfg, args.host, args.port).wifi_scan(), key=lambda n: -n["rssi"]):
                print(f'{n["rssi"]:>5} dBm  ch{n["channel"]:<3} {n["security"]:<10} {n["ssid"]}')
        elif args.cmd == "settings":
            cl = client_from_config(cfg, args.host, args.port)
            if any(v is not None for v in (args.ssid, args.password, args.measure_interval, args.record_interval)):
                res = cl.set_settings(ssid=args.ssid, password=args.password,
                                      measure_interval_s=args.measure_interval, record_interval_s=args.record_interval)
            else:
                res = cl.get_settings()
            print(json.dumps(res, ensure_ascii=False, indent=2))
        elif args.cmd == "sync":
            storage = Storage(cfg["db_path"])
            while True:
                cl = client_from_config(cfg, args.host, args.port)
                try:
                    refresh_device_info(cl, cfg)
                    tz = tz_from_config(cfg)
                    r = sync_from_device(cl, storage)
                    cfg.save()
                    print(f"[{fmt_ts(time.time(), tz)}] получено {r.downloaded}, новых {r.new}, "
                          f"всего в базе {r.total_in_db}  ({fmt_ts(r.first_ts, tz) if r.first_ts else '-'} — "
                          f"{fmt_ts(r.last_ts, tz) if r.last_ts else '-'})")
                except DeviceError as e:
                    if not args.loop:
                        raise
                    print(f"Ошибка: {e}", file=sys.stderr)
                if not args.loop:
                    break
                time.sleep(max(1.0, args.loop * 60))
        elif args.cmd == "import-csv":
            parsed, new = import_csv_file(Storage(cfg["db_path"]), args.file)
            print(f"Разобрано записей: {parsed}, новых добавлено: {new}")
        elif args.cmd in ("stats", "export"):
            storage = Storage(cfg["db_path"])
            start, end = resolve_period(_spec(args), tz, storage)
            unit = args.unit or cfg["pressure_unit"]
            if args.cmd == "stats":
                st = storage.stats(start, end)
                if not st["count"]:
                    print("Нет данных за период")
                    return 1
                print(f"Записей: {st['count']}   {fmt_ts(st['first_ts'], tz)} — {fmt_ts(st['last_ts'], tz)}")
                p = st["pressure"]
                print(f"Давление, {pressure_label(unit)}: мин {convert_pressure(p['min'], unit)}  "
                      f"макс {convert_pressure(p['max'], unit)}  среднее {convert_pressure(p['avg'], unit)}")
                for key, name, u in (("temperature", "Температура", "°C"), ("humidity", "Влажность", "%")):
                    s = st[key]
                    if s["min"] is not None:
                        print(f"{name}, {u}: мин {s['min']:.1f}  макс {s['max']:.1f}  среднее {s['avg']:.1f}")
            else:
                n = export_data(storage, args.format, args.out, start, end, tz, unit,
                                resample_s=parse_duration(args.resample), excel_ru=args.excel_csv)
                print(f"Экспортировано записей: {n} -> {args.out}")
    except (DeviceError, ValueError, OSError) as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 2
    except Exception as e:                     # ExportError и пр.
        print(f"Ошибка: {e}", file=sys.stderr)
        return 2
    return 0
