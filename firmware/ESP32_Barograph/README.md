# ESP32 Barograph

Автономный барограф / метеостанция на **ESP32-WROOM** (Arduino IDE): BMP280/BME280, история 72 ч, SD (CSV) или LittleFS, Web UI без интернета, REST API, NTP (Europe/Moscow, UTC+3), локальный прогноз по давлению.

> **Статус.** Прошивка собрана в Arduino IDE (ESP32 Arduino Core 3.3.12) и проверена на плате ESP32-WROOM с датчиком BMP280: датчик определяется, веб-интерфейс, NTP и Wi-Fi работают. Не проверялись на железе: BME280 (влажность), подключённая SD-карта и перенос flash → SD. Логика прогноза, разбор CSV и расчёт часового пояса дополнительно проверены тестом на ПК.

## 1. Библиотеки

Установить через *Скетч → Подключить библиотеку → Управлять библиотеками*:

| Библиотека | Зачем |
|---|---|
| **Adafruit BME280 Library** | чтение BME280 (chip ID 0x60) |
| **Adafruit BMP280 Library** | чтение BMP280 (chip ID 0x56–0x58) |
| **Adafruit Unified Sensor** | зависимость обеих |

Всё остальное (WiFi, WebServer, ESPmDNS, SD, SPI, LittleFS, Preferences, Wire) входит в ESP32 Core. ArduinoJson не нужна: JSON формируется и разбирается встроенным кодом.

## 2. Структура файлов

```
ESP32_Barograph/
    ESP32_Barograph.ino   setup()/loop(), watchdog
    config.h              все пины, интервалы, значения по умолчанию
    settings.h/.cpp       настройки в NVS (Wi-Fi, периоды)
    sensor_manager.*      поиск BMP280/BME280 на 0x76/0x77, чтение
    measurement.*         планировщик измерений и записи (millis)
    storage_manager.*     кольцевой буфер, SD CSV, LittleFS, перенос flash→SD
    time_manager.*        NTP, MSK-3, ручная установка времени
    wifi_manager.*        STA, резервная AP, mDNS
    forecast.*            тренд и прогноз (сменный модуль)
    api.*                 HTTP-сервер и REST API
    web_ui.*              страница интерфейса (HTML/CSS/JS в прошивке)
```

## 3. Подключение

| Модуль | Вывод модуля | ESP32 |
|---|---|---|
| BME280 / BMP280 | VCC / VIN | 3V3 |
| | GND | GND |
| | SDA | GPIO21 |
| | SCL | GPIO22 |
| | SDO (адрес) | GND → 0x76, 3V3 → 0x77 |
| SD-модуль (SPI) | VCC | 5V (если на модуле стабилизатор и преобразователь уровней) или 3V3 |
| | GND | GND |
| | SCK | GPIO18 |
| | MISO | GPIO19 |
| | MOSI | GPIO23 |
| | CS | GPIO5 |

Пины меняются в `config.h`. SD-карта: FAT32.

## 4. Установка

1. Установить Arduino IDE 2.x.
2. *Настройки → Дополнительные ссылки для менеджера плат*: `https://espressif.github.io/arduino-esp32/package_esp32_index.json`.
3. *Менеджер плат* → установить **esp32 by Espressif Systems**.
4. Установить библиотеки из п. 1.
5. Открыть `ESP32_Barograph/ESP32_Barograph.ino` (папка должна называться так же, как скетч).
6. *Инструменты → Плата → ESP32 Dev Module*; **Partition Scheme: Default 4MB with spiffs** (нужна файловая система LittleFS).
7. Выбрать COM-порт, нажать «Загрузить» (если не стартует — удерживать BOOT при начале прошивки).
8. Монитор порта: 115200 бод.

## 5. Первый запуск

1. По умолчанию устройство пробует подключиться к сети `MiWiFi` (значения в `config.h`).
2. Если не удалось за ~15 с — поднимается открытая точка доступа **ESP32_barograf** (без пароля).
3. Подключитесь к ней с телефона/ПК и откройте **http://192.168.4.2** (или http://esp32-barograf.local).
4. Вкладка **Настройки → Сканировать сети** → выбрать сеть → ввести пароль → **Сохранить**. Устройство подключится к сети; точка доступа отключится. IP виден в мониторе порта (`IP: ...`), также работает http://esp32-barograf.local.
5. Если сеть недоступна дольше 30 с, точка доступа поднимается снова; каждые 5 минут (если к AP никто не подключён) выполняется попытка вернуться в сеть.

