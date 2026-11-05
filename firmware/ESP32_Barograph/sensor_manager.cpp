// sensor_manager.cpp
// BME280 (chip ID 0x60) читается библиотекой Adafruit BME280,
// BMP280 (chip ID 0x56..0x58) - библиотекой Adafruit BMP280: они не взаимозаменяемы.
#include "sensor_manager.h"
#include <Wire.h>
#include <Adafruit_BME280.h>
#include <Adafruit_BMP280.h>

namespace {
  Adafruit_BME280 bme;                 // шина передаётся в bme.begin(addr, &Wire)
  Adafruit_BMP280 bmp(&Wire);
  SensorType  sType   = SensorType::NONE;
  uint8_t     sAddr   = 0;
  uint32_t    sErrors = 0;
  uint32_t    lastRetryMs = 0;
  uint32_t    lastReadMs  = 0;
  SensorReading lastReading = {0, 0, 0, false};
  bool        haveLast = false;
  bool        firstScanDone = false;
  int         sdaPin = PIN_I2C_SDA;
  int         sclPin = PIN_I2C_SCL;

  // Код ответа шины для адреса: 0 = устройство ответило (ACK)
  uint8_t probeCode(uint8_t addr) {
    Wire.beginTransmission(addr);
    return Wire.endTransmission();
  }
  bool probe(uint8_t addr) { return probeCode(addr) == 0; }

  // Чтение регистра chip ID (0xD0); -1 при ошибке
  int readChipId(uint8_t addr) {
    Wire.beginTransmission(addr);
    Wire.write((uint8_t)0xD0);
    if (Wire.endTransmission(false) != 0) return -1;
    if (Wire.requestFrom((int)addr, 1) != 1) return -1;
    return Wire.read();
  }

  // Диагностика: какие адреса вообще отвечают на шине
  void scanBus() {
    LOGI("I2C scan (SDA=%d, SCL=%d):", sdaPin, sclPin);
    int found = 0;
    for (uint8_t a = 1; a < 127; a++) {
      if (probe(a)) { LOGI("  device at 0x%02X", a); found++; }
    }
    if (!found) LOGW("  no I2C devices respond - check wiring/pull-ups/pins");
  }

  bool initBme(uint8_t addr) {
    if (!bme.begin(addr, &Wire)) return false;
    bme.setSampling(Adafruit_BME280::MODE_FORCED,
                    Adafruit_BME280::SAMPLING_X2,    // температура
                    Adafruit_BME280::SAMPLING_X16,   // давление
                    Adafruit_BME280::SAMPLING_X1,    // влажность
                    Adafruit_BME280::FILTER_OFF,
                    Adafruit_BME280::STANDBY_MS_1000);
    return true;
  }

  bool initBmp(uint8_t addr, uint8_t chipId) {
    if (!bmp.begin(addr, chipId)) return false;
    bmp.setSampling(Adafruit_BMP280::MODE_FORCED,
                    Adafruit_BMP280::SAMPLING_X2,    // температура
                    Adafruit_BMP280::SAMPLING_X16,   // давление
                    Adafruit_BMP280::FILTER_OFF,
                    Adafruit_BMP280::STANDBY_MS_500);
    return true;
  }

  // Поиск датчика на 0x76 / 0x77 с определением типа по chip ID
  bool detect() {
    const uint8_t addrs[2] = { SENSOR_ADDR_1, SENSOR_ADDR_2 };
    for (uint8_t i = 0; i < 2; i++) {
      uint8_t a = addrs[i];
      uint8_t code = 0xFF;
      for (uint8_t attempt = 0; attempt < 3; attempt++) {    // датчик может ответить не с первого раза
        code = probeCode(a);
        if (code == 0) break;
        delay(20);
      }
      if (code != 0) { LOGI("I2C 0x%02X: no ACK (error %u)", a, code); continue; }

      int id = readChipId(a);
      LOGI("I2C 0x%02X: ACK, chip ID = 0x%02X", a, id < 0 ? 0 : id);
      if (id == 0x60) {
        if (!initBme(a)) { LOGW("BME280 init failed at 0x%02X", a); continue; }
        sType = SensorType::BME280;
      } else if (id == 0x56 || id == 0x57 || id == 0x58) {
        if (!initBmp(a, (uint8_t)id)) { LOGW("BMP280 init failed at 0x%02X", a); continue; }
        sType = SensorType::BMP280;
      } else {
        LOGW("Device at 0x%02X is not BMP280/BME280 (chip ID 0x%02X)", a, id < 0 ? 0 : id);
        continue;
      }
      sAddr = a;
      LOGI("Sensor: %s", SensorManager::typeName());
      LOGI("Address: 0x%02X", sAddr);
      return true;
    }
    return false;
  }

