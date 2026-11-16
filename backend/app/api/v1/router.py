"""Aggregates every v1 module router. New modules are added here phase by phase."""

from fastapi import APIRouter

from app.api.v1.health.router import router as health_router

api_router = APIRouter()
api_router.include_router(health_router)
