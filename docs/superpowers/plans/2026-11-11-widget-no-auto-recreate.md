# Убрать авто-пересоздание виджета — план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Бот больше не пересоздаёт виджет-сводку сам по себе; график обновляется только по кнопке «Обновить» или `/climate`.

**Architecture:** Из фонового цикла `update_widget_data_once` удаляется ветка пересоздания (кулдаун 60 с, send+delete). Цикл оставляет только живые правки public_data и вычистку мёртвых записей. Код, существовавший только ради авто-пересоздания (`_last_seen`, `note_chat_message`, catch-all хендлер, `HTML_REFRESH_SEC`), удаляется. Ручной путь (`on_button` → `send_widget_summary` + удаление старого) не меняется.

**Tech Stack:** Python 3.13, aiogram 3, pytest (asyncio_mode=auto), Docker Compose.

**Spec:** `docs/superpowers/specs/2026-11-11-widget-no-auto-recreate-design.md`

## Global Constraints

- Язык проекта — русский: комментарии и тексты на русском.
- Фоновый цикл не должен умирать молча: исключения логируются, цикл продолжается (инвариант AGENTS.md).
- Лимиты виджета (`MAX_COMPRESSED_BYTES`, `PUBLIC_DATA_BUDGET`, `POINT_CAPS`) не трогать.
- Тесты: `.venv/Scripts/python.exe -m pytest -q`; весь сьют зелёный перед сборкой контейнера.

## Review Focus

- Проход с «устаревшим» кэшем после рестарта: виджет НЕ должен пересоздаться, даже если в кэше протухшее время (раньше именно это порождало всплески). Пин: `test_update_never_recreates_widget`.
- Мёртвая запись («message not found») по-прежнему вычищается из реестра и кэша (не регрессия при удалении веток). Пин: существующий `test_update_throttles_per_cycle_and_drops_dead_messages`.
- Новые показания без изменения значений: public_data всё равно правится (ts в данных меняется), повторной правки без изменений нет. Пины: `test_update_edits_only_on_change`, `test_update_edits_again_when_values_change`.

---

### Task 1: Убрать авто-пересоздание из цикла виджетов

**Files:**
- Modify: `app/widget.py` (`update_widget_data_once`, константы/функции рядом)
- Test: `tests/test_widget.py`

**Interfaces:**
- Consumes: `Store.widget_messages / drop_widget_message / latest`, `edit_widget_data`, `build_public_data`.
- Produces: `update_widget_data_once(bot, settings, store, cache)` с кэшем вида `cache[(chat_id, message_id)] = (data: str | None, n: int)`; константа `HTML_REFRESH_SEC` и функция `note_chat_message` удалены (экспорта больше нет).

- [ ] **Step 1: Написать падающий тест**

В `tests/test_widget.py` заменить три теста авто-пересоздания (`test_update_recreates_widget_with_stale_chart`, `test_update_skips_recreate_when_widget_not_last`, `test_update_keeps_widget_when_chart_fresh`) одним:

```python
async def test_update_never_recreates_widget():
    # Фоновый цикл не пересоздаёт виджет: никаких sendWidget, только правки public_data.
    import app.widget as widget

    bot = fake_bot_with_session(ok=True, result={"message_id": 55})
    store = widget_store()
    stale = int(time.time()) - 3600
    cache = {(7, 100): ("x", 1, stale, 0)}  # протухший кэш прежнего формата не должен оживлять пересоздание
    await update_widget_data_once(bot, S, store, cache)
    assert "sendWidget" not in [c[0] for c in bot.session.calls]
    assert store.get_widget_message(7, 100) == "AA"
```

Плюс убрать `HTML_REFRESH_SEC` из импортов в шапке файла.

- [ ] **Step 2: Прогнать — убедиться, что падает**

Run: `.venv/Scripts/python.exe -m pytest tests/test_widget.py -q -k never_recreates`
Expected: FAIL — `sendWidget` среди вызовов (ветка пересоздания всё ещё активна).

- [ ] **Step 3: Реализовать в `app/widget.py`**

- В `update_widget_data_once`: кэш прохода хранит только `(data, n)`; ветку «пересоздание при протухшем графике» (проверки `now - rebuilt < HTML_REFRESH_SEC`, `reading.ts <= chart_ts`, `_last_seen`, вызов `send_widget_summary`, удаление старого сообщения) удалить целиком.
- Удалить `_last_seen`, `note_chat_message`, константу `HTML_REFRESH_SEC` и комментарий к ней.
- Обновить docstring `update_widget_data_once`: пересоздание осталось только у кнопки «Обновить» в `handlers/climate.py`.
- Импорты `send_widget_summary` внутри widget.py остаются (используется в `send_widget_summary`/`on_button` — сама функция `send_widget_summary` в widget.py остаётся, она нужна хендлеру).

- [ ] **Step 4: Прогнать тесты**

Run: `.venv/Scripts/python.exe -m pytest tests/test_widget.py -q`
Expected: PASS (включая тесты из предыдущего фикса: dedup до последнего виджета, «not modified» как успех).

- [ ] **Step 5: Прогнать весь сьют**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 186 passed за вычетом удалённых тестов (итоговое число = 186 − 3 + 1 = 184).

### Task 2: Убрать ставший мёртвым catch-all хендлер

**Files:**
- Modify: `app/handlers/climate.py:61-65` (хендлер `track_last` и его импорт)
- Modify: `app/view.py` (комментарий в `build_widget_keyboard` про автопересоздание)

**Interfaces:**
- Consumes: ничего нового.
- Produces: `build_router` без catch-all `F.message()` хендлера; импорт `note_chat_message` удалён.

- [ ] **Step 1: Удалить хендлер и импорт**

В `app/handlers/climate.py` удалить функцию `track_last` и `note_chat_message` из импорта `..widget`. В `app/view.py` в `build_widget_keyboard` обновить комментарий: виджет обновляется кнопкой «Обновить» вручную.

- [ ] **Step 2: Прогнать сьют**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS. Если `tests/test_climate_handlers.py` упал на отсутствии `track_last` — поправить тест (проверить по факту; в текущем файле упоминаний `track_last`/`note_chat_message` нет).

- [ ] **Step 3: Commit**

```bash
git add app/widget.py app/handlers/climate.py app/view.py tests/test_widget.py
git commit -m "feat: убрать авто-пересоздание виджета, оставить живые правки public_data"
```
(Коммит — если пользователь попросит; в его отсутствие оставить изменения в рабочей копии и сказать об этом.)

### Task 3: Актуализировать документацию и проверить на живой системе

**Files:**
- Modify: `AGENTS.md` (строка 41-42: «public_data раз в 5 с, пересоздание HTML раз в 60 с»)

- [ ] **Step 1: Обновить AGENTS.md**

Строка про `widget.run_widget_updates`: оставить «живые обновления виджетов (public_data раз в 5 с)», убрать упоминание пересоздания HTML раз в 60 с. README не описывает автообновление — не трогать.

- [ ] **Step 2: Пересобрать и перезапустить контейнер**

Run: `docker compose up -d --build bot`
Expected: контейнер `bot` пересоздан и запущен.

- [ ] **Step 3: Проверить на живую**

Через 90 с после рестарта:
- `docker compose exec bot python -c "..."` — реестр `widget_messages` ровно одна запись на чат;
- `docker compose logs --since 90s bot` — нет `sendWidget`, нет `Widget update failed`, нет ошибок;
- попросить пользователя нажать «Обновить» на виджете — виджет пересоздаётся один раз со свежим графиком.
