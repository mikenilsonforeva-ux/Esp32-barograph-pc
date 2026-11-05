// time_manager.h - NTP, часовой пояс Europe/Moscow (UTC+3), форматирование времени
#pragma once
#include <Arduino.h>
#include "config.h"

namespace TimeManager {
  void        begin();                        // часовой пояс + запуск SNTP
  void        update(bool networkUp);         // вызывать в loop(); перезапускает SNTP при необходимости
  bool        isValid();                      // время установлено (NTP или браузер)
  bool        ntpSynced();                    // была успешная синхронизация по NTP
  const char* source();                       // "ntp" / "browser" / "none"
  uint32_t    now();                          // Unix time (UTC), 0 если время не установлено
  bool        setFromClient(uint32_t epoch);  // ручная установка (если нет интернета)
  int         tzOffsetSeconds();              // смещение локального времени, сек (10800)

  // Форматирование локального времени (Europe/Moscow)
  void formatDate(uint32_t ts, char* out, size_t n);   // YYYY-MM-DD
  void formatTime(uint32_t ts, char* out, size_t n);   // HH:MM:SS
  void formatIso(uint32_t ts, char* out, size_t n);    // 2026-10-04T12:34:56+03:00
}
