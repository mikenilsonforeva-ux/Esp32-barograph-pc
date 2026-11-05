// storage_manager.cpp
#include "storage_manager.h"
#include "time_manager.h"
#include <SD.h>
#include <SPI.h>
#include <LittleFS.h>
#include <esp_task_wdt.h>

namespace {
  // ---- кольцевой буфер ----
  Record* ring = nullptr;
  size_t  ringCap = 0, ringHead = 0, ringCnt = 0;
  uint32_t lastTs = 0;
  uint32_t recIntervalS = RECORD_INTERVAL_DEF;

  // ---- flash ----
  bool   fsOk = false;
  size_t flashCnt = 0;

  // ---- SD ----
  SPIClass sdSpi(VSPI);
  bool     sdOk = false;
  bool     sdSpiStarted = false;
  File     csv;
  uint32_t csvLastTsOnCard = 0;
  uint32_t lastHealthMs = 0, lastSdTryMs = 0, lastFlushMs = 0;
  uint16_t unflushed = 0;

  size_t capacityFor(uint32_t periodS) {
    size_t n = (size_t)(HISTORY_HOURS * 3600UL / periodS);
    return n + n * HISTORY_MARGIN_PCT / 100 + 30;
  }

  bool allocRing(size_t cap) {
    Record* p = (Record*)malloc(cap * sizeof(Record));
    while (!p && cap > 256) {                 // мало памяти - уменьшаем
      cap = cap * 3 / 4;
      p = (Record*)malloc(cap * sizeof(Record));
    }
    if (!p) return false;
    ring = p; ringCap = cap; ringHead = 0; ringCnt = 0;
    return true;
  }

  void ringPush(const Record& r) {
    if (!ring || ringCap == 0) return;
    if (ringCnt < ringCap) { ring[(ringHead + ringCnt) % ringCap] = r; ringCnt++; }
    else { ring[ringHead] = r; ringHead = (ringHead + 1) % ringCap; }
    lastTs = r.ts;
  }

  bool plausible(const Record& r) {
    return r.ts > TIME_MIN_VALID_EPOCH && r.pressurePa > 30000 && r.pressurePa < 110000;
  }

  // ======================= LittleFS =======================
  void flashInit() {
    fsOk = LittleFS.begin(true);              // true: форматировать при первом запуске
    if (!fsOk) { LOGE("LittleFS mount failed"); return; }
    // восстановление после сбоя питания при compaction
    if (!LittleFS.exists(FLASH_HISTORY_PATH) && LittleFS.exists(FLASH_HISTORY_TMP)) {
      LittleFS.rename(FLASH_HISTORY_TMP, FLASH_HISTORY_PATH);
    } else if (LittleFS.exists(FLASH_HISTORY_TMP)) {
      LittleFS.remove(FLASH_HISTORY_TMP);
    }
    File f = LittleFS.open(FLASH_HISTORY_PATH, FILE_READ);
    flashCnt = f ? f.size() / sizeof(Record) : 0;
    if (f) f.close();
    LOGI("LittleFS: OK, %u records", (unsigned)flashCnt);
  }

  // Переписать файл из ОЗУ (убирает старые записи)
  void flashCompact() {
    if (!fsOk || ringCnt == 0) return;
    File f = LittleFS.open(FLASH_HISTORY_TMP, FILE_WRITE);
    if (!f) return;
    bool ok = true;
    for (size_t i = 0; i < ringCnt && ok; i++) {
      Record r = ring[(ringHead + i) % ringCap];
      ok = f.write((const uint8_t*)&r, sizeof r) == sizeof r;
    }
    f.close();
    if (!ok) { LittleFS.remove(FLASH_HISTORY_TMP); LOGW("Flash compaction failed"); return; }
    LittleFS.remove(FLASH_HISTORY_PATH);
    LittleFS.rename(FLASH_HISTORY_TMP, FLASH_HISTORY_PATH);
    flashCnt = ringCnt;
  }

