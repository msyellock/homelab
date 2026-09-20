// ESP32 "fleet fighters" gadget: five original anime-style fighters, one per machine.
// Health = pose/aura, tap = special move. Data: http://192.168.1.162:8090/status.json (served by ubuntu, LAN only).
// Wi-Fi credentials are NOT in this file: they live in NVS ("gadget" namespace), provisioned over USB serial:  WIFI ssid|password
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include <TFT_eSPI.h>
#include "esp_partition.h"
#include "esp_spi_flash.h"

static const char* STATUS_URL = "http://192.168.1.162:8090/status.json";
enum { NF = 5 };
static const char* ANIMAL[NF] = {"owl", "ox", "fox", "meerkat", "hummingbird"};
static const char* TITLE[NF]  = {"OWL", "OX", "FOX", "MEERKAT", "HUMMINGBIRD"};
static const char* MOVE[NF]   = {"NIGHT-SIGHT BEAM", "STAMPEDE STRIKE", "FOX-FIRE BARRAGE", "SENTRY PULSE", "SONIC FLURRY"};
enum State { S_OK, S_BUSY, S_HOT, S_WARN, S_OFF, S_NONE };
static const char* SNAME[] = {"OK", "BUSY", "HOT", "WARNING", "OFFLINE", "NO DATA"};

// sprite blob layout (see build_assets.py): idle x5 (200x240), knocked-out x5 (200x240), small x5 (72x96); RGB565 big-endian, key 0xF81F
static const int CW = 200, CH = 240, SW = 72, SH = 96;
static const uint16_t KEYSW = 0x1FF8;            // 0xF81F byte-swapped
static const uint16_t* SPR = nullptr;
static const uint16_t* idleImg(int i)  { return SPR + (size_t)i * CW * CH; }
static const uint16_t* koImg(int i)    { return SPR + (size_t)(NF + i) * CW * CH; }
static const uint16_t* smallImg(int i) { return SPR + (size_t)2 * NF * CW * CH + (size_t)i * SW * SH; }
static const size_t BLOB_BYTES = (size_t)(2 * NF * CW * CH + NF * SW * SH) * 2;

static uint16_t ACOL[NF];                         // per-fighter accent colour (RGB565), set in setup()

// ---------------- data ----------------
struct Host { State st; float temp, load, cpu; int mem, disk; float upH; char name[16]; char alerts[96]; bool valid; };
static Host bufs[2][NF];
static volatile int curBuf = 0;
static volatile bool linkOk = false;
static char lastGen[40] = "";
static volatile uint32_t genChangedMs = 0;
static volatile uint32_t lastFetchMs = 0;
static volatile int fetchOk = 0, fetchFail = 0;

// ---------------- display ----------------
TFT_eSPI tft;
TFT_eSprite big = TFT_eSprite(&tft);              // 200x240 character canvas
TFT_eSprite cell = TFT_eSprite(&tft);             // 80x122 team-view cell
static uint16_t* bigBuf = nullptr;
static uint16_t* cellBuf = nullptr;

