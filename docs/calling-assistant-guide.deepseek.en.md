# A personal assistant that makes phone calls: a build specification (DeepSeek edition)

This document is written so that you can hand it as a whole to an AI coding
platform (Claude Code, Cursor, Codex, etc.) and say "build me this
assistant". There is no ready-made code here. There is everything you need to
know to write it: what the result should be, which services it uses, the
behavior rules, the settings, and the pitfalls to avoid.

This edition differs from the base guide in one place: the LLM in the bot runs
on the **DeepSeek API** by default, with Anthropic Claude kept as a switchable
alternative. The changes are in sections 2, 3, 5, 7.2, 9, 10, 11, 12, and 13,
and the details are collected in section 5.4. The voice robot in Retell does not
change (see 3 for why).

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
  insurance policy number), and the robot uses them in the conversation;
- a call to a real estate agent about a rental listing ("call the agent about
  the flat on Idealista, ref. 12345, Carrer de Mallorca, €1,400") checks
  whether the flat is still available, collects the conditions, and books a
  viewing (4.7).

Call languages: Spanish, English, Russian. Others are easy to add.

---

## 2. What to set up before you start (a human does this)

| What | Where | Why |
|------|-------|-----|
| Telegram bot | @BotFather | bot token; also find out your own `chat_id` |
| DeepSeek API key | platform.deepseek.com | the assistant's brain in the bot (default provider) |
| Anthropic API key (optional) | console.anthropic.com | only if you want to switch the bot to Claude |
| Retell AI account | retellai.com | voice calls: telephony, speech recognition, speech synthesis, LLM for the conversation |
| Phone number | Retell dashboard | US numbers (+1) can be bought in a couple of clicks, about $2/month. Connecting your own European number goes through SIP/Twilio and is a separate hassle. A robot calling from a US number reaches Spanish restaurants and clinics just fine |
| Google OAuth (optional) | console.cloud.google.com, Desktop type | read the calendar for free slots |
| VPS | any, 1 vCPU / 1 GB | the bot must run around the clock |

Keep at hand: `TELEGRAM_BOT_TOKEN`, your `chat_id`, `DEEPSEEK_API_KEY`
(optionally `ANTHROPIC_API_KEY`), `RETELL_API_KEY`, the purchased number, and
optionally the Google client id / secret.

---

## 3. Architecture

```
User ⇄ Telegram ⇄ Bot on the server ⇄ Bot LLM: DeepSeek API (default)
                          │                     or Anthropic API (switch)
                          │
                          ├── Google Calendar (free slots)
                          ├── local database (schedule, memory, dialog)
                          │
                          └── Retell AI ──► the business's phone
                              (agent = ears + brain + voice + telephony)
```

Key decision: **two different LLMs with different roles**.

- **The bot LLM** (DeepSeek or Claude) parses the user's text, picks a tool,
  and builds the brief. It never speaks on the phone.
- **The LLM inside Retell** conducts the conversation itself, following an
  instruction set once when the voice agent is created. For a specific call it
  receives only substitutions into that instruction.

This split keeps conversational latency low and lets you tune the robot's
voice and behavior independently of the bot. It also means the bot provider
can be swapped without touching the voice robot.

Why the voice robot stays on a Retell-hosted model: Retell does not offer
DeepSeek models in its built-in LLM list. The only way to plug DeepSeek into
the call itself is Retell's custom LLM mode, where Retell connects to your
server over a WebSocket. That needs a public endpoint (this design
deliberately has none), and every turn of the conversation adds a round trip
to your server and on to DeepSeek. The model inside Retell is billed by
Retell, so it does not need an Anthropic account.

Recommended stack (replace with anything you like): Python,
`python-telegram-bot`, the `anthropic` Python SDK (Messages API with tool
use) plus your own tool loop, `retell-sdk`, SQLite, systemd. One process, no
webhooks: Telegram via long polling, Retell via polling. The server does not
need public HTTPS.

Why the Anthropic SDK for DeepSeek: DeepSeek serves an Anthropic-compatible
endpoint (`https://api.deepseek.com/anthropic`). Both providers then speak the
same Messages API format, and switching between them means changing the base
URL, the key, and the model name. There is one code path and one set of tool
definitions. Details in 5.4.

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
| "Additional rules for this type of call (may be empty): {{playbook}}. Where they conflict with the rules above, they take priority" | rules for specific call types without a separate agent per type (4.7) |

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

Conversation LLM: Claude Sonnet (inside Retell, billed by Retell). Priority LLM
queue enabled for es and en: together with fast recognition mode this cut
response latency from 2.3 to 1.7 s. Haiku is another 0.7 s faster, but its
phrasing is drier and it slipped into re-greeting. DeepSeek is not available
here; see section 3.

### 4.5 What is passed into the call (dynamic variables)

When each call starts, the agent receives substitutions:

- `business_name`, `objective`, `details` — from the brief;
- `caller_name`, `caller_full_name`, `caller_phone` — from the owner config
  (the Cyrillic form of the name for ru);
- `about_me` — the owner's entire memory text;
- `availability` — free slots from the calendar, format in 7.1;
- `playbook` — the rules for the call's scenario, empty for `general` (4.7).

Plus call metadata: the language, so you can later tell which agent made the
call.

### 4.6 Summary in Russian

Retell's built-in summary is English-only. You need a custom post-call analysis
field `summary_ru` with the description: "A short summary of the conversation
STRICTLY in Russian (1–2 sentences): objective, outcome, key arrangements. Only
in Russian, even if the conversation was in another language." Use it in the
report, falling back to the English one if it's missing.

A second custom field, `facts_ru`: "Concrete facts learned in the call,
STRICTLY in Russian, one per line: prices, dates and times, conditions,
requirements, names, agreed next steps. Empty if nothing concrete was
learned." The summary says how the call went; this field keeps the details
that don't fit into two sentences (for a rental call: rent, deposit, fees,
viewing time).