**Время.** Без интернета NTP недоступен, а история пишется только при известном времени. Поэтому при открытии интерфейса, если время не установлено, страница сама передаёт время вашего устройства (`POST /api/time`). Как только появится NTP, оно точнее и используется автоматически.

## 6. Хранение данных

- **Кольцевой буфер в ОЗУ** — последние 72 ч + 10 % запаса (при периоде записи 60 с это ~4800 записей, ~57 КБ). Из него отдаются графики, API и прогноз. Запись — 12 байт: время, давление (Па), температура (0.01 °C), влажность (0.01 %).
- **Период измерений** (5–3600 с) и **период записи** (60–3600 с) независимы: между записями измерения усредняются. Минимум 60 с для записи выбран, чтобы 72 ч гарантированно помещались в ОЗУ.
- **SD доступна** → каждая запись добавляется в `/data/barograph.csv` (файл остаётся открытым, `flush` каждые 5 записей и не реже 2 минут). Формат: `timestamp,date,time,pressure_mmHg,temperature_c,humidity` (для BMP280 влажность пустая). При старте хвост CSV загружается в буфер; оборванная после потери питания последняя строка исправляется автоматически.
- **SD отсутствует** → записи дописываются в `/history.bin` (LittleFS); при превышении двойной ёмкости файл переписывается из буфера, поэтому износ flash невелик.
- **SD появилась / вставлена** (проверка раз в 30 с; потеря карты замечается за ≤10 с или по ошибке записи) → читается последняя метка времени в CSV, из flash переносятся только записи новее неё (без дублей), затем `/history.bin` удаляется и запись продолжается на SD.
- Файл CSV можно скачать из Web UI (вкладка Настройки) или `GET /api/export.csv` (выгрузка из буфера).

## 7. Прогноз

Модуль `forecast.cpp`: линейная регрессия по окнам 10 мин / 30 мин / 1 ч / 3 ч / 6 ч (окно учитывается, если заполнено ≥60 %); итоговая скорость = 0.6·(3 ч) + 0.4·(1 ч). Пороги (мм рт. ст./ч): ≥+1.5 очень быстрый рост, ≥+0.9 быстрый, ≥+0.25 медленный, ±0.25 стабильно, затем симметрично падение (≤−1.5 шторм). При температуре ≤ 0.5 °C и падении давления показывается снег. Вероятности ухудшения/улучшения — логистическая функция от скорости. Прогноз появляется после ~30 минут накопленной истории. Давление измеряется на высоте установки, поэтому прогноз опирается на динамику, а не на абсолютное значение.

## 8. REST API

Все ответы — JSON (UTF-8), заголовок `Access-Control-Allow-Origin: *`, поддержан preflight `OPTIONS`. Давление везде в **мм рт. ст.**, время — Unix (UTC) и ISO 8601 (`+03:00`). Авторизации нет (локальная сеть); маршруты собраны в `api.cpp`, туда же добавляется токен/Basic Auth.

### GET /api/current
```
curl http://esp32-barograf.local/api/current
{"state":"ok","pressure":755.42,"pressure_hpa":1007.20,"temperature":18.7,"humidity":61.4,
 "humidity_valid":true,"timestamp":1791097200,"datetime":"2026-10-04T12:00:00+03:00",
 "age_s":3,"trend_mmhg_h":1.80}
```
`state`: `ok` / `no_data` / `sensor_not_found` (значения тогда `null`). Для BMP280: `"humidity":null,"humidity_valid":false`.

### GET /api/history
Параметры: `hours` (0.5…72, по умолчанию 1), `max` (максимум точек, 10…2000, по умолчанию 400 — при превышении точки усредняются).
```
curl "http://esp32-barograf.local/api/history?hours=72"
{"hours":72.00,"record_interval_s":60,"raw_count":4320,"step":11,"count":393,
 "data":[{"timestamp":1791097200,"pressure":755.42,"temperature":18.7,"humidity":61.4}, ...]}
```
Ответ передаётся потоком (chunked), без построения большого JSON в ОЗУ.

