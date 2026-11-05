// forecast.h - локальный прогноз погоды по тренду давления (отдельный сменный модуль)
#pragma once
#include <Arduino.h>
#include <math.h>

namespace Forecast {

  struct Result {
    bool     valid;          // достаточно данных для прогноза
    uint32_t dataSpanS;      // за какой период накоплены данные в истории
    float    pressureMmHg;   // последнее значение в истории
    float    rate10m, rate30m, rate1h, rate3h, rate6h;   // мм рт. ст./ч, NAN если окно не заполнено
    float    rateMain;       // сглаженная скорость (NAN если нет данных)
    float    change3h;       // оценка изменения за 3 часа, мм рт. ст.
    const char* trend;       // "rising" / "falling" / "steady" / "unknown"
    const char* trendLabel;  // РОСТ / ПАДЕНИЕ / СТАБИЛЬНО
    const char* level;       // very_fast_rise ... very_fast_fall
    const char* icon;        // sun / partly / cloud / rain / storm / snow / unknown
    bool     windy;          // быстрые изменения давления - вероятен сильный ветер
    const char* summary;     // краткий вывод
    const char* details;     // пояснение
    int      probWorse;      // вероятность ухудшения, %
    int      probBetter;     // вероятность улучшения, %
  };

  // tempC / tempValid - текущая температура (для определения снега)
  void compute(Result& out, float tempC, bool tempValid);
}
