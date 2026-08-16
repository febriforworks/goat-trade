import sys
import os
from urllib.parse import parse_qs

# Menambahkan root project ke sys.path agar modul 'app' dapat diimport oleh Vercel
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app as fastapi_app

class VercelPathMiddleware:
    """
    Middleware untuk mengatasi isu path resolution di Vercel Serverless.
    Mengekstrak path asli dari parameter `_vercel_path` yang dikirimkan oleh rewrite rule vercel.json.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            query_string = scope.get("query_string", b"").decode("utf-8", errors="ignore")
            if "_vercel_path" in query_string:
                params = parse_qs(query_string, keep_blank_values=True)
                if "_vercel_path" in params and params["_vercel_path"]:
                    new_path = params["_vercel_path"][0]
                    if not new_path.startswith("/"):
                        new_path = "/" + new_path
                    scope["path"] = new_path
                    scope["raw_path"] = new_path.encode("utf-8")
                    
                    # Bersihkan _vercel_path dari query string
                    del params["_vercel_path"]
                    clean_items = []
                    for k, vals in params.items():
                        for v in vals:
                            clean_items.append(f"{k}={v}")
                    scope["query_string"] = "&".join(clean_items).encode("utf-8")
            elif scope.get("path") in ("/api/index.py", "/api/index", "/api/index/"):
                scope["path"] = "/"
                scope["raw_path"] = b"/"

        await self.app(scope, receive, send)

# Entrypoint instance untuk Vercel Serverless Function
app = VercelPathMiddleware(fastapi_app)
