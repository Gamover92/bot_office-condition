# Telegram-виджеты в /climate — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Заменить связку «PNG-график + кнопки» в `/climate` на интерактивный HTML-виджет Telegram в личных чатах: переключение метрики/периода внутри виджета, живые значения через `editMessageWidgetData`, фолбэк на PNG в группах и при любой ошибке.

**Architecture:** Новый модуль `app/widget.py`: сборка HTML с запечёнными сериями (все метрики × периоды одного датчика), контроль размера, сырые HTTP-вызовы Bot API (`sendWidget`, `editMessageWidgetData`) — aiogram 3.31 их не знает. Координаты виджет-сообщений — в SQLite (`Store`). Фоновый цикл правит `public_data` свежих сообщений. Маршрутизация в `app/handlers/climate.py`: личка → виджет, группа → текущий PNG-путь без изменений.

**Tech Stack:** Python 3, aiogram 3.31 (сессия aiohttp для сырых вызовов), SQLite, pytest (asyncio auto), Docker.

**Spec:** `docs/superpowers/specs/2026-11-10-telegram-widgets-design.md`

## Global Constraints

- HTML виджета: ≤ 32 KB исходника и ≤ 4 KB после `zlib.compress(html, 9)`; рабочий бюджет — **3800 байт** сжатых. Только inline CSS/JS, без внешних ресурсов и сети.
- `public_data` ≤ 1024 байта текста (рабочий бюджет 1000); пишет только бот.
- Виджеты только в личных чатах (прод-ограничение Bot API 10.4); в группах — PNG. Флаги: `WIDGETS_ENABLED` (по умолчанию вкл.), `WIDGETS_IN_GROUPS` (по умолчанию выкл.).
- **Любая** ошибка отправки виджета → фолбэк на PNG-путь (`view.send_view`); пользователь всегда получает рабочую сводку.
- Правки `public_data` не чаще одного раза в несколько секунд на сообщение, троттлинг суммарный; обновляем только сообщения моложе N часов.
- Подписи осей и времена — в часовом поясе офиса (`settings.tz`), как в PNG, а не в поясе зрителя.
- Owner-lock кнопок («кнопки только вызвавшего») сохраняется.
- Никаких входящих апдейтов виджетов: `allow_queries` не ставим, `widget_query` не обрабатываем.
- Новых зависимостей в `requirements.txt` не добавляем (aiohttp уже идёт с aiogram).

## Review Focus

- `public_data` длиннее 1024 байт при полном наборе метрик → сборщик обязан ужиматься/обрезаться, тест в задаче 5.
- Слишком много точек → HTML не влезает в 3800 сжатых байт → прореживание обязано добивать бюджет, тест в задаче 6.
- Частые MQTT + много живых виджетов → флуд-контроль: не более одной правки на сообщение за цикл и только при изменении данных, тест в задаче 9.
- Пользователь удалил виджет-сообщение → правка падает, запись чистится, цикл не умирает, тест в задаче 9.
- Виджет отправлен в группу при выключенном флаге / API ответил `INPUT_MEDIA_WIDGET_NOT_ALLOWED` → фолбэк на PNG, тест в задаче 8.

---

### Task 1: Спайк (фаза 1, throwaway, без тестов)

**Files:**
- Create (временно, не коммитить): `spike_widget.py` в корне
- Create: `docs/superpowers/specs/2026-11-10-telegram-widgets-spike-notes.md`

**Interfaces:**
- Produces: заметки с измеренным бюджетом данных (сколько точек × метрик × периодов влезает в 3800 сжатых байт), подтверждением `sendWidget`/`editMessageWidgetData` сырым HTTP и скриншотами рендера. Задачи 5–6 опираются на эти цифры.

- [ ] **Step 1: Написать спайк-скрипт**

Один файл `spike_widget.py`: берёт `BOT_TOKEN` и `SPIKE_CHAT_ID` из env, шлёт `sendWidget` POST-ом на `https://api.telegram.org/bot<token>/sendWidget` через `aiohttp` (HTML: текущие значения + один спарклайн CO₂ за 24 ч, данные из `Store`), печатает `message_id`, длину исходника и `len(zlib.compress(html, 9))`; затем раз в 5 секунд правит `public_data` через `editMessageWidgetData` 3 раза.