// ---------------- touch (bit-banged XPT2046; calibration fitted 2026-09-20) ----------------
static const int T_CLK = 25, T_MOSI = 32, T_MISO = 39, T_CS = 33, T_IRQ = 36;
static const float CX[3] = {-0.06650f, 0.00468f, 249.74f};
static const float CY[3] = {0.00046f, 0.08766f, -6.43f};
static uint8_t tbyte(uint8_t out) {
  uint8_t in = 0;
  for (int i = 7; i >= 0; i--) {
    digitalWrite(T_MOSI, (out >> i) & 1); digitalWrite(T_CLK, HIGH);
    in = (in << 1) | (digitalRead(T_MISO) ? 1 : 0); digitalWrite(T_CLK, LOW);
  }
  return in;
}
static uint16_t trd(uint8_t cmd) {
  digitalWrite(T_CS, LOW); tbyte(cmd); uint8_t h = tbyte(0), l = tbyte(0); digitalWrite(T_CS, HIGH);
  return (uint16_t)(((h << 8) | l) >> 3);
}
static bool readTouch(int &x, int &y) {
  if (digitalRead(T_IRQ) != 0) return false;
  uint16_t xs[5], ys[5];
  for (int i = 0; i < 5; i++) { xs[i] = trd(0xD0); ys[i] = trd(0x90); }
  for (int i = 0; i < 4; i++) for (int j = i + 1; j < 5; j++) { if (xs[j] < xs[i]) { uint16_t t = xs[i]; xs[i] = xs[j]; xs[j] = t; } if (ys[j] < ys[i]) { uint16_t t = ys[i]; ys[i] = ys[j]; ys[j] = t; } }
  if (digitalRead(T_IRQ) != 0) return false;
  x = (int)(CX[0] * xs[2] + CX[1] * ys[2] + CX[2]); y = (int)(CY[0] * xs[2] + CY[1] * ys[2] + CY[2]);
  x = constrain(x, 0, 239); y = constrain(y, 0, 319);
  return true;
}

// ---------------- helpers ----------------
static uint16_t rgb(int r, int g, int b) { return tft.color565(r, g, b); }
static uint16_t blend(uint16_t a, uint16_t b, int k /*0..255 = weight of b*/) {
  int ar = (a >> 11) & 31, ag = (a >> 5) & 63, ab = a & 31, br = (b >> 11) & 31, bg = (b >> 5) & 63, bb = b & 31;
  return (uint16_t)((((ar * (255 - k) + br * k) / 255) << 11) | (((ag * (255 - k) + bg * k) / 255) << 5) | ((ab * (255 - k) + bb * k) / 255));
}
static uint16_t stateColor(State s) {
  switch (s) { case S_OK: return rgb(60, 220, 90); case S_BUSY: return rgb(60, 200, 255); case S_HOT: return rgb(255, 70, 40);
               case S_WARN: return rgb(255, 210, 40); case S_OFF: return rgb(110, 110, 120); default: return rgb(80, 80, 120); }
}
static inline uint16_t tintPx(uint16_t w, int tint) {
  if (!tint) return w;
  uint16_t v = (w >> 8) | (w << 8);
  int r = (v >> 11) & 31, g = (v >> 5) & 63, b = v & 31;
  switch (tint) {
    case 1: r = min(31, r + (31 - r) / 3 + 3); g = g * 3 / 4; b = b * 3 / 4; break;      // hot: push to red
    case 2: r = r * 7 / 8; g = g * 7 / 8; b = b * 7 / 8; break;                            // warning: slightly darker
    case 3: r = min(31, r + 2); g = min(63, g + 4); b = min(31, b + 2); break;             // busy: brighter
    case 4: r /= 2; g /= 2; b /= 2; break;                                                 // no data: dim
    case 5: r = 31; g = 63; b = 63; break;                                                 // flash: white silhouette
  }
  v = (uint16_t)((r << 11) | (g << 5) | b);
  return (v >> 8) | (v << 8);
}
// draw a sprite into a 16-bit (byte-swapped) buffer with vertical scale about its bottom edge
static void blit(uint16_t* dst, int dw, int dh, int ox, int oy, const uint16_t* src, int sw, int sh, float sy, int dx, int dyoff, int tint) {
  int bottom = oy + sh - 1 + dyoff;
  for (int Y = 0; Y < dh; Y++) {
    int srow = (sh - 1) - (int)((bottom - Y) / sy);
    if (srow < 0 || srow > sh - 1 || (bottom - Y) < -1) continue;
    const uint16_t* s = src + (size_t)srow * sw; uint16_t* d = dst + (size_t)Y * dw;
    for (int sx = 0; sx < sw; sx++) {
      uint16_t v = s[sx]; if (v == KEYSW) continue;
      int X = ox + dx + sx; if (X < 0 || X >= dw) continue;
      d[X] = tintPx(v, tint);
    }
  }
}

