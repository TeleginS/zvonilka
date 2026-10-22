# zvonilka

Telegram-ассистент, который звонит в заведения от имени владельца. Собран по
спецификации [docs/calling-assistant-guide.deepseek.en.md](docs/calling-assistant-guide.deepseek.en.md):
бот на DeepSeek (или Claude), голосовой робот в Retell.

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
по умолчанию `aeza`): скрипт соберёт образ под архитектуру сервера, передаст
его по SSH, обновит `compose.yaml` и перезапустит бота.

Переменные сервера лежат в `.env.<хост>` (например, `.env.aeza`), а не в
локальном `.env`: у локального бота свой токен. Скрипт загружает
`.env.<хост>`, если на сервере `.env` ещё нет, или с `ENV_FILE=1`; обычный
`.env` он не загружает никогда:

```bash
deploy/deploy.sh
ENV_FILE=1 deploy/deploy.sh   # после правки .env.aeza
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
