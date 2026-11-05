// measurement.cpp
#include "measurement.h"
#include "sensor_manager.h"
#include "storage_manager.h"
#include "time_manager.h"
#include "settings.h"

namespace {
  Sample   cur = {false, 0, 0, 0, 0, 0, false};
  uint32_t lastMeasureMs = 0, lastRecordMs = 0;
  bool     measuredOnce = false, recordStarted = false;

  // накопители для усреднения между записями
  double   accP = 0, accT = 0, accH = 0;
  uint32_t accN = 0, accHN = 0;

  void resetAcc() { accP = accT = accH = 0; accN = accHN = 0; }

  bool takeSample() {
    SensorReading r;
    if (!SensorManager::measure(r)) return false;
    cur.valid = true;
    cur.ts = TimeManager::now();
    cur.takenMs = millis();
    cur.pressurePa = r.pressurePa;
    cur.tempC = r.tempC;
    cur.humidity = r.humidity;
    cur.humidityValid = r.humidityValid;
    accP += r.pressurePa; accT += r.tempC; accN++;
    if (r.humidityValid) { accH += r.humidity; accHN++; }
    return true;
  }

  Record makeRecord(uint32_t ts, double p, double t, bool hv, double h) {
    Record rec;
    rec.ts = ts;
    rec.pressurePa = (int32_t)lround(p);
    rec.tempC100 = (int16_t)lround(t * 100.0);
    rec.humRH100 = hv ? (uint16_t)lround(h * 100.0) : HUM_INVALID;
    return rec;
  }

  void commitRecord() {
    if (accN == 0) takeSample();             // период измерений длиннее периода записи
    if (accN == 0) return;                   // датчика нет - записывать нечего
    uint32_t ts = TimeManager::now();
    if (ts == 0) return;
    Record rec = makeRecord(ts, accP / accN, accT / accN, accHN > 0, accHN ? accH / accHN : 0);
    StorageManager::add(rec);
    resetAcc();
  }
}

namespace Measurement {

void begin() {
  lastMeasureMs = lastRecordMs = millis();
  resetAcc();
}

void update() {
  uint32_t now = millis();
  const AppSettings& s = Settings::get();

  if (!measuredOnce || now - lastMeasureMs >= s.measureIntervalS * 1000UL) {
    lastMeasureMs = now;
    if (SensorManager::present()) { takeSample(); measuredOnce = true; }
  }

  // запись в историю возможна только при установленном времени
  if (TimeManager::isValid() && SensorManager::present()) {
    if (!recordStarted || now - lastRecordMs >= s.recordIntervalS * 1000UL) {
      recordStarted = true;
      lastRecordMs = now;
      commitRecord();
    }
  }
}

const Sample& latest() { return cur; }

bool measureNow(Sample& out, bool storeToHistory) {
  if (!takeSample()) { out = cur; return false; }
  out = cur;
  if (storeToHistory && cur.ts != 0) {
    StorageManager::add(makeRecord(cur.ts, cur.pressurePa, cur.tempC, cur.humidityValid, cur.humidity));
  }
  return true;
}

}  // namespace Measurement