- [ ] **Step 2: Прогнать спайк против живого бота**

Run: `python spike_widget.py`
Expected: сообщение-виджет в личке, цифры обновляются 3 раза без новых сообщений; в логе — размеры.

- [ ] **Step 3: Измерить бюджет данных**

В спайке подставить серии всех 8 графических метрик (`CHART_METRICS` из `app/view.py`) × 3 периода (6 ч / 24 ч / 7 д) с реальной историей из `data/climate.db`; подобрать прореживание так, чтобы сжатый размер был ≤ 3800 байт. Зафиксировать, сколько точек на серию получилось.

- [ ] **Step 4: Посмотреть рендер**

Проверить на десктопе (430 px) и телефоне (~362 px), тёмную и светлую тему. Сверить читаемость с PNG (анти-цель: «хуже читается, чем PNG»).

- [ ] **Step 5: Зафиксировать выводы, удалить скрипт**

Записать в `docs/superpowers/specs/2026-11-10-telegram-widgets-spike-notes.md`: сжатые размеры, выбранную плотность точек, проблемы рендера, работоспособность `editMessageWidgetData`. Если бюджет меняет расклад (не влезают 8 метрик × 3 периода) — вернуться к спеке до задачи 6. `spike_widget.py` удалить.

```bash
git add docs/superpowers/specs/2026-11-10-telegram-widgets-spike-notes.md
git commit -m "docs: widget spike notes"
```

### Task 2: Флаги конфигурации

**Files:**
- Modify: `app/config.py:40-85`
- Modify: `.env.example`
- Modify: `README.md` (раздел про переменные окружения)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Settings.widgets_enabled: bool` (env `WIDGETS_ENABLED`, default `"on"`), `Settings.widgets_in_groups: bool` (env `WIDGETS_IN_GROUPS`, default `"off"`). Парсинг — как остальные on/off-флаги проекта.

- [ ] **Step 1: Написать падающие тесты**

```python
def test_widgets_defaults_on_and_groups_off(monkeypatch):
    s = Settings.from_env()
    assert s.widgets_enabled is True
    assert s.widgets_in_groups is False

def test_widgets_flags_from_env(monkeypatch):
    monkeypatch.setenv("WIDGETS_ENABLED", "off")
    monkeypatch.setenv("WIDGETS_IN_GROUPS", "on")
    s = Settings.from_env()
    assert s.widgets_enabled is False
    assert s.widgets_in_groups is True
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `pytest tests/test_config.py -v`
Expected: FAIL (`AttributeError: widgets_enabled`)

- [ ] **Step 3: Реализовать флаги в `Settings`**

Два поля в dataclass и разбор env в `from_env()` (значение `"on"` → True, иначе False; default см. выше).

- [ ] **Step 4: Тесты зелёные**

Run: `pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Документация и коммит**

`.env.example`: два флага с комментариями (группы — «включать, только когда Telegram откроет виджеты в группах»). README: строка про виджеты в личке и флаги.

```bash
git add app/config.py tests/test_config.py .env.example README.md
git commit -m "feat: WIDGETS_ENABLED and WIDGETS_IN_GROUPS flags"
```

### Task 3: Реестр виджет-сообщений в Store

**Files:**
- Modify: `app/store.py:14-25` (CREATE TABLE в `__init__`)
- Test: `tests/test_store.py`

**Interfaces:**
- Produces (на `Store`):
  - `add_widget_message(chat_id: int, message_id: int, mac: str, sent_at: int) -> None`
  - `get_widget_message(chat_id: int, message_id: int) -> str | None` — mac или None
  - `widget_messages(max_age_sec: int, now: int) -> list[tuple[int, int, str]]` — `(chat_id, message_id, mac)` свежих
  - `drop_widget_message(chat_id: int, message_id: int) -> None`
  - `prune_widget_messages(older_than: int) -> None`

- [ ] **Step 1: Написать падающий тест**

```python
def test_widget_messages_roundtrip():
    store = Store(":memory:")
    store.add_widget_message(-100, 5, "AA", sent_at=1000)
    store.add_widget_message(-100, 6, "BB", sent_at=500)
    assert store.get_widget_message(-100, 5) == "AA"
    assert store.get_widget_message(-100, 9) is None
    assert store.widget_messages(max_age_sec=600, now=1000) == [(-100, 5, "AA")]
    store.drop_widget_message(-100, 5)
    assert store.get_widget_message(-100, 5) is None

