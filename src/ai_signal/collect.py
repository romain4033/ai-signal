"""Étape 1 — COLLECT : lit toutes les sources et garde les éléments de la fenêtre.

Règle d'or : une source en panne ne fait JAMAIS échouer le run.
On note l'erreur dans le rapport et on passe à la suivante.
"""

from __future__ import annotations

import html
import logging
import re
import time
import xml.etree.ElementTree as ET
from calendar import timegm
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

import feedparser
import httpx
import yaml

from ai_signal.config import CONFIG_DIR
from ai_signal.models import Item, Source, SourceReport, SourcesFile

log = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; AI-Signal-bot/0.1; daily AI news digest)"
TIMEOUT = httpx.Timeout(20.0, connect=10.0)
MAX_SUMMARY_CHARS = 400
MAX_SITEMAP_TITLE_FETCHES = 15


# ───────────────────────── chargement ─────────────────────────

def load_sources(path: Path | None = None) -> SourcesFile:
    path = path or CONFIG_DIR / "sources.yaml"
    with open(path, encoding="utf-8") as f:
        return SourcesFile.model_validate(yaml.safe_load(f))


# ───────────────────────── utilitaires ─────────────────────────

def make_client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
        timeout=TIMEOUT,
        follow_redirects=True,
    )


def fetch(client: httpx.Client, url: str, params: dict | None = None, retries: int = 2) -> httpx.Response:
    """GET avec retries et backoff exponentiel (1 s, 2 s…) sur erreurs réseau et 5xx/429."""
    for attempt in range(retries + 1):
        try:
            r = client.get(url, params=params)
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
            r.raise_for_status()
            return r
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            retriable = isinstance(e, httpx.TransportError) or (
                e.response is not None and e.response.status_code in (429, 500, 502, 503, 504)
            )
            if attempt >= retries or not retriable:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("unreachable")


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_text(raw: str | None, limit: int = MAX_SUMMARY_CHARS) -> str:
    """Retire le HTML et coupe à `limit` caractères."""
    if not raw:
        return ""
    text = _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", raw))).strip()
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def parse_date(value: str | None) -> datetime | None:
    """Lit une date ISO 8601 (ou AAAA-MM-JJ) en UTC."""
    if not value:
        return None
    try:
        d = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)


def build_ai_matcher(keywords: list[str]):
    """Retourne une fonction texte → bool. Les sigles courts (AI, LLM…) sont sensibles à la casse."""
    strict = [k for k in keywords if k.isupper() and len(k) <= 5]
    loose = [k for k in keywords if k not in strict]
    rx_strict = re.compile(r"\b(" + "|".join(map(re.escape, strict)) + r")\b") if strict else None
    rx_loose = re.compile(r"\b(" + "|".join(map(re.escape, loose)) + r")\b", re.I) if loose else None

    def matches(text: str) -> bool:
        return bool((rx_strict and rx_strict.search(text)) or (rx_loose and rx_loose.search(text)))

    return matches


# ───────────────────────── lecteurs par méthode ─────────────────────────
# Chaque lecteur renvoie TOUS les éléments lus (le filtre de fenêtre est appliqué ensuite).

def read_rss(client: httpx.Client, src: Source, start: datetime, end: datetime) -> list[Item]:
    r = fetch(client, src.url)
    feed = feedparser.parse(r.content)
    if feed.bozo and not feed.entries:
        raise ValueError(f"flux illisible : {feed.bozo_exception}")
    items = []
    for e in feed.entries:
        t = e.get("published_parsed") or e.get("updated_parsed")
        if not t or not e.get("link") or not e.get("title"):
            continue
        items.append(Item(
            title=clean_text(e.title, 300),
            url=e.link,
            source=src.name,
            tier=src.tier,
            categories=src.categories,
            published=datetime.fromtimestamp(timegm(t), tz=timezone.utc),
            summary=clean_text(e.get("summary") or e.get("description")),
        ))
    return items


