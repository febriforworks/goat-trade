from fastapi import FastAPI, Request
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
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

@app.get("/docs", include_in_schema=False)
@app.get("/api/docs", include_in_schema=False)
async def swagger_ui():
    return get_swagger_ui_html(
        openapi_url="/api/openapi.json",
        title="Goat IDX API - Swagger Documentation",
        swagger_js_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js",
        swagger_css_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css",
    )

@app.get("/redoc", include_in_schema=False)
@app.get("/api/redoc", include_in_schema=False)
async def redoc_ui():
    return get_redoc_html(
        openapi_url="/api/openapi.json",
        title="Goat IDX API - ReDoc",
        redoc_js_url="https://cdn.jsdelivr.net/npm/redoc@next/bundles/redoc.standalone.js",
    )

@app.get("/openapi.json", include_in_schema=False)
@app.get("/api/openapi.json", include_in_schema=False)
async def openapi_schema():
    return JSONResponse(app.openapi())

@app.get("/api/init-db")
def initialize_database():
    init_db()
    return {"message": "Database tables created successfully"}

@app.get("/")
def read_root():
    return {
        "message": "Welcome to Goat IDX API",
        "docs": "/api/docs",
        "redoc": "/api/redoc"
    }

@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        headers_dict = {}
        for k, v in request.scope.get("headers", []):
            try:
                key = k.decode('utf-8') if isinstance(k, bytes) else str(k)
                val = v.decode('utf-8') if isinstance(v, bytes) else str(v)
                headers_dict[key] = val
            except Exception:
                pass
        return JSONResponse(
            status_code=404,
            content={
                "detail": "Not Found",
                "request_url_path": request.url.path,
                "scope_path": request.scope.get("path"),
                "scope_root_path": request.scope.get("root_path"),
                "headers": headers_dict
            }
        )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
