import os
import re
import urllib.parse
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url, URL
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
from app.db.models import Base

def _create_safe_engine():
    raw_url = str(settings.database_url).strip()
    masked = re.sub(r':([^@]+)@', ':***@', raw_url)
    print(f"[DB] Initializing database engine with URL: {masked}")

    if raw_url.startswith("postgres://"):
        raw_url = raw_url.replace("postgres://", "postgresql://", 1)

    try:
        url_obj = make_url(raw_url)
        return create_engine(url_obj)
    except Exception as e:
        print(f"[DB WARN] Standard make_url failed ({e}), constructing URL object via urlsplit...")
        parsed = urllib.parse.urlsplit(raw_url)
        
        username = parsed.username or "postgres"
        password = parsed.password or ""
        hostname = parsed.hostname or "localhost"
        
        try:
            port = parsed.port or 5432
        except Exception:
            port = 5432

        database = parsed.path.lstrip("/") if parsed.path else "saham_idx"
        query = dict(urllib.parse.parse_qsl(parsed.query)) if parsed.query else {}

        url_obj = URL.create(
            drivername="postgresql+psycopg2",
            username=username,
            password=password,
            host=hostname,
            port=port,
            database=database,
            query=query
        )
        return create_engine(url_obj)

# Initialize Database Engine
engine = _create_safe_engine()

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    print("Initializing database tables...")
    Base.metadata.create_all(bind=engine)
    print("Database tables initialized successfully.")

# Dependency to get a database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