  void markLost() {
    sErrors++;
    if (sType != SensorType::NONE) LOGE("%s lost (I2C error)", SensorManager::typeName());
    sType = SensorType::NONE;
    sAddr = 0;
    lastRetryMs = millis();
  }
}

namespace SensorManager {

void begin() {
  LOGI("Initializing I2C...");
  Wire.begin(sdaPin, sclPin);
  Wire.setClock(I2C_CLOCK_HZ);
  delay(100);                          // даём датчику время после включения питания
  if (detect()) { lastRetryMs = millis(); return; }

  LOGE("BME280/BMP280 not found on SDA=%d SCL=%d", sdaPin, sclPin);
  scanBus();
  firstScanDone = true;

  // Диагностика: датчик мог быть подключён к другим выводам (или SDA/SCL перепутаны).
  // Пробуем популярные пары; если нашли - работаем с ними и сообщаем, что прописать в config.h.
  static const int8_t pairs[][2] = {
    {22, 21}, {16, 17}, {17, 16}, {25, 26}, {26, 25}, {26, 27}, {27, 26}, {32, 33}, {33, 32}, {13, 14}, {14, 13}
  };
  for (size_t i = 0; i < sizeof(pairs) / sizeof(pairs[0]); i++) {
    int sda = pairs[i][0], scl = pairs[i][1];
    Wire.end();
    Wire.begin(sda, scl);
    Wire.setClock(I2C_CLOCK_HZ);
    delay(10);
    if (probe(SENSOR_ADDR_1) || probe(SENSOR_ADDR_2)) {
      LOGW("I2C device answers on SDA=%d SCL=%d (not %d/%d)!", sda, scl, PIN_I2C_SDA, PIN_I2C_SCL);
      sdaPin = sda; sclPin = scl;
      if (detect()) {
        LOGW("Using SDA=%d SCL=%d. Set PIN_I2C_SDA/PIN_I2C_SCL in config.h to make it permanent.", sda, scl);
        lastRetryMs = millis();
        return;
      }
    }
  }
  // ничего не нашли - возвращаем штатные выводы для повторных попыток
  Wire.end();
  sdaPin = PIN_I2C_SDA; sclPin = PIN_I2C_SCL;
  Wire.begin(sdaPin, sclPin);
  Wire.setClock(I2C_CLOCK_HZ);
  LOGE("No sensor on any tested pin pair (will retry every %lu s on SDA=%d SCL=%d)",
       (unsigned long)(SENSOR_RETRY_MS / 1000), sdaPin, sclPin);
  lastRetryMs = millis();
}

void update() {
  if (sType != SensorType::NONE) return;
  if (millis() - lastRetryMs < SENSOR_RETRY_MS) return;
  lastRetryMs = millis();
  if (detect()) LOGI("Sensor detected");
  else if (!firstScanDone) { scanBus(); firstScanDone = true; }
}

bool measure(SensorReading& out) {
  if (sType == SensorType::NONE) return false;
  // Не чаще раза в секунду: повторный вызов отдаёт последнее значение
  if (haveLast && (millis() - lastReadMs) < SENSOR_MIN_GAP_MS) { out = lastReading; return true; }

  if (!probe(sAddr)) { markLost(); return false; }          // защита от бесконечного ожидания в библиотеке

  float t, p, h = NAN;
  bool hv = false;
  if (sType == SensorType::BME280) {
    if (!bme.takeForcedMeasurement()) { markLost(); return false; }
    t = bme.readTemperature();
    p = bme.readPressure();                                  // Па
    h = bme.readHumidity();
    hv = true;
  } else {
    if (!bmp.takeForcedMeasurement()) { markLost(); return false; }
    t = bmp.readTemperature();
    p = bmp.readPressure();                                  // Па
  }

  if (isnan(t) || isnan(p) || p < 30000.0f || p > 110000.0f || t < -50.0f || t > 100.0f) {
    sErrors++;
    LOGW("Sensor returned invalid data (p=%.0f Pa, t=%.1f C)", p, t);
    return false;
  }
  if (hv && (isnan(h) || h < 0.0f || h > 101.0f)) hv = false;
  if (hv && h > 100.0f) h = 100.0f;

  out.pressurePa    = p;
  out.tempC         = t;
  out.humidity      = hv ? h : 0.0f;
  out.humidityValid = hv;
  lastReading = out;
  haveLast = true;
  lastReadMs = millis();
  return true;
}

bool        present()    { return sType != SensorType::NONE; }
SensorType  type()       { return sType; }
uint8_t     address()    { return sAddr; }
uint32_t    errorCount() { return sErrors; }
const char* state()      { return sType == SensorType::NONE ? "sensor_not_found" : "ok"; }
const char* typeName() {
  switch (sType) {
    case SensorType::BME280: return "BME280";
    case SensorType::BMP280: return "BMP280";
    default:                 return "none";
  }
}

}  // namespace SensorManager