  bool flashAppend(const Record& r) {
    if (!fsOk) return false;
    File f = LittleFS.open(FLASH_HISTORY_PATH, FILE_APPEND);
    if (!f) { LOGW("Flash open failed"); return false; }
    size_t w = f.write((const uint8_t*)&r, sizeof r);
    f.close();
    if (w != sizeof r) { LOGW("Flash write failed"); return false; }
    flashCnt++;
    if (flashCnt > ringCap * 2) flashCompact();
    return true;
  }

  // Загрузить записи из flash в ОЗУ (только новее minTs)
  void ringLoadFromFlash(uint32_t minTs) {
    if (!fsOk) return;
    File f = LittleFS.open(FLASH_HISTORY_PATH, FILE_READ);
    if (!f) return;
    size_t n = f.size() / sizeof(Record);
    size_t start = n > ringCap ? n - ringCap : 0;
    f.seek(start * sizeof(Record));
    Record r;
    size_t loaded = 0;
    while (f.read((uint8_t*)&r, sizeof r) == sizeof r) {
      if (!plausible(r) || r.ts <= minTs || r.ts <= lastTs) continue;
      ringPush(r);
      loaded++;
    }
    f.close();
    LOGI("History loaded from flash: %u records", (unsigned)loaded);
  }

  // ======================= CSV (SD) =======================
  void formatCsvLine(const Record& r, char* out, size_t n) {
    char d[16], t[16];
    TimeManager::formatDate(r.ts, d, sizeof d);
    TimeManager::formatTime(r.ts, t, sizeof t);
    if (recHumValid(r))
      snprintf(out, n, "%lu,%s,%s,%.2f,%.1f,%.1f\n", (unsigned long)r.ts, d, t,
               recPressureMmHg(r), recTempC(r), recHum(r));
    else
      snprintf(out, n, "%lu,%s,%s,%.2f,%.1f,\n", (unsigned long)r.ts, d, t,
               recPressureMmHg(r), recTempC(r));
  }

  // Разбор строки CSV; false если строка повреждена или это заголовок
  bool parseCsvLine(const char* line, Record& r) {
    if (line[0] < '0' || line[0] > '9') return false;
    int commas = 0;
    for (const char* p = line; *p; p++) if (*p == ',') commas++;
    if (commas < 5) return false;
    char* end;
    unsigned long ts = strtoul(line, &end, 10);
    if (*end != ',') return false;
    const char* p = end + 1;
    p = strchr(p, ','); if (!p) return false;           // пропускаем date
    p = strchr(p + 1, ','); if (!p) return false;       // пропускаем time
    p++;
    double mm = strtod(p, &end);
    if (*end != ',') return false;
    p = end + 1;
    double tc = strtod(p, &end);
    if (*end != ',') return false;
    p = end + 1;
    r.ts = (uint32_t)ts;
    r.pressurePa = (int32_t)lround(mm / 0.00750061683);
    r.tempC100 = (int16_t)lround(tc * 100.0);
    if (*p >= '0' && *p <= '9') r.humRH100 = (uint16_t)lround(atof(p) * 100.0);
    else r.humRH100 = HUM_INVALID;
    return plausible(r);
  }

  // Чтение строки без блокировок; false в конце файла
  bool readLine(File& f, char* buf, size_t n) {
    size_t i = 0;
    int c;
    bool any = false;
    while ((c = f.read()) >= 0) {
      any = true;
      if (c == '\n') break;
      if (c != '\r' && i < n - 1) buf[i++] = (char)c;
    }
    buf[i] = 0;
    return any;
  }

  // Если последняя строка оборвана (потеря питания) - закрыть переводом строки
  void csvRepairTail() {
    File f = SD.open(SD_CSV_PATH, FILE_READ);
    if (!f) return;
    size_t sz = f.size();
    bool needNl = false;
    if (sz > 0) { f.seek(sz - 1); needNl = (f.read() != '\n'); }
    f.close();
    if (needNl) {
      File a = SD.open(SD_CSV_PATH, FILE_APPEND);
      if (a) { a.write('\n'); a.close(); LOGW("CSV tail repaired"); }
    }
  }

