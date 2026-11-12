"""Schémas de données (Pydantic) partagés par tout le pipeline."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Category = Literal["models", "tools", "agents", "research", "business", "policy"]
Method = Literal["rss", "sitemap", "arxiv", "hn_algolia", "hf_papers", "github_trending", "web_search"]


class Source(BaseModel):
    """Une entrée de config/sources.yaml."""

    name: str
    url: str
    method: Method
    tier: Literal[1, 2, 3]
    categories: list[Category] = Field(default_factory=list)
    filter: Literal["ai"] | None = None
    enabled: bool = True
    note: str | None = None
    # Options propres à certaines méthodes
    include: list[str] = Field(default_factory=list)        # sitemap
    arxiv_categories: list[str] = Field(default_factory=list)  # arxiv
    max_items: int = 300                                     # arxiv
    date_lag_hours: int = 0                                  # fenêtre décalée
    min_points: int = 100                                    # hn_algolia
    min_upvotes: int = 10                                    # hf_papers


class SourcesFile(BaseModel):
    ai_keywords: list[str]
    sources: list[Source]


class Item(BaseModel):
    """Un élément collecté (article, papier, dépôt, discussion…)."""

    title: str
    url: str
    source: str
    tier: Literal[1, 2, 3]
    categories: list[Category] = Field(default_factory=list)
    published: datetime
    summary: str = ""
    # Lien vers la source primaire quand l'élément est un signal (ex. HN → article, HF → arXiv)
    primary_url: str | None = None
    extra: dict[str, int | float | str] = Field(default_factory=dict)


class SourceReport(BaseModel):
    """Résultat de la lecture d'une source (pour check-sources et les logs)."""

    name: str
    method: Method
    tier: int
    ok: bool
    total: int = 0          # éléments lus (avant filtre de date)
    in_window: int = 0      # éléments gardés dans la fenêtre
    newest: datetime | None = None
    error: str | None = None
    seconds: float = 0.0
