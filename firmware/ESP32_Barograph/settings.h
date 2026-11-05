// settings.h - пользовательские настройки в NVS (Preferences)
#pragma once
#include <Arduino.h>
#include "config.h"

struct AppSettings {
  char     ssid[33];
  char     password[65];
  uint32_t measureIntervalS;   // период измерений датчика
  uint32_t recordIntervalS;    // период записи в историю
};

namespace Settings {
  void         begin();                              // загрузка из NVS (или значения по умолчанию)
  AppSettings& get();                                // текущие настройки
  bool         setWifi(const char* ssid, const char* password);
  bool         setIntervals(uint32_t measureS, uint32_t recordS);
  bool         intervalsValid(uint32_t measureS, uint32_t recordS);
}
