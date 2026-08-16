from fastapi import FastAPI
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from fastapi.responses import JSONResponse
from app.db.database import init_db
from app.api.routes import scraper, alerts, screener

app = FastAPI(
    title="Goat IDX API", 
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None
)

app.include_router(scraper.router, prefix="/api/scrape", tags=["Scraper"])
app.include_router(alerts.router, prefix="/api/alerts", tags=["Alerts"])
app.include_router(screener.router, prefix="/api/screener", tags=["Screener"])

@app.get("/api/docs", include_in_schema=False)
@app.get("/docs", include_in_schema=False)
async def swagger_ui():
    return get_swagger_ui_html(
        openapi_url="/api/openapi.json",
        title="Goat IDX API - Swagger Documentation",
        swagger_js_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js",
        swagger_css_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css",
    )

@app.get("/api/redoc", include_in_schema=False)
@app.get("/redoc", include_in_schema=False)
async def redoc_ui():
    return get_redoc_html(
        openapi_url="/api/openapi.json",
        title="Goat IDX API - ReDoc",
        redoc_js_url="https://cdn.jsdelivr.net/npm/redoc@next/bundles/redoc.standalone.js",
    )

@app.get("/api/openapi.json", include_in_schema=False)
@app.get("/openapi.json", include_in_schema=False)
async def openapi_schema():
    return JSONResponse(app.openapi())

@app.get("/api/init-db")
def initialize_database():
    init_db()
    return {"message": "Database tables created successfully"}

@app.get("/api")
@app.get("/api/")
@app.get("/")
def read_root():
    return {
        "message": "Welcome to Goat IDX API",
        "docs": "/api/docs",
        "redoc": "/api/redoc"
    }
