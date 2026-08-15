from fastapi import FastAPI
from app.db.database import init_db
from app.api.routes import scraper, alerts, screener

app = FastAPI(
    title="Goat IDX API", 
    version="1.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url="/api/redoc"
)

app.include_router(scraper.router, prefix="/api/scrape", tags=["Scraper"])
app.include_router(alerts.router, prefix="/api/alerts", tags=["Alerts"])
app.include_router(screener.router, prefix="/api/screener", tags=["Screener"])

@app.get("/api/init-db")
def initialize_database():
    init_db()
    return {"message": "Database tables created successfully"}

@app.get("/")
def read_root():
    return {"message": "Welcome to Goat IDX API"}
