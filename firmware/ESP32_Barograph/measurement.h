// measurement.h - планировщик измерений и записи в историю (на millis(), без delay)
#pragma once
#include <Arduino.h>
#include "config.h"

struct Sample {
  bool     valid;          // есть хотя бы одно успешное измерение
  uint32_t ts;             // Unix time, 0 если время не установлено
  uint32_t takenMs;        // millis() в момент измерения
  float    pressurePa;
  float    tempC;
  float    humidity;
  bool     humidityValid;
};

namespace Measurement {
  void          begin();
  void          update();
  const Sample& latest();
  // Немедленное измерение (для API). storeToHistory - ещё и добавить в историю.
  bool          measureNow(Sample& out, bool storeToHistory);
}

inline float pascalToMmHg(float pa) { return pa * 0.00750061683f; }
