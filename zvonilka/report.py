"""The call report sent to Telegram (spec 6.4)."""

from __future__ import annotations

from zvonilka.retell_api import CallSnapshot

HEADERS = {
    "success": "✅ Готово",
    "completed": "☑️ Дозвонились, разговор завершён",
    "too_short": "⚠️ Звонок слишком короткий, вероятно, не удался. Проверь запись",
    "voicemail": "📭 Попали на автоответчик",
    "no_answer": "📵 Не дозвонились (занято / нет ответа)",
    "timeout": "⏱ Звонок прерван по таймауту",
    "failed": "❌ Звонок не удался",
    "in_progress": "⏳ Звонок ещё идёт",
}


def format_report(status: str, business_name: str, call: CallSnapshot) -> str:
    lines = [f"{HEADERS.get(status, status)}\n{business_name}"]
    summary = str(call.custom.get("summary_ru") or call.summary_en or "").strip()
    if summary:
        lines.append(summary)
    facts = [line.strip().lstrip("-•* ").strip() for line in str(call.custom.get("facts_ru") or "").splitlines()]
    facts = [fact for fact in facts if fact]
    if facts:
        lines.append("\n".join(f"• {fact}" for fact in facts))
    if call.duration_ms is not None:
        lines.append(f"Длительность: {round(call.duration_ms / 1000)} с")
    return "\n\n".join(lines)
