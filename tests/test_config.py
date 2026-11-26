from app.config import get_settings


def test_project_directories_exist() -> None:
    settings = get_settings()
    assert settings.project_root.is_dir()
    assert settings.data_dir.is_dir()
    assert settings.web_dir.is_dir()
    assert (settings.data_dir / "processes").is_dir()
    assert (settings.data_dir / "reliability").is_dir()
    assert (settings.data_dir / "experiments").is_dir()


def test_llm_is_optional_by_default() -> None:
    settings = get_settings()
    assert settings.llm_provider == "opencode-go"
    assert settings.llm_model == "deepseek-v4.1-flash"
    assert settings.llm_base_url == "https://opencode.ai/inference/go/openai/v1"
    assert settings.llm_auth_mode == "opencode-auth"
