// web_ui.h - встроенный Web UI (HTML/CSS/JS хранятся в прошивке, внешние ресурсы не нужны)
#pragma once
#include <Arduino.h>

namespace WebUi {
  const char* indexHtml();   // единая страница (SPA), UTF-8
}
