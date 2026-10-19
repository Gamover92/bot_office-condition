# Office climate bot: design

Date: 2026-10-19. Status: approved in brainstorming, waiting for spec review.

## 1. Goal

A Telegram bot shows the climate in the office. The data comes from a Qingping Air Monitor (2 / Lite) through MQTT. All parts run in Docker on one office PC.

Scope of version 1:

- `/climate` summary with a PNG chart and inline buttons.
- Alerts to the chat when a value goes out of the norm and when it is back.
- Morning report on a schedule.
- `/settings` menu for chat admins.

Out of scope: Telegram Mini App. The Mini App needs a public HTTPS address, and the office has no domain. The code structure must let us add it later.

## 2. Constraints

- No ports open to the Internet. The bot uses long polling (outbound connections only).
- Port 1883 (MQTT) is open only in the office LAN, for the sensor.
- No external services except Telegram. Charts are drawn locally.
- All data stays on the PC, in `./data/climate.db` (SQLite).

## 3. Architecture

```
Qingping Air Monitor ──MQTT──▶ mosquitto (1883, LAN)
                                   │
                                   ▼
                     bot (Python 3.13, aiogram 3, aiomqtt)
                       ├─ mqtt: readings → SQLite
                       ├─ handlers: /climate, /settings, callbacks
                       ├─ charts: matplotlib → PNG
                       └─ scheduler: alerts + morning report
                                   │ long polling
                                   ▼
                               Telegram
```

Docker Compose has two services: `mosquitto` (eclipse-mosquitto 2.0) and `bot`.

### Modules (`app/`)

| Module | Task |
|---|---|
| `config.py` | Read `.env` |
| `qingping.py` | Parse Qingping JSON. Rate values: good / fair / bad |
| `store.py` | Readings in SQLite: add (merge partial data), latest, history, delete old rows |
| `chat_settings.py` | Settings and alert state for each chat, in SQLite. Defaults come from `.env` |
| `summary.py` | Caption text for the summary, alert texts |
| `charts.py` | PNG chart for one metric and one period |
| `alerts.py` | Pure logic: from values, limits, state and time → messages and the new state |
| `handlers/climate.py` | `/climate`, keywords, inline buttons of the summary |
| `handlers/settings.py` | `/settings` menu and value input |
| `scheduler.py` | Alert check each minute, morning report |
| `mqtt_listener.py` | Subscribe, parse, save, reconnect |
| `main.py` | Start all parts |

Keep from the WIP draft: `qingping.py`, `store.py`, `config.py`, `mqtt_listener.py`, and their tests. Delete: `web.py`, `auth.py`, `static/`, the `cloudflared` service, and the Mini App settings.

## 4. Data

### MQTT input

- Topic: `qingping/+/up` (configurable).
- Format: Qingping JSON, `{"mac": ..., "type": "12"|"17", "sensorData": [{"timestamp": {"value": ...}, "co2": {"value": ...}, ...}]}`.
- The parser also accepts plain numbers, one `sensorData` object, and a MAC from the topic.
- The bot ignores messages without known metrics.
- Metrics: temperature, humidity, co2, pm25, pm10, tvoc, tvoc_index, noise, pressure, battery.

### SQLite tables

- `readings(mac, ts, data JSON)`, primary key `(mac, ts)`. Rows older than `HISTORY_DAYS` (default 30) are deleted each hour.
- `chat_settings(chat_id, data JSON)`. Only the values that differ from the defaults are stored.
- `alert_state(chat_id, mac, metric, state, sent)`. `state` is the current `ok` or `bad`. `sent` is the state of the last message sent to the chat. If `state` differs from `sent`, a message waits (for example, during quiet hours).
- A chat is registered (a row in `chat_settings`) when someone uses the bot in it. Chats from `ALLOWED_CHAT_IDS` are always registered.
- `report_log(chat_id, date)`. The date of the last morning report.

## 5. User flows

### `/climate`

The bot also replies to the words "климат" and "душно?".

The bot sends one photo with a caption and buttons:

- **Caption:** the overall state, and each metric with 🟢🟡🔴 and its value. Then advice, the time of the newest data, and "⚠️ данные устарели" if the data is older than `STALE_AFTER_MIN`.
- **Buttons:**
  - Metrics: only the metrics that the sensor sends.
  - Period: 6 h / 24 h / 7 d.
  - Sensors: only if there are 2 or more, sorted by MAC.
  - "🔄 Обновить".
- **Default chart:** CO₂, 24 h, for the sensor with the newest data. `scripts/forget-sensor.sh <MAC>` deletes a sensor's data (for example, the test sensor from the README).

A button push edits the same message (photo and caption), so the bot does not send a new message. The callback data holds the sensor, the metric and the period.

The chart shows a line and green / yellow / red norm zones for the metric. The time axis uses `TZ`. If there are fewer than 2 points, the bot sends text without a photo.

### Alerts

The scheduler runs each minute. For each chat with alerts on, for each sensor and each metric with a limit (co2, temperature, humidity, pm25):

| Current state | Condition | Action |
|---|---|---|
| `ok` | Value is outside the limit | State becomes `bad`. Send "🔴 CO₂ 1250 ppm — выше 1200. Проветрите." |
| `bad` | Value is inside the limit by 5 % of the limit or more (hysteresis) | State becomes `ok`. Send "🟢 CO₂ снова в норме: 780 ppm." |
| any | Any other value | No change, no message |