// ---------------- data fetching (runs on core 0) ----------------
static Preferences prefs;
static String wifiSsid, wifiPass;
static State parseState(const char* s) {
  if (!s) return S_NONE;
  if (!strcmp(s, "ok")) return S_OK; if (!strcmp(s, "busy")) return S_BUSY; if (!strcmp(s, "hot")) return S_HOT;
  if (!strcmp(s, "warn")) return S_WARN; if (!strcmp(s, "offline")) return S_OFF; return S_NONE;
}
static void fetchTask(void*) {
  WiFi.setHostname("esp32-gadget");
  for (;;) {
    if (wifiSsid.length() == 0) { delay(1000); continue; }
    if (WiFi.status() != WL_CONNECTED) {
      linkOk = false; WiFi.mode(WIFI_STA); WiFi.setSleep(false); WiFi.begin(wifiSsid.c_str(), wifiPass.c_str());
      uint32_t t0 = millis(); while (WiFi.status() != WL_CONNECTED && millis() - t0 < 20000) delay(250);
      if (WiFi.status() != WL_CONNECTED) { Serial.println("wifi: not connected, retrying"); delay(5000); continue; }
      Serial.printf("wifi: connected %s rssi %d\n", WiFi.localIP().toString().c_str(), WiFi.RSSI());
    }
    HTTPClient http; http.setTimeout(4000); http.setConnectTimeout(3000);
    if (http.begin(STATUS_URL)) {
      int code = http.GET();
      if (code == 200) {
        String body = http.getString();
        JsonDocument doc;
        if (!deserializeJson(doc, body)) {
          int nb = 1 - curBuf; for (int i = 0; i < NF; i++) { memset(&bufs[nb][i], 0, sizeof(Host)); bufs[nb][i].st = S_NONE; }
          for (JsonObject h : doc["hosts"].as<JsonArray>()) {
            const char* an = h["animal"] | ""; int idx = -1;
            for (int i = 0; i < NF; i++) if (!strcmp(an, ANIMAL[i])) idx = i;
            if (idx < 0) continue;
            Host &H = bufs[nb][idx]; H.valid = true; H.st = parseState(h["state"] | "");
            H.temp = h["temp_c"] | -1.0f; H.load = h["load"] | -1.0f; H.cpu = h["cpu_pct"] | -1.0f;
            H.mem = h["mem_pct"] | -1; H.disk = (int)(h["disk_pct"] | -1.0f); H.upH = h["uptime_h"] | -1.0f;
            strlcpy(H.name, h["name"] | "?", sizeof(H.name));
            String al; for (JsonVariant a : h["alerts"].as<JsonArray>()) { if (al.length()) al += "; "; al += a.as<const char*>(); }
            strlcpy(H.alerts, al.c_str(), sizeof(H.alerts));
          }
          const char* gen = doc["generated"] | "";
          if (strcmp(gen, lastGen)) { strlcpy(lastGen, gen, sizeof(lastGen)); genChangedMs = millis(); }
          curBuf = nb; linkOk = true; lastFetchMs = millis(); fetchOk++;
        } else { fetchFail++; Serial.println("fetch: bad json"); }
      } else { fetchFail++; linkOk = false; Serial.printf("fetch: http %d\n", code); }
      http.end();
    } else { fetchFail++; }
    delay(20000);
  }
}

// ---------------- rendering ----------------
static State effState(int i) { return bufs[curBuf][i].valid ? bufs[curBuf][i].st : S_NONE; }
static bool staleData() { return genChangedMs == 0 || (millis() - genChangedMs) > 150000UL; }

