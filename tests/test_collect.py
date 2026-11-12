"""Tests de la collecte — aucun appel réseau : on simule les réponses HTTP."""

from datetime import datetime, timezone

import httpx

from ai_signal.collect import build_ai_matcher, clean_text, collect_source, load_sources
from ai_signal.models import Source

START = datetime(2026, 11, 11, 8, tzinfo=timezone.utc)
END = datetime(2026, 11, 12, 8, tzinfo=timezone.utc)

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>Lab</title>
<item><title>New model released</title><link>https://lab.example/new-model</link>
<pubDate>Wed, 11 Nov 2026 15:00:00 GMT</pubDate><description>&lt;p&gt;A &lt;b&gt;big&lt;/b&gt; LLM.&lt;/p&gt;</description></item>
<item><title>Old post</title><link>https://lab.example/old</link>
<pubDate>Mon, 09 Nov 2026 15:00:00 GMT</pubDate></item>
<item><title>Gardening tips</title><link>https://lab.example/garden</link>
<pubDate>Wed, 11 Nov 2026 16:00:00 GMT</pubDate></item>
</channel></rss>"""


def client_returning(body: str, status: int = 200) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(status, text=body)))


def src(**kw) -> Source:
    base = {"name": "Lab", "url": "https://lab.example/feed", "method": "rss", "tier": 1}
    return Source(**{**base, **kw})


def matcher():
    return build_ai_matcher(load_sources().ai_keywords)


def test_sources_yaml_is_valid():
    sf = load_sources()
    names = [s.name for s in sf.sources]
    assert len(names) == len(set(names)), "deux sources ont le même nom"
    assert all(s.url.startswith(("http://", "https://")) for s in sf.sources)
    assert any(s.tier == 1 for s in sf.sources)


def test_ai_matcher():
    m = matcher()
    assert m("OpenAI releases a new LLM")
    assert m("Building agents with MCP")
    assert not m("I said the rain was nice")      # "ai" dans un mot ne compte pas
    assert not m("Gardening tips for autumn")


def test_rss_window_and_cleaning():
    items, report = collect_source(client_returning(RSS), src(), START, END, matcher())
    assert report.ok and report.total == 3
    assert [i.title for i in items] == ["New model released", "Gardening tips"]
    assert items[0].summary == "A big LLM."


def test_ai_filter():
    items, _ = collect_source(client_returning(RSS), src(filter="ai"), START, END, matcher())
    assert [i.title for i in items] == ["New model released"]


def test_broken_source_never_raises():
    items, report = collect_source(client_returning("nope", status=404), src(), START, END, matcher())
    assert items == [] and not report.ok and "404" in report.error


def test_date_lag_shifts_window():
    items, _ = collect_source(client_returning(RSS), src(date_lag_hours=48), START, END, matcher())
    assert [i.title for i in items] == ["Old post"]


def test_clean_text_truncates():
    assert clean_text("<p>" + "word " * 200 + "</p>", limit=50).endswith("…")