### 4.7 Scenario playbooks

Some call types need rules on top of the general prompt. They live in code as
playbooks: one text block per scenario, chosen by the `scenario` parameter of
`place_call` (5.2) and passed into the call as `{{playbook}}`. This keeps one
agent per language instead of one per language and scenario. `general` has an
empty playbook. A new scenario is a scenario file with an intake and a
playbook (5.5), a new `scenario` value, and a new acceptance scenario.

Unlike the rules in 4.2, the playbook below hasn't been tested on real calls
yet. Treat it as a starting point and tune it the same way (5–10 test calls).

**`rental_inquiry`: calling a real estate agent about a rental listing**

| Rule | Why |
|------|-----|
| "Start by naming the listing: reference, address or area, price, and where it was published (from {{details}})" | an agency handles dozens of flats; without this they can't tell which one you mean |
| "Find out, in this order, only what isn't already in {{details}}: whether the flat is still available; the monthly rent and what it includes (community fees, utilities); the deposit (fianza) and any additional guarantee; agency fees and who pays them; contract type and minimum term (long-term or temporary); the earliest move-in date; furnished or not; whether pets are allowed; which documents they need" | the deal-breaker goes first; if the flat is gone, the rest doesn't matter |
| "If the flat is available, propose a viewing in the owner's free slots. If it isn't, ask whether they have something similar in the same area and price range, and note it" | a viewing is the real result of the call; an "it's gone" call can still produce leads |
| "Answer questions about the tenant (job, contract type, income, who will live there, pets) ONLY from {{about_me}}. Whatever isn't there, the owner will send with the documents" | agents screen tenants on the first call; an invented income is worse than "I'll send it" |
| "Agreeing to send documents or details afterwards by email or WhatsApp is fine: give {{caller_phone}} or the email from {{about_me}}. But availability and the viewing are settled on this call" | here sending documents is the normal next step, not a brush-off; this rule overrides the general "don't agree to email" rule |
| "Don't commit to anything: don't agree to rent, don't accept the price, don't agree to pay a reservation deposit (señal) or any fee, don't give bank or card details. Say the owner will decide after the viewing" | the robot collects information and books viewings; deciding and paying are the owner's job |
| "If they answer in Catalan, politely ask whether you can continue in Spanish" | Barcelona agencies sometimes answer in Catalan, and the es agent is set up for Spanish |

The viewing is not added to the calendar automatically: the bot has read-only
access (7.1). Add it yourself from the report.

