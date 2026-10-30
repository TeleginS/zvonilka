# zvonilka

[Русский](README.md) | English

A Telegram assistant that phones businesses on its owner's behalf. Built from
the spec in [docs/calling-assistant-guide.deepseek.en.md](docs/calling-assistant-guide.deepseek.en.md):
the bot runs on DeepSeek (or Claude), the voice robot on Retell.

## Before you start

Accounts and keys you need to get yourself:

| What | Where | Why |
|------|-------|-----|
| Telegram bot | [@BotFather](https://t.me/BotFather) | bot token (`TELEGRAM_BOT_TOKEN`) |
| Your Telegram `chat_id` | e.g. [@userinfobot](https://t.me/userinfobot) | only chats in `ALLOWED_CHAT_IDS` can use the bot; the bot also logs the id of every chat it ignores |
| DeepSeek API key | [platform.deepseek.com](https://platform.deepseek.com) | the bot's LLM (default provider) |
| Anthropic API key (optional) | [console.anthropic.com](https://console.anthropic.com) | only to switch the bot to Claude (`LLM_PROVIDER=anthropic`) |
| Retell AI account | [retellai.com](https://www.retellai.com) | the calls themselves: telephony, speech recognition and synthesis, the conversation LLM |
| Phone number | Retell dashboard | a US (+1) number takes a couple of clicks, about $2/month, and reaches European businesses fine; your own European number needs SIP/Twilio |
| Google OAuth client (optional) | [console.cloud.google.com](https://console.cloud.google.com), Desktop type | read your calendar for free slots: client id, secret and a refresh token |
| VPS | any, 1 vCPU / 1 GB is enough; e.g. [Aeza](https://aeza.net/?ref=937107) (referral link) has 1 vCPU, 4 GB RAM, 10 GB NVMe for €2/month | the bot must run around the clock; no open ports needed |

Then fill in `.env` (see `.env.example`):

- `TELEGRAM_BOT_TOKEN`, `ALLOWED_CHAT_IDS` (comma-separated), `TIMEZONE`
  (IANA name, e.g. `Europe/Madrid`)
- `LLM_PROVIDER` and its key: `DEEPSEEK_API_KEY` or `ANTHROPIC_API_KEY`
- `RETELL_API_KEY`, `RETELL_FROM_NUMBER`, and the agent ids printed by
  `zvonilka-setup-agents` (`RETELL_AGENT_ID_ES` / `_EN` / `_RU`)
- the owner: `OWNER_NAME`, `OWNER_SURNAME`, the Cyrillic `OWNER_NAME_RU` /
  `OWNER_SURNAME_RU`, and `OWNER_PHONE` (your real phone: the robot gives it
  out when booking)
- optionally `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
  `GOOGLE_REFRESH_TOKEN`, `GOOGLE_CALENDAR_IDS`. With the client id and
  secret in `.env`, `uv run zvonilka-google-token` opens the Google sign-in
  and prints the refresh token. While the OAuth app is in Testing status the
  token expires after 7 days; publish the app to keep it

Calls are enabled only once the Retell key, the number and at least one agent
are set. `make env-check` shows which variables are set without printing them.

Cost, roughly: $0.5–1 per 3–5 minute call (almost all of it Retell), $2/month
for the number, from €2/month for the VPS; DeepSeek costs a fraction of a cent
per request.

## Getting started

The common commands live in the Makefile: `make help` lists them (tests,
Retell agents, local Docker, deploy, server logs and status, checking the
variables without printing their values).

```bash
uv sync
cp .env.example .env && chmod 600 .env   # fill it in
```

First run (section 9 of the spec):

1. Buy a number in Retell, set `RETELL_API_KEY` and `RETELL_FROM_NUMBER`.
2. Create the voice agents and put their ids into `.env`:
   ```bash
   uv run zvonilka-setup-agents        # all languages; or: uv run zvonilka-setup-agents es
   ```
3. Fill in the owner's details, `TIMEZONE`, and the DeepSeek key.
4. Check how the model parses requests (calls the real API, dials nobody):
   ```bash
   uv run zvonilka-routing-tests
   ```
5. Start the bot and send it "call me at <your number> and say hello":
   ```bash
   uv run zvonilka
   ```
6. Listen to the recording, adjust the prompt and voice in `zvonilka/robot.py`, apply:
   ```bash
   uv run zvonilka-sync-agents
   ```

## Where things are

| What | Where |
|------|-------|
| Robot prompt, voices, agent settings | `zvonilka/robot.py` |
| Call scenarios (intake + rules for the robot) | `scenarios/<name>.md` |
| How the bot questions the user | `.agents/skills/grilling/SKILL.md` |
| Bot tools and argument validation | `zvonilka/tools.py` |
| Tool-calling loop, confirmations | `zvonilka/assistant.py` |
| LLM client (DeepSeek / Claude) | `zvonilka/llm.py` |
| Call lifecycle and report | `zvonilka/calls.py`, `status.py`, `report.py` |
| Free slots from the calendar | `zvonilka/availability.py` |
| Scheduled calls | `zvonilka/scheduler.py` |
| Telegram | `zvonilka/bot.py` |

A new scenario is a new file in `scenarios/`: frontmatter with a description
and the required fields, plus `## Intake` and `## Playbook` sections. No code
changes needed.

## Tests

```bash
uv run pytest
```

Retell and the LLM are mocked in the tests; real calls follow the acceptance
scenarios in section 11 of the spec.

## Server: Docker

The image holds the code, `scenarios/` and the `grilling` skill. It contains
no secrets: variables come from `.env` at run time. The SQLite database lives
in the `zvonilka-data` volume.

Build and run in place:

```bash
docker compose up --build -d
docker compose logs -f
```

The scripts run in the same image:

```bash
docker compose run --rm bot zvonilka-setup-agents
docker compose run --rm bot zvonilka-sync-agents
docker compose run --rm bot zvonilka-routing-tests
```

Prebuilt image: on a version tag, GitHub Actions runs the tests and publishes
an amd64 and arm64 image to `ghcr.io/telegins/zvonilka`
(`.github/workflows/image.yml`):

```bash
git tag v0.1.0 && git push --tags
```

The server needs only `compose.yaml` and `.env`:

```bash
docker login ghcr.io            # if the package is private
docker compose pull && docker compose up -d
```

To ship to your own server without a registry, in one command (host from
`~/.ssh/config`, `my-server` by default): the script builds the image for the
server's architecture, sends it over SSH, updates `compose.yaml` and restarts
the bot.

The server's variables live in `.env.<host>` (e.g. `.env.my-server`), not in the
local `.env`: the local bot has its own token. The script uploads
`.env.<host>` when the server has no `.env` yet, or with `ENV_FILE=1`; it
never uploads the plain `.env`:

```bash
deploy/deploy.sh
ENV_FILE=1 deploy/deploy.sh   # after editing .env.my-server
```

To build for the server by hand on a Mac (a Mac builds arm64, most VPSs are amd64):

```bash
docker buildx build --platform linux/amd64 -t ghcr.io/telegins/zvonilka:latest --push .
```

Run one container per bot token: two instances on the same token steal each
other's messages, and the call scheduler lives inside the process.

## Server: systemd

Copy the project to `/opt/zvonilka`, run `uv sync`, add `.env` (mode 600),
put `deploy/zvonilka.service` into `/etc/systemd/system/` and enable it:

```bash
sudo systemctl enable --now zvonilka
journalctl -u zvonilka -f
```
