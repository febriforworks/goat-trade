from fastapi import FastAPI
from app.db.database import init_db
from app.api.routes import scraper

app = FastAPI(title="Goat IDX API", version="1.0.0")

@app.on_event("startup")
def on_startup():
    init_db()

app.include_router(scraper.router, prefix="/api/scrape", tags=["Scraper"])

@app.get("/")
def read_root():
    return {"message": "Welcome to Goat IDX API"}
