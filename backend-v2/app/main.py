from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import auth, camera_models, incidents, model_catalog, platform_models, sites
from app.config import get_settings
from app.db.session import engine

settings = get_settings()
app = FastAPI(
    title='PPE Construction API', version='0.1.0',
    docs_url='/docs' if settings.enable_api_docs else None,
    redoc_url=None,
    openapi_url='/openapi.json' if settings.enable_api_docs else None,
)
app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_origins,
    allow_methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'],
    allow_headers=['Authorization', 'Content-Type'],
    allow_credentials=False,
)


@app.get('/health/live', tags=['health'])
def liveness():
    return {'status': 'ok'}


@app.get('/health/ready', tags=['health'])
def readiness():
    try:
        with engine.connect() as conn:
            conn.execute(text('SELECT 1'))
    except Exception:
        raise HTTPException(503, 'Database unavailable') from None
    return {'status': 'ready'}


app.include_router(auth.router, prefix='/api/v1')
app.include_router(sites.router, prefix='/api/v1')
app.include_router(incidents.router, prefix='/api/v1')
app.include_router(platform_models.router, prefix='/api/v1')
app.include_router(model_catalog.router, prefix='/api/v1')
app.include_router(camera_models.router, prefix='/api/v1')