static void aura(TFT_eSprite &s, int cx, int cy, uint16_t col, int strength /*0..255*/, float pulse) {
  uint16_t bg = 0x0000;
  for (int k = 5; k >= 1; k--) {
    int rx = (int)((30 + k * 14) * (0.92f + 0.08f * pulse)), ry = (int)((40 + k * 16) * (0.92f + 0.08f * pulse));
    s.fillEllipse(cx, cy, rx, ry, blend(bg, col, strength * (6 - k) / 6 / 2));
  }
}
static void drawCharacter(int i, State st, uint32_t now, float special /* <0 none, else seconds into special move */) {
  float t = now / 1000.0f; int dx = 0, dy = 0, tint = 0; float sy = 1.0f; const uint16_t* img = idleImg(i);
  uint16_t ac = ACOL[i];
  big.fillSprite(blend(0x0000, ac, 22));
  switch (st) {
    case S_OK:   dy = (int)(sinf(t * 2.2f) * 2); sy = 1.0f + 0.012f * sinf(t * 2.2f); break;
    case S_BUSY: dy = (int)(sinf(t * 6.0f) * 3); sy = 1.0f + 0.02f * sinf(t * 6.0f); tint = 3; aura(big, 100, 130, rgb(60, 200, 255), 200, 0.5f + 0.5f * sinf(t * 7)); break;
    case S_HOT:  dx = (int)(random(-2, 3)); dy = (int)(sinf(t * 9.0f) * 2); tint = 1; aura(big, 100, 130, rgb(255, 70, 30), 230, 0.5f + 0.5f * sinf(t * 11)); break;
    case S_WARN: dx = (int)(sinf(t * 1.6f) * 3); sy = 0.97f; tint = 2; aura(big, 100, 130, rgb(255, 210, 40), 90, 0.5f + 0.5f * sinf(t * 3)); break;
    case S_OFF:  img = koImg(i); break;
    default:     tint = 4; dy = (int)(sinf(t * 1.5f) * 1); break;
  }
  if (special >= 0) {
    float p = special; uint16_t c1 = ACOL[i], c2 = rgb(255, 255, 255);
    // energy burst: expanding rings, radial lines, shake, flash
    for (int r = 0; r < 3; r++) { float rr = (p * 150.0f) - r * 26.0f; if (rr > 4) big.drawCircle(100, 130, (int)rr, blend(c1, c2, r * 70)); if (rr > 6) big.drawCircle(100, 130, (int)rr - 1, c1); }
    for (int k = 0; k < 18; k++) {
      float a = k * 0.3491f + p * 0.9f, r0 = 20 + p * 60, r1 = 30 + p * 170;
      big.drawLine(100 + (int)(cosf(a) * r0), 130 + (int)(sinf(a) * r0), 100 + (int)(cosf(a) * r1), 130 + (int)(sinf(a) * r1), (k & 1) ? c1 : c2);
    }
    dx = random(-4, 5); dy = random(-3, 4); sy = 1.0f + 0.05f * sinf(p * 20); tint = (p < 0.12f) ? 5 : 3; img = idleImg(i);
  }
  blit(bigBuf, CW, CH, 0, 0, img, CW, CH, sy, dx, dy, tint);
  if (st == S_HOT && special < 0) for (int k = 0; k < 4; k++) big.fillCircle(60 + k * 25 + (int)(sinf(t * 3 + k) * 5), 40 - ((int)(t * 40 + k * 17) % 40), 3, rgb(230, 230, 230));
  if (st == S_WARN && special < 0) { big.fillTriangle(170, 20, 190, 20, 180, 4, rgb(255, 210, 40)); big.drawLine(180, 8, 180, 14, 0); }
  if (st == S_OFF && special < 0) { big.setTextColor(rgb(200, 200, 230)); big.drawString("Z z z", 120 + (int)(sinf(t * 2) * 6), 60 - ((int)(t * 12) % 20), 4); }
}

static void drawHeader(const char* left, const char* right, uint16_t col) {
  tft.fillRect(0, 0, 240, 28, rgb(20, 20, 40));
  tft.setTextColor(col); tft.setTextDatum(ML_DATUM); tft.drawString(left, 6, 14, 4);
  tft.setTextColor(rgb(160, 160, 190)); tft.setTextDatum(MR_DATUM); tft.drawString(right, 234, 14, 2);
}

