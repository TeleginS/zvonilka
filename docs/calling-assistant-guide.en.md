# A personal assistant that makes phone calls: a build specification

This document is written so that you can hand it as a whole to an AI coding
platform (Claude Code, Cursor, Codex, etc.) and say "build me this
assistant". There is no ready-made code here. There is everything you need to
know to write it: what the result should be, which services it uses, the
behavior rules, the settings, and the pitfalls to avoid.

How to use it:

1. Create the accounts and keys from section 2 (a human does this, not the AI).
2. Paste the whole document into a chat with a coding agent and add the
   starter prompt from section 10.
3. Check the result against the scenarios in section 11.

---

## 1. What the result should be

The user writes to a Telegram bot in plain text:

> call the restaurant "Name" +34 9xx xxx xxx, book a table for two tomorrow at 20:00

Then:

1. The assistant understands the task and builds a call brief: business name,
   number, call language, objective, details.
2. The bot shows the brief and asks for confirmation with «Да / Нет»
   ("Yes / No") buttons. The call does not start without «Да».
3. After «Да», the bot starts the call through the voice call service and
   immediately replies «Звоню, отчёт пришлю отдельно» ("Calling, I'll send the
   report separately"). The user can give other tasks while the conversation
   is in progress.
4. The voice robot calls from a rented number, introduces itself as the
   owner's assistant, speaks the required language, gets through phone menus,
   waits on hold, and makes the arrangement in the owner's name.
5. When the conversation is over, the bot sends a report: status, a short
   summary in Russian, duration, and the audio recording as a file.

Additionally:

- "call at 18:00" schedules the call; `/calls` shows pending calls with a
  cancel button;
- the robot knows the owner's free slots from Google Calendar and books only
  free time;
- `/memory <text>` adds facts about the owner to memory (phone, allergies,
  insurance policy number), and the robot uses them in the conversation.

Call languages: Spanish, English, Russian. Others are easy to add.

---

## 2. What to set up before you start (a human does this)

| What | Where | Why |
|------|-------|-----|
| Telegram bot | @BotFather | bot token; also find out your own `chat_id` |
| Anthropic API key | console.anthropic.com | the assistant's brain in the bot |
| Retell AI account | retellai.com | voice calls: telephony, speech recognition, speech synthesis, LLM for the conversation |
| Phone number | Retell dashboard | US numbers (+1) can be bought in a couple of clicks, about $2/month. Connecting your own European number goes through SIP/Twilio and is a separate hassle. A robot calling from a US number reaches Spanish restaurants and clinics just fine |
| Google OAuth (optional) | console.cloud.google.com, Desktop type | read the calendar for free slots |
| VPS | any, 1 vCPU / 1 GB | the bot must run around the clock |

Keep at hand: `TELEGRAM_BOT_TOKEN`, your `chat_id`, `ANTHROPIC_API_KEY`,
`RETELL_API_KEY`, the purchased number, and optionally the Google client id /
secret.

---

## 3. Architecture

```
User ⇄ Telegram ⇄ Bot on the server ⇄ Claude (Anthropic API)
                          │
                          ├── Google Calendar (free slots)
                          ├── local database (schedule, memory, dialog)
                          │
                          └── Retell AI ──► the business's phone
                              (agent = ears + brain + voice + telephony)
```

Key decision: **two different LLMs with different roles**.

- **Claude in the bot** parses the user's text, picks a tool, and builds the
  brief. It never speaks on the phone.
- **The LLM inside Retell** conducts the conversation itself, following an
  instruction set once when the voice agent is created. For a specific call it
  receives only substitutions into that instruction.

This split keeps conversational latency low and lets you tune the robot's
voice and behavior independently of the bot.

Recommended stack (replace with anything you like): Python,
`python-telegram-bot`, Claude Agent SDK (or the Messages API with tool use),
`retell-sdk`, SQLite, systemd. One process, no webhooks: Telegram via long
polling, Retell via polling. The server does not need public HTTPS.

---

## 4. The voice robot in Retell

### 4.1 How many agents and how they are created

One agent per language (es, en, ru). Each has its own prompt, its own voice,
and its own language code (`es-ES`, `en-US`, `ru-RU`). All agents use the same
purchased number.

Implementation requirement: agent prompts and settings live **in code**, not
in the dashboard. Two scripts are needed:

- `setup` — creates the agents once (LLM with prompt and tools → agent with
  voice and settings) and prints their ids for the config;
- `sync` — idempotently applies the current prompt, model, voice, and settings
  to the existing agents. Run it after every prompt change.

Without this, in a month nobody will remember what was changed and where.

### 4.2 Instructions for the robot (the prompt)

Data for the specific call is substituted into the prompt via `{{variables}}`
(list in 4.5). Below are the rules the prompt must contain, and why. Each one
was paid for with a failed call.

| Rule | Why |
|------|-----|
| "You are {{caller_name}}'s assistant, calling on their behalf. Introduce yourself: 'Hello, I'm {{caller_name}}'s assistant'. If asked whether you are a human, honestly say you are an AI assistant" | the robot acts on the owner's behalf but does not pretend to be human. In the EU this is a legal requirement (AI Act, Art. 50), and it's simply honest |
| "You are calling {{business_name}}. Objective: {{objective}}. Details: {{details}}" | the brief itself |
| "Make the booking in the name of {{caller_full_name}}; if asked for a contact phone, give {{caller_phone}}" | the business needs the owner's name and phone, not the robot's name |
| "About the owner: {{about_me}}. Answer questions about them ONLY from this data. If you don't know something (date of birth, policy number, address), don't make it up; say you'll check and get back to them" | otherwise the LLM confidently invents a date of birth and an address |
| "The owner's free slots: {{availability}}. Propose and confirm only times from these slots. If they offer another time or the list is empty, agree tentatively and say you'll check the schedule and call back if it doesn't work" | booking a busy slot is worse than not booking at all |
| "When on hold (music, 'all lines are busy', an answering system asking you to wait), stay on the line SILENTLY for as long as needed. NEVER hang up while waiting" | without this the robot hangs up at the first bar of music |
| "If a phone menu asks you to press a digit, use the press-digit tool and pick the option that leads to a live person (reception, appointments, operator). If unsure, press 0 or wait" | otherwise "para reservas, pulse 2" leaves the robot stuck |
| "If they suggest writing an email, going to the website, or calling back later, DO NOT agree. Politely say you'd like to settle it now by phone, ask to be connected to someone who can help, or to be kept on the line" | the standard way to brush off a caller |
| "If you reach voicemail that only records a message (not a hold queue), don't leave a message, silently hang up" | voicemail messages are useless |
| "Don't hang up right after the greeting or before the other party has answered. If you didn't catch something, ask them to repeat; never end the call because of poor audio" | drops in the first seconds |
| "Once the other party has confirmed the objective, say goodbye in ONE short phrase and immediately end the call with the tool. Never say 'ending the call' out loud. Don't drag out the goodbye, don't repeat thanks" | otherwise the robot stretches the goodbye for 30 seconds and voices its internal actions |
| "Be brief and polite, confirm details. If there are no openings, ask for alternatives" | basic manners |

On AI disclosure: it's tempting to write "never say you are a bot", because
some operators hang up. Don't do it: a robot posing as a human violates
Art. 50 of the AI Act, and fines from €500k are being discussed in Spain. If
they hang up, the call comes back without an arrangement, and you'll call
yourself.

For the Russian prompt: pass the owner's name in Cyrillic; TTS reads Latin
script with the wrong stress. If the owner is a woman, specify feminine
grammatical gender in the prompt.

### 4.3 The robot's tools

Exactly two, both required:

- **end call** (`end_call`) — without it the robot can't finish the conversation;
- **press digit** (`press_digit`) — without it the robot can't get through phone menus.

### 4.4 Agent settings

Duration and silence:

| Parameter | Value | Why |
|-----------|-------|-----|
| maximum call duration | 2 hours (Retell's ceiling) | wait for an operator "until the end" |
| end call on silence | 2 hours, equal to the maximum duration | **hold music does not reset the silence timer**: with the default, the call dropped after 15 s with reason `inactivity` |
| reminder on silence | after 30 s, at most once | the default of ~10 s made the robot re-greet during pauses |

Voice and latency (tuned on test calls, a starting point):

| Language | Voice | Voice model | Speed | Recognition |
|----------|-------|-------------|-------|-------------|
| es | `retell-Andrea` (MiniMax, platform voice) | default | 0.9 | fast |
| en | `11labs-Lily` | `eleven_v3` | 1.0 | fast |
| ru | `11labs-Lily` | `eleven_multilingual_v2` | 1.1 | accurate |

What we learned: a voice can only be chosen by listening. For Spanish, Cartesia
sounded robotic and `eleven_v3` rattled along too fast. For Russian there is no
native voice, so a multilingual ElevenLabs voice is used, but `eleven_v3` makes
Russian sound robotic.

Other agent settings: `coffee-shop` background noise (volume 1.5 for es, 0.3
for the others; it masks the synthetic silence between turns), backchanneling
enabled at frequency 0.3 (0.8 got in the way), `responsiveness` 1, interruption
sensitivity 0.6, expressive mode enabled, dynamic speed and dynamic
responsiveness disabled.

Conversation LLM: Claude Sonnet (inside Retell). Priority LLM queue enabled for
es and en: together with fast recognition mode this cut response latency from
2.3 to 1.7 s. Haiku is another 0.7 s faster, but its phrasing is drier and it
slipped into re-greeting.

### 4.5 What is passed into the call (dynamic variables)

When each call starts, the agent receives substitutions:

- `business_name`, `objective`, `details` — from the brief;
- `caller_name`, `caller_full_name`, `caller_phone` — from the owner config
  (the Cyrillic form of the name for ru);
- `about_me` — the owner's entire memory text;
- `availability` — free slots from the calendar, format in 7.1.

Plus call metadata: the language, so you can later tell which agent made the
call.

### 4.6 Summary in Russian

Retell's built-in summary is English-only. You need a custom post-call analysis
field `summary_ru` with the description: "A short summary of the conversation
STRICTLY in Russian (1–2 sentences): objective, outcome, key arrangements. Only
in Russian, even if the conversation was in another language." Use it in the
report, falling back to the English one if it's missing.

---

## 5. The assistant in the bot and the "call" tool

### 5.1 How the assistant works

Claude with the system prompt "you are the user's personal assistant in
Telegram, reply briefly, in Russian" and a set of tools. Call-related details:

- the owner's time zone and the current time are passed with every message;
- dialog context persists between messages (one session per chat); after a
  pause of more than 2 hours a new one starts;
- before irreversible and externally visible actions, the system asks the user
  for confirmation; the assistant must not duplicate that question in text.

### 5.2 The `place_call` tool

Parameters:

| Parameter | Type | Description for the model |
|-----------|------|---------------------------|
| `business_name` | string | business name |
| `to_number` | string | number in E.164 format (+34…) |
| `language` | `es` / `en` / `ru` | conversation language |
| `objective` | string | call objective |
| `details` | string | details: date, time, number of people, name, what to ask |
| `when` | string, ISO datetime | **only** if the user explicitly named a future time ("at 18:00", "tomorrow at 10", "in an hour"). If they said "now" or named no time, do not pass it at all; the call goes out immediately |
| `availability_from` | string, ISO date | start of the period in which the booking is needed. **Only** if the booking is explicitly not for the near term ("book something in October" → October 1st). Otherwise do not pass it |

The "only" and "do not pass" wording in the tool description matters: without
it the model scheduled calls "for now" and passed `availability_from` for every
booking.

Behavior:

- `when` in the future (more than a minute ahead) → add to the schedule, return
  «Звонок запланирован на …» ("Call scheduled for …");
- otherwise → start the call **and return immediately** «Звоню, отчёт пришлю
  отдельно» ("Calling, I'll send the report separately"). The tool does not
  wait for the conversation to end.

### 5.3 Confirmation

`place_call` is on the list of tools that require confirmation. Before the
call, the bot shows the tool name and its arguments in Telegram with
«✅ Да / ❌ Нет» ("Yes / No") buttons and waits for a tap. «Нет» returns the
user's refusal to the model. This way the owner sees the number, language, and objective before
anyone picks up the phone.

---

## 6. Call lifecycle

### 6.1 Why the tool is non-blocking

A call can last an hour (waiting for an operator). If the tool waits for the
result, the chat is blocked and the agent loop hits a timeout. So the tool
returns immediately, and the call id is handed to a background task in the bot
that watches the call and sends the report as a separate message.

### 6.2 Polling the call

- Poll the status every 5 s while the call is in progress. The wait ceiling is
  slightly above the maximum call duration (2 h + margin); once it expires,
  treat the status as `timeout`.
- After the call ends, Retell takes a few more seconds to compute the post-call
  analysis (summary, success flag). **Wait for it** in a separate loop (up to
  ~12 attempts, 5 s apart) for calls with non-zero duration, otherwise the
  report goes out empty.

### 6.3 Status normalization

Retell returns three different fields: call status, disconnection reason, and
post-call analysis (success, whether voicemail was reached). Reduce them to a
single status using these rules, in this order:

| Condition | Status |
|-----------|--------|
| call status `error` | `failed` |
| status `not_connected` | `no_answer` |
| status not `ended` | `in_progress` |
| analysis says "voicemail" or reason `voicemail_reached` | `voicemail` |
| reason `dial_busy` / `dial_failed` / `dial_no_answer` | `no_answer` |
| reason `max_duration_reached` | `timeout` |
| analysis says "successful" | `success` |
| otherwise | `completed` |

And on top of that: **if the call is shorter than 10 seconds, a `success` or
`completed` status is downgraded to `too_short`**. Retell sometimes marks a
three-second call where nobody picked up as "successful" and invents a summary.
Without this rule the user gets «✅ Готово, столик забронирован» ("Done, table
booked") for a call that never happened.

### 6.4 Report in Telegram

Header by status:

| Status | Text | Meaning |
|--------|------|---------|
| `success` | ✅ Готово | Done |
| `completed` | ☑️ Дозвонились, разговор завершён | Got through, conversation finished |
| `too_short` | ⚠️ Звонок слишком короткий, вероятно, не удался. Проверь запись | Call too short, probably failed. Check the recording |
| `voicemail` | 📭 Попали на автоответчик | Reached voicemail |
| `no_answer` | 📵 Не дозвонились (занято / нет ответа) | Couldn't get through (busy / no answer) |
| `timeout` | ⏱ Звонок прерван по таймауту | Call cut off by timeout |
| `failed` | ❌ Звонок не удался | Call failed |

Then the summary (`summary_ru`), the duration in seconds, and, as a separate
message, the audio recording: download it from the Retell link and send it as
audio, or as a document if that fails.

---

## 7. Context for the conversation

### 7.1 Free slots from the calendar

- Fetch events from all of the owner's calendars for 14 days ahead (or starting
  from `availability_from`).
- Working window 09:00–21:00 in the owner's time zone; subtract busy time;
  drop slots shorter than 30 minutes; treat today's elapsed time as busy.
- Format for the prompt, one line per day, skipping fully busy days:

```
2026-09-11 (Fri): 09:00–12:30, 15:00–21:00
2026-09-12 (Sat): 10:00–21:00
```

- Calendar unavailable → pass an **empty string**, not "the whole day is
  free". On an empty list the prompt switches to tentative-agreement mode. A
  calendar error must never break the call.

### 7.2 Memory about the owner

The `/memory <text>` command modifies a single profile record: "date of birth
is such-and-such", "allergic to nuts", "policy number is such-and-such",
"forget about the allergy". The merge is done by a cheap model (Haiku) with the
instruction: return only the updated list of short facts, one per line, keeping
old facts unless the instruction explicitly cancels them. `/memory` without
text shows the current memory. The entire memory text goes into
`{{about_me}}`.

---

## 8. Scheduled calls

- A table in the local database: chat, business, number, language, objective,
  details, trigger time, status (`pending` / `done` / `cancelled` / `missed`).
- On scheduling — a timer job for the required time with a ~5 minute
  tolerance for lateness.
- On trigger — run the whole call (start + polling), send the report and the
  recording, mark `done`. On error — report «не удалось выполнить
  запланированный звонок» ("failed to run the scheduled call").
- On bot startup, re-read `pending`: put future ones on the timer, mark overdue
  ones `missed` and post to the chat «⚠️ Пропущен запланированный звонок в …
  (на …), бот был офлайн» ("Missed scheduled call at … (to …), the bot was
  offline").
- `/calls` — a list of pending calls with a «❌ Отменить» ("Cancel") button on each;
  cancelling removes the timer and marks the call `cancelled`.
- Interpret a `when` time without an offset in the owner's time zone.

---

## 9. Deployment and configuration

Environment variables:

```
TELEGRAM_BOT_TOKEN, ALLOWED_CHAT_IDS (comma-separated), TIMEZONE
ANTHROPIC_API_KEY
RETELL_API_KEY, RETELL_FROM_NUMBER (+1…, purchased in Retell)
RETELL_AGENT_ID_ES, RETELL_AGENT_ID_EN, RETELL_AGENT_ID_RU
OWNER_NAME, OWNER_SURNAME, OWNER_NAME_RU, OWNER_SURNAME_RU
OWNER_PHONE (the owner's real phone: the robot gives it out for bookings)
GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN, GOOGLE_CALENDAR_IDS
```

Calls are enabled only when the Retell key, the number, and at least one agent
are set; otherwise the `place_call` tool is not registered.

Running: a systemd service with auto-restart, `.env` with mode 600, logs in the
journal. The bot responds only to chats in `ALLOWED_CHAT_IDS`.

First-run order:

1. Buy a number in Retell, fill in the key and the number.
2. Run `setup`, fill in the agent ids.
3. Fill in the owner's details and time zone.
4. Start the bot, write "call me at <your number> and say hello".
5. Listen to the recording, adjust the prompt and voice, run `sync`, repeat.
   Expect 5–10 test calls per language before the result is acceptable.

---

## 10. Starter prompt for the coding agent

> Build me a Telegram assistant following the specification below. Stack:
> Python, python-telegram-bot, Claude Agent SDK, retell-sdk, SQLite. Start with
> the voice agent in Retell (section 4) and the setup/sync scripts, then the
> place_call tool with confirmation (section 5), then the call lifecycle and
> report (section 6), then calendar and memory (section 7), then scheduled
> calls (section 8). Write tests for each block with Retell mocked out; I'll
> make the real calls myself. Take the keys from .env, and create a
> .env.example template.

---

## 11. Acceptance scenarios

Run manually after the build, against your own number and a couple of real
businesses:

- [ ] "call me at <number> and say hello" → a «Да/Нет» prompt appears; after
  «Да» the call goes out, the report and recording arrive as a separate
  message.
- [ ] Tap «Нет» → no call, the assistant responds calmly.
- [ ] Don't pick up → status `no_answer`, not «✅ Готово».
- [ ] Pick up and immediately hang up → `too_short`.
- [ ] Turn on voicemail → `voicemail`, no message left on it.
- [ ] Put it on hold for 3 minutes with music → the robot waits, doesn't hang
  up, doesn't re-greet.
- [ ] Ask the robot "are you a bot?" → answers honestly.
- [ ] Ask for a date of birth that isn't in memory → "I'll check and get back
  to you", doesn't make it up.
- [ ] Add a fact via `/memory`, ask about it during a call → it gives it.
- [ ] Propose a time that's busy in the calendar → agrees tentatively and
  promises to call back.
- [ ] "call in 3 minutes" → there's an entry in `/calls`, the call goes out on
  time, the report arrives.
- [ ] Restart the bot with a pending call → the call isn't lost; with an
  overdue one → a «Пропущен…» ("missed") message.
- [ ] While a call is in progress, give the bot another task → it responds
  without waiting for the call to end.
- [ ] The report summary is in Russian, even if the conversation was in
  Spanish.

---

## 12. Pitfall checklist

All from real calls. Check that the coding agent took these into account:

- [ ] Silence timer equals the maximum duration, otherwise the call drops on hold music.
- [ ] Press-digit tool and the phone menu rule in the prompt.
- [ ] The "don't agree to email / website / call back later" rule.
- [ ] Voicemail → hang up silently.
- [ ] `too_short`: a call shorter than 10 s can't be successful.
- [ ] Wait for post-call analysis after the call ends, otherwise the summary is empty.
- [ ] Custom `summary_ru`; the built-in summary is English-only.
- [ ] Cyrillic name for the Russian agent.
- [ ] "Don't make things up" and memory via `/memory`.
- [ ] Empty availability ≠ a fully free day.
- [ ] The tool doesn't block the assistant; the report comes as a separate message.
- [ ] Confirmation with buttons before dialing.
- [ ] `when` only for an explicitly future time.
- [ ] Scheduled calls survive a restart; overdue ones are marked.
- [ ] Agent prompts and settings in code, plus a `sync` script.
- [ ] The robot introduces itself as an assistant and honestly says it's an AI.

---

## 13. Cost

Ballpark for a 3–5 minute call: Retell (telephony, recognition, synthesis, LLM)
about $0.5–1, the number about $2 per month, plus pennies of Anthropic usage
for parsing the task in the bot, plus a VPS at $6–12 per month. An hour of
waiting on hold costs correspondingly more; the 2-hour ceiling is set
deliberately.

---

## 14. How to extend

- **A different voice provider** (Vapi, Bland, your own pipeline on Twilio +
  Deepgram + Claude): keep the provider behind a "start call / get status"
  interface, normalize its statuses into the table from 6.3, and nothing else
  changes.
- **A new language**: a prompt, a voice, a language code, one more agent, and a
  variable with its id.
- **Inbound calls**: Retell supports them, but they need a webhook, i.e. public
  HTTPS, which this design deliberately does without.
- **Retry on no answer**: on `no_answer` status, schedule the call again in
  15 minutes.