What the owner should know about Spanish rental rules (check that they are
still current; the robot doesn't argue with the agent, it only records the
answers): since Ley 12/2023, for a long-term rental of a primary home the
agency fees are paid by the landlord, not the tenant; the legal deposit for a
home is one month's rent, and an additional guarantee is capped at two months'
rent for contracts of up to five years. Temporary rentals (alquiler de
temporada) don't fall under these rules, which is one reason agencies offer
them. The answers about fees and contract type end up in `facts_ru`, so you see
them before the viewing.

---

## 5. The assistant in the bot and the "call" tool

### 5.1 How the assistant works

The bot LLM with the system prompt "you are the user's personal assistant in
Telegram, reply briefly, in Russian" and a set of tools. Call-related details:

- the owner's time zone and the current time are passed with every message,
  in the user message, not in the system prompt (keeps the prompt prefix
  stable for caching, see 5.4);
- dialog context persists between messages (one session per chat); after a
  pause of more than 2 hours a new one starts. With your own tool loop the bot
  stores the message history itself (SQLite, per chat), including the
  `tool_use` / `tool_result` blocks, and trims the oldest turns when the
  history gets long;
- before irreversible and externally visible actions, the tool loop asks the
  user for confirmation (5.3); the assistant must not duplicate that question
  in text.

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
| `scenario` | `general` / `rental_inquiry` | `rental_inquiry` for a call to a real estate agent or a landlord about renting a home; `general` for everything else. For `rental_inquiry`, `details` must include the listing's reference, address or area, price, and where it was published, plus the owner's requirements (move-in date, budget, questions). If the user didn't give the reference or the address, ask for them before calling (intake, 5.5) |

The "only" and "do not pass" wording in the tool description matters: without
it the model scheduled calls "for now" and passed `availability_from` for every
booking. This wording was tuned on Claude; re-check it on DeepSeek with the
routing tests from 5.4.

Validate the arguments in code before showing the confirmation, whatever the
provider: `to_number` matches E.164, `language` is one of the enum values,
`when` and `availability_from` parse as dates. Treat an empty string, `null`,
or a value like `"now"` in `when` / `availability_from` as "not passed". On
invalid arguments, return the error to the model as the tool result so it can
fix the call, and don't ask the user.

Behavior:

- `when` in the future (more than a minute ahead) → add to the schedule, return
  «Звонок запланирован на …» ("Call scheduled for …");
- otherwise → start the call **and return immediately** «Звоню, отчёт пришлю
  отдельно» ("Calling, I'll send the report separately"). The tool does not
  wait for the conversation to end.

### 5.3 Confirmation

`place_call` is on the list of tools that require confirmation. When the model
returns a `tool_use` block for such a tool, the loop does not execute it right
away. It shows the tool name and its arguments in Telegram with
«✅ Да / ❌ Нет» ("Yes / No") buttons and waits for a tap. «Нет» returns the
user's refusal to the model as the tool result. This way the owner sees the
number, language, and objective before anyone picks up the phone.

The refusal text must say it plainly, for example "The user declined this
call. Do not call again unless the user asks." DeepSeek ignores the
`is_error` flag on tool results (5.4), so the flag alone is not enough.

### 5.4 Bot LLM providers: DeepSeek and Claude

The bot talks to the LLM through one client in the Anthropic Messages API
format. The provider is chosen by config:

| | DeepSeek (default) | Anthropic |
|---|---|---|
| base URL | `https://api.deepseek.com/anthropic` | SDK default |
| key | `DEEPSEEK_API_KEY` | `ANTHROPIC_API_KEY` |
| assistant model | `deepseek-flash` | a current Claude Sonnet |
| memory merge model (7.2) | `deepseek-flash` | a current Claude Haiku |
| thinking | explicitly disabled | not requested |

Model names change; check the current list at api-docs.deepseek.com before
setting the defaults. `deepseek-v4-pro` is the larger model; use it only if
`deepseek-flash` routes tasks badly on your tests.

What differs on DeepSeek, and what the code must account for:

- **Thinking mode.** DeepSeek models can think before answering, and on its
  OpenAI-format endpoint thinking is on by default. Parsing a call request
  doesn't need it, and it adds seconds to every reply. Pass
  `thinking: {"type": "disabled"}` explicitly; don't rely on the default.
- **`is_error` on tool results is ignored.** Put the meaning into the result
  text: "Error: …", "The user declined …".
- **`disable_parallel_tool_use` is ignored.** The model may return several
  `tool_use` blocks in one response. The loop must handle all of them, return a
  `tool_result` for every `tool_use` id, and ask for confirmation for each
  `place_call` separately.
