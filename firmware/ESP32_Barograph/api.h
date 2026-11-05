// api.h - HTTP-сервер: REST API + раздача Web UI
#pragma once
#include <Arduino.h>

namespace Api {
  void begin();     // регистрация маршрутов и запуск сервера
  void handle();    // вызывать в loop()
}
