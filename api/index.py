import sys
import os

# Menambahkan root project ke sys.path agar modul 'app' dapat diimport oleh Vercel
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app

# Vercel serverless function entrypoint
