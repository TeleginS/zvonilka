from zvonilka.env_check import main


def test_env_check_prints_names_not_values(tmp_path, capsys):
    env = tmp_path / ".env"
    env.write_text(
        "TELEGRAM_BOT_TOKEN=secret-token\nALLOWED_CHAT_IDS=1\nTIMEZONE=Europe/Madrid\n"
        "OWNER_NAME=A\nOWNER_PHONE=+34600000000\nDEEPSEEK_API_KEY=secret-key\nRETELL_API_KEY=r\n"
    )
    assert main([str(env)]) == 0
    out = capsys.readouterr().out
    assert "secret" not in out
    assert "✓ TELEGRAM_BOT_TOKEN" in out and "· RETELL_FROM_NUMBER" in out
    assert "calls disabled, missing: RETELL_FROM_NUMBER, RETELL_AGENT_ID_<LANG>" in out


def test_env_check_reports_config_errors(tmp_path, capsys):
    env = tmp_path / ".env"
    env.write_text("TELEGRAM_BOT_TOKEN=t\n")
    assert main([str(env)]) == 1
    assert "✗ config: ALLOWED_CHAT_IDS is not set" in capsys.readouterr().out