static int cellX(int i) { return (i < 3) ? i * 80 : 40 + (i - 3) * 80; }
static int cellY(int i) { return (i < 3) ? 28 : 150; }
static void shortName(const char* n, char* out) { strlcpy(out, n, 11); }

static void drawTeam(uint32_t now) {
  float t = now / 1000.0f; bool stale = staleData();
  for (int i = 0; i < NF; i++) {
    Host &H = bufs[curBuf][i]; State st = effState(i); if (stale && st != S_NONE) st = S_NONE;
    cell.fillSprite(rgb(14, 14, 28));
    int dy = 0, tint = 0;
    switch (st) { case S_OK: dy = (int)(sinf(t * 2.2f + i) * 2); break; case S_BUSY: dy = (int)(sinf(t * 6 + i) * 3); tint = 3; break;
      case S_HOT: dy = (int)(sinf(t * 9 + i) * 2); tint = 1; break; case S_WARN: tint = 2; break; case S_OFF: tint = 4; break; default: tint = 4; }
    blit(cellBuf, 80, 122, 4, 2, smallImg(i), SW, SH, 1.0f, 0, dy, tint);
    uint16_t sc = stateColor(st);
    cell.fillRect(4, 100, 72, 3, sc);
    char nm[12]; shortName(H.valid ? H.name : ANIMAL[i], nm);
    cell.setTextColor(rgb(230, 230, 240)); cell.setTextDatum(TC_DATUM); cell.drawString(nm, 40, 105, 1);
    char line[24]; if (H.valid && H.temp >= 0) snprintf(line, sizeof(line), "%s %.0fC", SNAME[st], H.temp); else snprintf(line, sizeof(line), "%s", SNAME[st]);
    cell.setTextColor(sc); cell.drawString(line, 40, 114, 1);
    cell.pushSprite(cellX(i), cellY(i));
  }
}
static void drawTeamStatic() {
  tft.fillScreen(rgb(14, 14, 28));
}
static uint32_t lastAlertDraw = 0;
static void drawTeamFooter(uint32_t now, bool force) {
  if (!force && now - lastAlertDraw < 1000) return; lastAlertDraw = now;
  tft.fillRect(0, 272, 240, 48, rgb(20, 20, 40));
  bool stale = staleData(); char ago[32];
  uint32_t secs = genChangedMs ? (now - genChangedMs) / 1000 : 0;
  if (stale) snprintf(ago, sizeof(ago), "COLLECTOR OFFLINE %lus", (unsigned long)secs); else snprintf(ago, sizeof(ago), "data %lus old", (unsigned long)secs);
  drawHeader("FLEET", linkOk ? ago : "no link", stale || !linkOk ? rgb(255, 120, 60) : rgb(120, 230, 160));
  // alerts: first three hosts that have any
  int shown = 0; tft.setTextDatum(TL_DATUM);
  for (int i = 0; i < NF && shown < 3; i++) { Host &H = bufs[curBuf][i]; if (H.valid && H.alerts[0]) { char l[48]; snprintf(l, sizeof(l), "%s: %s", H.name, H.alerts); tft.setTextColor(rgb(255, 210, 60)); tft.drawString(l, 4, 274 + shown * 14, 1); shown++; } }
  if (!shown) { tft.setTextColor(stale ? rgb(255, 150, 80) : rgb(90, 230, 130)); tft.drawString(stale ? "Waiting for fresh data..." : "All systems OK", 4, 276, 2); }
  tft.setTextColor(rgb(120, 120, 150)); tft.setTextDatum(BR_DATUM); tft.drawString("tap a fighter", 236, 318, 1);
}

// ---------------- state machine ----------------
enum Mode { M_DEMO, M_TEAM, M_DETAIL };
static Mode mode = M_DEMO;
static int selected = 0;
static uint32_t modeStart = 0, specialStart = 0, lastTouchMs = 0, lastFrame = 0, lastDetailHdr = 0;
static bool specialActive = false; static int demoIdx = 0;
static uint32_t frames = 0, fpsMark = 0; static float fps = 0;