def test_prune_widget_messages():
    store = Store(":memory:")
    store.add_widget_message(1, 1, "AA", sent_at=100)
    store.prune_widget_messages(older_than=200)
    assert store.widget_messages(max_age_sec=10**9, now=300) == []
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `pytest tests/test_store.py -k widget -v`
Expected: FAIL (`AttributeError`)

- [ ] **Step 3: Реализовать таблицу и методы**

Таблица `widget_messages (chat_id INTEGER, message_id INTEGER, mac TEXT, sent_at INTEGER, PRIMARY KEY (chat_id, message_id))`, `CREATE TABLE IF NOT EXISTS` в `Store.__init__` рядом с `readings`. Методы — простые INSERT/SELECT/DELETE в стиле соседних методов.

- [ ] **Step 4: Тесты зелёные и коммит**

Run: `pytest tests/test_store.py -v`
Expected: PASS

```bash
git add app/store.py tests/test_store.py
git commit -m "feat: widget message registry in Store"
```

### Task 4: Сырые вызовы Bot API

**Files:**
- Create: `app/widget.py`
- Test: `tests/test_widget.py`

**Interfaces:**
- Consumes: `aiogram.Bot` (его `bot.session` и `bot.token`).
- Produces:
  - `async def send_widget(bot: Bot, chat_id: int, html: str, caption: str, keyboard: InlineKeyboardMarkup | None) -> int` — возвращает `message_id`; при ошибке API кидает исключение.
  - `async def edit_widget_data(bot: Bot, chat_id: int, message_id: int, public_data: str) -> None` — при ошибке API кидает исключение.

- [ ] **Step 1: Написать падающие тесты**

Фейковая сессия вместо сети: подменить `bot.session` объектом, записывающим `(method, payload)` и возвращающим заготовленный ответ.

```python
async def test_send_widget_returns_message_id():
    bot = fake_bot_with_session(ok=True, result={"message_id": 42})
    mid = await send_widget(bot, 7, "<html>…</html>", "caption", None)
    assert mid == 42
    method, payload = bot.session.calls[0]
    assert method == "sendWidget" and payload["chat_id"] == 7

async def test_send_widget_raises_on_api_error():
    bot = fake_bot_with_session(ok=False, description="INPUT_MEDIA_WIDGET_NOT_ALLOWED")
    with pytest.raises(Exception, match="INPUT_MEDIA_WIDGET_NOT_ALLOWED"):
        await send_widget(bot, -100, "<html/>", "c", None)

async def test_edit_widget_data_payload():
    bot = fake_bot_with_session(ok=True, result=True)
    await edit_widget_data(bot, 7, 42, '{"co2":700}')
    method, payload = bot.session.calls[0]
    assert method == "editMessageWidgetData"
    assert payload["public_data"] == '{"co2":700}'
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `pytest tests/test_widget.py -v`
Expected: FAIL (нет модуля `app.widget`)

- [ ] **Step 3: Реализовать `send_widget` и `edit_widget_data` в `app/widget.py`**

POST на `https://api.telegram.org/bot{token}/{method}` через `bot.session` (aiohttp), тело — form data (`chat_id`, `html`, `caption`, `reply_markup` как JSON-строка; `public_data`). Проверять `ok` в ответе; при `ok: false` кидать `RuntimeError` с `description`. `caption` — HTML parse mode, как у бота по умолчанию.

- [ ] **Step 4: Тесты зелёные и коммит**

Run: `pytest tests/test_widget.py -v`
Expected: PASS

```bash
git add app/widget.py tests/test_widget.py
git commit -m "feat: raw sendWidget/editMessageWidgetData client"
```

### Task 5: `build_public_data` — компактный JSON последних значений

**Files:**
- Modify: `app/widget.py`
- Test: `tests/test_widget.py`

**Interfaces:**
- Consumes: `qingping.Reading`.
- Produces: `build_public_data(reading: Reading) -> str` — компактный JSON (сепараторы без пробелов), всегда ≤ 1000 байт; ключи метрик, значения и `ts` — структуру выбирает строитель (она же должна читаться JS виджета из задачи 6).

- [ ] **Step 1: Написать падающие тесты**

