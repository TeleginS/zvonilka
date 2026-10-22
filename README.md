# zvonilka

Telegram-ассистент, который звонит в заведения от имени владельца. Собран по
спецификации [docs/calling-assistant-guide.deepseek.en.md](docs/calling-assistant-guide.deepseek.en.md):
бот на DeepSeek (или Claude), голосовой робот в Retell.

## Запуск

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

## Сервер

Скопировать проект в `/opt/zvonilka`, `uv sync`, положить `.env` (права 600),
поставить `deploy/zvonilka.service` в `/etc/systemd/system/` и включить:

```bash
sudo systemctl enable --now zvonilka
journalctl -u zvonilka -f
```
