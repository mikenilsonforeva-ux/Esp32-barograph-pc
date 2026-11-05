// storage_manager.h - история измерений: кольцевой буфер в ОЗУ + SD (CSV) или LittleFS
#pragma once
#include <Arduino.h>
#include "config.h"

// Компактная запись истории (12 байт)
struct Record {
  uint32_t ts;          // Unix time, UTC
  int32_t  pressurePa;  // давление, Па
  int16_t  tempC100;    // температура, 0.01 C
  uint16_t humRH100;    // влажность, 0.01 %RH; HUM_INVALID если нет
};
static const uint16_t HUM_INVALID = 0xFFFF;

inline float recPressureMmHg(const Record& r) { return r.pressurePa * 0.00750061683f; }
inline float recTempC(const Record& r)        { return r.tempC100 / 100.0f; }
inline bool  recHumValid(const Record& r)     { return r.humRH100 != HUM_INVALID; }
inline float recHum(const Record& r)          { return r.humRH100 / 100.0f; }

namespace StorageManager {
  void   begin(uint32_t recordIntervalS);        // LittleFS + SD + загрузка истории
  void   update();                               // flush, проверка SD, повторное подключение SD
  bool   add(const Record& r);                   // false: дубликат / время пошло назад
  void   setRecordInterval(uint32_t seconds);    // пересчёт ёмкости буфера

  size_t count();                                // записей в ОЗУ
  size_t capacity();
  bool   get(size_t index, Record& out);         // 0 = самая старая
  uint32_t lastTimestamp();

  bool        sdOnline();
  const char* backend();                         // "sd" или "flash"
  uint64_t    sdCardBytes();
  uint32_t    csvBytes();
  bool        flashOk();
  size_t      flashRecords();
}