_SM_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
_TITLE_RE = re.compile(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', re.I)
_TITLE_RE2 = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_DESC_RE = re.compile(r'<meta[^>]+(?:name|property)=["\'](?:og:)?description["\'][^>]+content=["\']([^"\']+)', re.I)


def _sitemap_entries(client: httpx.Client, url: str, depth: int = 0) -> list[tuple[str, str | None]]:
    root = ET.fromstring(fetch(client, url).content)
    if root.tag == f"{_SM_NS}sitemapindex" and depth < 1:
        out = []
        for sm in root.findall(f"{_SM_NS}sitemap")[:20]:
            loc = sm.findtext(f"{_SM_NS}loc")
            if loc:
                out += _sitemap_entries(client, loc.strip(), depth + 1)
        return out
    return [
        (u.findtext(f"{_SM_NS}loc", "").strip(), u.findtext(f"{_SM_NS}lastmod"))
        for u in root.findall(f"{_SM_NS}url")
    ]


def read_sitemap(client: httpx.Client, src: Source, start: datetime, end: datetime) -> list[Item]:
    entries = _sitemap_entries(client, src.url)
    items: list[Item] = []
    fetched_titles = 0
    for loc, lastmod in entries:
        if src.include and not any(p in loc for p in src.include):
            continue
        published = parse_date(lastmod)
        if not published:
            continue
        slug = loc.rstrip("/").rsplit("/", 1)[-1]
        if not slug or any(loc.rstrip("/").endswith(p.rstrip("/")) for p in src.include):
            continue  # page d'index (/news/), pas un article
        title, summary = slug.replace("-", " ").capitalize(), ""
        # Le sitemap ne donne pas le titre : on lit la page, mais seulement pour les éléments récents.
        if start <= published < end and fetched_titles < MAX_SITEMAP_TITLE_FETCHES:
            fetched_titles += 1
            try:
                page = fetch(client, loc, retries=1).text[:200_000]
                m = _TITLE_RE.search(page) or _TITLE_RE2.search(page)
                if m:
                    title = clean_text(m.group(1), 300)
                d = _DESC_RE.search(page)
                summary = clean_text(d.group(1)) if d else ""
            except Exception as e:  # noqa: BLE001
                log.info("titre introuvable pour %s : %s", loc, e)
        items.append(Item(title=title, url=loc, source=src.name, tier=src.tier,
                          categories=src.categories, published=published, summary=summary))
    return items


def read_arxiv(client: httpx.Client, src: Source, start: datetime, end: datetime) -> list[Item]:
    query = " OR ".join(f"cat:{c}" for c in src.arxiv_categories)
    r = fetch(client, src.url.replace("http://", "https://"), params={
        "search_query": query,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": src.max_items,
    })
    feed = feedparser.parse(r.content)
    items = []
    for e in feed.entries:
        t = e.get("published_parsed")
        if not t:
            continue
        link = e.link.replace("http://", "https://")
        items.append(Item(
            title=clean_text(e.title, 300),
            url=re.sub(r"v\d+$", "", link),  # lien sans numéro de version
            source=src.name,
            tier=src.tier,
            categories=src.categories,
            published=datetime.fromtimestamp(timegm(t), tz=timezone.utc),
            summary=clean_text(e.get("summary"), 600),
        ))
    return items


def read_hn(client: httpx.Client, src: Source, start: datetime, end: datetime) -> list[Item]:
    r = fetch(client, src.url, params={
        "tags": "story",
        "numericFilters": f"created_at_i>={int(start.timestamp())},"
                          f"created_at_i<{int(end.timestamp())},points>={src.min_points}",
        "hitsPerPage": 300,
    })
    items = []
    for h in r.json().get("hits", []):
        hn_url = f"https://news.ycombinator.com/item?id={h['objectID']}"
        items.append(Item(
            title=clean_text(h.get("title"), 300),
            url=h.get("url") or hn_url,
            source=src.name,
            tier=src.tier,
            categories=src.categories,
            published=datetime.fromtimestamp(h["created_at_i"], tz=timezone.utc),
            primary_url=h.get("url"),
            extra={"points": h.get("points") or 0, "comments": h.get("num_comments") or 0,
                   "hn_url": hn_url},
        ))
    return items


def read_hf_papers(client: httpx.Client, src: Source, start: datetime, end: datetime) -> list[Item]:
    items = []
    day = start.date()
    while day <= end.date():
        r = fetch(client, src.url, params={"date": day.isoformat()})
        for p in r.json():
            paper = p.get("paper", {})
            upvotes = paper.get("upvotes", 0) or 0
            arxiv_id = paper.get("id")
            # Date d'arrivée dans les Daily Papers ; à défaut, midi du jour demandé
            # (la date "publishedAt" est celle du papier sur arXiv, souvent bien plus ancienne).
            published = (parse_date(paper.get("submittedOnDailyAt"))
                         or parse_date(p.get("submittedOnDailyAt"))
                         or datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc))
            if not arxiv_id or not published or upvotes < src.min_upvotes:
                continue
            items.append(Item(
                title=clean_text(paper.get("title") or p.get("title"), 300),
                url=f"https://huggingface.co/papers/{arxiv_id}",
                source=src.name,
                tier=src.tier,
                categories=src.categories,
                published=published,
                summary=clean_text(paper.get("summary"), 600),
                primary_url=f"https://arxiv.org/abs/{arxiv_id}",
                extra={"upvotes": upvotes},
            ))
        day += timedelta(days=1)
    return items


