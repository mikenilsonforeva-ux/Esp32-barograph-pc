// wifi_manager.h - STA с сохранёнными настройками, резервная точка доступа, mDNS
#pragma once
#include <Arduino.h>
#include "config.h"

namespace WifiManager {
  void        begin();                 // не блокирует: подключение идёт в update()
  void        update();                // вызывать в loop()
  void        applyNewCredentials();   // после смены SSID/пароля (применится через ~0.8 с)
  bool        staConnected();
  bool        apActive();
  const char* stateName();             // "connecting" / "connected" / "ap"
  String      ssid();                  // текущая сеть (STA) или имя AP
  String      ip();                    // IP в STA, иначе IP точки доступа
  int         rssi();                  // dBm, 0 если нет подключения
}
