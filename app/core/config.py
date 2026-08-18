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
        direct_url = (os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or self.database_url_override or "").strip()
        
        # 2. Cek jika DB_HOST terisi full URL (misal: postgresql://... atau postgres://...)
        if not direct_url and self.db_host and (self.db_host.strip().startswith("postgresql://") or self.db_host.strip().startswith("postgres://")):
            direct_url = self.db_host.strip()

        if direct_url:
            # SQLAlchemy memerlukan prefix postgresql:// bukan postgres://
            if direct_url.startswith("postgres://"):
                direct_url = direct_url.replace("postgres://", "postgresql://", 1)
            # Bersihkan tanda titik dua tanpa port jika ada (misal @host:/db -> @host/db)
            if "://" in direct_url:
                import re
                scheme, rest = direct_url.split("://", 1)
                rest = re.sub(r':(?=[/?]|$)', '', rest)
                direct_url = f"{scheme}://{rest}"
            return direct_url

        # 3. Format dari individual DB components dengan sanitasi otomatis
        clean_host = self.db_host.strip() if self.db_host else "localhost"
        if "://" in clean_host:
            clean_host = clean_host.split("://", 1)[1]
        if "@" in clean_host:
            clean_host = clean_host.split("@", 1)[1]
        if "/" in clean_host:
            clean_host = clean_host.split("/", 1)[0]
            
        port = str(self.db_port).strip() if self.db_port else ""
        if ":" in clean_host:
            parts = clean_host.split(":", 1)
            clean_host = parts[0]
            if parts[1].isdigit() and not port:
                port = parts[1]
                
        if not port or not port.isdigit():
            port = "5432"

        encoded_password = urllib.parse.quote_plus(self.db_password) if self.db_password else ""
        user_part = f"{self.db_user}:{encoded_password}" if encoded_password else self.db_user
        
        return f"postgresql://{user_part}@{clean_host}:{port}/{self.db_name}"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()