static void startSpecial(int i) { selected = i; specialActive = true; specialStart = millis(); Serial.printf("special: %s\n", MOVE[i]); }
static void enterTeam() { mode = M_TEAM; modeStart = millis(); drawTeamStatic(); drawTeamFooter(millis(), true); Serial.println("mode: team"); }
static void enterDetail(int i, bool doSpecial) {
  mode = M_DETAIL; selected = i; modeStart = millis(); tft.fillScreen(rgb(14, 14, 28));
  Host &H = bufs[curBuf][i]; char t[40]; snprintf(t, sizeof(t), "< %s", TITLE[i]); drawHeader(t, H.valid ? H.name : "", ACOL[i]);
  if (doSpecial) startSpecial(i); Serial.printf("mode: detail %d\n", i);
}
static void drawDetailInfo(int i) {
  Host &H = bufs[curBuf][i]; State st = effState(i); uint16_t sc = stateColor(st);
  tft.fillRect(0, 268, 240, 52, rgb(20, 20, 40));
  tft.setTextDatum(TL_DATUM); tft.setTextColor(sc); tft.drawString(SNAME[st], 6, 271, 4);
  char l1[64]; if (H.valid) snprintf(l1, sizeof(l1), "%s%.0fC  mem %d%%  disk %d%%  up %.0fh", H.temp >= 0 ? "" : "", H.temp >= 0 ? H.temp : 0.0f, H.mem, H.disk, H.upH); else snprintf(l1, sizeof(l1), "no data yet");
  tft.setTextColor(rgb(210, 210, 230)); tft.drawString(l1, 6, 297, 1);
  tft.setTextColor(rgb(255, 210, 60)); tft.drawString(H.valid && H.alerts[0] ? H.alerts : (specialActive ? MOVE[i] : "tap her for a special move"), 6, 308, 1);
}

static void handleTap(int x, int y) {
  Serial.printf("tap %d,%d\n", x, y);
  if (mode == M_DEMO) { demoIdx = NF; return; }
  if (mode == M_TEAM) {
    for (int i = 0; i < NF; i++) if (x >= cellX(i) && x < cellX(i) + 80 && y >= cellY(i) && y < cellY(i) + 122) { enterDetail(i, true); return; }
  } else if (mode == M_DETAIL) {
    if (y < 30) { enterTeam(); return; }
    if (!specialActive) startSpecial(selected);
  }
}

