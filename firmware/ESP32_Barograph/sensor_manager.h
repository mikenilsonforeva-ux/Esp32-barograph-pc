// sensor_manager.h - автоопределение и чтение BMP280 / BME280 (I2C)
#pragma once
#include <Arduino.h>
#include "config.h"

enum class SensorType : uint8_t { NONE = 0, BMP280 = 1, BME280 = 2 };

// Одно "сырое" измерение датчика (без времени)
struct SensorReading {
  float pressurePa;
  float tempC;
  float humidity;        // % RH, имеет смысл только если humidityValid
  bool  humidityValid;
};

namespace SensorManager {
  void        begin();                         // инициализация I2C + поиск датчика (не зависает)
  void        update();                        // периодически повторяет поиск, если датчика нет
  bool        measure(SensorReading& out);     // новое измерение; false при ошибке
  bool        present();
  SensorType  type();
  const char* typeName();                      // "BME280" / "BMP280" / "none"
  const char* state();                         // "ok" / "sensor_not_found"
  uint8_t     address();                       // 0x76 / 0x77 / 0
  uint32_t    errorCount();
}
