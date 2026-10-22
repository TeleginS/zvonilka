from datetime import timedelta

from tests.conftest import NOW, TZ, FakeLLM, text, tool_use
from zvonilka.assistant import DECLINED, Assistant, Tool, system_prompt, trim_history
from zvonilka.tools import ToolInputError


def make(llm, db, *, needs_confirm=True, now=lambda: NOW):
    runs = []

    def prepare(args):
        if args.get("bad"):
            raise ToolInputError("bad argument")
        return args

    async def run(chat_id, args):
        runs.append(args)
        return "Звоню, отчёт пришлю отдельно"

    tool = Tool(
        schema={"name": "place_call", "description": "", "input_schema": {"type": "object"}},
        run=run,
        prepare=prepare,
        confirm_text=(lambda args: f"confirm {args}") if needs_confirm else None,
    )
    return Assistant(llm, db, [tool], system=system_prompt("- general: every other call"), tz=TZ, now=now), runs


def confirmer(answers):
    asked = []

    async def confirm(text):
        asked.append(text)
        return answers.pop(0)

    return confirm, asked


async def test_confirmed_call_runs_and_model_replies(db):
    llm = FakeLLM([tool_use("place_call", {"n": 1}), text("Звоню!")])
    assistant, runs = make(llm, db)
    confirm, asked = confirmer([True])
    assert await assistant.handle(1, "позвони", confirm) == "Звоню!"
    assert runs == [{"n": 1}] and len(asked) == 1
    tool_result = llm.requests[1]["messages"][-1]["content"][0]
    assert tool_result == {"type": "tool_result", "tool_use_id": "t1", "content": "Звоню, отчёт пришлю отдельно"}


async def test_declined_call_is_explained_in_text(db):
    llm = FakeLLM([tool_use("place_call", {"n": 1}), text("Хорошо, не звоню.")])
    assistant, runs = make(llm, db)
    confirm, _ = confirmer([False])
    await assistant.handle(1, "позвони", confirm)
    assert runs == []
    # DeepSeek ignores is_error, so the refusal must be in the content.
    assert llm.requests[1]["messages"][-1]["content"][0]["content"] == DECLINED


async def test_invalid_arguments_go_back_to_model_without_asking(db):
    llm = FakeLLM([tool_use("place_call", {"bad": True}), text("Уточни номер")])
    assistant, runs = make(llm, db)
    confirm, asked = confirmer([])
    await assistant.handle(1, "позвони", confirm)
    assert asked == [] and runs == []
    assert llm.requests[1]["messages"][-1]["content"][0]["content"] == "Error: bad argument"


async def test_parallel_tool_uses_each_get_a_result_and_a_confirmation(db):
    reply = tool_use("place_call", {"n": 1}, "a")
    reply.blocks += tool_use("place_call", {"n": 2}, "b").blocks
    llm = FakeLLM([reply, text("Оба звонка пошли")])
    assistant, runs = make(llm, db)
    confirm, asked = confirmer([True, False])
    await assistant.handle(1, "позвони в два места", confirm)
    assert len(asked) == 2 and runs == [{"n": 1}]
    results = llm.requests[1]["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["a", "b"]
    assert results[1]["content"] == DECLINED


async def test_time_goes_into_user_message_and_system_prompt_is_stable(db):
    llm = FakeLLM([text("ок"), text("ок")])
    assistant, _ = make(llm, db)
    confirm, _ = confirmer([])
    await assistant.handle(1, "привет", confirm)
    await assistant.handle(1, "ещё", confirm)
    assert llm.requests[0]["system"] == llm.requests[1]["system"]
    assert "2026-10-23 12:00" not in llm.requests[0]["system"]
    assert llm.requests[0]["messages"][0]["content"].startswith("[2026-10-23 12:00 (Fri), Europe/Madrid]\nпривет")
    # The second message continues the same session.
    assert len(llm.requests[1]["messages"]) == 3


async def test_system_prompt_knows_the_owner_and_follows_memory(db, owner):
    memory = ["Аллергия на орехи"]
    llm = FakeLLM([text("Сергей"), text("ок")])
    assistant = Assistant(
        llm, db, [], system=lambda: system_prompt(None, owner, memory[0]), tz=TZ, now=lambda: NOW
    )
    confirm, _ = confirmer([])
    await assistant.handle(1, "как меня зовут?", confirm)
    first = llm.requests[0]["system"]
    assert "Sergei Telegin" in first and "Сергей Телегин" in first
    assert "+34600000000" in first and "Аллергия на орехи" in first
    memory[0] = "Полис 123"
    await assistant.handle(1, "что ты обо мне знаешь?", confirm)
    assert "Полис 123" in llm.requests[1]["system"]


async def test_new_session_after_two_hours(db):
    current = [NOW]
    llm = FakeLLM([text("ок"), text("ок")])
    assistant, _ = make(llm, db, now=lambda: current[0])
    confirm, _ = confirmer([])
    await assistant.handle(1, "привет", confirm)
    current[0] = NOW + timedelta(hours=2, minutes=1)
    await assistant.handle(1, "снова", confirm)
    assert len(llm.requests[1]["messages"]) == 1


async def test_crash_mid_loop_leaves_a_valid_history(db):
    async def broken_confirm(text):
        raise RuntimeError("telegram down")

    llm = FakeLLM([tool_use("place_call", {"n": 1})])
    assistant, _ = make(llm, db)
    try:
        await assistant.handle(1, "позвони", broken_confirm)
    except RuntimeError:
        pass
    messages, _ = db.load_session(1)
    assert messages[-1]["content"][0] == {"type": "tool_result", "tool_use_id": "t1", "content": "Error: interrupted"}


async def test_clear_session_starts_fresh(db):
    llm = FakeLLM([text("ок"), text("ок")])
    assistant, _ = make(llm, db)
    confirm, _ = confirmer([])
    await assistant.handle(1, "привет", confirm)
    db.clear_session(1)
    await assistant.handle(1, "снова", confirm)
    assert len(llm.requests[1]["messages"]) == 1


def test_trim_history_keeps_tool_pairs_together():
    plain = lambda i: {"role": "user", "content": f"msg {i}"}  # noqa: E731
    pair = [
        {"role": "assistant", "content": [{"type": "tool_use", "id": "x", "name": "t", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": "ok"}]},
    ]
    messages = [plain(0), *pair, plain(1), *pair, plain(2)]
    trimmed = trim_history(messages, limit=4)
    assert trimmed[0] == plain(1)
    assert trim_history(messages, limit=100) == messages
