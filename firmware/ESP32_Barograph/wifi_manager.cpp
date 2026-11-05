// wifi_manager.cpp
#include "wifi_manager.h"
#include "settings.h"
#include <WiFi.h>
#include <ESPmDNS.h>

namespace {
  enum State { ST_CONNECTING, ST_CONNECTED, ST_AP };
  State    state = ST_CONNECTING;
  uint32_t stateSinceMs = 0;        // начало попытки подключения
  uint32_t lostSinceMs  = 0;        // когда пропала связь (STA)
  uint32_t lastApRetryMs = 0;
  bool     apRetrying = false;      // в режиме AP идёт попытка подключения к сети
  bool     pendingApply = false;
  uint32_t applyAtMs = 0;

  void startMdns() {
    MDNS.end();
    if (MDNS.begin(WIFI_HOSTNAME)) {
      MDNS.addService("http", "tcp", HTTP_PORT);
      LOGI("mDNS: %s.local", WIFI_HOSTNAME);
    } else {
      LOGW("mDNS start failed");
    }
  }

  void beginSta() {
    const AppSettings& s = Settings::get();
    LOGI("Initializing WiFi...");
    LOGI("SSID: %s", s.ssid);
    WiFi.setAutoReconnect(true);
    WiFi.begin(s.ssid, s.password);
    stateSinceMs = millis();
  }

  void onConnected() {
    if (WiFi.getMode() != WIFI_STA) {
      WiFi.softAPdisconnect(true);          // AP больше не нужна
      WiFi.mode(WIFI_STA);
    }
    state = ST_CONNECTED;
    apRetrying = false;
    lostSinceMs = 0;
    LOGI("WiFi connected");
    LOGI("IP: %s", WiFi.localIP().toString().c_str());
    startMdns();
  }

  void startAp() {
    LOGW("WiFi connection failed, starting access point");
    WiFi.setAutoReconnect(false);
    WiFi.disconnect();
    WiFi.mode(WIFI_AP_STA);                  // AP + STA: сканирование и попытки подключения работают
    WiFi.softAP(AP_SSID, nullptr, AP_CHANNEL);   // без пароля
    delay(100);
    IPAddress ip(AP_IP_A, AP_IP_B, AP_IP_C, AP_IP_D);
    if (!WiFi.softAPConfig(ip, ip, IPAddress(255, 255, 255, 0))) LOGW("softAPConfig failed");
    state = ST_AP;
    apRetrying = false;
    lastApRetryMs = millis();
    LOGI("AP: %s  IP: %s", AP_SSID, WiFi.softAPIP().toString().c_str());
    startMdns();
  }

  void retryStaFromAp() {
    apRetrying = true;
    lastApRetryMs = millis();
    stateSinceMs = millis();
    const AppSettings& s = Settings::get();
    LOGI("AP mode: trying to connect to %s", s.ssid);
    WiFi.disconnect();
    WiFi.begin(s.ssid, s.password);
  }
}

namespace WifiManager {

void begin() {
  WiFi.persistent(false);                    // настройки храним сами (NVS), не изнашиваем flash
  WiFi.setHostname(WIFI_HOSTNAME);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);                      // стабильный отклик веб-сервера
  if (strlen(Settings::get().ssid) == 0) { startAp(); return; }
  state = ST_CONNECTING;
  beginSta();
}

void update() {
  uint32_t now = millis();

  if (pendingApply && (int32_t)(now - applyAtMs) >= 0) {
    pendingApply = false;
    const AppSettings& s = Settings::get();
    if (strlen(s.ssid) == 0) { if (state != ST_AP) startAp(); return; }
    if (state == ST_AP) {
      retryStaFromAp();
    } else {
      WiFi.disconnect();
      state = ST_CONNECTING;
      lostSinceMs = 0;
      beginSta();
    }
    return;
  }

  switch (state) {
    case ST_CONNECTING:
      if (WiFi.status() == WL_CONNECTED) onConnected();
      else if (now - stateSinceMs > WIFI_STA_TIMEOUT_MS) startAp();
      break;

    case ST_CONNECTED:
      if (WiFi.status() == WL_CONNECTED) {
        lostSinceMs = 0;
      } else {
        if (lostSinceMs == 0) { lostSinceMs = now ? now : 1; LOGW("WiFi connection lost"); }
        else if (now - lostSinceMs > WIFI_STA_LOST_MS) startAp();
      }
      break;

    case ST_AP:
      if (apRetrying) {
        if (WiFi.status() == WL_CONNECTED) onConnected();
        else if (now - stateSinceMs > WIFI_STA_TIMEOUT_MS) {
          apRetrying = false;
          WiFi.disconnect();                 // остановить попытки, чтобы не мешать клиентам AP
          LOGW("Retry failed, staying in AP mode");
        }
      } else if (strlen(Settings::get().ssid) > 0 &&
                 WiFi.softAPgetStationNum() == 0 &&
                 now - lastApRetryMs > WIFI_AP_RETRY_MS) {
        retryStaFromAp();                    // только если к AP никто не подключён
      }
      break;
  }
}

void applyNewCredentials() { pendingApply = true; applyAtMs = millis() + 800; }

bool staConnected() { return WiFi.status() == WL_CONNECTED; }
bool apActive()     { return state == ST_AP; }

const char* stateName() {
  switch (state) {
    case ST_CONNECTED: return staConnected() ? "connected" : "reconnecting";
    case ST_AP:        return "ap";
    default:           return "connecting";
  }
}

String ssid() { return staConnected() ? WiFi.SSID() : String(state == ST_AP ? AP_SSID : Settings::get().ssid); }
String ip()   { return staConnected() ? WiFi.localIP().toString() : (state == ST_AP ? WiFi.softAPIP().toString() : String("0.0.0.0")); }
int    rssi() { return staConnected() ? WiFi.RSSI() : 0; }

}  // namespace WifiManager