  uint32_t csvReadLastTs() {
    File f = SD.open(SD_CSV_PATH, FILE_READ);
    if (!f) return 0;
    size_t sz = f.size();
    if (sz == 0) { f.close(); return 0; }
    size_t from = sz > 300 ? sz - 300 : 0;
    f.seek(from);
    char line[96];
    uint32_t last = 0;
    if (from > 0) readLine(f, line, sizeof line);          // отбрасываем обрезанную строку
    Record r;
    while (readLine(f, line, sizeof line)) if (parseCsvLine(line, r)) last = r.ts;
    f.close();
    return last;
  }

  // Загрузка хвоста CSV в кольцевой буфер
  void ringLoadFromCsv() {
    File f = SD.open(SD_CSV_PATH, FILE_READ);
    if (!f) return;
    size_t sz = f.size();
    size_t tail = ringCap * 80UL + 4096;
    size_t from = sz > tail ? sz - tail : 0;
    f.seek(from);
    char line[96];
    if (from > 0) readLine(f, line, sizeof line);
    Record r;
    size_t loaded = 0, guard = 0;
    while (readLine(f, line, sizeof line)) {
      if (parseCsvLine(line, r) && r.ts > lastTs) { ringPush(r); loaded++; }
      if ((++guard & 0x3FF) == 0) esp_task_wdt_reset();
    }
    f.close();
    LOGI("History loaded from SD: %u records", (unsigned)loaded);
  }

  bool csvAppend(const Record& r) {
    if (!csv) return false;
    char line[96];
    formatCsvLine(r, line, sizeof line);
    size_t len = strlen(line);
    if (csv.write((const uint8_t*)line, len) != len) return false;
    unflushed++;
    if (unflushed >= SD_FLUSH_EVERY_N) { csv.flush(); unflushed = 0; lastFlushMs = millis(); }
    return true;
  }

  void sdGoOffline(const char* why) {
    if (!sdOk) return;
    LOGW("SD card offline (%s)", why);
    if (csv) csv.close();
    SD.end();
    sdOk = false;
    unflushed = 0;
    lastSdTryMs = millis();
  }

  // Монтирование карты, подготовка каталога и файла. Заполняет csvLastTsOnCard.
  bool sdMount() {
    if (!sdSpiStarted) {
      sdSpi.begin(PIN_SD_SCK, PIN_SD_MISO, PIN_SD_MOSI, PIN_SD_CS);
      sdSpiStarted = true;
    }
    if (!SD.begin(PIN_SD_CS, sdSpi, SD_SPI_HZ) || SD.cardType() == CARD_NONE) {
      SD.end();
      return false;
    }
    if (!SD.exists(SD_CSV_DIR) && !SD.mkdir(SD_CSV_DIR)) { LOGE("SD: mkdir failed"); SD.end(); return false; }
    csvRepairTail();
    csvLastTsOnCard = csvReadLastTs();
    return true;
  }

  // Открыть CSV на дозапись (после чтения!)
  bool sdOpenCsv() {
    csv = SD.open(SD_CSV_PATH, FILE_APPEND);
    if (!csv) { LOGE("SD: cannot open CSV"); SD.end(); return false; }
    if (csv.size() == 0) { csv.println(SD_CSV_HEADER); csv.flush(); }
    sdOk = true;
    unflushed = 0;
    lastFlushMs = lastHealthMs = millis();
    return true;
  }

