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

    # Engine configuration options for resilient connections
    engine_kwargs = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
        "pool_size": 10,
        "max_overflow": 20,
    }
    
    # TCP Keepalives for PostgreSQL to prevent idle SSL disconnection by remote servers/firewalls
    connect_args = {
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 5,
    }

    try:
        url_obj = make_url(raw_url)
        if "postgres" in url_obj.drivername:
            return create_engine(url_obj, connect_args=connect_args, **engine_kwargs)
        return create_engine(url_obj, **engine_kwargs)
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
        return create_engine(url_obj, connect_args=connect_args, **engine_kwargs)

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
