from fastapi import FastAPI
from app.core.db import engine
from app.infrastructure.db.base import Base
from app.api.routes import health, whatsapp

app = FastAPI()

@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

app.include_router(health.router)
app.include_router(whatsapp.router)