  // Перенос записей из flash на SD без дублей (только ts > последней записи на карте)
  void syncFlashToSd() {
    if (!fsOk || !sdOk || !LittleFS.exists(FLASH_HISTORY_PATH)) return;
    File f = LittleFS.open(FLASH_HISTORY_PATH, FILE_READ);
    if (!f) return;
    Record r;
    size_t moved = 0, skipped = 0;
    bool ok = true;
    while (f.read((uint8_t*)&r, sizeof r) == sizeof r) {
      if (!plausible(r)) continue;
      if (r.ts <= csvLastTsOnCard) { skipped++; continue; }
      if (!csvAppend(r)) { ok = false; break; }
      csvLastTsOnCard = r.ts;
      moved++;
      if ((moved & 0x1FF) == 0) esp_task_wdt_reset();
    }
    f.close();
    if (!ok) { sdGoOffline("write error during sync"); return; }
    csv.flush();
    unflushed = 0;
    LittleFS.remove(FLASH_HISTORY_PATH);
    flashCnt = 0;
    LOGI("Flash -> SD sync done: moved %u, skipped %u", (unsigned)moved, (unsigned)skipped);
  }
}

namespace StorageManager {

void begin(uint32_t recordIntervalS) {
  recIntervalS = recordIntervalS;
  if (!allocRing(capacityFor(recIntervalS))) LOGE("Cannot allocate history buffer!");
  LOGI("History buffer: %u records (%u KB)", (unsigned)ringCap, (unsigned)(ringCap * sizeof(Record) / 1024));

  LOGI("Initializing SD...");
  flashInit();
  if (sdMount()) {
    LOGI("SD: OK");
    ringLoadFromCsv();                       // старые записи с карты
    ringLoadFromFlash(csvLastTsOnCard);      // записи, сделанные без карты
    if (sdOpenCsv()) syncFlashToSd();
  } else {
    LOGW("SD card not available");
    ringLoadFromFlash(0);
  }
  lastSdTryMs = millis();
}

void update() {
  uint32_t now = millis();
  if (sdOk) {
    if (now - lastHealthMs >= SD_HEALTH_CHECK_MS) {
      lastHealthMs = now;
      if (!SD.exists(SD_CSV_PATH)) sdGoOffline("card removed");
    }
    if (sdOk && unflushed > 0 && now - lastFlushMs >= SD_FLUSH_MAX_MS) {
      csv.flush(); unflushed = 0; lastFlushMs = now;
    }
  } else if (now - lastSdTryMs >= SD_RETRY_MS) {
    lastSdTryMs = now;
    if (sdMount() && sdOpenCsv()) {
      LOGI("SD card detected");
      syncFlashToSd();
    }
  }
}

bool add(const Record& r) {
  if (!ring || r.ts <= lastTs) return false;
  ringPush(r);
  if (sdOk) {
    if (csvAppend(r)) { csvLastTsOnCard = r.ts; return true; }
    sdGoOffline("write error");
  }
  flashAppend(r);
  return true;
}

void setRecordInterval(uint32_t seconds) {
  if (seconds == recIntervalS) return;
  size_t newCap = capacityFor(seconds);
  Record* old = ring;
  size_t oldCap = ringCap, oldHead = ringHead, oldCnt = ringCnt;
  if (!allocRing(newCap)) { ring = old; ringCap = oldCap; ringHead = oldHead; ringCnt = oldCnt; return; }
  recIntervalS = seconds;
  size_t keep = oldCnt > ringCap ? ringCap : oldCnt;
  for (size_t i = oldCnt - keep; i < oldCnt; i++) ring[ringCnt++] = old[(oldHead + i) % oldCap];
  free(old);
}

size_t   count()         { return ringCnt; }
size_t   capacity()      { return ringCap; }
uint32_t lastTimestamp() { return lastTs; }
bool get(size_t i, Record& out) {
  if (i >= ringCnt) return false;
  out = ring[(ringHead + i) % ringCap];
  return true;
}

bool        sdOnline()    { return sdOk; }
const char* backend()     { return sdOk ? "sd" : "flash"; }
uint64_t    sdCardBytes() { return sdOk ? SD.cardSize() : 0; }
uint32_t    csvBytes()    { return (sdOk && csv) ? (uint32_t)csv.size() : 0; }
bool        flashOk()     { return fsOk; }
size_t      flashRecords(){ return flashCnt; }

}  // namespace StorageManager