```python
def test_public_data_fits_budget_with_all_metrics():
    values = {k: 12345.6 for k in METRICS}
    data = build_public_data(Reading("AA", 1730000000, values))
    assert len(data.encode()) <= 1000

def test_public_data_roundtrip():
    data = build_public_data(Reading("AA", 1730000000, {"co2": 700.0, "temperature": 22.5}))
    parsed = json.loads(data)
    assert parsed["co2"] == 700 and parsed["ts"] == 1730000000
```

(Точный формат ключей — решение строителя; тест roundtrip поправить под него.)

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `pytest tests/test_widget.py -k public_data -v`
Expected: FAIL

- [ ] **Step 3: Реализовать `build_public_data`**

Округление по `METRICS[metric][2]` (digits), короткие ключи при необходимости. Если при полном наборе метрик не влезает — отбрасывать метрики с конца порядка `METRICS`, пока не влезет (budget 1000 байт).

- [ ] **Step 4: Тесты зелёные и коммит**

Run: `pytest tests/test_widget.py -v`
Expected: PASS

```bash
git add app/widget.py tests/test_widget.py
git commit -m "feat: build_public_data with size budget"
```

### Task 6: `build_widget_html` — сборка HTML с запечёнными сериями

**Files:**
- Modify: `app/widget.py`
- Test: `tests/test_widget.py`

**Interfaces:**
- Consumes: `Store.history`, `Store.latest`, `view.CHART_METRICS`, `view.PERIODS`, `qingping` (`LIMITS`, `BANDS`, `METRICS`), `settings.tz`.
- Produces:
  - `MAX_COMPRESSED_BYTES = 3800`
  - `compressed_size(html: str) -> int` — `len(zlib.compress(html.encode(), 9))`
  - `build_widget_html(settings: Settings, store: Store, mac: str, now: float) -> str | None` — None, если данных нет. HTML: зоны 🟢🟡🔴 (цвета и пороги из `charts.ZONE_COLORS`/`LIMITS`/`BANDS`), переключение метрики и периода на JS без сети, текущие значения (обновляемые из `public_data`), шкала времени в `settings.tz`. Формат кодирования серий и прореживание — решение строителя по замерам спайка (задача 1).

- [ ] **Step 1: Написать падающие тесты**

```python
def test_html_none_without_data():
    assert build_widget_html(S, Store(":memory:"), "AA", time.time()) is None

def test_html_fits_budget_with_dense_history():
    store = Store(":memory:")
    now = time.time()
    values = {m: 100.0 for m in CHART_METRICS}
    store.add([Reading("AA", int(now) - i * 60, values) for i in range(7 * 24 * 60)])
    html = build_widget_html(S, store, "AA", now)
    assert compressed_size(html) <= MAX_COMPRESSED_BYTES
    assert len(html.encode()) <= 32 * 1024

def test_html_bakes_all_metrics_periods_and_office_tz():
    store = Store(":memory:")
    now = fill(store, "AA", {"co2": 700.0, "temperature": 22.0})
    html = build_widget_html(S, store, "AA", now)
    for metric in ("co2", "temperature"):
        assert metric in html
    assert "Europe/Moscow" in html or "+03:00" in html
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `pytest tests/test_widget.py -k html -v`
Expected: FAIL

- [ ] **Step 3: Реализовать сборку HTML**

Шаблон — строка-константа с inline CSS/JS; данные серий подставляются одним JSON/кодированным блоком. Прореживание: уменьшать точность/число точек, пока `compressed_size` не ≤ 3800. Вёрстка в процентах под 362–430 px, без `vh`/`vmin`; тема из `TelegramWidget`; без блоков JS дольше 500 мс и постоянной анимации. JS читает обновления цифр из `public_data` (формат — как в задаче 5).

- [ ] **Step 4: Тесты зелёные**

Run: `pytest tests/test_widget.py -v`
Expected: PASS

- [ ] **Step 5: Ручная проверка рендера и коммит**

Прогнать HTML через песочницу widget-sandbox (`pnpm dev`) на десктопе и телефоне, обе темы; сверить с PNG. Фолбэк-тест: HTML с гарантированным переполнением (серии без прореживания) → `compressed_size > MAX_COMPRESSED_BYTES` — покрыто шагом 1 бюджетным тестом.

```bash
git add app/widget.py tests/test_widget.py
git commit -m "feat: build_widget_html with baked series and size budget"
```

### Task 7: Клавиатура виджета (датчик + обновить)

**Files:**
- Modify: `app/view.py:68-80`
- Test: `tests/test_view.py`

**Interfaces:**
- Consumes: `ClimateCb`, `device_name`.
- Produces: `build_widget_keyboard(settings: Settings, macs: list[str], mac: str, owner: int) -> InlineKeyboardMarkup` — строка датчиков (если > 1) + «🔄 Обновить»; callback — `ClimateCb(mac=…, metric="co2", hours=24, owner=owner)` (metric/hours не используются виджетом).

- [ ] **Step 1: Написать падающий тест**

```python
def test_widget_keyboard_two_devices():
    kb = build_widget_keyboard(S, ["AA", "BB"], "BB", owner=7)
    assert texts(kb) == [["Датчик AA", "• Датчик BB •"], ["🔄 Обновить"]]
    data = ClimateCb.unpack(kb.inline_keyboard[1][0].callback_data)
    assert (data.mac, data.owner) == ("BB", 7)

