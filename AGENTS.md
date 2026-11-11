# AGENTS.md — office-climate

Telegram-бот «Климат в офисе» для датчиков **Qingping Air Monitor (2 / Lite)**.
Показывает температуру, влажность, CO₂ и пыль, шлёт уведомления о выходе за пороги
и утренний отчёт с графиком. Работает полностью локально в Docker: датчики шлют
данные по MQTT на ПК в офисе, бот общается с Telegram через long polling
(только исходящие соединения, никаких открытых портов в интернет).

Язык проекта — русский (тексты бота, комментарии, README).

## Поток данных

```
Qingping Air Monitor ──MQTT──▶ mosquitto (порт 1883, офисная сеть)
                                   │
                                   ▼
                           bot (Python, app/main.py) ──▶ SQLite ./data/climate.db
                                   │ long polling
                                   ▼
                               Telegram
```

## Архитектура

Один процесс (`python -m app.main`, asyncio) соединяет три контура:

1. **Приём данных** — `mqtt_listener.run_mqtt`: подписка на `qingping/+/up`
   (aiomqtt), автоматический реконнект. Парсинг в `qingping.parse_message`:
   терпимый к формату разбор JSON (`sensorData` — список или один объект,
   `{"value": ...}` или голые числа), нормализация MAC, миллисекунды → секунды.
   Фильтрация невозможных значений — `PLAUSIBLE` (датчики отдают коды ошибок,
   напр. `999999999` у умирающего PM-сенсора).
2. **Хранение** — `store.Store`: SQLite в WAL, одно соединение из event loop.
   Таблицы: `readings` (PK mac+ts, значения — JSON-столбец), `widget_messages`.
   Частичные сообщения одного сэмпла **мержатся** по (mac, ts). Чистка истории —
   фоновый `prune_loop` (1 раз в час, `HISTORY_DAYS`).
3. **Отправка в Telegram** — aiogram Dispatcher (long polling) + фоновые задачи:
   - `scheduler.run_scheduler` — тик раз в минуту: проверка алертов
     (`alerts.step`, чистые функции с гистерезисом 5 % и тихими часами) и утренний
     отчёт (`report_due`, окно «догона» до 12:00);
   - `widget.run_widget_updates` — живые обновления Telegram-виджетов
     (public_data раз в 5 с; виджет не пересоздаётся — график обновляет
     кнопка «Обновить» или /climate);
   - роутеры (`app/handlers/`): climate (`/start`, `/climate`, ключевые слова
     «климат», «душно», «душновато», кнопки сводки), settings (меню `/settings`
     с FSM-вводом значений), migration (переезд настроек при апгрейде группы
     в супергруппу).

Порядок роутеров важен: сначала `migration`, потом `settings`, потом `climate` —
обработчик ввода значений настроек должен увидеть текст раньше keyword-хендлера.

### Разделение ответственности модулей (`app/`)

| Модуль | Роль |
|---|---|
| `config.py` | `Settings`: все env-переменные из `.env`, валидация TZ и IGNORE_METRICS |
| `qingping.py` | Модель данных `Reading`, парсинг MQTT-JSON, справочники `METRICS` / `PLAUSIBLE` / `LIMITS` / `BANDS`, оценка `rate()`/`overall()`/`advice()` |
| `mqtt_listener.py` | Подписка и запись показаний, реконнект |
| `store.py` | SQLite: показания, виджет-сообщения, удаление датчиков |
| `chat_settings.py` | `ChatConfig` (дефолты + env-оверрайды), `ChatStore`: настройки чатов, состояния алертов, журнал отчётов, миграция ID |
| `alerts.py` | Чистая логика алертов: гистерезис, события, тихие часы (без Telegram и БД) |
| `scheduler.py` | Минутный тик: алерты + отчёт, обработка ошибок Telegram (ban, миграция, «chat not found») |
| `summary.py` | Тексты (HTML): подпись сводки, тексты алертов |
| `charts.py` | PNG-график matplotlib (Figure API — безопасно в тредах), цветные зоны нормы |
| `view.py` | «Представление» сводки: клавиатура, сборка View, send/edit (с пересозданием при смене photo↔text) |
| `widget.py` | Виджеты Bot API 10.4 (aiogram их не знает — прямые POST через `bot.session`): HTML+JS с запечёнными сериями, бюджеты сжатия zlib/public_data, живые апдейты |
| `access.py` | `AccessMiddleware` (allow-list чатов/пользователей) и `AdminChecker` (admins only для /settings, кэш 5 мин) |
| `handlers/` | Роутеры aiogram: climate, settings, migration |

## Ключевые решения и инварианты

- **Безопасность доступа**: пустые `ALLOWED_CHAT_IDS`/`ALLOWED_USER_IDS` = доступ всем
  (удобно для разработки, опасно в проде — в README это подчёркнуто).
  Кнопки сводки привязаны к `owner` (кто вызвал) — чужие кнопки не работают.
- **Фоновые задачи должны жить вечно**: `on_task_done` в `main.py` делает
  `os._exit(1)` при падении любой из них — Docker перезапустит контейнер.
  Не глотай исключения молча в фоновых циклах.
- **Пороги алертов — в настройках чата** (`ChatConfig`), а шкалы «хорошо/удовл./плохо»
  для сводки и графиков — константы в `qingping.py` (`LIMITS`, `BANDS`). Не смешивай их.
