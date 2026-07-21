from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Chatwoot
    chatwoot_api_url: str
    chatwoot_api_token: str
    chatwoot_webhook_secret: str = ""  # 빈 값이면 서명 검증 생략

    # LLM (팀원 담당 — llm_client.py에서 사용)
    groq_api_key: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
