# zvonilka

Русский | [English](README.en.md)

Telegram-ассистент, который звонит в заведения от имени владельца. Собран по
спецификации [docs/calling-assistant-guide.deepseek.en.md](docs/calling-assistant-guide.deepseek.en.md):
бот на DeepSeek (или Claude), голосовой робот в Retell. Русская версия
спецификации (редакция с Claude): [docs/calling-assistant-guide.ru.md](docs/calling-assistant-guide.ru.md).

## Что подготовить до старта

Аккаунты и ключи, которые нужно получить самому:

| Что | Где | Зачем |
|-----|-----|-------|
| Telegram-бот | [@BotFather](https://t.me/BotFather) | токен бота (`TELEGRAM_BOT_TOKEN`) |
| Свой `chat_id` в Telegram | например, [@userinfobot](https://t.me/userinfobot) | бот отвечает только чатам из `ALLOWED_CHAT_IDS`; id каждого чата, которому он отказал, бот пишет в лог |
| Ключ DeepSeek API | [platform.deepseek.com](https://platform.deepseek.com) | LLM бота (провайдер по умолчанию) |
| Ключ Anthropic API (опционально) | [console.anthropic.com](https://console.anthropic.com) | только чтобы перевести бота на Claude (`LLM_PROVIDER=anthropic`) |
| Аккаунт Retell AI | [retellai.com](https://www.retellai.com) | сами звонки: телефония, распознавание и синтез речи, LLM для разговора |
| Номер телефона | панель Retell | американский номер (+1) покупается в пару кликов, около $2 в месяц, и до европейских заведений дозванивается нормально; свой европейский номер подключается через SIP/Twilio |
| Google OAuth-клиент (опционально) | [console.cloud.google.com](https://console.cloud.google.com), тип Desktop | читать календарь для свободных окон: client id, secret и refresh token |
| VPS | любой, хватит 1 vCPU / 1 GB; например, у [Aeza](https://aeza.net/?ref=937107) (реферальная ссылка) есть 1 vCPU, 4 GB RAM, 10 GB NVMe за €2 в месяц | бот должен работать круглосуточно; открытые порты не нужны |

Затем заполнить `.env` (образец в `.env.example`):

- `TELEGRAM_BOT_TOKEN`, `ALLOWED_CHAT_IDS` (через запятую), `TIMEZONE`
  (имя из базы IANA, например `Europe/Madrid`)
- `LLM_PROVIDER` и ключ к нему: `DEEPSEEK_API_KEY` или `ANTHROPIC_API_KEY`
- `RETELL_API_KEY`, `RETELL_FROM_NUMBER` и id агентов, которые напечатает
  `zvonilka-setup-agents` (`RETELL_AGENT_ID_ES` / `_EN` / `_RU`)
- владелец: `OWNER_NAME`, `OWNER_SURNAME`, кириллицей `OWNER_NAME_RU` /
  `OWNER_SURNAME_RU` и `OWNER_PHONE` (ваш настоящий телефон: робот диктует
  его при бронировании)
- опционально `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
  `GOOGLE_REFRESH_TOKEN`, `GOOGLE_CALENDAR_IDS`. Когда client id и secret уже
  в `.env`, `uv run zvonilka-google-token` откроет вход в Google и напечатает
  refresh token. Пока OAuth-приложение в статусе Testing, токен живёт 7 дней;
  чтобы он не истекал, опубликуйте приложение

Звонки включаются, только когда заданы ключ Retell, номер и хотя бы один
агент. `make env-check` покажет, какие переменные заданы, не выводя значений.

Сколько стоит, примерно: $0.5–1 за звонок на 3–5 минут (почти всё — Retell),
$2 в месяц за номер, VPS от €2 в месяц; DeepSeek — доли цента за запрос.

## Запуск

Все частые команды собраны в Makefile: `make help` покажет список (тесты,
агенты Retell, локальный Docker, деплой, логи и статус на сервере, проверка
переменных без вывода значений).

```bash
uv sync
cp .env.example .env && chmod 600 .env   # заполнить
```

Первый запуск (раздел 9 спецификации):

1. Купить номер в Retell, вписать `RETELL_API_KEY` и `RETELL_FROM_NUMBER`.
2. Создать голосовых агентов и вписать их id в `.env`:
   ```bash
   uv run zvonilka-setup-agents        # все языки; или: uv run zvonilka-setup-agents es
   ```
3. Заполнить данные владельца, `TIMEZONE`, ключ DeepSeek.
4. Проверить, как модель разбирает запросы (ходит в настоящий API, никуда не звонит):
   ```bash
   uv run zvonilka-routing-tests
   ```
5. Запустить бота и написать ему «позвони мне на <свой номер> и скажи привет»:
   ```bash
   uv run zvonilka
   ```
6. Послушать запись, поправить промпт и голос в `zvonilka/robot.py`, применить:
   ```bash
   uv run zvonilka-sync-agents
   ```

## Где что лежит

| Что | Где |
|-----|-----|
| Промпт робота, голоса, настройки агентов | `zvonilka/robot.py` |
| Сценарии звонков (опрос + правила для робота) | `scenarios/<name>.md` |
| Метод опроса пользователя | `.agents/skills/grilling/SKILL.md` |
| Инструменты бота и проверка аргументов | `zvonilka/tools.py` |
| Цикл вызова инструментов, подтверждения | `zvonilka/assistant.py` |
| Клиент LLM (DeepSeek / Claude) | `zvonilka/llm.py` |
| Жизненный цикл звонка и отчёт | `zvonilka/calls.py`, `status.py`, `report.py` |
| Свободные окна из календаря | `zvonilka/availability.py` |
| Отложенные звонки | `zvonilka/scheduler.py` |
| Telegram | `zvonilka/bot.py` |

Новый сценарий — это новый файл в `scenarios/`: frontmatter с описанием и
обязательными полями, разделы `## Intake` и `## Playbook`. Код менять не нужно.

## Тесты

```bash
uv run pytest
```

Retell и LLM в тестах подменены; настоящие звонки — по сценариям приёмки из
раздела 11 спецификации.

## Сервер: Docker

Образ содержит код, `scenarios/` и скилл `grilling`. Секретов в нём нет:
переменные берутся из `.env` при запуске. База SQLite лежит в томе
`zvonilka-data`.

Собрать и запустить на месте:

```bash
docker compose up --build -d
docker compose logs -f
```

Скрипты запускаются в том же образе:

```bash
docker compose run --rm bot zvonilka-setup-agents
docker compose run --rm bot zvonilka-sync-agents
docker compose run --rm bot zvonilka-routing-tests
```

Готовый образ: по тегу версии GitHub Actions прогоняет тесты и публикует
образ для amd64 и arm64 в `ghcr.io/telegins/zvonilka`
(`.github/workflows/image.yml`):

```bash
git tag v0.1.0 && git push --tags
```

На сервере нужны только `compose.yaml` и `.env`:

```bash
docker login ghcr.io            # если пакет приватный
docker compose pull && docker compose up -d
```

Выложить на свой сервер без registry, одной командой (хост из `~/.ssh/config`,
по умолчанию `my-server`): скрипт соберёт образ под архитектуру сервера, передаст
его по SSH, обновит `compose.yaml` и перезапустит бота.

Переменные сервера лежат в `.env.<хост>` (например, `.env.my-server`), а не в
локальном `.env`: у локального бота свой токен. Скрипт загружает
`.env.<хост>`, если на сервере `.env` ещё нет, или с `ENV_FILE=1`; обычный
`.env` он не загружает никогда:

```bash
deploy/deploy.sh
ENV_FILE=1 deploy/deploy.sh   # после правки .env.my-server
```

Собрать для сервера вручную с Mac (Mac собирает arm64, большинство VPS — amd64):

```bash
docker buildx build --platform linux/amd64 -t ghcr.io/telegins/zvonilka:latest --push .
```

Запускайте один контейнер на один токен бота: два экземпляра с одним токеном
мешают друг другу получать сообщения, а планировщик звонков живёт внутри процесса.

## Сервер: systemd

Скопировать проект в `/opt/zvonilka`, `uv sync`, положить `.env` (права 600),
поставить `deploy/zvonilka.service` в `/etc/systemd/system/` и включить:

```bash
sudo systemctl enable --now zvonilka
journalctl -u zvonilka -f
```
