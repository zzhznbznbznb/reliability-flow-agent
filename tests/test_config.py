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


def test_agent_rpc_reader_limits_are_configurable_and_above_64k() -> None:
    settings = get_settings()
    assert settings.agent_rpc_max_message_bytes > 64 * 1024
    assert settings.agent_rpc_read_chunk_bytes > 0
