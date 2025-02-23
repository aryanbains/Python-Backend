# api/index.py

from app import app

# Vercel handler
def handler(request):
    return app(request)