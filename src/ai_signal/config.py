"""Chargement et validation des réglages (config/settings.yaml)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

# Racine du projet = deux dossiers au-dessus de src/ai_signal/
ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
SITE_DIR = ROOT / "site"
PROMPTS_DIR = ROOT / "prompts"
TEMPLATES_DIR = ROOT / "templates"

Effort = Literal["low", "medium", "high", "xhigh", "max"]


class EditionSize(BaseModel):
    min_stories: int = Field(ge=1)
    max_stories: int = Field(ge=1)
    candidates: int = Field(ge=1)


class Editions(BaseModel):
    daily: EditionSize
    weekly: EditionSize
    radar_items_min: int = 3
    radar_items_max: int = 5


class Models(BaseModel):
    triage: str
    investigate: str
    edit: str


class Efforts(BaseModel):
    triage: Effort = "low"
    investigate: Effort = "medium"
    edit: Effort = "medium"


class Tools(BaseModel):
    web_search: str
    web_fetch: str


class Budget(BaseModel):
    max_web_searches_per_run: int = Field(ge=0)
    max_fetches_per_run: int = Field(ge=0)
    max_content_tokens: int = Field(ge=1000)
    max_cost_usd_per_run: float = Field(gt=0)


class ModelPrice(BaseModel):
    input: float
    cache_write_5m: float
    cache_read: float
    output: float


class EmailSettings(BaseModel):
    enabled: bool = True
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465


class Settings(BaseModel):
    name: str = "AI Signal"
    language: str = "en"
    frequency: Literal["daily", "weekly"] = "daily"
    window_cutoff_hour_utc: int = Field(default=8, ge=0, le=23)
    display_timezone: str = "Europe/Paris"
    editions: Editions
    triage_min_score: float = Field(default=6, ge=0, le=10)
    models: Models
    effort: Efforts
    tools: Tools
    budget: Budget
    pricing: dict[str, ModelPrice | float]
    email: EmailSettings
    site_url: str

    @property
    def edition_size(self) -> EditionSize:
        return self.editions.daily if self.frequency == "daily" else self.editions.weekly

    def price_for(self, model: str) -> ModelPrice:
        price = self.pricing.get(model)
        if not isinstance(price, ModelPrice):
            raise KeyError(f"Pas de tarif pour le modèle '{model}' dans settings.yaml → pricing")
        return price

    @property
    def web_search_price(self) -> float:
        """Prix d'UNE recherche web, en dollars."""
        return float(self.pricing.get("web_search_per_1000", 10.0)) / 1000

    def window(self, edition_date: date) -> tuple[datetime, datetime]:
        """Fenêtre de collecte [début, fin[ en UTC pour l'édition du jour `edition_date`."""
        end = datetime.combine(edition_date, time(self.window_cutoff_hour_utc), tzinfo=timezone.utc)
        days = 1 if self.frequency == "daily" else 7
        return end - timedelta(days=days), end


def load_settings(path: Path | None = None) -> Settings:
    path = path or CONFIG_DIR / "settings.yaml"
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return Settings.model_validate(raw)
