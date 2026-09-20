# ESP32 fleet gadget ("fleet fighters")

A small touch-screen board on the LAN that shows the health of every machine in the lab as an animated
anime-style character. It is a **network gadget, not the official monitor**: nothing in the lab depends on it
(see [ADR 010](../../docs/decisions/010-esp32-fleet-status-gadget.md)).

| Machine | Character (animal motif) |
|---|---|
| `illntentpc` | owl |
| `ubuntu` | ox |
| `novo1` | fox |
| `chromebook` | meerkat |
| Note 10+ | hummingbird |

Health shows as pose and aura: calm stance (ok), blue power-up (busy), red aura and steam (hot), dim yellow
with a warning triangle (warning), knocked out with "Zzz" (offline). Tap a character for her special move;
all five play once at power-up. The characters are original, adult, fully clothed fighters in a 1990s
shonen-battle-anime style with an animal motif each.

## Hardware
A 2.8" 240x320 resistive-touch ESP32 board (ESP32-WROOM-32E, 4 MB flash, no PSRAM, ILI9341 display,
XPT2046 touch, SD slot, speaker header). Pins used: display on SPI1 (SCK 14, MOSI 13, MISO 12, CS 15,
DC 2, backlight 21); touch on separate pins (CLK 25, MOSI 32, MISO 39, CS 33, IRQ 36). Wi-Fi is 2.4 GHz only.

## Data path
```
illntentpc: collector.py (cron, every minute)  --ssh-->  ubuntu:~/status/status.json
ubuntu: status-web.service (user unit, python http.server, port 8090, LAN-only UFW rule)
board:  HTTP GET http://192.168.1.162:8090/status.json every 20 s
```
- `collector/collector.py` is read-only: it reads load, memory, disk, temperature, uptime, reboot flag and a few
  service states from each Linux host over SSH, from Windows through PowerShell, and from the phone through its
  Termux `sshd` and a TCP check of the two `llama-server` ports. It writes `~/sysmon/status.json` and copies it to ubuntu.
- The fleet SSH key has a passphrase and only works through an `ssh-agent`. Cron has no agent, so the collector
  looks for a running agent that holds the key and **skips the run** (leaving the last good file) if there is none.
  The board treats a file that has not changed for 150 s as "collector offline" and dims every character.
- `ubuntu/status-web.service` is a **user** systemd unit (needs `loginctl enable-linger ubuntu`). Firewall rule:
  `sudo ufw allow from 192.168.1.0/24 to any port 8090 proto tcp`. It serves one read-only JSON file.
- The board holds no SSH keys and no lab secrets. Its only secret is the Wi-Fi password, kept in the chip's NVS
  (never in this repo or in the firmware image).

## Build the firmware (no sudo)
```
arduino-cli core install esp32:esp32@2.0.17
arduino-cli lib install TFT_eSPI ArduinoJson
FLAGS="-DUSER_SETUP_LOADED=1 -DILI9341_DRIVER=1 -DTFT_WIDTH=240 -DTFT_HEIGHT=320 -DTFT_MISO=12 -DTFT_MOSI=13 \
 -DTFT_SCLK=14 -DTFT_CS=15 -DTFT_DC=2 -DTFT_RST=-1 -DTFT_BL=21 -DLOAD_GLCD=1 -DLOAD_FONT2=1 -DLOAD_FONT4=1 \
 -DSPI_FREQUENCY=40000000 -DSPI_READ_FREQUENCY=16000000 -DUSE_HSPI_PORT=1"
arduino-cli compile --fqbn esp32:esp32:esp32 --build-property "compiler.cpp.extra_flags=$FLAGS" --output-dir build firmware
```
The sketch folder must be named like the `.ino` (`gadget`), so copy `firmware/` to a folder called `gadget/` first,
or rename it. `partitions.csv` gives a 1.5 MB app slot and a 2.4 MB raw `sprites` data partition (subtype `0x40`).

## Sprites (not in this repo)
`tools/gen_art.py` fetches one image from the free, community-run [AI Horde](https://aihorde.net) (anonymous key,
model "Counterfeit", about 80 s per image when the queue is short) and `tools/build_assets.py` turns five
`art/raw/f_<animal>.webp` files into `sprites.bin` (idle, knocked-out and small versions, RGB565, transparent
key `0xF81F`). The images and `sprites.bin` are **not committed**: AI-generated art has unclear copyright and the
binary is 1 MB. Regenerate them from the prompts below. Prompts describe original characters only; do not name
franchises or artists. Base prompt (one per animal, motif varies):
`1 original anime female warrior character, adult woman, 1990s shonen battle anime style, athletic martial artist,
confident fighting stance, full body, standing, front view, flat cel shading, bold clean outline, plain flat bright
green background` plus a motif (owl: swept-back hair with feather tips, feather armor, wing-shaped shoulder guards;
ox: strong build, short brown hair, small curved horns, heavy gauntlets; fox: spiky orange hair, fox ears and tail,
white-and-orange gi; meerkat: agile scout, tan hair, dark eye patches, sandy outfit, ringed tail; hummingbird:
slender speedster, teal-green hair, small wings). Set `GEN_NEG` to exclude child, nude, revealing and nsfw.

## Flash (from Windows; the serial port is not visible inside WSL)
```
esptool --port COMx erase-flash                      # first time
esptool --port COMx --baud 460800 write-flash 0x1000 bootloader.bin 0x8000 partitions.bin 0x10000 app.bin 0x190000 sprites.bin
esptool --port COMx --baud 460800 write-flash 0x10000 app.bin     # firmware-only update, keeps Wi-Fi settings
```
Provision Wi-Fi over USB serial at 115200: send `WIFI ssid|password`. The board saves it and restarts.
Serial debug commands: `INFO`, `TEAM`, `DETAIL n`, `SPECIAL n`, `TAP x y`, `SHOT i state progress` (dump the
character canvas), `SCREEN` (read the screen back; colours come back scrambled on this panel).

## Verified (2026-09-20) and not verified
Verified over serial: sprites mapped, about 116 KB heap free, about 26 fps, live data with no fetch failures,
correct rendering of every health state and special move (from canvas dumps), display colours and touch
calibration on the real screen. Confirmed by the owner on the physical board: it works. Not covered: touch accuracy
beyond about 6 px at the corners and 9 px at the centre.

## Known limits
- After a WSL restart or Windows reboot the collector stays skipped until the fleet key is added to an agent again.
- The special moves are one generic energy-burst effect in each character's colour; no per-move art and no sound.
- Only idle images exist (knocked-out is a rotated, desaturated copy).