- **`cache_control` is ignored.** DeepSeek caches repeated prompt prefixes on
  its side automatically. Keep the system prompt and tool definitions identical
  between requests, and put changing data (current time) at the end, in the
  user message.
- **Unsupported model names.** On the Anthropic-format endpoint, names that
  start with `claude` are mapped to DeepSeek models, and other unknown names
  return `400`. Always set the DeepSeek model name explicitly so it's clear
  which model is running.
- **Data location.** DeepSeek processes and stores data on servers in China.
  The bot sends it the user's messages, business phone numbers, and the
  owner's memory facts (during `/memory` merges). Decide whether that's
  acceptable for you; in the EU this is a GDPR question. If not, switch the
  provider to Anthropic, or use DeepSeek models from another host (see 14).

Routing tests. A small script with 15–20 sample user messages and the expected
tool call (or no call) for each, run against the real API of the chosen
provider. At minimum: "call now" → no `when`; "call at 18:00" → `when` set;
a plain booking → no `availability_from`; "book something in October" →
`availability_from` set; a call to an agent about a listing →
`scenario: rental_inquiry`; a rental request without a reference or address
→ no `place_call`, the bot asks; a message that isn't about calls → no
`place_call`.
Run it after changing the provider, the model, or the tool descriptions.

Why not the Claude Agent SDK here: it can be pointed at DeepSeek through
`ANTHROPIC_BASE_URL` and run, but it's built around Claude, and you get less
control over thinking, history, and the confirmation step. A loop of your own
over the Messages API is a few dozen lines and behaves the same on both
providers.

### 5.5 Intake: questions to the user before the call

For every scenario except `general`, the bot asks the user for what's missing
before it calls. The questioning method is the `grilling` skill from the
repo, `.agents/skills/grilling/SKILL.md`: questions go in rounds, each one
numbered and with a recommended answer, worded so that "yes" accepts the
recommendation, and the next round comes only after the answers. The bot reads
the skill text at runtime (without the frontmatter), so a change to the skill
reaches the bot without touching the code. This works the same on DeepSeek and
Claude: the skill is just text returned by a tool.

How it's wired:

- Each scenario is a file `scenarios/<name>.md` with two sections: **intake**
  (required fields, the decisions to put to the user, how to write `details`)
  and **playbook** (rules for the robot, 4.7).
- The system prompt lists the scenarios, one line each. When the model
  recognizes a scenario, it calls the `get_scenario_guide(scenario)` tool,
  which returns the grilling method, the adaptation rules below, and the
  scenario's intake. The full text is loaded only when it's needed, and the
  system prompt stays short and stable for caching (5.4).
- `place_call` checks the scenario's required fields in code. If any are
  missing, the tool returns an error naming them, and the bot asks the user
  instead of calling.

The skill is written for a coding agent. For the bot, these rules take
priority over it:

- The design tree is the call brief, not an open-ended plan. Ask only about
  the required fields and the decisions listed in the scenario's intake, and
  not "relentlessly": usually one round, at most two.
- Facts come from the user's message, memory (7.2), and the calendar (7.1);
  never ask the user for them. The bot has no sub-agents; it looks facts up
  with its own tools.
- Keep the skill's round format (❓ Q1 … ➡️ recommendation), in Russian. A
  reply of «да» accepts all recommendations; the user can also answer single
  questions by number.
- The skill's final "confirm we've reached a shared understanding" is the
  «Да / Нет» confirmation of `place_call` (5.3). Don't ask for a separate text
  confirmation.
- If the user gave facts about themselves during intake (job, income, pets),
  offer in one line, after the call is placed, to save them with `/memory`.
- `general` calls skip intake entirely and work as before.

Intake for `rental_inquiry`:

- required fields: the listing's reference or address, the price, and where
  it was published;
- decisions to put to the user: which contract types are acceptable
  (long-term only, or temporary too); whether to ask for similar flats if this
  one is taken; when to view (the nearest free slot or specific days); any
  questions of their own beyond the list in 4.7;
- from memory, don't ask: the tenant profile (7.2). If part of it is missing,
  ask for it once, in the same round.

An example round:

