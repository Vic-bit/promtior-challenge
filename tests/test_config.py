from app.config import Settings


def test_timezone_defaults_to_montevideo(monkeypatch):
    monkeypatch.delenv("TIMEZONE", raising=False)
    settings = Settings(
        _env_file=None,
        database_url="postgresql://test",
        groq_api_key="test",
        agent_model="test",
        guardian_model="test",
        jwt_secret="test",
    )
    assert settings.timezone == "America/Montevideo"