_GH_REPO_RE = re.compile(r'<h2 class="h3 lh-condensed">\s*<a[^>]+href="/([^"/]+/[^"/]+)"', re.S)
_GH_ARTICLE_RE = re.compile(r'<article class="Box-row">(.*?)</article>', re.S)
_GH_DESC_RE = re.compile(r'<p class="col-9[^"]*">(.*?)</p>', re.S)
_GH_STARS_RE = re.compile(r"([\d,]+)\s+stars? (today|this week)")


def read_github_trending(client: httpx.Client, src: Source, start: datetime, end: datetime) -> list[Item]:
    page = fetch(client, src.url).text
    now = min(datetime.now(timezone.utc), end - timedelta(seconds=1))
    items = []
    for block in _GH_ARTICLE_RE.findall(page):
        m = _GH_REPO_RE.search(block)
        if not m:
            continue
        repo = m.group(1).strip()
        desc = _GH_DESC_RE.search(block)
        stars = _GH_STARS_RE.search(block)
        items.append(Item(
            title=repo,
            url=f"https://github.com/{repo}",
            source=src.name,
            tier=src.tier,
            categories=src.categories,
            published=now,  # "trending aujourd'hui" : pas de date propre
            summary=clean_text(desc.group(1)) if desc else "",
            extra={"stars_today": int(stars.group(1).replace(",", ""))} if stars else {},
        ))
    return items


READERS = {
    "rss": read_rss,
    "sitemap": read_sitemap,
    "arxiv": read_arxiv,
    "hn_algolia": read_hn,
    "hf_papers": read_hf_papers,
    "github_trending": read_github_trending,
}


# ───────────────────────── orchestration ─────────────────────────

def collect_source(client: httpx.Client, src: Source, start: datetime, end: datetime,
                   ai_match) -> tuple[list[Item], SourceReport]:
    t0 = time.monotonic()
    report = SourceReport(name=src.name, method=src.method, tier=src.tier, ok=True)
    if src.method == "web_search":
        report.error = "pas de flux : couvert par web_search à l'étape d'enquête"
        return [], report
    if src.date_lag_hours:
        lag = timedelta(hours=src.date_lag_hours)
        start, end = start - lag, end - lag
    try:
        items = READERS[src.method](client, src, start, end)
    except Exception as e:  # noqa: BLE001 — une source en panne ne doit jamais casser le run
        report.ok = False
        report.error = f"{type(e).__name__}: {str(e).splitlines()[0][:150] if str(e) else ''}"
        report.seconds = round(time.monotonic() - t0, 1)
        return [], report

    report.total = len(items)
    report.newest = max((i.published for i in items), default=None)
    kept = [i for i in items if start <= i.published < end]
    if src.filter == "ai":
        kept = [i for i in kept if ai_match(f"{i.title} {i.summary}")]
    report.in_window = len(kept)
    report.seconds = round(time.monotonic() - t0, 1)
    return kept, report


def collect_all(start: datetime, end: datetime, sources_file: SourcesFile | None = None,
                max_workers: int = 8) -> tuple[list[Item], list[SourceReport]]:
    sf = sources_file or load_sources()
    ai_match = build_ai_matcher(sf.ai_keywords)
    active = [s for s in sf.sources if s.enabled]
    with make_client() as client, ThreadPoolExecutor(max_workers=max_workers) as pool:
        results = list(pool.map(lambda s: collect_source(client, s, start, end, ai_match), active))
    items = [i for its, _ in results for i in its]
    reports = [r for _, r in results]
    return items, reports