def test_widget_keyboard_one_device():
    assert texts(build_widget_keyboard(S, ["AA"], "AA", owner=7)) == [["🔄 Обновить"]]
```

- [ ] **Step 2: Убедиться, что тест падает**

Run: `pytest tests/test_view.py -k widget -v`
Expected: FAIL

- [ ] **Step 3: Реализовать `build_widget_keyboard` в `app/view.py`**

Рядом с `build_keyboard`, переиспользовать `_button`.

- [ ] **Step 4: Тесты зелёные и коммит**

Run: `pytest tests/test_view.py -v`
Expected: PASS

```bash
git add app/view.py tests/test_view.py
git commit -m "feat: widget keyboard (sensor switch + refresh)"
```

### Task 8: Маршрутизация и отправка с фолбэком

**Files:**
- Modify: `app/handlers/climate.py:35-74`
- Modify: `app/widget.py`
- Test: `tests/test_widget.py`, `tests/test_climate_handlers.py`

**Interfaces:**
- Consumes: задачи 2–7 (`send_widget`, `build_widget_html`, `build_public_data`, `build_widget_keyboard`, реестр `Store`, `send_view`, `caption`).
- Produces:
  - `widgets_allowed(settings: Settings, chat_type: str) -> bool` — `settings.widgets_enabled and (chat_type == "private" or settings.widgets_in_groups)`
  - `async def send_widget_summary(bot: Bot, settings: Settings, store: Store, chat_id: int, owner: int, mac: str | None = None) -> Message | None` — None, если виджет не отправлен (нет данных, переполнение размера, любая ошибка API); тогда вызывающий шлёт PNG. При успехе: запись в реестр, caption из `summary.caption`.

- [ ] **Step 1: Написать падающие тесты**

```python
def test_widgets_allowed_routing():
    on = Settings(bot_token="x")          # widgets_enabled=True, in_groups=False
    off = Settings(bot_token="x", widgets_enabled=False)
    groups = Settings(bot_token="x", widgets_in_groups=True)
    assert widgets_allowed(on, "private") and not widgets_allowed(on, "supergroup")
    assert not widgets_allowed(off, "private")
    assert widgets_allowed(groups, "supergroup")

async def test_send_widget_summary_falls_back_on_api_error():
    # send_widget кидает RuntimeError("INPUT_MEDIA_WIDGET_NOT_ALLOWED")
    assert await send_widget_summary(bot_raising, S, store_with_data, -100, owner=7) is None

async def test_send_widget_summary_registers_message():
    msg = await send_widget_summary(bot_ok, S, store_with_data, 7, owner=7)
    assert msg is not None
    assert store_with_data.get_widget_message(7, msg.message_id) == "AA"
