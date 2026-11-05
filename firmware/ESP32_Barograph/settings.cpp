// settings.cpp
#include "settings.h"
#include <Preferences.h>

namespace {
  AppSettings g;
  const char* NS = "baro";

  void copyStr(char* dst, size_t n, const String& src) {
    strlcpy(dst, src.c_str(), n);
  }
}

namespace Settings {

bool intervalsValid(uint32_t m, uint32_t r) {
  return m >= MEASURE_INTERVAL_MIN && m <= MEASURE_INTERVAL_MAX &&
         r >= RECORD_INTERVAL_MIN  && r <= RECORD_INTERVAL_MAX;
}

void begin() {
  Preferences p;
  if (!p.begin(NS, true)) {           // read-only; если пространства ещё нет - берём умолчания
    LOGW("NVS namespace not found, using defaults");
    strlcpy(g.ssid, WIFI_DEFAULT_SSID, sizeof g.ssid);
    strlcpy(g.password, WIFI_DEFAULT_PASSWORD, sizeof g.password);
    g.measureIntervalS = MEASURE_INTERVAL_DEF;
    g.recordIntervalS  = RECORD_INTERVAL_DEF;
    return;
  }
  copyStr(g.ssid, sizeof g.ssid, p.getString("ssid", WIFI_DEFAULT_SSID));
  copyStr(g.password, sizeof g.password, p.getString("pass", WIFI_DEFAULT_PASSWORD));
  g.measureIntervalS = p.getUInt("meas_s", MEASURE_INTERVAL_DEF);
  g.recordIntervalS  = p.getUInt("rec_s", RECORD_INTERVAL_DEF);
  p.end();
  if (!intervalsValid(g.measureIntervalS, g.recordIntervalS)) {   // защита от битых настроек
    LOGW("Invalid stored intervals, using defaults");
    g.measureIntervalS = MEASURE_INTERVAL_DEF;
    g.recordIntervalS  = RECORD_INTERVAL_DEF;
  }
}

AppSettings& get() { return g; }

bool setWifi(const char* ssid, const char* password) {
  if (!ssid || strlen(ssid) == 0 || strlen(ssid) > 32) return false;
  if (!password) password = "";
  size_t pl = strlen(password);
  if (pl > 63 || (pl > 0 && pl < 8)) return false;     // WPA2: 8..63 символов
  Preferences p;
  if (!p.begin(NS, false)) return false;
  p.putString("ssid", ssid);
  p.putString("pass", password);
  p.end();
  strlcpy(g.ssid, ssid, sizeof g.ssid);
  strlcpy(g.password, password, sizeof g.password);
  return true;
}

bool setIntervals(uint32_t m, uint32_t r) {
  if (!intervalsValid(m, r)) return false;
  Preferences p;
  if (!p.begin(NS, false)) return false;
  p.putUInt("meas_s", m);
  p.putUInt("rec_s", r);
  p.end();
  g.measureIntervalS = m;
  g.recordIntervalS  = r;
  return true;
}

}  // namespace Settings