static void serialCmd(String s) {
  s.trim(); if (!s.length()) return;
  if (s.startsWith("WIFI ")) {
    int bar = s.indexOf('|'); if (bar > 5) { prefs.putString("ssid", s.substring(5, bar)); prefs.putString("pass", s.substring(bar + 1)); Serial.println("wifi credentials saved; restarting"); delay(300); ESP.restart(); }
  } else if (s.startsWith("SPECIAL ")) { int i = constrain(s.substring(8).toInt(), 0, NF - 1); enterDetail(i, true); }
  else if (s.startsWith("DETAIL ")) { int i = constrain(s.substring(7).toInt(), 0, NF - 1); enterDetail(i, false); }
  else if (s == "TEAM") enterTeam();
  else if (s.startsWith("TAP ")) { int sp = s.indexOf(' ', 4); handleTap(s.substring(4, sp).toInt(), s.substring(sp + 1).toInt()); }
  else if (s.startsWith("SHOT ")) {   // debug: render one character frame and dump the 200x240 canvas as hex
    int i = 0, st = 0; float pr = -1; sscanf(s.c_str() + 5, "%d %d %f", &i, &st, &pr);
    drawCharacter(constrain(i, 0, NF - 1), (State)constrain(st, 0, 5), millis(), pr);
    Serial.printf("SHOT_BEGIN %d %d\n", CW, CH); static char row[CW * 4 + 2];
    for (int y = 0; y < CH; y++) { for (int x = 0; x < CW; x++) { uint16_t v = bigBuf[y * CW + x]; static const char* H = "0123456789ABCDEF"; row[x * 4] = H[(v >> 12) & 15]; row[x * 4 + 1] = H[(v >> 8) & 15]; row[x * 4 + 2] = H[(v >> 4) & 15]; row[x * 4 + 3] = H[v & 15]; } row[CW * 4] = '\n'; Serial.write((uint8_t*)row, CW * 4 + 1); }
    Serial.println("SHOT_END");
  }
  else if (s == "SCREEN") {           // debug: read back the physical screen and dump it (RGB565 hex, 240x320)
    Serial.println("SCREEN_BEGIN 240 320"); static uint16_t strip[240 * 8]; static char row[240 * 4 + 2];
    for (int y = 0; y < 320; y += 8) { tft.readRect(0, y, 240, 8, strip);
      for (int r = 0; r < 8; r++) { for (int x = 0; x < 240; x++) { uint16_t v = strip[r * 240 + x]; static const char* H = "0123456789ABCDEF"; row[x * 4] = H[(v >> 12) & 15]; row[x * 4 + 1] = H[(v >> 8) & 15]; row[x * 4 + 2] = H[(v >> 4) & 15]; row[x * 4 + 3] = H[v & 15]; } row[960] = '\n'; Serial.write((uint8_t*)row, 961); } }
    Serial.println("SCREEN_END");
  }
  else if (s == "INFO") {
    Serial.printf("fps %.1f heap %u minheap %u link %d ok %d fail %d stale %d mode %d\n", fps, ESP.getFreeHeap(), ESP.getMinFreeHeap(), (int)linkOk, fetchOk, fetchFail, (int)staleData(), (int)mode);
    for (int i = 0; i < NF; i++) { Host &H = bufs[curBuf][i]; Serial.printf("  %s: %s valid %d temp %.1f mem %d disk %d alerts '%s'\n", ANIMAL[i], SNAME[effState(i)], (int)H.valid, H.temp, H.mem, H.disk, H.alerts); }
  }
}

void setup() {
  Serial.begin(115200); delay(200); Serial.println("\nfleet fighters: boot");
  pinMode(T_CLK, OUTPUT); pinMode(T_MOSI, OUTPUT); pinMode(T_CS, OUTPUT); digitalWrite(T_CS, HIGH); digitalWrite(T_CLK, LOW); pinMode(T_MISO, INPUT); pinMode(T_IRQ, INPUT);
  tft.init(); tft.setRotation(0); tft.fillScreen(TFT_BLACK); pinMode(21, OUTPUT); digitalWrite(21, HIGH);
  ACOL[0] = rgb(255, 210, 60); ACOL[1] = rgb(255, 110, 50); ACOL[2] = rgb(255, 150, 30); ACOL[3] = rgb(150, 235, 60); ACOL[4] = rgb(40, 230, 210);
  tft.setTextColor(TFT_WHITE); tft.setTextDatum(MC_DATUM); tft.drawString("starting...", 120, 160, 4);
  // map the sprite partition into memory
  const esp_partition_t* part = esp_partition_find_first(ESP_PARTITION_TYPE_DATA, (esp_partition_subtype_t)0x40, "sprites");
  if (part) { const void* ptr; spi_flash_mmap_handle_t h; if (esp_partition_mmap(part, 0, BLOB_BYTES, SPI_FLASH_MMAP_DATA, &ptr, &h) == ESP_OK) SPR = (const uint16_t*)ptr; }
  Serial.printf("sprites: %s (partition %s, %u bytes needed)\n", SPR ? "mapped" : "MISSING", part ? "found" : "missing", (unsigned)BLOB_BYTES);
  big.setColorDepth(16); bigBuf = (uint16_t*)big.createSprite(CW, CH);
  cell.setColorDepth(16); cellBuf = (uint16_t*)cell.createSprite(80, 122);
  Serial.printf("canvas: big %s cell %s heap %u\n", bigBuf ? "ok" : "FAILED", cellBuf ? "ok" : "FAILED", ESP.getFreeHeap());
  if (!SPR || !bigBuf || !cellBuf) { tft.fillScreen(TFT_BLACK); tft.setTextColor(TFT_RED); tft.drawString("sprite/memory error", 120, 150, 4); tft.setTextColor(TFT_WHITE); tft.drawString("see serial log", 120, 190, 2); for (;;) { delay(1000); } }
  prefs.begin("gadget", false); wifiSsid = prefs.getString("ssid", ""); wifiPass = prefs.getString("pass", "");
  for (int i = 0; i < NF; i++) { bufs[0][i].st = bufs[1][i].st = S_NONE; }
  if (wifiSsid.length() == 0) Serial.println("NEED WIFI: send  WIFI ssid|password  over USB serial");
  xTaskCreatePinnedToCore(fetchTask, "fetch", 10240, NULL, 1, NULL, 0);
  mode = M_DEMO; demoIdx = 0; modeStart = millis(); tft.fillScreen(rgb(14, 14, 28)); drawHeader("< DEMO", "special moves", rgb(255, 255, 255)); startSpecial(0); selected = 0;
  fpsMark = millis(); lastFrame = 0;
}

