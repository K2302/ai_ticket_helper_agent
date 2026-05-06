from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql://postgres:postgres@localhost:5432/ai_human_loop"
    kafka_bootstrap_servers: str = "localhost:9092"
    ticket_created_topic: str = "support.ticket.created"
    kafka_group_id: str = "ai-triage-service"
    low_confidence_threshold: float = 0.70
    openrouter_api_key: str | None = None
    openrouter_model: str = "openai/gpt-4o-mini"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_http_referer: str | None = None
    openrouter_app_title: str = "ai-human-loop"
    # Phase 4 — kill switch check on startup for known providers
    openrouter_provider_key: str = "openrouter:openai/gpt-4o-mini"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")