### GET | POST /api/measure
Немедленное измерение. `store=1` — дополнительно добавить в историю.
```
curl -X POST "http://esp32-barograf.local/api/measure?store=1"
{"success":true,"pressure":755.43,"temperature":18.8,"humidity":61.2,"humidity_valid":true,"timestamp":1791097260,"stored":true}
```
Ошибки: `503 {"success":false,"error":"sensor_not_found"}`, `500 measurement_failed`. Реальное чтение датчика — не чаще раза в секунду.

### GET /api/status
```
{"wifi":true,"wifi_state":"connected","ssid":"MiWiFi","ip":"192.168.1.94","rssi":-52,"ap":false,
 "mdns":"esp32-barograf.local","sd":true,"sd_card_mb":7580,"csv_bytes":183450,"csv_file":"barograph.csv",
 "storage":"sd","flash_ok":true,"flash_records":0,"sensor":"BME280","sensor_state":"ok","sensor_address":"0x76",
 "uptime":123456,"free_heap":180000,"history_records":4320,"history_capacity":4782,
 "time_synced":true,"ntp_synced":true,"time_source":"ntp","epoch":1791097200,
 "datetime":"2026-10-04T12:00:00+03:00","tz_offset_s":10800,"fw_version":"1.0.0"}
```
`uptime` — секунды. Без датчика: `"sensor":"none","sensor_state":"sensor_not_found"`.

### GET /api/forecast
```
{"valid":true,"data_span_s":18000,"pressure":755.4,"trend":"falling","trend_label":"ПАДЕНИЕ",
 "level":"fast_fall","rate_mmhg_h":-1.12,"change_3h_mmhg":-3.36,
 "rates":{"10m":-1.3,"30m":-1.2,"1h":-1.1,"3h":-1.1,"6h":null},
 "icon":"rain","windy":false,"summary":"Ухудшение погоды, дождь","details":"...",
 "probability_worse":78,"probability_better":4}
```
`icon`: sun / partly / cloud / rain / storm / snow / unknown. Недостающие окна — `null`.

### GET | POST | PUT /api/settings
`GET` отдаёт настройки (пароль Wi-Fi не возвращается, только `wifi_password_set`). Для изменения — form-urlencoded или JSON:
```
curl -X POST http://esp32-barograf.local/api/settings -d "measure_interval_s=30&record_interval_s=300"
curl -X POST http://esp32-barograf.local/api/settings -H "Content-Type: application/json" \
     -d '{"ssid":"MyWiFi","password":"secret123"}'
```
Параметры: `ssid`, `password` (8–63 символа; для новой SSID без пароля — открытая сеть), `measure_interval_s` (5–3600), `record_interval_s` (60–3600). Ответ содержит текущие значения и `"reconnecting":true`, если менялся Wi-Fi. Ошибка: `400 {"success":false,"error":"invalid_interval"}` и т. п.

### GET /api/wifi/scan
Асинхронное сканирование: `?start=1` запускает, повторный запрос без параметров отдаёт результат.
```
{"status":"done","networks":[{"ssid":"MiWiFi","rssi":-42,"channel":6,"security":"WPA2"}]}
```
`status`: `scanning` / `done` / `idle`.

### GET | POST /api/time
`POST epoch=<unix>` устанавливает время, если NTP ещё не синхронизирован (`"applied":false`, если уже есть NTP). Ответ: `{"success":true,"applied":true,"synced":true,"source":"browser","epoch":...,"datetime":"..."}`.

### GET /api/export.csv
История из буфера в формате CSV.

## 9. Особенности и расширение

- Основной цикл неблокирующий (`millis()`); сканирование Wi-Fi асинхронное. Короткие блокировки возможны при монтировании SD (раз в 30 с, пока карты нет).
- Watchdog 30 с (`WDT_TIMEOUT_S`); долгие операции с SD сбрасывают его сами.
- Датчик пропал → API сообщает `sensor_not_found`, поиск повторяется каждые 10 с.
- Измерение, хранение, Wi-Fi, время, прогноз, API и UI разнесены по модулям. OTA, MQTT, Home Assistant, новые датчики добавляются как отдельные модули + вызов в `loop()`.
- Веб-сервер — штатный `WebServer` (один поток), поэтому общие данные не требуют блокировок.
- Пароль Wi-Fi по умолчанию лежит в `config.h` — смените его перед публикацией кода.
