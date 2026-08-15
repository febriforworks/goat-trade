import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    db_host: str = "localhost"
    db_port: str = "5432"
    db_user: str = "postgres"
    db_password: str = ""
    db_name: str = "saham_idx"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    
    @property
    def database_url(self) -> str:
        import urllib.parse
        encoded_password = urllib.parse.quote_plus(self.db_password)
        return f"postgresql://{self.db_user}:{encoded_password}@{self.db_host}:{self.db_port}/{self.db_name}"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
