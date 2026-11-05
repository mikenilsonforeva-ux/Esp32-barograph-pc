// ============================================================================
//  config.h - все настройки проекта в одном месте
//  ESP32 BAROGRAPH (BMP280 / BME280, SD + LittleFS, Web UI, REST API)
// ============================================================================
#pragma once
#include <Arduino.h>

#define FW_NAME     "ESP32 BAROGRAPH"
#define FW_VERSION  "1.0.0"

// ---- Логирование в Serial --------------------------------------------------
#define LOGI(fmt, ...)  Serial.printf(fmt "\n", ##__VA_ARGS__)
#define LOGW(fmt, ...)  Serial.printf("[WARN] " fmt "\n", ##__VA_ARGS__)
#define LOGE(fmt, ...)  Serial.printf("[ERROR] " fmt "\n", ##__VA_ARGS__)

// ---- I2C / датчик ----------------------------------------------------------
#define PIN_I2C_SDA            21
#define PIN_I2C_SCL            22
#define I2C_CLOCK_HZ           100000
#define SENSOR_ADDR_1          0x76
#define SENSOR_ADDR_2          0x77
#define SENSOR_RETRY_MS        10000UL   // период повторного поиска датчика
#define SENSOR_MIN_GAP_MS      1000UL    // не чаще одного реального чтения в секунду

// ---- SD-карта (SPI) --------------------------------------------------------
#define PIN_SD_SCK             18
#define PIN_SD_MISO            19
#define PIN_SD_MOSI            23
#define PIN_SD_CS              5
#define SD_SPI_HZ              4000000
#define SD_CSV_DIR             "/data"
#define SD_CSV_PATH            "/data/barograph.csv"
#define SD_CSV_HEADER          "timestamp,date,time,pressure_mmHg,temperature_c,humidity"
#define SD_HEALTH_CHECK_MS     10000UL   // проверка, что карта не вынута
#define SD_RETRY_MS            30000UL   // попытка смонтировать карту, если её нет
#define SD_FLUSH_EVERY_N       5         // flush каждые N записей
#define SD_FLUSH_MAX_MS        120000UL  // и не реже чем раз в 2 минуты

// ---- Внутренняя flash (LittleFS) -------------------------------------------
#define FLASH_HISTORY_PATH     "/history.bin"
#define FLASH_HISTORY_TMP      "/history.tmp"

// ---- История ---------------------------------------------------------------
#define HISTORY_HOURS          72        // обязательный минимум хранения
#define HISTORY_MARGIN_PCT     10        // запас ёмкости, %

// ---- Интервалы (секунды) ---------------------------------------------------
#define MEASURE_INTERVAL_MIN   5
#define MEASURE_INTERVAL_MAX   3600
#define MEASURE_INTERVAL_DEF   10
// Период записи в историю. Минимум 60 с: так 72 ч помещаются в ~4800 записей
// (около 57 КБ ОЗУ). Между записями измерения усредняются.
#define RECORD_INTERVAL_MIN    60
#define RECORD_INTERVAL_MAX    3600
#define RECORD_INTERVAL_DEF    60

// ---- Время -----------------------------------------------------------------
#define TIME_TZ_POSIX          "MSK-3"   // Europe/Moscow, UTC+3 без перехода на летнее время
#define TIME_NTP_SERVER_1      "pool.ntp.org"
#define TIME_NTP_SERVER_2      "time.nist.gov"
#define TIME_MIN_VALID_EPOCH   1700000000UL  // всё, что меньше - время не установлено
#define TIME_NTP_KICK_MS       60000UL       // перезапуск SNTP, если не синхронизировано

// ---- Wi-Fi -----------------------------------------------------------------
#define WIFI_DEFAULT_SSID      "MiWiFi"
#define WIFI_DEFAULT_PASSWORD  "AA1C301mS"
#define WIFI_HOSTNAME          "esp32-barograf"
#define WIFI_STA_TIMEOUT_MS    15000UL   // сколько ждать подключения к сети
#define WIFI_STA_LOST_MS       30000UL   // потеря связи дольше этого -> поднимаем AP
#define WIFI_AP_RETRY_MS       300000UL  // раз в 5 минут пробуем вернуться в STA (если к AP никто не подключён)
#define AP_SSID                "ESP32_barograf"
#define AP_CHANNEL             1
#define AP_IP_A 192
#define AP_IP_B 168
#define AP_IP_C 4
#define AP_IP_D 2

// ---- Web -------------------------------------------------------------------
#define HTTP_PORT              80
#define HISTORY_DEFAULT_POINTS 400       // downsampling: максимум точек в ответе по умолчанию
#define HISTORY_MAX_POINTS     2000

// ---- Watchdog --------------------------------------------------------------
#define WDT_TIMEOUT_S          30