```

Тесты хендлера: личка + ошибка виджета → вызван `send_view` (PNG); группа → `send_view` без попытки виджета; callback по виджет-сообщению (есть в реестре) → отправлен **новый** виджет со свежими данными, старое сообщение удалено, реестр обновлён; чужой callback → `NOT_YOURS` (уже покрыто существующим тестом owner-lock).

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `pytest tests/test_widget.py tests/test_climate_handlers.py -v`
Expected: FAIL

- [ ] **Step 3: Реализовать маршрутизацию**

В `handlers/climate.py`:
- `show()`: если `widgets_allowed(settings, message.chat.type)` — `send_widget_summary(...)`; при None — текущий `send_view(...)`.
- `send_widget_summary` в `app/widget.py`: собрать HTML и `public_data`; если HTML None или `compressed_size > MAX_COMPRESSED_BYTES` — вернуть None; `send_widget` в try/except Exception → log.warning + None; при успехе `store.add_widget_message(...)`.
- `on_button`: если `store.get_widget_message(chat_id, message_id)` is not None — пересоздание: `send_widget_summary(bot, settings, store, chat_id, owner, mac=callback_data.mac)`; при None — фолбэк `edit_view` (PNG); при успехе — удалить старое сообщение (как в `edit_view`, `contextlib.suppress(TelegramBadRequest)`) и `drop_widget_message` старой записи.

- [ ] **Step 4: Тесты зелёные и коммит**

Run: `pytest tests/ -v`
Expected: PASS (включая старые тесты климата — групповой путь не изменён)

```bash
git add app/handlers/climate.py app/widget.py tests/test_widget.py tests/test_climate_handlers.py
git commit -m "feat: widget send path with PNG fallback and chat routing"
```

### Task 9: Живые обновления `public_data` и очистка

**Files:**
- Modify: `app/widget.py`
- Modify: `app/main.py:74-88`
- Test: `tests/test_widget.py`

**Interfaces:**
- Consumes: `edit_widget_data`, `build_public_data`, `Store.widget_messages`, `Store.drop_widget_message`, `Store.prune_widget_messages`, `Store.latest`.
- Produces:
  - `UPDATE_INTERVAL_SEC = 5`, `MAX_WIDGET_AGE_HOURS = 24` (константы модуля)
  - `async def update_widget_data_once(bot: Bot, settings: Settings, store: Store, cache: dict) -> None` — один проход: для каждого свежего виджет-сообщения правит `public_data`, если значения изменились с прошлой правки (`cache[(chat_id, message_id)] = data`); при ошибке «message not found» — `drop_widget_message`; прочие ошибки — log.warning, цикл живёт.
  - `async def run_widget_updates(bot: Bot, settings: Settings, store: Store) -> None` — бесконечный цикл `sleep(UPDATE_INTERVAL_SEC)` + `update_widget_data_once` + периодический `prune_widget_messages`.

- [ ] **Step 1: Написать падающие тесты**

```python
async def test_update_edits_only_on_change():
    # два прохода подряд без новых данных → один вызов edit_widget_data
    await update_widget_data_once(bot, S, store, cache)
    await update_widget_data_once(bot, S, store, cache)
    assert len(edit_calls(bot)) == 1

async def test_update_throttles_per_cycle_and_drops_dead_messages():
    # 3 живых сообщения: не больше одной правки на сообщение за проход;
    # правка по удалённому сообщению падает "message not found" → запись вычищена
    ...
    assert store.get_widget_message(chat_id, dead_mid) is None

async def test_update_ignores_old_messages():
    # sent_at старше MAX_WIDGET_AGE_HOURS → правок нет
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `pytest tests/test_widget.py -k update -v`
Expected: FAIL

- [ ] **Step 3: Реализовать цикл обновлений**

Правки идут последовательно в одном проходе — суммарная частота ограничена интервалом цикла и размером реестра. Ошибки API не роняют цикл. В `main()`: добавить `asyncio.create_task(run_widget_updates(bot, settings, store))` в список `background` (только если `settings.widgets_enabled`), рядом `prune_widget_messages` раз в проход или реже.

- [ ] **Step 4: Тесты зелёные и коммит**

Run: `pytest tests/ -v`
Expected: PASS

```bash
git add app/widget.py app/main.py tests/test_widget.py
git commit -m "feat: live public_data updates with throttling"
```

---

## Проверка целиком

1. `pytest tests/ -v` — всё зелёное, включая старые тесты (групповой путь не тронут).
2. Руками против живого бота: `/climate` в личке → виджет, переключение метрики/периода внутри, цифры обновляются сами; «🔄 Обновить» и переключение датчика пересоздают сообщение; `/climate` в группе → PNG как раньше; `WIDGETS_ENABLED=off` → PNG везде.
3. Старый клиент (< layer 233) видит caption — сводка читается.