- The bot does not repeat an alert while the state stays `bad`.
- **Quiet hours** (default 20:00–08:00, can be off): the bot changes the state but sends nothing, and marks `pending`. When quiet hours end, the bot sends a message only if the state now differs from the state of the last sent message. Example: CO₂ goes out of the norm at night and stays out of the norm in the morning. The bot sends one alert at 08:00. If CO₂ is back in the norm before 08:00, the bot sends nothing.
- If the data is older than `STALE_AFTER_MIN`, the bot does not evaluate alerts.
- For a range (temperature, humidity), the hysteresis is 5 % of the range width, inside each boundary.

### Morning report

- At the time that you set (default 09:00), on the days that you set (default Mon–Fri), in `TZ`.
- It has the same content as `/climate`, with the CO₂ chart for the last 12 h.
- `report_log` makes sure that the bot sends the report once per day, also after a restart. If the bot was off at the report time, it sends the report when it starts, if the time is before 12:00. If the report time is 12:00 or later, the catch-up period is 10 minutes after the report time.

### `/settings` (chat admins only)

The menu is one message that the bot edits in place:

- 🔔 Alerts: on / off.
- 🌅 Morning report: on / off, time, days (Mon–Fri or every day).
- 🌙 Quiet hours: on / off, start–end.
- 📏 Limits: CO₂ max, temperature min–max, humidity min–max, PM2.5 max.
- ↩️ Reset to defaults, ✖️ Close.

For a value, the admin pushes "изменить". The bot asks for the value and waits for the admin's next message in this chat (aiogram FSM, 5 min timeout). Accepted formats:

- number: `1000`
- range: `19-26`
- time: `09:00`
- time range: `20:00-08:00`

The bot rejects bad values with an example of the correct format.

### Defaults (`.env`)

| Setting | Default |
|---|---|
| CO₂ max | 1200 ppm |
| Temperature | 18–27 °C |
| Humidity | 30–70 % |
| PM2.5 max | 35 µg/m³ |
| Alerts | on |
| Morning report | on, 09:00, Mon–Fri |
| Quiet hours | on, 20:00–08:00 |

The 🟢🟡🔴 rating in the summary uses the stricter comfort scale from `qingping.py` (for example, CO₂ good ≤ 800, fair ≤ 1200). The alert limits are per chat.

## 6. Access

- `ALLOWED_CHAT_IDS`, `ALLOWED_USER_IDS`: the bot replies only in these chats or to these users. Empty lists mean everyone has access.
- Settings in a group: the user must be a group admin (`getChatMember`, cached for 5 min).
- Settings in a private chat: the user who owns the chat (`user_id == chat_id`) or a user in `ADMIN_USER_IDS` is an admin. So each user manages alerts and the report for their own private chat.
- Set `ALLOWED_CHAT_IDS` or `ALLOWED_USER_IDS` in production: with empty lists, any Telegram user can read the office data.
- A user who is not an admin pushes a settings button: the bot shows the popup "Только для админов".

## 7. Error handling

| Situation | Behavior |
|---|---|
| MQTT broker not available | Connect again every 5 s, log a warning. `/climate` uses the saved data |
| Unknown or bad MQTT message | Ignore it, log at DEBUG |
| Partial data | Merge with the newest values |
| Data is stale | Warning in the summary. No alert evaluation |
| No data at all | Short instruction about the sensor and MQTT setup |
| Fewer than 2 points for a chart | Text without a photo |
| Telegram API error | aiogram retries. The scheduler logs the error and continues with the next chat |
| Bot removed from a chat (403) | Turn off alerts and the report for that chat |
| Bad value in `/settings` | Reply with the correct format, wait again |
| Restart | Settings, alert state and report log are in SQLite, so the bot sends no duplicates |

## 8. Tests

pytest, no network:

- **Parser:** Qingping type 12/17, plain values, bad input, MAC from the topic.
- **Rating and advice.**
- **Store:** merge, history, delete old rows.
- **`alerts.py`:**
  - one alert when the value goes out of the norm
  - no repeat while the state stays `bad`
  - one message when the value is back in the norm, with hysteresis
  - values near the limit cause no message series
  - quiet hours with a delayed alert, and with nothing to send
  - stale data causes no alerts
- **Morning report:** time and day check in `TZ`, once per day, catch-up after a restart.
- **Settings:** parse number, range, time and time range. Reject bad input. Reset to defaults.
- **Charts:** PNG is valid and not empty.
- **Handlers:** caption and keyboard build. Admin check with a mock bot.

The README gives a manual check after deployment:

1. `docker compose up -d`.
2. Send a test message with `mosquitto_pub`.
3. Send `/climate`.
4. Set the CO₂ limit to 400 and get an alert.

## 9. Deployment

- Files: `docker-compose.yml`, `Dockerfile` (python:3.13-slim + matplotlib), `.env.example`, `mosquitto/config/mosquitto.conf`, `scripts/mqtt-passwd.sh`.
- MQTT has no password by default, because it is in the office LAN. The README tells how to turn on a password.
- The README is in Russian. It covers:
  - BotFather setup (create the bot, turn off privacy mode or use commands in groups)
  - Qingping private MQTT setup in the Qingping developer portal (broker = office PC IP:1883, topic `qingping/<MAC>/up`)
  - `.env`
  - start and update commands
