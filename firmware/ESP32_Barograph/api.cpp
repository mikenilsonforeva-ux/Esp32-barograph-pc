// api.cpp - REST API (JSON, CORS: Access-Control-Allow-Origin: *)
#include "api.h"
#include "config.h"
#include "settings.h"
#include "sensor_manager.h"
#include "storage_manager.h"
#include "measurement.h"
#include "time_manager.h"
#include "wifi_manager.h"
#include "forecast.h"
#include "web_ui.h"
#include <WebServer.h>
#include <WiFi.h>

namespace {

WebServer server(HTTP_PORT);

// ------------------------------------------------------------------ helpers
void addCors() {
  server.sendHeader("Access-Control-Allow-Origin", "*");           // при необходимости заменить на конкретный origin
  server.sendHeader("Access-Control-Allow-Methods", "GET,POST,PUT,OPTIONS");
  server.sendHeader("Access-Control-Allow-Headers", "Content-Type");
  server.sendHeader("Cache-Control", "no-store");
}

void sendJson(int code, const String& body) {
  addCors();
  server.send(code, "application/json; charset=utf-8", body);
}

void sendError(int code, const char* err) {
  String s = "{\"success\":false,\"error\":\"";
  s += err;
  s += "\"}";
  sendJson(code, s);
}

// число в JSON: NAN -> null
void putNum(String& s, float v, int dec) {
  if (isnan(v) || isinf(v)) { s += "null"; return; }
  char t[24];
  snprintf(t, sizeof t, "%.*f", dec, (double)v);
  s += t;
}

void putStr(String& s, const String& v) {
  s += '"';
  for (size_t i = 0; i < v.length(); i++) {
    char c = v[i];
    if (c == '"' || c == '\\') { s += '\\'; s += c; }
    else if (c == '\n') s += "\\n";
    else if (c == '\r') s += "\\r";
    else if (c == '\t') s += "\\t";
    else if ((uint8_t)c < 0x20) { /* управляющие символы пропускаем */ }
    else s += c;
  }
  s += '"';
}

void putIso(String& s, uint32_t ts) {
  if (ts == 0) { s += "null"; return; }
  char t[32];
  TimeManager::formatIso(ts, t, sizeof t);
  s += '"'; s += t; s += '"';
}

// Минимальный разбор JSON-тела {"key": value} без внешних библиотек
bool jsonFind(const String& b, const char* key, String& out) {
  String pat = String("\"") + key + "\"";
  int i = b.indexOf(pat);
  if (i < 0) return false;
  i += pat.length();
  int n = b.length();
  while (i < n && (b[i] == ' ' || b[i] == ':' || b[i] == '\t' || b[i] == '\n' || b[i] == '\r')) i++;
  if (i >= n) return false;
  out = "";
  if (b[i] == '"') {
    i++;
    while (i < n && b[i] != '"') {
      if (b[i] == '\\' && i + 1 < n) { i++; out += (b[i] == 'n') ? '\n' : (b[i] == 't' ? '\t' : b[i]); }
      else out += b[i];
      i++;
    }
    return true;
  }
  while (i < n && b[i] != ',' && b[i] != '}' && b[i] != ' ' && b[i] != '\r' && b[i] != '\n') { out += b[i]; i++; }
  return out.length() > 0;
}

// Параметр из form-urlencoded / query / JSON-тела
bool getParam(const char* name, String& out) {
  if (server.hasArg(name)) { out = server.arg(name); return true; }
  if (server.hasArg("plain")) {
    String body = server.arg("plain");
    if (body.length() > 0 && body[0] == '{') return jsonFind(body, name, out);
  }
  return false;
}

// ------------------------------------------------------------------ GET /api/current
void handleCurrent() {
  const Sample& s = Measurement::latest();
  bool ok = SensorManager::present() && s.valid;
  Forecast::Result f;
  Forecast::compute(f, s.tempC, ok);

  String j;
  j.reserve(400);
  j += "{\"state\":\"";
  j += !SensorManager::present() ? "sensor_not_found" : (s.valid ? "ok" : "no_data");
  j += "\",\"pressure\":";    putNum(j, ok ? pascalToMmHg(s.pressurePa) : NAN, 2);
  j += ",\"pressure_hpa\":";  putNum(j, ok ? s.pressurePa / 100.0f : NAN, 2);
  j += ",\"temperature\":";   putNum(j, ok ? s.tempC : NAN, 1);
  j += ",\"humidity\":";      putNum(j, (ok && s.humidityValid) ? s.humidity : NAN, 1);
  j += ",\"humidity_valid\":"; j += (ok && s.humidityValid) ? "true" : "false";
  j += ",\"timestamp\":";     if (ok && s.ts) j += s.ts; else j += "null";
  j += ",\"datetime\":";      putIso(j, ok ? s.ts : 0);
  j += ",\"age_s\":";         if (ok) j += (millis() - s.takenMs) / 1000UL; else j += "null";
  j += ",\"trend_mmhg_h\":";  putNum(j, f.valid ? f.rateMain : NAN, 2);
  j += "}";
  sendJson(200, j);
}

// ------------------------------------------------------------------ GET /api/history
void handleHistory() {
  float hours = server.hasArg("hours") ? server.arg("hours").toFloat() : 1.0f;
  if (!(hours > 0.0f)) hours = 1.0f;
  if (hours > (float)HISTORY_HOURS) hours = (float)HISTORY_HOURS;
  int maxPts = server.hasArg("max") ? server.arg("max").toInt() : HISTORY_DEFAULT_POINTS;
  if (maxPts < 10) maxPts = 10;
  if (maxPts > HISTORY_MAX_POINTS) maxPts = HISTORY_MAX_POINTS;

  size_t n = StorageManager::count();
  uint32_t ref = TimeManager::isValid() ? TimeManager::now() : StorageManager::lastTimestamp();
  uint32_t win = (uint32_t)(hours * 3600.0f);
  uint32_t cutoff = ref > win ? ref - win : 0;

  // первая запись внутри окна (идём с конца)
  size_t startIdx = n;
  Record r;
  while (startIdx > 0) {
    if (!StorageManager::get(startIdx - 1, r) || r.ts < cutoff) break;
    startIdx--;
  }
  size_t m = n - startIdx;
  size_t step = m ? (m + maxPts - 1) / maxPts : 1;
  size_t nOut = m ? (m + step - 1) / step : 0;

  addCors();
  server.setContentLength(CONTENT_LENGTH_UNKNOWN);
  server.send(200, "application/json; charset=utf-8", "");

  char buf[1024];
  int len = snprintf(buf, sizeof buf,
      "{\"hours\":%.2f,\"record_interval_s\":%lu,\"raw_count\":%u,\"step\":%u,\"count\":%u,\"data\":[",
      (double)hours, (unsigned long)Settings::get().recordIntervalS,
      (unsigned)m, (unsigned)step, (unsigned)nOut);

  for (size_t b = 0; b < m; b += step) {
    double sp = 0, st = 0, sh = 0, sts = 0;
    size_t c = 0, ch = 0;
    for (size_t k = b; k < b + step && k < m; k++) {
      if (!StorageManager::get(startIdx + k, r)) continue;
      sts += r.ts; sp += recPressureMmHg(r); st += recTempC(r); c++;
      if (recHumValid(r)) { sh += recHum(r); ch++; }
    }
    if (c == 0) continue;
    if (len > (int)sizeof(buf) - 140) { server.sendContent(buf, len); len = 0; }
    len += snprintf(buf + len, sizeof(buf) - len, "%s{\"timestamp\":%lu,\"pressure\":%.2f,\"temperature\":%.1f,\"humidity\":",
                    b ? "," : "", (unsigned long)(sts / c + 0.5), sp / c, st / c);
    if (ch) len += snprintf(buf + len, sizeof(buf) - len, "%.1f}", sh / ch);
    else    len += snprintf(buf + len, sizeof(buf) - len, "null}");
  }
  len += snprintf(buf + len, sizeof(buf) - len, "]}");
  server.sendContent(buf, len);
  server.sendContent("");                       // завершение chunked-ответа
}

// ------------------------------------------------------------------ GET|POST /api/measure
void handleMeasure() {
  if (server.method() == HTTP_OPTIONS) { addCors(); server.send(204); return; }
  if (!SensorManager::present()) { sendError(503, "sensor_not_found"); return; }
  String st;
  bool store = getParam("store", st) && (st == "1" || st == "true");
  Sample s;
  if (!Measurement::measureNow(s, store)) { sendError(500, "measurement_failed"); return; }
  String j;
  j += "{\"success\":true,\"pressure\":";   putNum(j, pascalToMmHg(s.pressurePa), 2);
  j += ",\"temperature\":";                 putNum(j, s.tempC, 1);
  j += ",\"humidity\":";                    putNum(j, s.humidityValid ? s.humidity : NAN, 1);
  j += ",\"humidity_valid\":";              j += s.humidityValid ? "true" : "false";
  j += ",\"timestamp\":";                   if (s.ts) j += s.ts; else j += "null";
  j += ",\"stored\":";                      j += store ? "true" : "false";
  j += "}";
  sendJson(200, j);
}

// ------------------------------------------------------------------ GET /api/status
void handleStatus() {
  String j;
  j.reserve(700);
  uint32_t ts = TimeManager::now();
  char hex[8];
  snprintf(hex, sizeof hex, "0x%02X", SensorManager::address());

  j += "{\"wifi\":";           j += WifiManager::staConnected() ? "true" : "false";
  j += ",\"wifi_state\":\"";   j += WifiManager::stateName(); j += "\"";
  j += ",\"ssid\":";           putStr(j, WifiManager::ssid());
  j += ",\"ip\":";             putStr(j, WifiManager::ip());
  j += ",\"rssi\":";           j += WifiManager::rssi();
  j += ",\"ap\":";             j += WifiManager::apActive() ? "true" : "false";
  j += ",\"mdns\":\"" WIFI_HOSTNAME ".local\"";
  j += ",\"sd\":";             j += StorageManager::sdOnline() ? "true" : "false";
  j += ",\"sd_card_mb\":";     j += (unsigned long)(StorageManager::sdCardBytes() / (1024ULL * 1024ULL));
  j += ",\"csv_bytes\":";      j += (unsigned long)StorageManager::csvBytes();
  j += ",\"csv_file\":\"barograph.csv\"";
  j += ",\"storage\":\"";      j += StorageManager::backend(); j += "\"";
  j += ",\"flash_ok\":";       j += StorageManager::flashOk() ? "true" : "false";
  j += ",\"flash_records\":";  j += (unsigned long)StorageManager::flashRecords();
  j += ",\"sensor\":\"";       j += SensorManager::typeName(); j += "\"";
  j += ",\"sensor_state\":\""; j += SensorManager::state(); j += "\"";
  j += ",\"sensor_address\":"; if (SensorManager::present()) { j += '"'; j += hex; j += '"'; } else j += "null";
  j += ",\"uptime\":";         j += (unsigned long)(millis() / 1000UL);
  j += ",\"free_heap\":";      j += (unsigned long)ESP.getFreeHeap();
  j += ",\"history_records\":"; j += (unsigned long)StorageManager::count();
  j += ",\"history_capacity\":"; j += (unsigned long)StorageManager::capacity();
  j += ",\"time_synced\":";    j += TimeManager::isValid() ? "true" : "false";
  j += ",\"ntp_synced\":";     j += TimeManager::ntpSynced() ? "true" : "false";
  j += ",\"time_source\":\"";  j += TimeManager::source(); j += "\"";
  j += ",\"epoch\":";          if (ts) j += ts; else j += "null";
  j += ",\"datetime\":";       putIso(j, ts);
  j += ",\"tz_offset_s\":";    j += TimeManager::tzOffsetSeconds();
  j += ",\"fw_version\":\"" FW_VERSION "\"}";
  sendJson(200, j);
}

// ------------------------------------------------------------------ GET /api/forecast
void handleForecast() {
  const Sample& s = Measurement::latest();
  Forecast::Result f;
  Forecast::compute(f, s.tempC, s.valid && SensorManager::present());
  String j;
  j.reserve(700);
  j += "{\"valid\":";          j += f.valid ? "true" : "false";
  j += ",\"data_span_s\":";    j += (unsigned long)f.dataSpanS;
  j += ",\"pressure\":";       putNum(j, f.pressureMmHg, 2);
  j += ",\"trend\":\"";        j += f.trend; j += "\"";
  j += ",\"trend_label\":\"";  j += f.trendLabel; j += "\"";
  j += ",\"level\":\"";        j += f.level; j += "\"";
  j += ",\"rate_mmhg_h\":";    putNum(j, f.rateMain, 2);
  j += ",\"change_3h_mmhg\":"; putNum(j, f.change3h, 2);
  j += ",\"rates\":{\"10m\":"; putNum(j, f.rate10m, 2);
  j += ",\"30m\":";            putNum(j, f.rate30m, 2);
  j += ",\"1h\":";             putNum(j, f.rate1h, 2);
  j += ",\"3h\":";             putNum(j, f.rate3h, 2);
  j += ",\"6h\":";             putNum(j, f.rate6h, 2);
  j += "},\"icon\":\"";        j += f.icon; j += "\"";
  j += ",\"windy\":";          j += f.windy ? "true" : "false";
  j += ",\"summary\":";        putStr(j, f.summary);
  j += ",\"details\":";        putStr(j, f.details);
  j += ",\"probability_worse\":"; j += f.probWorse;
  j += ",\"probability_better\":"; j += f.probBetter;
  j += "}";
  sendJson(200, j);
}

// ------------------------------------------------------------------ GET|POST|PUT /api/settings
void sendSettings(bool success, bool reconnecting) {
  const AppSettings& s = Settings::get();
  String j;
  j.reserve(400);
  j += "{\"success\":"; j += success ? "true" : "false";
  j += ",\"ssid\":";    putStr(j, String(s.ssid));
  j += ",\"wifi_password_set\":"; j += strlen(s.password) > 0 ? "true" : "false";   // сам пароль не отдаётся
  j += ",\"measure_interval_s\":"; j += (unsigned long)s.measureIntervalS;
  j += ",\"record_interval_s\":";  j += (unsigned long)s.recordIntervalS;
  j += ",\"measure_interval_range\":[" + String(MEASURE_INTERVAL_MIN) + "," + String(MEASURE_INTERVAL_MAX) + "]";
  j += ",\"record_interval_range\":[" + String(RECORD_INTERVAL_MIN) + "," + String(RECORD_INTERVAL_MAX) + "]";
  j += ",\"ap_ssid\":\"" AP_SSID "\"";
  j += ",\"reconnecting\":"; j += reconnecting ? "true" : "false";
  j += "}";
  sendJson(200, j);
}

void handleSettings() {
  HTTPMethod m = server.method();
  if (m == HTTP_OPTIONS) { addCors(); server.send(204); return; }
  if (m == HTTP_GET) { sendSettings(true, false); return; }
  if (m != HTTP_POST && m != HTTP_PUT) { sendError(405, "method_not_allowed"); return; }

  const AppSettings& cur = Settings::get();
  String ssid, pass, ms, rs;
  bool hasSsid = getParam("ssid", ssid);
  bool hasPass = getParam("password", pass);
  bool hasM = getParam("measure_interval_s", ms) || getParam("measure_interval", ms);
  bool hasR = getParam("record_interval_s", rs)  || getParam("record_interval", rs);
  if (!hasSsid && !hasPass && !hasM && !hasR) { sendError(400, "no_parameters"); return; }

  // --- 1. проверка всех значений до применения ---
  bool wifiChange = false;
  String newSsid = hasSsid ? ssid : String(cur.ssid);
  String newPass = String(cur.password);
  if (hasSsid || hasPass) {
    bool ssidChanged = (newSsid != String(cur.ssid));
    if (hasPass && (pass.length() > 0 || ssidChanged)) newPass = pass;
    else if (ssidChanged) newPass = "";                        // новая сеть без пароля (открытая)
    if (newSsid.length() == 0 || newSsid.length() > 32) { sendError(400, "invalid_ssid"); return; }
    if (newPass.length() > 63 || (newPass.length() > 0 && newPass.length() < 8)) { sendError(400, "invalid_password_length_8_63"); return; }
    wifiChange = ssidChanged || newPass != String(cur.password);
  }
  uint32_t newM = cur.measureIntervalS, newR = cur.recordIntervalS;
  if (hasM) newM = (uint32_t)ms.toInt();
  if (hasR) newR = (uint32_t)rs.toInt();
  if ((hasM || hasR) && !Settings::intervalsValid(newM, newR)) { sendError(400, "invalid_interval"); return; }

  // --- 2. применение ---
  if (wifiChange) {
    if (!Settings::setWifi(newSsid.c_str(), newPass.c_str())) { sendError(500, "save_failed"); return; }
  }
  if (hasM || hasR) {
    if (!Settings::setIntervals(newM, newR)) { sendError(500, "save_failed"); return; }
    StorageManager::setRecordInterval(newR);
  }
  sendSettings(true, wifiChange);
  if (wifiChange) WifiManager::applyNewCredentials();
}

// ------------------------------------------------------------------ GET /api/wifi/scan
void handleWifiScan() {
  bool start = server.hasArg("start") && server.arg("start") == "1";
  int n = WiFi.scanComplete();
  if (start) {
    if (n != WIFI_SCAN_RUNNING) { WiFi.scanDelete(); WiFi.scanNetworks(true); }   // асинхронно, loop не блокируется
    sendJson(200, "{\"status\":\"scanning\",\"networks\":[]}");
    return;
  }
  if (n == WIFI_SCAN_RUNNING) { sendJson(200, "{\"status\":\"scanning\",\"networks\":[]}"); return; }
  if (n < 0)                  { sendJson(200, "{\"status\":\"idle\",\"networks\":[]}"); return; }

  String j;
  j.reserve(64 + n * 90);
  j += "{\"status\":\"done\",\"networks\":[";
  bool first = true;
  for (int i = 0; i < n; i++) {
    String ss = WiFi.SSID(i);
    if (ss.length() == 0) continue;                              // скрытые сети пропускаем
    const char* sec;
    switch (WiFi.encryptionType(i)) {
      case WIFI_AUTH_OPEN:         sec = "Open"; break;
      case WIFI_AUTH_WEP:          sec = "WEP"; break;
      case WIFI_AUTH_WPA_PSK:      sec = "WPA"; break;
      case WIFI_AUTH_WPA2_PSK:     sec = "WPA2"; break;
      case WIFI_AUTH_WPA_WPA2_PSK: sec = "WPA/WPA2"; break;
      case WIFI_AUTH_WPA3_PSK:     sec = "WPA3"; break;
      case WIFI_AUTH_WPA2_WPA3_PSK: sec = "WPA2/WPA3"; break;
      default:                     sec = "Secured"; break;
    }
    if (!first) j += ',';
    first = false;
    j += "{\"ssid\":";   putStr(j, ss);
    j += ",\"rssi\":";   j += WiFi.RSSI(i);
    j += ",\"channel\":"; j += WiFi.channel(i);
    j += ",\"security\":\""; j += sec; j += "\"}";
  }
  j += "]}";
  WiFi.scanDelete();
  sendJson(200, j);
}

// ------------------------------------------------------------------ GET|POST /api/time
void handleTime() {
  if (server.method() == HTTP_OPTIONS) { addCors(); server.send(204); return; }
  bool applied = false;
  if (server.method() == HTTP_POST || server.method() == HTTP_PUT) {
    String e;
    if (!getParam("epoch", e)) { sendError(400, "epoch_required"); return; }
    uint32_t epoch = (uint32_t)strtoul(e.c_str(), nullptr, 10);
    if (epoch <= TIME_MIN_VALID_EPOCH) { sendError(400, "invalid_epoch"); return; }
    applied = TimeManager::setFromClient(epoch);           // false, если уже есть время от NTP
  }
  uint32_t ts = TimeManager::now();
  String j = "{\"success\":true,\"applied\":";
  j += applied ? "true" : "false";
  j += ",\"synced\":";  j += TimeManager::isValid() ? "true" : "false";
  j += ",\"source\":\""; j += TimeManager::source(); j += "\"";
  j += ",\"epoch\":";   if (ts) j += ts; else j += "null";
  j += ",\"datetime\":"; putIso(j, ts);
  j += "}";
  sendJson(200, j);
}

// ------------------------------------------------------------------ GET /api/export.csv
void handleExport() {
  addCors();
  server.sendHeader("Content-Disposition", "attachment; filename=\"barograph.csv\"");
  server.setContentLength(CONTENT_LENGTH_UNKNOWN);
  server.send(200, "text/csv; charset=utf-8", "");
  server.sendContent(SD_CSV_HEADER "\n");
  char buf[1024], d[16], t[16];
  int len = 0;
  size_t n = StorageManager::count();
  Record r;
  for (size_t i = 0; i < n; i++) {
    if (!StorageManager::get(i, r)) continue;
    if (len > (int)sizeof(buf) - 100) { server.sendContent(buf, len); len = 0; }
    TimeManager::formatDate(r.ts, d, sizeof d);
    TimeManager::formatTime(r.ts, t, sizeof t);
    len += snprintf(buf + len, sizeof(buf) - len, "%lu,%s,%s,%.2f,%.1f,", (unsigned long)r.ts, d, t,
                    (double)recPressureMmHg(r), (double)recTempC(r));
    if (recHumValid(r)) len += snprintf(buf + len, sizeof(buf) - len, "%.1f\n", (double)recHum(r));
    else                len += snprintf(buf + len, sizeof(buf) - len, "\n");
  }
  if (len) server.sendContent(buf, len);
  server.sendContent("");
}

void handleRoot() { server.send_P(200, "text/html; charset=utf-8", WebUi::indexHtml()); }

void handleNotFound() {
  if (server.method() == HTTP_OPTIONS) { addCors(); server.send(204); return; }   // CORS preflight
  if (server.uri().startsWith("/api/")) { sendError(404, "not_found"); return; }
  server.send(404, "text/plain; charset=utf-8", "404 Not Found");
}

}  // namespace

namespace Api {

void begin() {
  server.on("/", HTTP_GET, handleRoot);
  server.on("/api/current",  HTTP_GET, handleCurrent);
  server.on("/api/history",  HTTP_GET, handleHistory);
  server.on("/api/measure",  HTTP_ANY, handleMeasure);
  server.on("/api/status",   HTTP_GET, handleStatus);
  server.on("/api/forecast", HTTP_GET, handleForecast);
  server.on("/api/settings", HTTP_ANY, handleSettings);
  server.on("/api/wifi/scan", HTTP_GET, handleWifiScan);
  server.on("/api/time",     HTTP_ANY, handleTime);
  server.on("/api/export.csv", HTTP_GET, handleExport);
  server.onNotFound(handleNotFound);
  server.begin();
  LOGI("Web server started");
}

void handle() { server.handleClient(); }

}  // namespace Api
