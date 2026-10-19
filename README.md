# Климат в офисе — Telegram-бот для Qingping

Бот показывает температуру, влажность, CO₂ и пыль с датчика **Qingping Air Monitor** (2 / Lite).
Данные идут по MQTT на ваш ПК в офисе. Всё работает локально в Docker: без домена,
без открытых портов в интернет и без внешних сервисов (кроме самого Telegram).

## Что умеет

- `/climate` (или слова «климат», «душно?») — сводка 🟢🟡🔴 и график. Кнопки под сообщением
  меняют показатель (CO₂, температура, влажность, PM2.5…), период (6 ч / 24 ч / 7 д) и датчик.
- Уведомления в чат: одно сообщение, когда показатель вышел за порог, и одно, когда вернулся в норму.
  Без повторов. Ночью (тихие часы) бот молчит и, если проблема осталась, пишет утром.
- Утренний отчёт по расписанию (по умолчанию 09:00, пн–пт) с графиком CO₂ за ночь.
- `/settings` — пороги, время отчёта, тихие часы, вкл/выкл. Менять могут только админы чата.

## Как это устроено

```
Qingping Air Monitor ──MQTT──▶ mosquitto (порт 1883, только офисная сеть)
                                   │
                                   ▼
                           bot (Python) ──▶ SQLite ./data/climate.db
                                   │ long polling (только исходящие соединения)
                                   ▼
                               Telegram
```

## Установка

### 1. Создайте бота

1. Напишите [@BotFather](https://t.me/BotFather) команду `/newbot` и получите токен.
2. Если хотите, чтобы бот отвечал на слово «климат» в группе, отключите режим приватности:
   `/mybots` → ваш бот → Bot Settings → Group Privacy → Turn off.
   Режим приватности важен только для слова «климат». Команды `/climate` и `/settings`
   (включая ввод значений в настройках) работают и без этого.
3. Добавьте бота в рабочую группу.

### 2. Запустите на ПК в офисе

Нужен Docker с Docker Compose (Docker Desktop на Windows/macOS или Docker Engine на Linux).

```bash
git clone <этот репозиторий> office-climate
cd office-climate
cp .env.example .env
# откройте .env и впишите BOT_TOKEN и ALLOWED_CHAT_IDS (или ALLOWED_USER_IDS)
docker compose up -d --build
docker compose logs -f bot
```

**Обязательно задайте `ALLOWED_CHAT_IDS` (или `ALLOWED_USER_IDS`).** Если оба списка пустые,
данные из офиса может прочитать любой пользователь Telegram, который найдёт бота.

В логе должно быть `MQTT connected`. Порт 1883 должен быть доступен из офисной сети
(на Windows разрешите его в брандмауэре). У ПК должен быть постоянный IP в локальной сети
(закрепите его в настройках роутера).

### 3. Настройте датчик Qingping

Air Monitor умеет отправлять данные на свой MQTT-брокер («частный доступ»):

1. Войдите на [developer.qingping.co](https://developer.qingping.co) тем же аккаунтом, что в приложении Qingping+.
2. Откройте раздел частного доступа (Private Access Config) и создайте конфигурацию **MQTT**:
   - Host: локальный IP вашего ПК, например `192.168.1.50`
   - Port: `1883`
   - Username / Password: пусто (или см. «Пароль для MQTT» ниже)
   - Up topic: `qingping/<MAC>/up`, Down topic: `qingping/<MAC>/down`
   - Интервал отправки: 1–5 минут
3. Привяжите конфигурацию к устройству. Датчик должен быть в той же сети, что и ПК.

Названия пунктов в портале могут немного отличаться — ищите «Private access» / «MQTT».

Проверка: выполните в Telegram `/climate`. Если бот пишет «Данных с датчиков пока нет», посмотрите,
что приходит в брокер:

```bash
docker compose exec mosquitto mosquitto_sub -t 'qingping/#' -v
```

### 4. Проверка без датчика

Отправьте тестовое сообщение. Команда одна и та же для bash (Linux/macOS) и PowerShell (Windows):

```bash
echo '{"mac":"582D34000000","co2":1300,"temperature":23}' | docker compose exec -T mosquitto mosquitto_pub -t qingping/582D34000000/up -s
```

В сообщении нет времени — бот возьмёт текущее. JSON передаётся через stdin (`-s`), потому что
Windows PowerShell 5.1 убирает внутренние кавычки из аргументов (`-m '{"mac":...}'`) у внешних программ.

Затем `/climate` в Telegram покажет CO₂ 1300 ppm. Через минуту придёт уведомление о высоком CO₂
(если сейчас не тихие часы).

После проверки удалите тестовый датчик, чтобы он не появлялся в сводке:

```bash
./scripts/forget-sensor.sh 582D34000000
```

В Windows PowerShell то же самое:

```powershell
docker compose exec bot python -c "from app.store import Store; Store('/data/climate.db').delete_device('582D34000000')"
```

## Настройки

Значения по умолчанию задаются в `.env` (см. комментарии в `.env.example`).
Каждый чат может поменять их в `/settings`. Формат ввода: число `1000`, диапазон `19-26`,
время `09:00`, период `20:00-08:00`.

Когда Telegram превращает группу в супергруппу (так бывает, например, когда бота делают админом), ID чата меняется: замените старый ID на новый в `ALLOWED_CHAT_IDS` (новый ID бот пишет в предупреждении в логе).

| Переменная | Что значит |
|---|---|
| `ALLOWED_CHAT_IDS`, `ALLOWED_USER_IDS` | Где и кому бот отвечает. **Задайте обязательно**: пусто = любому пользователю Telegram |
| `ADMIN_USER_IDS` | Кто ещё может менять `/settings` в личке с ботом. В личном чате каждый пользователь сам управляет своими уведомлениями и отчётом. В группах `/settings` меняют админы группы |
| `DEVICE_NAMES` | Имена датчиков: `MAC=Имя;MAC=Имя` |
| `TZ` | Часовой пояс |
| `STALE_AFTER_MIN` | Через сколько минут без данных они считаются устаревшими |

## Пароль для MQTT (по желанию)

По умолчанию брокер без пароля — это нормально для закрытой офисной сети. Чтобы включить пароль:

```bash
./scripts/mqtt-passwd.sh qingping
```

В `mosquitto/config/mosquitto.conf` замените `allow_anonymous true` на:

```
allow_anonymous false
password_file /mosquitto/config/passwd
```

Впишите `MQTT_USER` / `MQTT_PASSWORD` в `.env`, укажите те же данные в портале Qingping
и перезапустите: `docker compose up -d`.

## Обновление и данные

```bash
git pull
docker compose up -d --build
```

История хранится в `./data/climate.db` (30 дней по умолчанию). Для резервной копии достаточно
скопировать папку `data`.

## Разработка

```bash
pip install -r requirements-dev.txt
python -m pytest -q
./scripts/smoke-mqtt.sh   # проверка цепочки MQTT → бот → SQLite в Docker
```
