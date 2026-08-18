import os
import urllib.parse
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    db_host: str = "localhost"
    db_port: str = "5432"
    db_user: str = "postgres"
    db_password: str = ""
    db_name: str = "saham_idx"
    database_url_override: Optional[str] = None
    
    # Telegram Alert Configuration
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    
    @property
    def database_url(self) -> str:
        # 1. Prioritaskan jika DATABASE_URL atau POSTGRES_URL disediakan langsung
        direct_url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or self.database_url_override
        if direct_url:
            # SQLAlchemy memerlukan prefix postgresql:// bukan postgres://
            if direct_url.startswith("postgres://"):
                return direct_url.replace("postgres://", "postgresql://", 1)
            return direct_url

        # 2. Format dari individual DB components
        encoded_password = urllib.parse.quote_plus(self.db_password) if self.db_password else ""
        
        # Validasi port: jika kosong atau bukan angka, fallback ke default '5432'
        port = str(self.db_port).strip() if self.db_port else ""
        if not port or not port.isdigit():
            port = "5432"
            
        user_part = f"{self.db_user}:{encoded_password}" if encoded_password else self.db_user
        return f"postgresql://{user_part}@{self.db_host}:{port}/{self.db_name}"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()

