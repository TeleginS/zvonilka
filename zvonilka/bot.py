"""Telegram side: messages, confirmation buttons, /memory, /calls."""

from __future__ import annotations

import asyncio
import logging
import secrets

import httpx
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from zvonilka.access import is_allowed
from zvonilka.app import Components, build_components
from zvonilka.config import Config
from zvonilka.memory import MemoryMergeError, merge_memory
from zvonilka.tools import format_local

log = logging.getLogger(__name__)

TELEGRAM_LIMIT = 4000
CONFIRM_TIMEOUT = 600

HELP = (
    "Я звоню в заведения от твоего имени.\n\n"
    "Напиши, куда и зачем позвонить, например: «позвони в ресторан +34 9xx xxx xxx, "
    "забронируй столик на двоих на завтра в 20:00». Перед звонком я покажу бриф с кнопками «Да / Нет».\n\n"
    "/memory <текст> — добавить или изменить факты о тебе; /memory — показать память\n"
    "/calls — запланированные звонки"
)


def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    chunks = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        cut = cut if cut > 0 else limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return chunks + [text] if text else chunks


class TelegramNotifier:
    def __init__(self, bot: Bot):
        self._bot = bot

    async def send_text(self, chat_id: int, text: str) -> None:
        for chunk in split_message(text):
            await self._bot.send_message(chat_id, chunk)

    async def send_recording(self, chat_id: int, url: str, caption: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as http:
                response = await http.get(url)
                response.raise_for_status()
            audio = response.content
        except Exception:
            log.warning("downloading recording failed", exc_info=True)
            await self.send_text(chat_id, f"{caption}\n{url}")
            return
        filename = url.rsplit("/", 1)[-1].split("?", 1)[0] or "call.wav"
        try:
            await self._bot.send_audio(chat_id, audio=audio, filename=filename, caption=caption)
        except Exception:
            log.info("sending recording as audio failed, sending as document", exc_info=True)
            await self._bot.send_document(chat_id, document=audio, filename=filename, caption=caption)


class Confirmations:
    """«✅ Да / ❌ Нет» buttons whose answer the tool loop awaits (spec 5.3)."""

    def __init__(self, bot: Bot):
        self._bot = bot
        self._pending: dict[str, asyncio.Future] = {}

    async def ask(self, chat_id: int, text: str) -> bool | None:
        token = secrets.token_hex(6)
        future = asyncio.get_running_loop().create_future()
        self._pending[token] = future
        markup = InlineKeyboardMarkup(
            [[
                InlineKeyboardButton("✅ Да", callback_data=f"cf:{token}:1"),
                InlineKeyboardButton("❌ Нет", callback_data=f"cf:{token}:0"),
            ]]
        )
        message = await self._bot.send_message(chat_id, text, reply_markup=markup)
        try:
            return await asyncio.wait_for(future, CONFIRM_TIMEOUT)
        except TimeoutError:
            await message.edit_text(f"{text}\n\n⌛ Нет ответа, звонок не подтверждён")
            return None
        finally:
            self._pending.pop(token, None)

    def resolve(self, token: str, answer: bool) -> bool:
        future = self._pending.get(token)
        if future is None or future.done():
            return False
        future.set_result(answer)
        return True


class Handlers:
    def __init__(self, config: Config, components: Components, confirmations: Confirmations, notifier: TelegramNotifier):
        self._config = config
        self._c = components
        self._confirmations = confirmations
        self._notifier = notifier

    def register(self, app: Application) -> None:
        app.add_handler(CommandHandler(["start", "help"], self.on_help))
        app.add_handler(CommandHandler("memory", self.on_memory))
        app.add_handler(CommandHandler("calls", self.on_calls))
        app.add_handler(CallbackQueryHandler(self.on_confirm, pattern=r"^cf:"))
        app.add_handler(CallbackQueryHandler(self.on_cancel, pattern=r"^cc:"))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_text))

    def _allowed(self, update: Update) -> bool:
        chat = update.effective_chat
        return chat is not None and is_allowed(chat.id, self._config)

    async def on_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if self._allowed(update):
            await update.effective_message.reply_text(HELP)

    async def on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._allowed(update):
            return
        chat_id = update.effective_chat.id
        await context.bot.send_chat_action(chat_id, "typing")
        try:
            reply = await self._c.assistant.handle(
                chat_id, update.effective_message.text, lambda text: self._confirmations.ask(chat_id, text)
            )
        except Exception as e:
            log.exception("handling a message failed")
            reply = f"⚠️ Не получилось обработать сообщение: {type(e).__name__}: {e}"
        await self._notifier.send_text(chat_id, reply)

    async def on_memory(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._allowed(update):
            return
        parts = (update.effective_message.text or "").split(maxsplit=1)
        instruction = parts[1].strip() if len(parts) > 1 else ""
        db = self._c.db
        if not instruction:
            current = db.get_memory()
            await self._notifier.send_text(update.effective_chat.id, current or "Память пуста. Добавить: /memory <текст>")
            return
        try:
            updated = await merge_memory(self._c.llm, db.get_memory(), instruction)
        except MemoryMergeError as e:
            await update.effective_message.reply_text(f"Не получилось обновить память, оставил как было: {e}")
            return
        db.set_memory(updated)
        await self._notifier.send_text(update.effective_chat.id, f"Запомнил. Сейчас в памяти:\n{updated}")

    async def on_calls(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._allowed(update):
            return
        scheduler = self._c.scheduler
        jobs = scheduler.pending(update.effective_chat.id) if scheduler else []
        if not jobs:
            await update.effective_message.reply_text("Запланированных звонков нет")
            return
        tz = self._config.owner.timezone
        for job in jobs:
            req = job.request
            markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отменить", callback_data=f"cc:{job.id}")]])
            await update.effective_message.reply_text(
                f"{format_local(job.run_at, tz)} — {req.business_name}, {req.to_number}\n{req.objective}",
                reply_markup=markup,
            )

    async def on_confirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()
        if not self._allowed(update):
            return
        _, token, answer = query.data.split(":")
        accepted = answer == "1"
        if not self._confirmations.resolve(token, accepted):
            await query.edit_message_reply_markup(None)
            return
        mark = "✅ Подтверждено" if accepted else "❌ Отменено"
        await query.edit_message_text(f"{query.message.text}\n\n{mark}")

    async def on_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()
        if not self._allowed(update) or self._c.scheduler is None:
            return
        call_id = int(query.data.split(":")[1])
        if self._c.scheduler.cancel(call_id):
            await query.edit_message_text(f"{query.message.text}\n\n❌ Отменён")
        else:
            await query.edit_message_text(f"{query.message.text}\n\nЭтот звонок уже не ждёт")


async def _post_init(app: Application) -> None:
    scheduler = app.bot_data.get("scheduler")
    if scheduler:
        await scheduler.restore()


def build_application(config: Config) -> Application:
    # Concurrent updates: the tool loop awaits a button press, which is another update.
    app = ApplicationBuilder().token(config.telegram_token).concurrent_updates(True).post_init(_post_init).build()
    notifier = TelegramNotifier(app.bot)
    components = build_components(config, notifier)
    app.bot_data["scheduler"] = components.scheduler
    Handlers(config, components, Confirmations(app.bot), notifier).register(app)
    return app