void loop() {
  uint32_t now = millis();
  static String line; while (Serial.available()) { char c = Serial.read(); if (c == '\n') { serialCmd(line); line = ""; } else if (c != '\r') line += c; }
  if (now - lastFrame < 38) { delay(2); return; } lastFrame = now;
  // touch (edge detect + debounce)
  static bool wasDown = false; int tx, ty; bool down = readTouch(tx, ty);
  if (down && !wasDown && now - lastTouchMs > 250) { lastTouchMs = now; handleTap(tx, ty); }
  wasDown = down;
  if (mode == M_DEMO) {
    if (demoIdx >= NF) { enterTeam(); return; }
    float p = (now - specialStart) / 1000.0f;
    if (p > 2.6f) { demoIdx++; if (demoIdx >= NF) { enterTeam(); return; } tft.fillRect(0, 268, 240, 52, rgb(20, 20, 40)); startSpecial(demoIdx); p = 0; }
    int i = demoIdx; char t[32]; snprintf(t, sizeof(t), "< %s", TITLE[i]); if (now - lastDetailHdr > 700) { drawHeader(t, "demo", ACOL[i]); lastDetailHdr = now; }
    drawCharacter(i, S_OK, now, p); big.pushSprite(20, 30);
    tft.setTextDatum(MC_DATUM); tft.setTextColor(ACOL[i]); tft.drawString(MOVE[i], 120, 290, 4);
  } else if (mode == M_TEAM) {
    drawTeam(now); drawTeamFooter(now, false);
    if (now - lastTouchMs > 120000UL && now - modeStart > 120000UL) { /* attract: nothing extra */ }
  } else if (mode == M_DETAIL) {
    float p = specialActive ? (now - specialStart) / 1000.0f : -1.0f;
    if (specialActive && p > 2.6f) { specialActive = false; p = -1; drawDetailInfo(selected); }
    drawCharacter(selected, effState(selected), now, p); big.pushSprite(20, 30);
    if (specialActive) { tft.setTextDatum(MC_DATUM); tft.setTextColor(ACOL[selected]); tft.fillRect(0, 268, 240, 52, rgb(20, 20, 40)); tft.drawString(MOVE[selected], 120, 294, 4); }
    else if (now - lastDetailHdr > 1000) { lastDetailHdr = now; drawDetailInfo(selected); char t[40]; snprintf(t, sizeof(t), "< %s", TITLE[selected]); drawHeader(t, bufs[curBuf][selected].valid ? bufs[curBuf][selected].name : "", ACOL[selected]); }
    if (now - lastTouchMs > 45000UL && now - modeStart > 45000UL) enterTeam();
  }
  frames++; if (now - fpsMark >= 2000) { fps = frames * 1000.0f / (now - fpsMark); frames = 0; fpsMark = now; }
}
