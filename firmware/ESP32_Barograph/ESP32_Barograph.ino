// ============================================================================
//  ESP32 BAROGRAPH - цифровой барограф / метеостанция на ESP32-WROOM
//  Датчик: BMP280 / BME280 (I2C), история 72 ч (SD CSV или LittleFS),
//  Web UI + REST API, NTP (Europe/Moscow), локальный прогноз по давлению.
//
//  Библиотеки (Library Manager):
//    - Adafruit BME280 Library   (для BME280)
//    - Adafruit BMP280 Library   (для BMP280)
//    - Adafruit Unified Sensor   (зависимость обеих)
//  Остальное (WiFi, WebServer, ESPmDNS, SD, SPI, LittleFS, Preferences, Wire)
//  входит в ESP32 Arduino Core.
//
//  Плата: ESP32 Dev Module (ESP32 WROOM), Partition Scheme: "Default 4MB with spiffs"
// ============================================================================
#include <esp_task_wdt.h>
#include "config.h"
#include "settings.h"
#include "sensor_manager.h"
#include "storage_manager.h"
#include "wifi_manager.h"
#include "time_manager.h"
#include "measurement.h"
#include "api.h"

static void initWatchdog() {
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
  esp_task_wdt_config_t cfg;
  cfg.timeout_ms = WDT_TIMEOUT_S * 1000;
  cfg.idle_core_mask = 0;                       // idle-задачи не отслеживаем
  cfg.trigger_panic = true;                     // перезагрузка при зависании
  if (esp_task_wdt_reconfigure(&cfg) == ESP_ERR_INVALID_STATE) esp_task_wdt_init(&cfg);
#else
  esp_task_wdt_init(WDT_TIMEOUT_S, true);
#endif
  esp_task_wdt_add(NULL);                       // подписываем задачу loop()
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println();
  Serial.println("================================");
  Serial.println(FW_NAME " v" FW_VERSION);
  Serial.println("================================");

  initWatchdog();
  Settings::begin();
  SensorManager::begin();
  StorageManager::begin(Settings::get().recordIntervalS);
  WifiManager::begin();                         // подключение идёт в loop(), не блокируя
  TimeManager::begin();
  Measurement::begin();
  Api::begin();

  LOGI("System ready");
  Serial.println("================================");
}

void loop() {
  esp_task_wdt_reset();

  WifiManager::update();
  TimeManager::update(WifiManager::staConnected());
  Api::handle();
  SensorManager::update();
  Measurement::update();
  StorageManager::update();

  delay(2);                                     // отдаём время системным задачам
}
