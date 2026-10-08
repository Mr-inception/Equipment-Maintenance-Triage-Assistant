from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Equipment Maintenance Triage Assistant"
    database_url: str = "sqlite:///./triage.db"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173"
    knowledge_base_dir: str = ""  # empty = <project root>/knowledge_base

    llm_provider: str = "gemini"  # "gemini" or "anthropic"
    llm_timeout_seconds: int = 60
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-4-6"  # Anthropic model name


settings = Settings()
