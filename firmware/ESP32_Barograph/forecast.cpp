// forecast.cpp
// Алгоритм: линейная регрессия давления по окнам 10 мин / 30 мин / 1 ч / 3 ч / 6 ч,
// сглаженная скорость = 0.6*(3 ч) + 0.4*(1 ч) (или лучшее доступное окно),
// классификация по скорости (пороги близки к шкале ВМО: 3.6 гПа/3ч ~ 0.9 мм рт. ст./ч),
// вероятность - логистическая функция от скорости. Для замены алгоритма достаточно
// переписать Forecast::compute().
#include "forecast.h"
#include "storage_manager.h"

namespace {

  // Наклон линейной регрессии за окно (мм рт. ст./ч). NAN, если данных мало.
  float windowSlope(size_t n, uint32_t newestTs, uint32_t windowS) {
    if (n < 3) return NAN;
    double sx = 0, sy = 0, sxx = 0, sxy = 0;
    size_t cnt = 0;
    uint32_t t0 = 0, firstTs = 0;
    for (size_t k = 0; k < n; k++) {
      size_t i = n - 1 - k;                    // идём от новых записей к старым
      Record r;
      if (!StorageManager::get(i, r)) break;
      if (newestTs - r.ts > windowS) break;
      if (cnt == 0) t0 = r.ts;                 // t0 = самая новая точка
      double x = -((double)(t0 - r.ts)) / 3600.0;
      double y = recPressureMmHg(r);
      sx += x; sy += y; sxx += x * x; sxy += x * y;
      firstTs = r.ts;
      cnt++;
    }
    if (cnt < 3) return NAN;
    if ((t0 - firstTs) < windowS * 6 / 10) return NAN;       // окно заполнено менее чем на 60%
    double den = cnt * sxx - sx * sx;
    if (fabs(den) < 1e-12) return NAN;
    return (float)((cnt * sxy - sx * sy) / den);
  }

  int logistic(float x) {                      // 0..100 %
    double p = 100.0 / (1.0 + exp(-(2.2 * x - 1.0)));
    if (p < 1) p = 1;
    if (p > 99) p = 99;
    return (int)lround(p);
  }
}

namespace Forecast {

void compute(Result& o, float tempC, bool tempValid) {
  o.valid = false; o.dataSpanS = 0; o.pressureMmHg = NAN;
  o.rate10m = o.rate30m = o.rate1h = o.rate3h = o.rate6h = o.rateMain = NAN;
  o.change3h = NAN;
  o.trend = "unknown"; o.trendLabel = "НЕТ ДАННЫХ"; o.level = "unknown"; o.icon = "unknown";
  o.windy = false;
  o.summary = "Накопление данных";
  o.details = "Для прогноза нужно не менее 30 минут истории давления.";
  o.probWorse = 0; o.probBetter = 0;

  size_t n = StorageManager::count();
  if (n < 3) return;
  Record first, last;
  if (!StorageManager::get(0, first) || !StorageManager::get(n - 1, last)) return;
  uint32_t newest = last.ts;
  o.dataSpanS = newest - first.ts;
  o.pressureMmHg = recPressureMmHg(last);

  o.rate10m = windowSlope(n, newest, 600);
  o.rate30m = windowSlope(n, newest, 1800);
  o.rate1h  = windowSlope(n, newest, 3600);
  o.rate3h  = windowSlope(n, newest, 10800);
  o.rate6h  = windowSlope(n, newest, 21600);

  // сглаженная скорость
  float main;
  if (!isnan(o.rate3h) && !isnan(o.rate1h)) main = 0.6f * o.rate3h + 0.4f * o.rate1h;
  else if (!isnan(o.rate1h))  main = o.rate1h;
  else if (!isnan(o.rate30m)) main = o.rate30m;
  else return;                                  // данных недостаточно
  o.valid = true;
  o.rateMain = main;
  o.change3h = main * 3.0f;

  // классификация
  bool snowTemp = tempValid && tempC <= 0.5f;
  if (main >= 1.5f) {
    o.level = "very_fast_rise"; o.trend = "rising"; o.trendLabel = "РОСТ"; o.icon = "sun"; o.windy = true;
    o.summary = "Быстрое улучшение погоды";
    o.details = "Давление очень быстро растёт: прояснение, возможен порывистый ветер.";
  } else if (main >= 0.9f) {
    o.level = "fast_rise"; o.trend = "rising"; o.trendLabel = "РОСТ"; o.icon = "sun";
    o.summary = "Улучшение погоды";
    o.details = "Давление быстро растёт: ожидается прояснение и устойчивая погода.";
  } else if (main >= 0.25f) {
    o.level = "slow_rise"; o.trend = "rising"; o.trendLabel = "РОСТ"; o.icon = "partly";
    o.summary = "Переменная облачность";
    o.details = "Давление медленно растёт: погода постепенно улучшается.";
  } else if (main > -0.25f) {
    o.level = "steady"; o.trend = "steady"; o.trendLabel = "СТАБИЛЬНО"; o.icon = "partly";
    o.summary = "Стабильная погода";
    o.details = "Давление почти не меняется: резких перемен погоды не ожидается.";
  } else if (main > -0.9f) {
    o.level = "slow_fall"; o.trend = "falling"; o.trendLabel = "ПАДЕНИЕ"; o.icon = snowTemp ? "snow" : "cloud";
    o.summary = snowTemp ? "Возможен снег" : "Вероятно ухудшение погоды";
    o.details = "Давление медленно падает: увеличивается облачность, возможны осадки.";
  } else if (main > -1.5f) {
    o.level = "fast_fall"; o.trend = "falling"; o.trendLabel = "ПАДЕНИЕ"; o.icon = snowTemp ? "snow" : "rain";
    o.summary = snowTemp ? "Возможен снег" : "Ухудшение погоды, дождь";
    o.details = "Давление быстро падает: ожидаются осадки и усиление ветра.";
  } else {
    o.level = "very_fast_fall"; o.trend = "falling"; o.trendLabel = "ПАДЕНИЕ"; o.windy = true;
    o.icon = snowTemp ? "snow" : "storm";
    o.summary = snowTemp ? "Возможен снег, метель" : "Штормовая / дождливая погода";
    o.details = "Давление очень быстро падает: вероятны сильный ветер, ливень или гроза.";
  }

  // вероятности: падение ускоряется (1 ч хуже 3 ч) - небольшая добавка
  float x = -main;
  if (!isnan(o.rate1h) && !isnan(o.rate3h) && (o.rate1h - o.rate3h) < -0.3f) x += 0.15f;
  if (!isnan(o.rate1h) && !isnan(o.rate3h) && (o.rate1h - o.rate3h) >  0.3f) x -= 0.15f;
  o.probWorse  = logistic(x);
  o.probBetter = logistic(-x);
}

}  // namespace Forecast
