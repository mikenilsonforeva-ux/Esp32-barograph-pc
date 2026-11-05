// time_manager.cpp
#include "time_manager.h"
#include <time.h>
#include <sys/time.h>
#include <esp_sntp.h>

namespace {
  volatile bool ntpDone = false;      // выставляется из callback SNTP
  bool     browserSet = false;
  uint32_t lastKickMs = 0;

  void onSntpSync(struct timeval* tv) { (void)tv; ntpDone = true; }

  void startSntp() {
    configTzTime(TIME_TZ_POSIX, TIME_NTP_SERVER_1, TIME_NTP_SERVER_2);
    lastKickMs = millis();
  }
}

namespace TimeManager {

void begin() {
  setenv("TZ", TIME_TZ_POSIX, 1);
  tzset();
  sntp_set_time_sync_notification_cb(onSntpSync);
  startSntp();
}

void update(bool networkUp) {
  static bool wasUp = false;
  if (networkUp && !wasUp) startSntp();                        // сеть появилась - перезапускаем SNTP
  wasUp = networkUp;
  if (networkUp && !ntpDone && millis() - lastKickMs >= TIME_NTP_KICK_MS) {
    LOGW("NTP not synchronized yet, restarting SNTP");
    startSntp();
  }
  static bool reported = false;
  if (ntpDone && !reported) { reported = true; LOGI("Time synchronized (NTP)"); }
}

bool isValid() { return time(nullptr) > (time_t)TIME_MIN_VALID_EPOCH; }
bool ntpSynced() { return ntpDone && isValid(); }

const char* source() {
  if (!isValid()) return "none";
  if (ntpDone) return "ntp";
  return browserSet ? "browser" : "none";
}

uint32_t now() {
  time_t t = time(nullptr);
  return t > (time_t)TIME_MIN_VALID_EPOCH ? (uint32_t)t : 0;
}

bool setFromClient(uint32_t epoch) {
  if (epoch <= TIME_MIN_VALID_EPOCH) return false;
  if (ntpDone) return false;                                   // NTP точнее, не перебиваем
  struct timeval tv;
  tv.tv_sec = (time_t)epoch;
  tv.tv_usec = 0;
  settimeofday(&tv, nullptr);
  browserSet = true;
  LOGI("Time set from client: %lu", (unsigned long)epoch);
  return true;
}

namespace {
  // Смещение локального времени от UTC для момента t (без tm_gmtoff - его нет в newlib ESP32)
  long offsetAt(time_t t) {
    struct tm lt, gt;
    localtime_r(&t, &lt);
    gmtime_r(&t, &gt);
    lt.tm_isdst = 0;
    gt.tm_isdst = 0;
    return (long)(mktime(&lt) - mktime(&gt));
  }
}

int tzOffsetSeconds() { return (int)offsetAt(time(nullptr)); }

void formatDate(uint32_t ts, char* out, size_t n) {
  time_t t = (time_t)ts;
  struct tm lt;
  localtime_r(&t, &lt);
  strftime(out, n, "%Y-%m-%d", &lt);
}

void formatTime(uint32_t ts, char* out, size_t n) {
  time_t t = (time_t)ts;
  struct tm lt;
  localtime_r(&t, &lt);
  strftime(out, n, "%H:%M:%S", &lt);
}

void formatIso(uint32_t ts, char* out, size_t n) {
  time_t t = (time_t)ts;
  struct tm lt;
  localtime_r(&t, &lt);
  char base[24];
  strftime(base, sizeof base, "%Y-%m-%dT%H:%M:%S", &lt);
  long off = offsetAt(t);
  char sign = off < 0 ? '-' : '+';
  if (off < 0) off = -off;
  snprintf(out, n, "%s%c%02ld:%02ld", base, sign, off / 3600, (off % 3600) / 60);
}

}  // namespace TimeManager
