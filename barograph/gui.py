"""Графический интерфейс (tkinter + matplotlib). Все сетевые операции и работа с БД - в фоновых потоках."""
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

from . import __version__, plotting
from .api_client import DeviceError
from .service import (EXPORT_FORMATS, PERIOD_PRESETS, RESAMPLE_PRESETS, client_from_config, export_data,
                      import_csv_file, refresh_device_info, resolve_period, sync_from_device, tz_from_config)
from .storage import Storage
from .timeutil import fmt_ts, local_offset_s
from .units import PRESSURE_UNITS, convert_pressure, pressure_label

# только символы из BMP (Tk на Windows не умеет остальные)
WEATHER_ICONS = {"sun": "☀", "partly": "⛅", "cloud": "☁", "rain": "☂", "storm": "⚡", "snow": "❄", "unknown": "…"}
MEASURE_VALUES = [5, 10, 30, 60, 300, 600, 1800, 3600]
RECORD_VALUES = [60, 120, 300, 600, 1800, 3600]


def open_path(path):
    """Открыть папку/файл в файловом менеджере ОС."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)                                  # noqa
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except OSError:
        pass


class PeriodSelector(ttk.Frame):
    """Выбор периода: готовые интервалы или свои даты."""

    def __init__(self, master, default="24 часа", on_change=None):
        super().__init__(master)
        self.on_change = on_change
        self.var = tk.StringVar(value=default)
        self.start_var = tk.StringVar()
        self.end_var = tk.StringVar()
        ttk.Label(self, text="Период:").pack(side="left")
        self.combo = ttk.Combobox(self, textvariable=self.var, values=[p[0] for p in PERIOD_PRESETS],
                                  state="readonly", width=13)
        self.combo.pack(side="left", padx=4)
        ttk.Label(self, text="с").pack(side="left")
        self.start_entry = ttk.Entry(self, textvariable=self.start_var, width=16)
        self.start_entry.pack(side="left", padx=3)
        ttk.Label(self, text="по").pack(side="left")
        self.end_entry = ttk.Entry(self, textvariable=self.end_var, width=16)
        self.end_entry.pack(side="left", padx=3)
        ttk.Label(self, text="(ДД.ММ.ГГГГ ЧЧ:ММ)", foreground="gray").pack(side="left", padx=4)
        self.combo.bind("<<ComboboxSelected>>", self._changed)
        self._apply_state()

    def _apply_state(self):
        state = "normal" if self.var.get() == "Свой период" else "disabled"
        self.start_entry.configure(state=state)
        self.end_entry.configure(state=state)

    def _changed(self, _event=None):
        self._apply_state()
        if self.on_change:
            self.on_change(self)

    def set_custom_defaults(self, start_text, end_text):
        if not self.start_var.get():
            self.start_var.set(start_text)
        if not self.end_var.get():
            self.end_var.set(end_text)

    def spec(self):
        label = self.var.get()
        for name, value in PERIOD_PRESETS:
            if name == label:
                if value == "custom":
                    return ("custom", self.start_var.get(), self.end_var.get())
                if value is None:
                    return ("all",)
                return ("hours", value)
        return ("hours", 24)


class App(tk.Tk):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.title(f"ESP32 Барограф — {__version__}")
        self.geometry("1120x780")
        self.minsize(900, 640)
        self._q = queue.Queue()
        self._live_busy = False
        self._sync_busy = False
        self._connected = None
        self._last_live = 0.0
        self._last_sync = 0.0
        self._scan_busy = False
        try:
            self.storage = Storage(cfg["db_path"])
        except OSError as e:
            messagebox.showerror("База данных", f"Не удалось открыть базу:\n{cfg['db_path']}\n{e}")
            from .paths import data_dir
            cfg["db_path"] = str(data_dir() / "barograph.db")
            self.storage = Storage(cfg["db_path"])

        style = ttk.Style(self)
        if sys.platform.startswith("linux") and "clam" in style.theme_names():
            style.theme_use("clam")
        self.big_font = tkfont.Font(size=26, weight="bold")
        self.mid_font = tkfont.Font(size=14, weight="bold")
        self.icon_font = tkfont.Font(size=44)
        self.fixed_font = tkfont.nametofont("TkFixedFont")

        self._build_toolbar()
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=6, pady=4)
        self._build_live_tab()
        self._build_data_tab()
        self._build_export_tab()
        self._build_device_tab()
        self._build_app_tab()
        self._build_log_tab()
        self._build_statusbar()
        self.nb.bind("<<NotebookTabChanged>>", self._tab_changed)

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self._pump)
        self.after(300, self.refresh_live)
        self.after(1000, self._auto_tick)
        self.update_db_info()
        self.log(f"Приложение запущено. База данных: {cfg['db_path']}")

    # ================================================================== инфраструктура
    def tz(self):
        return tz_from_config(self.cfg)

    def unit(self):
        return self.cfg["pressure_unit"] if self.cfg["pressure_unit"] in PRESSURE_UNITS else "mmHg"

    def client(self):
        host = self.host_var.get().strip() or self.cfg["host"]
        try:
            port = int(self.port_var.get())
        except ValueError:
            port = 80
        self.cfg["host"], self.cfg["port"] = host, port
        return client_from_config(self.cfg)

    def bg(self, job, ok=None, err=None):
        """Выполнить job() в потоке, затем ok(результат) или err(исключение) в потоке интерфейса."""
        def worker():
            try:
                res = job()
            except Exception as e:                              # noqa
                self._q.put((err or self._generic_err, e))
            else:
                self._q.put((ok, res))
        threading.Thread(target=worker, daemon=True).start()

    def _pump(self):
        try:
            while True:
                cb, arg = self._q.get_nowait()
                if cb:
                    try:
                        cb(arg)
                    except Exception as e:                      # ошибка в обработчике не должна ронять приложение
                        self.log(f"Внутренняя ошибка: {e!r}")
        except queue.Empty:
            pass
        self.after(100, self._pump)

    def log(self, msg):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}\n"
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _generic_err(self, e):
        self.log(f"Ошибка: {e}")
        messagebox.showerror("Ошибка", str(e))

    def on_close(self):
        self._save_geometry_and_cfg()
        self.destroy()

    def _save_geometry_and_cfg(self):
        self.cfg["host"] = self.host_var.get().strip() or self.cfg["host"]
        self.cfg.save()

    # ================================================================== панель подключения / статус
    def _build_toolbar(self):
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=8, pady=(8, 2))
        self.host_var = tk.StringVar(value=self.cfg["host"])
        self.port_var = tk.StringVar(value=str(self.cfg["port"]))
        ttk.Label(bar, text="Устройство:").pack(side="left")
        ttk.Entry(bar, textvariable=self.host_var, width=26).pack(side="left", padx=4)
        ttk.Label(bar, text="порт").pack(side="left")
        ttk.Entry(bar, textvariable=self.port_var, width=6).pack(side="left", padx=4)
        ttk.Button(bar, text="Подключиться", command=self.refresh_live).pack(side="left", padx=6)
        self.conn_label = ttk.Label(bar, text="● нет связи", foreground="#c0392b")
        self.conn_label.pack(side="left", padx=10)
        ttk.Button(bar, text="Синхронизировать историю", command=self.start_sync).pack(side="right")

    def _build_statusbar(self):
        bar = ttk.Frame(self)
        bar.pack(fill="x", side="bottom", padx=8, pady=(0, 6))
        self.db_label = ttk.Label(bar, text="")
        self.db_label.pack(side="left")
        ttk.Label(bar, text=f"v{__version__}", foreground="gray").pack(side="right")

    def update_db_info(self):
        def job():
            return self.storage.count(), self.storage.bounds()

        def ok(res):
            count, b = res
            tz = self.tz()
            rng = f"{fmt_ts(b[0], tz, '%d.%m.%Y %H:%M')} — {fmt_ts(b[1], tz, '%d.%m.%Y %H:%M')}" if b else "пусто"
            self.db_label.configure(text=f"База: {count} записей ({rng})")
            if hasattr(self, "app_db_info"):
                self.app_db_info.configure(text=f"Записей: {count}. Период: {rng}")
        self.bg(job, ok, lambda e: self.log(f"БД: {e}"))

    def _tab_changed(self, _e=None):
        tab = self.nb.index(self.nb.select())
        if tab == 1:
            self.replot()
        elif tab == 2:
            self._refresh_export_name()
        elif tab == 3:
            self.load_device_settings()

    # ================================================================== вкладка 1: устройство
    def _build_live_tab(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="  Устройство  ")
        grid = ttk.Frame(tab)
        grid.pack(fill="x", padx=10, pady=10)
        self.live_vars = {}
        items = [("pressure", "Давление"), ("temperature", "Температура"), ("humidity", "Влажность"),
                 ("trend", "Тренд")]
        for i, (key, title) in enumerate(items):
            box = ttk.LabelFrame(grid, text=title)
            box.grid(row=0, column=i, padx=6, pady=4, sticky="nsew")
            grid.columnconfigure(i, weight=1)
            var = tk.StringVar(value="--")
            self.live_vars[key] = var
            ttk.Label(box, textvariable=var, font=self.big_font).pack(padx=10, pady=(8, 0))
            unit_var = tk.StringVar(value="")
            self.live_vars[key + "_unit"] = unit_var
            ttk.Label(box, textvariable=unit_var, foreground="gray").pack(pady=(0, 8))

        self.live_info = tk.StringVar(value="")
        ttk.Label(tab, textvariable=self.live_info, foreground="gray").pack(anchor="w", padx=16)

        fbox = ttk.LabelFrame(tab, text="Прогноз по тренду давления")
        fbox.pack(fill="x", padx=16, pady=10)
        top = ttk.Frame(fbox)
        top.pack(fill="x", padx=10, pady=8)
        self.fc_icon = tk.StringVar(value="…")
        ttk.Label(top, textvariable=self.fc_icon, font=self.icon_font, width=3).pack(side="left", padx=(4, 16))
        txt = ttk.Frame(top)
        txt.pack(side="left", fill="x", expand=True)
        self.fc_summary = tk.StringVar(value="—")
        self.fc_details = tk.StringVar(value="")
        self.fc_trend = tk.StringVar(value="")
        ttk.Label(txt, textvariable=self.fc_summary, font=self.mid_font).pack(anchor="w")
        ttk.Label(txt, textvariable=self.fc_details, wraplength=640).pack(anchor="w")
        ttk.Label(txt, textvariable=self.fc_trend, foreground="gray").pack(anchor="w", pady=(4, 0))
        prob = ttk.Frame(fbox)
        prob.pack(fill="x", padx=14, pady=(0, 10))
        self.p_worse = tk.DoubleVar(value=0)
        self.p_better = tk.DoubleVar(value=0)
        self.p_worse_txt = tk.StringVar(value="Ухудшение: —")
        self.p_better_txt = tk.StringVar(value="Улучшение: —")
        ttk.Label(prob, textvariable=self.p_worse_txt, width=22).grid(row=0, column=0, sticky="w")
        ttk.Progressbar(prob, variable=self.p_worse, maximum=100, length=320).grid(row=0, column=1, padx=6, pady=2)
        ttk.Label(prob, textvariable=self.p_better_txt, width=22).grid(row=1, column=0, sticky="w")
        ttk.Progressbar(prob, variable=self.p_better, maximum=100, length=320).grid(row=1, column=1, padx=6, pady=2)

        act = ttk.Frame(tab)
        act.pack(fill="x", padx=16, pady=6)
        ttk.Button(act, text="Измерить сейчас", command=self.measure_now).pack(side="left")
        self.store_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(act, text="записать это измерение в историю устройства", variable=self.store_var).pack(
            side="left", padx=10)
        self.measure_result = tk.StringVar(value="")
        ttk.Label(act, textvariable=self.measure_result, foreground="gray").pack(side="left", padx=10)

    def refresh_live(self):
        if self._live_busy:
            return
        self._live_busy = True
        self._last_live = time.time()
        cl = self.client()

        def job():
            st = refresh_device_info(cl, self.cfg)
            return st, cl.current(), cl.forecast()
        self.bg(job, self._live_ok, self._live_err)

    def _live_ok(self, res):
        self._live_busy = False
        st, cur, fc = res
        if self._connected is not True:
            self.log(f"Подключено: {self.client().active_host} ({st.get('sensor')}, ПО {st.get('fw_version')})")
        self._connected = True
        self.conn_label.configure(text="● на связи", foreground="#1e8449")
        self.cfg.save()
        self.tz_hours_var.set(self._fmt_hours(self.cfg["tz_offset_s"]))
        ok = cur.get("state") == "ok"
        unit = self.unit()
        p = cur.get("pressure")
        self.live_vars["pressure"].set(f"{convert_pressure(p, unit):.{2 if unit != 'kPa' else 3}f}" if ok and p is not None else "--")
        self.live_vars["pressure_unit"].set(pressure_label(unit))
        self.live_vars["temperature"].set(f"{cur['temperature']:.1f}" if ok and cur.get("temperature") is not None else "--")
        self.live_vars["temperature_unit"].set("°C")
        hum = cur.get("humidity")
        self.live_vars["humidity"].set(f"{hum:.0f}" if ok and hum is not None else "N/A")
        self.live_vars["humidity_unit"].set("%" if hum is not None else "датчик без влажности")
        tr = cur.get("trend_mmhg_h")
        self.live_vars["trend"].set("--" if tr is None else f"{convert_pressure(tr, unit):+.2f}")
        self.live_vars["trend_unit"].set(f"{pressure_label(unit)}/ч")
        if cur.get("state") == "sensor_not_found":
            self.live_vars["pressure"].set("нет датчика")
        self.live_info.set(f"Датчик: {st.get('sensor')} {st.get('sensor_address') or ''} · время устройства: "
                           f"{st.get('datetime') or 'не установлено'} ({st.get('time_source')}) · "
                           f"Wi-Fi: {st.get('ssid')} {st.get('rssi')} dBm · хранилище: {st.get('storage')}")
        self.fc_icon.set(WEATHER_ICONS.get(fc.get("icon"), "…") + (" ≋" if fc.get("windy") else ""))
        self.fc_summary.set(fc.get("summary") or "—")
        self.fc_details.set(fc.get("details") or "")
        r = fc.get("rate_mmhg_h")
        self.fc_trend.set(f"Тренд: {fc.get('trend_label')}" + ("" if r is None else f" ({r:+.2f} мм рт. ст./ч)"))
        if fc.get("valid"):
            self.p_worse.set(fc["probability_worse"])
            self.p_better.set(fc["probability_better"])
            self.p_worse_txt.set(f"Ухудшение: {fc['probability_worse']} %")
            self.p_better_txt.set(f"Улучшение: {fc['probability_better']} %")
        else:
            self.p_worse.set(0)
            self.p_better.set(0)
            self.p_worse_txt.set("Ухудшение: —")
            self.p_better_txt.set("Улучшение: —")
        self.show_device_status(st)

    def _live_err(self, e):
        self._live_busy = False
        if self._connected is not False:
            self.log(f"Нет связи с устройством: {e}")
        self._connected = False
        self.conn_label.configure(text="● нет связи", foreground="#c0392b")

    def measure_now(self):
        cl = self.client()
        store = self.store_var.get()
        self.measure_result.set("измеряю…")

        def ok(m):
            unit = self.unit()
            hum = f", {m['humidity']:.1f} %" if m.get("humidity") is not None else ""
            self.measure_result.set(f"{convert_pressure(m['pressure'], unit)} {pressure_label(unit)}, "
                                    f"{m['temperature']:.1f} °C{hum}" + (" · записано в историю" if m.get("stored") else ""))
            self.refresh_live()

        def err(e):
            self.measure_result.set(f"ошибка: {e}")
        self.bg(lambda: cl.measure(store=store), ok, err)

    # ================================================================== вкладка 2: график
    def _build_data_tab(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="  Данные и график  ")
        top = ttk.Frame(tab)
        top.pack(fill="x", padx=8, pady=6)
        self.period_plot = PeriodSelector(top, default="24 часа", on_change=self._period_changed)
        self.period_plot.pack(side="left")
        row2 = ttk.Frame(tab)
        row2.pack(fill="x", padx=8, pady=2)
        self.metric_vars = {}
        for key, label in (("pressure", "Давление"), ("temperature", "Температура"), ("humidity", "Влажность")):
            v = tk.BooleanVar(value=key != "humidity")
            self.metric_vars[key] = v
            ttk.Checkbutton(row2, text=label, variable=v, command=self.replot).pack(side="left", padx=6)
        ttk.Button(row2, text="Построить", command=self.replot).pack(side="left", padx=12)
        ttk.Button(row2, text="Сохранить PNG…", command=self.save_png).pack(side="left")
        ttk.Button(row2, text="Загрузить с устройства", command=self.start_sync).pack(side="right")

        self.stats_var = tk.StringVar(value="")
        ttk.Label(tab, textvariable=self.stats_var, justify="left").pack(fill="x", padx=12, pady=2)
        plot_frame = ttk.Frame(tab)
        plot_frame.pack(fill="both", expand=True, padx=8, pady=4)
        self.fig = plotting.new_figure()
        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_frame)
        self.toolbar = NavigationToolbar2Tk(self.canvas, plot_frame)
        self.toolbar.update()
        self.canvas.get_tk_widget().pack(side="top", fill="both", expand=True)

    def _period_changed(self, sel):
        if sel.var.get() == "Свой период":
            now = time.time()
            tz = self.tz()
            sel.set_custom_defaults(fmt_ts(now - 86400, tz, "%d.%m.%Y %H:%M"), fmt_ts(now, tz, "%d.%m.%Y %H:%M"))
        elif sel is self.period_plot:
            self.replot()

    def selected_metrics(self):
        return [k for k, v in self.metric_vars.items() if v.get()]

    def replot(self):
        try:
            start, end = resolve_period(self.period_plot.spec(), self.tz(), self.storage)
        except ValueError as e:
            messagebox.showerror("Период", str(e))
            return
        metrics = self.selected_metrics()

        def job():
            return self.storage.query(start, end, max_points=3000), self.storage.stats(start, end)
        self.bg(job, lambda res: self._plot_done(res, metrics))

    def _plot_done(self, res, metrics):
        rows, st = res
        tz, unit = self.tz(), self.unit()
        plotting.draw_figure(self.fig, rows, metrics, tz, unit)
        self.canvas.draw_idle()
        self.toolbar.update()
        if not st["count"]:
            self.stats_var.set("Нет данных за период. Нажмите «Загрузить с устройства» или импортируйте CSV на вкладке «Экспорт».")
            return
        p = st["pressure"]
        lines = [f"Записей: {st['count']}   ({fmt_ts(st['first_ts'], tz)} — {fmt_ts(st['last_ts'], tz)})",
                 f"Давление, {pressure_label(unit)}: мин {convert_pressure(p['min'], unit)}  "
                 f"макс {convert_pressure(p['max'], unit)}  среднее {convert_pressure(p['avg'], unit)}  "
                 f"изменение {convert_pressure(p.get('change'), unit):+}"]
        t, h = st["temperature"], st["humidity"]
        if t["min"] is not None:
            lines.append(f"Температура, °C: мин {t['min']:.1f}  макс {t['max']:.1f}  среднее {t['avg']:.1f}"
                         + (f"      Влажность, %: мин {h['min']:.1f}  макс {h['max']:.1f}  среднее {h['avg']:.1f}"
                            if h["min"] is not None else ""))
        self.stats_var.set("\n".join(lines))

    def save_png(self):
        try:
            start, end = resolve_period(self.period_plot.spec(), self.tz(), self.storage)
        except ValueError as e:
            messagebox.showerror("Период", str(e))
            return
        path = filedialog.asksaveasfilename(
            title="Сохранить график", defaultextension=".png", filetypes=[("PNG", "*.png")],
            initialdir=self.cfg["export_dir"], initialfile=time.strftime("barograph_%Y%m%d_%H%M.png"))
        if not path:
            return
        self.cfg["export_dir"] = os.path.dirname(path)
        metrics = self.selected_metrics()
        tz, unit = self.tz(), self.unit()
        self.bg(lambda: export_data(self.storage, "png", path, start, end, tz, unit, metrics=metrics),
                lambda n: self.log(f"График сохранён: {path}"))

    # ================================================================== синхронизация
    def start_sync(self, silent=False):
        if self._sync_busy:
            return
        self._sync_busy = True
        self._last_sync = time.time()
        cl = self.client()
        self.log("Синхронизация: загрузка истории с устройства…")

        def job():
            refresh_device_info(cl, self.cfg)
            return sync_from_device(cl, self.storage)

        def ok(r):
            self._sync_busy = False
            tz = self.tz()
            self.cfg.save()
            span = f"{fmt_ts(r.first_ts, tz)} — {fmt_ts(r.last_ts, tz)}" if r.downloaded else "нет записей"
            self.log(f"Синхронизация завершена: получено {r.downloaded}, новых {r.new}, всего в базе {r.total_in_db} ({span})")
            self.update_db_info()
            if self.nb.index(self.nb.select()) == 1:
                self.replot()

        def err(e):
            self._sync_busy = False
            self.log(f"Синхронизация не удалась: {e}")
            if not silent:
                messagebox.showerror("Синхронизация", str(e))
        self.bg(job, ok, err)

    # ================================================================== вкладка 3: экспорт
    def _build_export_tab(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="  Экспорт / импорт  ")
        box = ttk.LabelFrame(tab, text="Экспорт данных из локальной базы")
        box.pack(fill="x", padx=12, pady=10)
        self.period_export = PeriodSelector(box, default="Всё время", on_change=self._period_changed)
        self.period_export.pack(anchor="w", padx=8, pady=8)
        r = ttk.Frame(box)
        r.pack(fill="x", padx=8, pady=4)
        ttk.Label(r, text="Формат:").pack(side="left")
        self.fmt_var = tk.StringVar(value="Excel (xlsx)")
        fc = ttk.Combobox(r, textvariable=self.fmt_var, values=list(EXPORT_FORMATS), state="readonly", width=16)
        fc.pack(side="left", padx=6)
        fc.bind("<<ComboboxSelected>>", lambda e: self._refresh_export_name(force=True))
        ttk.Label(r, text="Усреднение:").pack(side="left", padx=(14, 0))
        self.resample_var = tk.StringVar(value=RESAMPLE_PRESETS[0][0])
        ttk.Combobox(r, textvariable=self.resample_var, values=[p[0] for p in RESAMPLE_PRESETS],
                     state="readonly", width=16).pack(side="left", padx=6)
        self.excel_ru_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(r, text="CSV для русского Excel (; и запятая)", variable=self.excel_ru_var).pack(
            side="left", padx=14)
        r2 = ttk.Frame(box)
        r2.pack(fill="x", padx=8, pady=8)
        ttk.Label(r2, text="Файл:").pack(side="left")
        self.out_var = tk.StringVar()
        ttk.Entry(r2, textvariable=self.out_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(r2, text="Обзор…", command=self.browse_out).pack(side="left")
        ttk.Button(box, text="Экспортировать", command=self.do_export).pack(anchor="w", padx=8, pady=(4, 10))
        ttk.Label(box, foreground="gray", wraplength=900, justify="left", text=(
            "Единицы давления и часовой пояс берутся из вкладки «Приложение». Усреднение уменьшает объём данных "
            "(полезно для Excel и длинных периодов). SQLite-экспорт создаёт новую базу с той же структурой.")).pack(
            anchor="w", padx=8, pady=(0, 8))

        imp = ttk.LabelFrame(tab, text="Импорт")
        imp.pack(fill="x", padx=12, pady=6)
        ttk.Label(imp, wraplength=900, justify="left", text=(
            "Загрузка CSV в локальную базу без дублей: файл, ранее экспортированный этим приложением, или "
            "/data/barograph.csv с SD-карты барографа (там хранится вся история с момента установки карты).")).pack(
            anchor="w", padx=8, pady=6)
        ttk.Button(imp, text="Импортировать CSV…", command=self.do_import).pack(anchor="w", padx=8, pady=(0, 10))

    def _refresh_export_name(self, force=False):
        ext = EXPORT_FORMATS[self.fmt_var.get()][1]
        cur = self.out_var.get().strip()
        if force or not cur:
            self.out_var.set(os.path.join(self.cfg["export_dir"], time.strftime("barograph_%Y%m%d_%H%M") + ext))

    def browse_out(self):
        fmt_name = self.fmt_var.get()
        ext = EXPORT_FORMATS[fmt_name][1]
        path = filedialog.asksaveasfilename(
            title="Файл экспорта", defaultextension=ext, filetypes=[(fmt_name, "*" + ext), ("Все файлы", "*.*")],
            initialdir=self.cfg["export_dir"], initialfile=os.path.basename(self.out_var.get()))
        if path:
            self.out_var.set(path)
            self.cfg["export_dir"] = os.path.dirname(path)

    def do_export(self):
        fmt = EXPORT_FORMATS[self.fmt_var.get()][0]
        path = self.out_var.get().strip()
        if not path:
            messagebox.showwarning("Экспорт", "Укажите файл")
            return
        try:
            start, end = resolve_period(self.period_export.spec(), self.tz(), self.storage)
        except ValueError as e:
            messagebox.showerror("Период", str(e))
            return
        if os.path.exists(path) and not messagebox.askyesno("Файл существует", f"Перезаписать файл?\n{path}"):
            return
        resample = dict(RESAMPLE_PRESETS)[self.resample_var.get()]
        tz, unit, ru = self.tz(), self.unit(), self.excel_ru_var.get()
        self.log(f"Экспорт ({self.fmt_var.get()}) → {path}")

        def ok(n):
            self.log(f"Экспорт завершён: {n} записей")
            if messagebox.askyesno("Экспорт", f"Готово: {n} записей.\nОткрыть папку с файлом?"):
                open_path(os.path.dirname(os.path.abspath(path)))

        def err(e):
            self.log(f"Экспорт не удался: {e}")
            messagebox.showerror("Экспорт", str(e))
        self.bg(lambda: export_data(self.storage, fmt, path, start, end, tz, unit, resample_s=resample, excel_ru=ru),
                ok, err)

    def do_import(self):
        path = filedialog.askopenfilename(title="CSV для импорта", filetypes=[("CSV", "*.csv"), ("Все файлы", "*.*")],
                                          initialdir=self.cfg["export_dir"])
        if not path:
            return

        def ok(res):
            parsed, new = res
            self.log(f"Импорт {os.path.basename(path)}: разобрано {parsed}, новых {new}")
            messagebox.showinfo("Импорт", f"Разобрано записей: {parsed}\nНовых добавлено: {new}")
            self.update_db_info()
        self.bg(lambda: import_csv_file(self.storage, path), ok)

    # ================================================================== вкладка 4: настройки устройства
    def _build_device_tab(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="  Настройки устройства  ")
        left = ttk.Frame(tab)
        left.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        right = ttk.Frame(tab)
        right.pack(side="left", fill="both", padx=10, pady=10)

        wf = ttk.LabelFrame(left, text="Wi-Fi")
        wf.pack(fill="both", expand=True)
        self.wifi_state = tk.StringVar(value="")
        ttk.Label(wf, textvariable=self.wifi_state, foreground="gray").pack(anchor="w", padx=8, pady=4)
        ttk.Button(wf, text="Сканировать сети", command=self.scan_wifi).pack(anchor="w", padx=8)
        self.net_tree = ttk.Treeview(wf, columns=("ssid", "rssi", "ch", "sec"), show="headings", height=7)
        for col, title, w in (("ssid", "Сеть", 200), ("rssi", "dBm", 60), ("ch", "Канал", 60), ("sec", "Защита", 90)):
            self.net_tree.heading(col, text=title)
            self.net_tree.column(col, width=w, anchor="w")
        self.net_tree.pack(fill="x", padx=8, pady=6)
        self.net_tree.bind("<<TreeviewSelect>>", self._net_selected)
        f = ttk.Frame(wf)
        f.pack(fill="x", padx=8, pady=4)
        ttk.Label(f, text="SSID:").grid(row=0, column=0, sticky="w")
        self.ssid_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.ssid_var, width=30).grid(row=0, column=1, padx=6, pady=2)
        ttk.Label(f, text="Пароль:").grid(row=1, column=0, sticky="w")
        self.pass_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.pass_var, show="•", width=30).grid(row=1, column=1, padx=6, pady=2)
        ttk.Label(wf, foreground="gray", wraplength=480, justify="left", text=(
            "Пароль 8–63 символа. Пустой пароль при той же сети — не менять; пустой при новой сети — открытая сеть. "
            "После применения устройство переподключится, связь может прерваться.")).pack(anchor="w", padx=8)
        ttk.Button(wf, text="Применить Wi-Fi", command=self.apply_wifi).pack(anchor="w", padx=8, pady=8)

        inf = ttk.LabelFrame(left, text="Периоды")
        inf.pack(fill="x", pady=(10, 0))
        g = ttk.Frame(inf)
        g.pack(fill="x", padx=8, pady=6)
        self.meas_var = tk.StringVar(value="10")
        self.rec_var = tk.StringVar(value="60")
        ttk.Label(g, text="Измерение, с:").grid(row=0, column=0, sticky="w")
        ttk.Combobox(g, textvariable=self.meas_var, values=[str(v) for v in MEASURE_VALUES], width=8).grid(
            row=0, column=1, padx=6, pady=2)
        ttk.Label(g, text="Запись в историю, с:").grid(row=1, column=0, sticky="w")
        ttk.Combobox(g, textvariable=self.rec_var, values=[str(v) for v in RECORD_VALUES], width=8).grid(
            row=1, column=1, padx=6, pady=2)
        ttk.Label(g, foreground="gray", text="измерение 5–3600 с, запись 60–3600 с").grid(row=0, column=2, rowspan=2, padx=10)
        ttk.Button(inf, text="Применить периоды", command=self.apply_intervals).pack(anchor="w", padx=8, pady=(0, 8))

        st = ttk.LabelFrame(right, text="Состояние устройства")
        st.pack(fill="x")
        self.dev_status = tk.StringVar(value="нет данных")
        ttk.Label(st, textvariable=self.dev_status, justify="left", font=self.fixed_font).pack(
            anchor="w", padx=10, pady=8)
        ttk.Button(st, text="Обновить", command=self.load_device_settings).pack(anchor="w", padx=8, pady=(0, 8))
        tm = ttk.LabelFrame(right, text="Время устройства")
        tm.pack(fill="x", pady=10)
        ttk.Label(tm, wraplength=330, justify="left", foreground="gray", text=(
            "Если у устройства нет интернета (NTP), время можно задать с этого компьютера. "
            "При работающем NTP устройство своё время не меняет.")).pack(anchor="w", padx=8, pady=6)
        ttk.Button(tm, text="Установить время с компьютера", command=self.set_device_time).pack(anchor="w", padx=8, pady=(0, 8))

    def show_device_status(self, st):
        lines = [
            f"Прошивка:   {st.get('fw_version')}",
            f"Датчик:     {st.get('sensor')} {st.get('sensor_address') or ''} ({st.get('sensor_state')})",
            f"Wi-Fi:      {st.get('ssid')}  {st.get('ip')}  {st.get('rssi')} dBm" + ("  [точка доступа]" if st.get("ap") else ""),
            f"SD-карта:   {'есть, ' + str(st.get('sd_card_mb')) + ' МБ' if st.get('sd') else 'нет'}",
            f"Хранилище:  {st.get('storage')}  (CSV {st.get('csv_bytes', 0) // 1024} КБ)",
            f"История:    {st.get('history_records')} / {st.get('history_capacity')} записей",
            f"Время:      {st.get('datetime') or 'не установлено'} [{st.get('time_source')}]",
            f"Работает:   {st.get('uptime', 0) // 3600} ч {st.get('uptime', 0) % 3600 // 60} мин",
            f"Свободно ОЗУ: {st.get('free_heap', 0) // 1024} КБ",
        ]
        self.dev_status.set("\n".join(lines))
        self.wifi_state.set(f"Сеть: {st.get('ssid')} · IP {st.get('ip')} · {st.get('wifi_state')}")

    def load_device_settings(self):
        cl = self.client()

        def ok(res):
            st, s = res
            self.show_device_status(st)
            self.ssid_var.set(s.get("ssid", ""))
            self.pass_var.set("")
            self.meas_var.set(str(s.get("measure_interval_s", "")))
            self.rec_var.set(str(s.get("record_interval_s", "")))
        self.bg(lambda: (cl.status(), cl.get_settings()), ok, lambda e: self.log(f"Настройки устройства: {e}"))

    def scan_wifi(self):
        if self._scan_busy:
            return
        self._scan_busy = True
        cl = self.client()
        self.wifi_state.set("Сканирование сетей…")

        def ok(nets):
            self._scan_busy = False
            self.net_tree.delete(*self.net_tree.get_children())
            seen = set()
            for n in sorted(nets, key=lambda n: -n["rssi"]):
                if n["ssid"] in seen:
                    continue
                seen.add(n["ssid"])
                self.net_tree.insert("", "end", values=(n["ssid"], n["rssi"], n["channel"], n["security"]))
            self.wifi_state.set(f"Найдено сетей: {len(seen)}")

        def err(e):
            self._scan_busy = False
            self.wifi_state.set("")
            self._generic_err(e)
        self.bg(cl.wifi_scan, ok, err)

    def _net_selected(self, _e=None):
        sel = self.net_tree.selection()
        if sel:
            self.ssid_var.set(self.net_tree.item(sel[0], "values")[0])
            self.pass_var.set("")

    def apply_wifi(self):
        ssid, pw = self.ssid_var.get().strip(), self.pass_var.get()
        if not ssid:
            messagebox.showwarning("Wi-Fi", "Укажите SSID")
            return
        if pw and not 8 <= len(pw) <= 63:
            messagebox.showwarning("Wi-Fi", "Пароль должен быть 8–63 символа")
            return
        if not messagebox.askyesno("Wi-Fi", f"Переключить устройство на сеть «{ssid}»?\nСвязь может прерваться; "
                                            f"если сеть недоступна, устройство поднимет свою точку доступа."):
            return
        cl = self.client()

        def ok(r):
            self.cfg["last_ip"] = ""                         # IP в новой сети будет другим
            self.log(f"Wi-Fi: настройки отправлены (SSID {ssid}). Устройство переподключается.")
            messagebox.showinfo("Wi-Fi", "Настройки применены. Подождите ~20 секунд и нажмите «Подключиться».\n"
                                         "Если не подключается, найдите IP в мониторе порта или используйте esp32-barograf.local.")
        self.bg(lambda: cl.set_settings(ssid=ssid, password=pw if pw else None), ok)

    def apply_intervals(self):
        try:
            m, r = int(self.meas_var.get()), int(self.rec_var.get())
        except ValueError:
            messagebox.showwarning("Периоды", "Введите целые числа секунд")
            return
        cl = self.client()
        self.bg(lambda: cl.set_settings(measure_interval_s=m, record_interval_s=r),
                lambda res: self.log(f"Периоды применены: измерение {res['measure_interval_s']} с, запись {res['record_interval_s']} с"))

    def set_device_time(self):
        cl = self.client()

        def ok(r):
            msg = "Время установлено" if r.get("applied") else "Время уже синхронизировано по NTP — не изменено"
            self.log(f"{msg}: {r.get('datetime')}")
            messagebox.showinfo("Время устройства", f"{msg}\n{r.get('datetime')}")
            self.refresh_live()
        self.bg(cl.set_time, ok)

    # ================================================================== вкладка 5: приложение
    def _build_app_tab(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="  Приложение  ")
        db = ttk.LabelFrame(tab, text="Локальная база данных (SQLite)")
        db.pack(fill="x", padx=12, pady=10)
        r = ttk.Frame(db)
        r.pack(fill="x", padx=8, pady=6)
        self.db_path_var = tk.StringVar(value=self.cfg["db_path"])
        ttk.Entry(r, textvariable=self.db_path_var, state="readonly").pack(side="left", fill="x", expand=True)
        ttk.Button(r, text="Выбрать/создать…", command=self.change_db).pack(side="left", padx=6)
        ttk.Button(r, text="Открыть папку", command=lambda: open_path(os.path.dirname(os.path.abspath(self.cfg["db_path"])))).pack(side="left")
        self.app_db_info = ttk.Label(db, text="")
        self.app_db_info.pack(anchor="w", padx=8, pady=(0, 8))

        opt = ttk.LabelFrame(tab, text="Параметры")
        opt.pack(fill="x", padx=12, pady=6)
        g = ttk.Frame(opt)
        g.pack(fill="x", padx=8, pady=8)
        self.unit_var = tk.StringVar(value=self.cfg["pressure_unit"])
        ttk.Label(g, text="Единица давления:").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Combobox(g, textvariable=self.unit_var, values=list(PRESSURE_UNITS), state="readonly", width=8).grid(
            row=0, column=1, sticky="w", padx=6)
        self.tz_auto_var = tk.BooleanVar(value=self.cfg["tz_auto"])
        self.tz_hours_var = tk.StringVar(value=self._fmt_hours(self.cfg["tz_offset_s"]))
        ttk.Label(g, text="Часовой пояс (UTC+, ч):").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(g, textvariable=self.tz_hours_var, width=8).grid(row=1, column=1, sticky="w", padx=6)
        ttk.Checkbutton(g, text="брать у устройства", variable=self.tz_auto_var).grid(row=1, column=2, sticky="w")
        ttk.Button(g, text="как на этом ПК", command=lambda: (self.tz_hours_var.set(self._fmt_hours(local_offset_s())),
                                                              self.tz_auto_var.set(False))).grid(row=1, column=3, padx=6)
        self.auto_refresh_var = tk.BooleanVar(value=self.cfg["auto_refresh"])
        self.refresh_s_var = tk.StringVar(value=str(self.cfg["refresh_s"]))
        ttk.Checkbutton(g, text="Автообновление текущих значений каждые", variable=self.auto_refresh_var).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=3)
        ttk.Entry(g, textvariable=self.refresh_s_var, width=5).grid(row=2, column=2, sticky="w")
        ttk.Label(g, text="с").grid(row=2, column=3, sticky="w")
        self.auto_sync_var = tk.BooleanVar(value=self.cfg["auto_sync"])
        self.sync_min_var = tk.StringVar(value=str(self.cfg["sync_minutes"]))
        ttk.Checkbutton(g, text="Автосинхронизация истории каждые", variable=self.auto_sync_var).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=3)
        ttk.Entry(g, textvariable=self.sync_min_var, width=5).grid(row=3, column=2, sticky="w")
        ttk.Label(g, text="мин (устройство хранит 72 ч — не ставьте больше 1000 мин)").grid(
            row=3, column=3, columnspan=2, sticky="w")
        ttk.Button(opt, text="Применить", command=self.apply_app_settings).pack(anchor="w", padx=8, pady=(0, 8))

    @staticmethod
    def _fmt_hours(offset_s):
        h = offset_s / 3600.0
        return f"{h:g}"

    def apply_app_settings(self):
        try:
            hours = float(self.tz_hours_var.get().replace(",", "."))
            refresh = max(2, int(self.refresh_s_var.get()))
            minutes = max(1, int(self.sync_min_var.get()))
        except ValueError:
            messagebox.showwarning("Параметры", "Проверьте числовые поля")
            return
        if not -14 <= hours <= 14:
            messagebox.showwarning("Параметры", "Часовой пояс должен быть от -14 до +14")
            return
        if int(round(hours * 3600)) != self.cfg["tz_offset_s"] and self.tz_auto_var.get():
            self.tz_auto_var.set(False)                        # пользователь задал пояс вручную
        self.cfg["pressure_unit"] = self.unit_var.get()
        self.cfg["tz_auto"] = self.tz_auto_var.get()
        self.cfg["tz_offset_s"] = int(round(hours * 3600))
        self.cfg["auto_refresh"] = self.auto_refresh_var.get()
        self.cfg["refresh_s"] = refresh
        self.cfg["auto_sync"] = self.auto_sync_var.get()
        self.cfg["sync_minutes"] = minutes
        self.cfg.save()
        self.log("Параметры приложения сохранены")
        self.update_db_info()
        self.refresh_live()

    def change_db(self):
        path = filedialog.asksaveasfilename(
            title="Файл базы данных", defaultextension=".db", confirmoverwrite=False,
            filetypes=[("SQLite", "*.db *.sqlite"), ("Все файлы", "*.*")],
            initialdir=os.path.dirname(self.cfg["db_path"]), initialfile=os.path.basename(self.cfg["db_path"]))
        if not path:
            return
        try:
            self.storage = Storage(path)
        except Exception as e:                                  # noqa
            messagebox.showerror("База данных", str(e))
            return
        self.cfg["db_path"] = path
        self.db_path_var.set(path)
        self.cfg.save()
        self.log(f"Используется база: {path}")
        self.update_db_info()

    # ================================================================== вкладка 6: журнал
    def _build_log_tab(self):
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="  Журнал  ")
        self.log_text = tk.Text(tab, state="disabled", wrap="word", height=10)
        sb = ttk.Scrollbar(tab, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True, padx=6, pady=6)

    # ================================================================== таймеры
    def _auto_tick(self):
        now = time.time()
        try:
            if self.cfg["auto_refresh"] and not self._live_busy and now - self._last_live >= self.cfg["refresh_s"]:
                self.refresh_live()
            if (self.cfg["auto_sync"] and self._connected and not self._sync_busy
                    and now - self._last_sync >= self.cfg["sync_minutes"] * 60):
                self.start_sync(silent=True)
        finally:
            self.after(1000, self._auto_tick)


def run_gui(cfg) -> int:
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)      # чёткий текст на HiDPI-мониторах
        except Exception:                                       # noqa
            pass
    try:
        app = App(cfg)
    except tk.TclError as e:
        print(f"Не удалось открыть окно: {e}\nНа Ubuntu без графической сессии используйте командную строку "
              f"(python barograph_app.py --help).", file=sys.stderr)
        return 1
    app.mainloop()
    return 0