- **Сырые данные неизменны**: `clean()`/`PLAUSIBLE` применяются и при записи, и при
  чтении (старые строки чистятся на лету). Новую метрику добавляй во все три места:
  `METRICS`, `PLAUSIBLE` и при необходимости `LIMITS`/`BANDS`.
- **Виджет — фича-флаг**: `WIDGETS_ENABLED`/`WIDGETS_IN_GROUPS`. Любой сбой виджета
  должен тихо падать на PNG-сводку (`send_widget_summary` возвращает `None`).
  Лимиты Telegram: `MAX_COMPRESSED_BYTES` (zlib-9) = 3800, public_data ≤ 1000 байт.
- **Время**: всё в Unix-секундах (`ts`), отображение — через `ZoneInfo(settings.tz)`.
- **Группа → супергруппа** меняет chat_id: настройки мигрируют через
  `ChatStore.migrate`, scheduler и access middleware это обрабатывают.
  ID супергруппы начинается с `-100`.

## Инфраструктура

- `docker-compose.yml`: `mosquitto` (eclipse-mosquitto, порт 1883) и `bot`
  (build из `Dockerfile`, python:3.13-slim, volume `./data:/data`, env из `.env`).
- База — `./data/climate.db` (WAL; рядом лежат `-shm`/`-wal`). Бэкап = копия папки `data`.
- Скрипты: `scripts/forget-sensor.sh` (удалить датчик), `mqtt-passwd.sh` (пароль
  брокера), `smoke-mqtt.sh` (смоук-тест MQTT → бот → SQLite в Docker).

## Разработка

```bash
pip install -r requirements-dev.txt
python -m pytest -q          # asyncio_mode=auto; conftest закрывает все SQLite-соединения
./scripts/smoke-mqtt.sh      # полная цепочка в Docker
```

Тесты лежат рядом по именам: `tests/test_<модуль>.py` ↔ `app/<модуль>.py`.
Покрываются чистые функции парсинга, оценки, алертов, настроек и обработчики.
Новый код следует этому паттерну; Telegram/MQTT оборачиваются в тонкие слои,
логику выноси в чистые функции без aiogram и БД (как `alerts.py`, `qingping.py`).

Если меняешь поведение, задокументированное в README (команды, env-переменные,
настройки) — обнови и README.

## Как безопасно вносить изменения

Перед коммитом, затрагивающем код в `app/`:

1. `python -m pytest -q` — весь сьют должен быть зелёным. Логику выноси в чистые
   функции и покрывай тестом сразу (см. `alerts.py`, `qingping.py` как образец).
2. Если трогал парсинг MQTT или `Store` — прогони `./scripts/smoke-mqtt.sh`
   (нужен запущенный Docker): он проверяет цепочку MQTT → бот → SQLite.
3. Если менял тексты, кнопки или сценарии (`/climate`, `/settings`, виджет) —
   проверь вручную в Telegram: в тестах aiogram-хендлеры покрыты частично,
   регрессии в разметке/HTML ловятся только глазами.
4. `git status` — убери мусор из прогонов (логи, `data/_dbg_widget.html`,
   изменения в `data/climate.db*` — база и её WAL не коммитятся).

**Не трогай без явной просьбы:**
- `data/` — рабочая база продовой установки; кроме `climate.db` там дебаг-артефакты.
- `mosquitto/data/` — состояние брокера.
- Лимиты виджета (`MAX_COMPRESSED_BYTES`, `PUBLIC_DATA_BUDGET`, `POINT_CAPS`) —
  их подобрали под реальные отказы Telegram; менять только вместе с ручной
  проверкой виджета на живом чате.

После изменения env-переменных правь три места сразу: `app/config.py`,
`.env.example` и README (таблица настроек).

## Типичная задача end-to-end: добавить новую метрику

1. `app/qingping.py`: ключ в `METRICS` (название, единица, digits), допустимый
   диапазон в `PLAUSIBLE`, при желании шкалу в `LIMITS` (верхние пороги) или
   `BANDS` (комфортный диапазон).
2. `app/view.py`: короткое имя в `SHORT`, включи ключ в `CHART_METRICS`, если
   метрика графикабельна.
3. Если метрика участвует в уведомлениях — порог в `ChatConfig`
   (`app/chat_settings.py`), поле в `FIELDS` меню (`app/handlers/settings.py`),
   дефолт в `.env.example` и `defaults_from_env`.
4. Тесты: парсинг в `tests/test_qingping.py`, оценку — туда же или в
   `tests/test_summary.py`, отображение — `tests/test_view.py`/`test_widget.py`.
5. `pytest -q`, вручную: `/climate`, сводка виджета, алерт при выходе за порог.

## Чек-лист ревью изменений

- [ ] Логика без aiogram/Telegram/БД? Чистая функция + тест лучше хендлера с логикой внутри.
- [ ] Все новые пути завершения (`return None`, исключения) обработаны? Фоновые циклы не должны умирать молча — `on_task_done` убьёт процесс.
- [ ] Любой сбой новой фичи имеет фолбэк (как виджет → PNG), а не молчаливый отказ?
- [ ] Время сравнивается в Unix-секундах, отображается через `settings.tz`.
- [ ] Тексты — на русском, HTML экранируется (`html.escape` для пользовательских данных).
- [ ] Env-переменная добавлена во все три места (config / .env.example / README)?
- [ ] `pytest -q` зелёный; сценарии с кнопками/HTML проверены вручную в Telegram?
- [ ] README и этот файл актуальны, если менялось документированное поведение.