```
❓ Q1 — Тип аренды: рассматриваем только долгосрочную?
➡️ Да, только долгосрочную

❓ Q2 — Если квартиру уже сдали: спросить похожие варианты в том же районе?
➡️ Да

❓ Q3 — Просмотр: записываться на ближайшее свободное окно из календаря?
➡️ Да
```

The skill file is shared with the coding agents that work on this repo. If
its wording for development drifts away from what suits the bot, copy it into
`scenarios/` and load the copy instead.

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

Then the summary (`summary_ru`), the facts (`facts_ru`, if not empty), the
duration in seconds, and, as a separate
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
"forget about the allergy". The merge is done by the provider's cheap model
(`deepseek-flash` with thinking disabled, or Claude Haiku) with the
instruction: return only the updated list of short facts, one per line, keeping
old facts unless the instruction explicitly cancels them. Check the result
before saving: if the model returned an empty answer or something that isn't a
list of facts, keep the old memory and report the error. `/memory` without
text shows the current memory. The entire memory text goes into
`{{about_me}}`.

For rental calls (4.7), memory should hold the tenant profile: job and
contract type, net monthly income, who will live in the flat, pets, desired
move-in date, budget, and an email for documents. Without it the robot can
only promise that the owner will send the details later.

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
LLM_PROVIDER (deepseek | anthropic, default deepseek)
DEEPSEEK_API_KEY (for deepseek)
ANTHROPIC_API_KEY (for anthropic)
LLM_MODEL, LLM_MEMORY_MODEL, LLM_BASE_URL (optional overrides of the provider defaults from 5.4)
RETELL_API_KEY, RETELL_FROM_NUMBER (+1…, purchased in Retell)
RETELL_AGENT_ID_ES, RETELL_AGENT_ID_EN, RETELL_AGENT_ID_RU
OWNER_NAME, OWNER_SURNAME, OWNER_NAME_RU, OWNER_SURNAME_RU
OWNER_PHONE (the owner's real phone: the robot gives it out for bookings)
GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN, GOOGLE_CALENDAR_IDS
```

On startup, check that the key for the chosen `LLM_PROVIDER` is set, and stop
with a clear error if it isn't. Log the provider and model in use.

Calls are enabled only when the Retell key, the number, and at least one agent
are set; otherwise the `place_call` tool is not registered.

Running: a systemd service with auto-restart, `.env` with mode 600, logs in the
journal. The bot responds only to chats in `ALLOWED_CHAT_IDS`.

Write the code so that it can later serve more than one user (see 14):

- the access check is one function, `is_allowed(chat_id)`; nothing else
  compares chat ids with `ALLOWED_CHAT_IDS`;
- the owner's data (name, Cyrillic name, phone, time zone, memory, calendar
  settings) is one profile object, loaded from the config at startup and
  passed to the code that needs it. The rest of the code doesn't read these
  values from the environment directly.

First-run order:

1. Buy a number in Retell, fill in the key and the number.
2. Run `setup`, fill in the agent ids.
3. Fill in the owner's details, time zone, and the DeepSeek key.
4. Run the routing tests from 5.4.
5. Start the bot, write "call me at <your number> and say hello".
6. Listen to the recording, adjust the prompt and voice, run `sync`, repeat.
   Expect 5–10 test calls per language before the result is acceptable.

---

## 10. Starter prompt for the coding agent

> Build me a Telegram assistant following the specification below. Stack:
> Python, python-telegram-bot, the anthropic Python SDK with my own tool loop,
> retell-sdk, SQLite. The bot LLM is switchable between DeepSeek (default,
> through its Anthropic-compatible endpoint) and Anthropic, as described in
> section 5.4. Start with the voice agent in Retell (section 4) and the
> setup/sync scripts, then the LLM client with both providers and the tool
> loop, then the place_call tool with confirmation (section 5), then the call
> lifecycle and report (section 6), then calendar and memory (section 7), then
> scheduled calls (section 8). Write tests for each block with Retell and the
> LLM mocked out, plus the routing test script from 5.4 that runs against the
> real LLM API; I'll make the real calls myself. Take the keys from .env, and
> create a .env.example template.

---

## 11. Acceptance scenarios

Run manually after the build, against your own number and a couple of real
businesses. Run the bot scenarios (everything except the robot's behavior on
the call) on DeepSeek, and the first three again after switching
`LLM_PROVIDER` to `anthropic`:

- [ ] "call me at <number> and say hello" → a «Да/Нет» prompt appears; after
  «Да» the call goes out, the report and recording arrive as a separate
  message.
- [ ] Tap «Нет» → no call, the assistant responds calmly and doesn't try the
  call again on its own.
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
- [ ] "call now" → the call goes out immediately, nothing is scheduled.
- [ ] Ask for two calls in one message → two separate confirmations.
- [ ] Restart the bot with a pending call → the call isn't lost; with an
  overdue one → a «Пропущен…» ("missed") message.
- [ ] While a call is in progress, give the bot another task → it responds
  without waiting for the call to end.
- [ ] The report summary is in Russian, even if the conversation was in
  Spanish.
- [ ] Rental call (someone plays the agent on your number): the robot names
  the listing, asks whether it's available and about the conditions, proposes
  a viewing in a free slot, agrees to receive documents by WhatsApp, refuses
  to pay a reservation deposit; the report lists the facts.
- [ ] Rental request without a reference or address → the bot asks one round
  of questions in the grilling format and doesn't call.
- [ ] Reply «да» to the round → the recommendations are accepted, the
  «Да / Нет» call confirmation appears, no extra text confirmation.
- [ ] A `general` call → no questions, straight to the confirmation.
- [ ] Bot replies arrive within a few seconds (thinking really is disabled).

---

## 12. Pitfall checklist

All from real calls, plus the provider items from 5.4. Check that the coding
agent took these into account:

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
- [ ] One LLM client, provider chosen by `LLM_PROVIDER`; no provider-specific code outside it.
- [ ] Thinking explicitly disabled on DeepSeek.
- [ ] Refusals and errors stated in the tool result text, not only via `is_error`.
- [ ] Every `tool_use` in a response gets its own `tool_result`; each `place_call` confirmed separately.
- [ ] Tool arguments validated in code; empty / "now" `when` treated as absent.
- [ ] Stable system prompt and tools; current time in the user message.
- [ ] Routing tests pass on the provider and model in use.
- [ ] Access check in one `is_allowed()` function; owner data in one profile object.
- [ ] Scenario playbooks in code; `rental_inquiry` allows sending documents afterwards but forbids commitments and payments.
- [ ] Custom `facts_ru` in post-call analysis and in the report.
- [ ] Intake via the `grilling` skill for every scenario except `general`; one or two rounds; facts from memory and the calendar, not from the user.
- [ ] Required scenario fields checked in `place_call`, in code.

---

## 13. Cost

Ballpark for a 3–5 minute call: Retell (telephony, recognition, synthesis, LLM)
about $0.5–1, the number about $2 per month, plus a fraction of a cent of
DeepSeek usage for parsing the task in the bot (usually cheaper than Claude for
the same work; check current prices at api-docs.deepseek.com), plus a VPS at
$6–12 per month. Almost all the cost is Retell, so the bot provider barely
changes the total. An hour of waiting on hold costs correspondingly more; the
2-hour ceiling is set deliberately.

---

## 14. How to extend

- **A different voice provider** (Vapi, Bland, your own pipeline on Twilio +
  Deepgram + an LLM): keep the provider behind a "start call / get status"
  interface, normalize its statuses into the table from 6.3, and nothing else
  changes.
- **DeepSeek models from another host** (for example, to keep data out of
  China): many hosts serve DeepSeek models through an OpenAI-compatible API.
  Add a second implementation of the LLM client in the OpenAI Chat Completions
  format (`tools` with `type: "function"`, `tool_calls` in the reply), and keep
  the tool loop and confirmation logic shared. Re-run the routing tests on the
  new host.
- **DeepSeek in the call itself**: only through Retell's custom LLM over a
  WebSocket, which needs a public endpoint and adds latency (see 3).
- **A new language**: a prompt, a voice, a language code, one more agent, and a
  variable with its id.
- **Inbound calls**: Retell supports them, but they need a webhook, i.e. public
  HTTPS, which this design deliberately does without.
- **Retry on no answer**: on `no_answer` status, schedule the call again in
  15 minutes.
- **Selling calls to other users** for Telegram Stars: access from a users
  table instead of `ALLOWED_CHAT_IDS`, a balance in minutes, a profile per
  user, abuse limits. The plan is in
  https://github.com/TeleginS/zvonilka/issues/1. The `is_allowed()` and
  profile requirements from section 9 keep this change local.
