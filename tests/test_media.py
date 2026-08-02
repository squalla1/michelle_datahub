"""Media fields (feedback 2026-07-19): RSS media extraction, image_url on the
content API, favicon on sources, company logo injection, and the typed
endpoint's latest-N fallback for low-frequency modules."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import feedparser
import pytest
from fastapi.testclient import TestClient

from datahub.api.app import create_app
from datahub.fetchers.rss import _entry_media
from datahub.models import ContentItem, DataSource
from datahub.storage import session_scope

_FEED = """<?xml version="1.0"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"
     xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
     xmlns:yt="http://www.youtube.com/xml/schemas/2015">
<channel><title>t</title>
  <item>
    <title>news with media:content image</title>
    <media:content url="https://cdn.example.com/hero.jpg" medium="image"/>
  </item>
  <item>
    <title>news with image enclosure</title>
    <enclosure url="https://cdn.example.com/pic.png" type="image/png" length="1"/>
  </item>
  <item>
    <title>podcast episode</title>
    <enclosure url="https://cdn.example.com/ep1.mp3" type="audio/mpeg" length="2"/>
    <itunes:duration>31:45</itunes:duration>
  </item>
  <item>
    <title>youtube video</title>
    <link>https://www.youtube.com/watch?v=abc123</link>
    <yt:videoId>abc123</yt:videoId>
    <media:thumbnail url="https://i.ytimg.com/vi/abc123/hq.jpg"/>
  </item>
  <item><title>plain text item</title></item>
</channel></rss>"""


def test_entry_media_extraction():
    entries = feedparser.parse(_FEED).entries
    assert _entry_media(entries[0]) == ("https://cdn.example.com/hero.jpg", {})
    assert _entry_media(entries[1]) == ("https://cdn.example.com/pic.png", {})

    image, extras = _entry_media(entries[2])
    assert image is None
    assert extras == {
        "audio_url": "https://cdn.example.com/ep1.mp3",
        "audio_mime": "audio/mpeg",
        "audio_duration": "31:45",
    }

    image, extras = _entry_media(entries[3])
    assert image == "https://i.ytimg.com/vi/abc123/hq.jpg"
    assert extras == {
        "video_url": "https://www.youtube.com/watch?v=abc123",
        "video_id": "abc123",
    }

    assert _entry_media(entries[4]) == (None, {})


@pytest.fixture
def client(clean_db):
    now = datetime.now(timezone.utc)
    with session_scope() as s:
        src = DataSource(module="news", tab="1_新闻", name="src",
                         url="https://feeds.example.com/rss", enabled=True)
        s.add(src)
        s.flush()
        s.add(ContentItem(source_id=src.id, module="news", external_id="n1",
                          title="with image", image_url="https://cdn.example.com/a.jpg",
                          published_at=now))
        s.add(ContentItem(source_id=src.id, module="company", external_id="c1",
                          title="apple filing", published_at=now,
                          payload={"symbol": "AAPL", "data_type": "公告"}))
        # calendar: only an old item — exercises the latest-N fallback
        s.add(ContentItem(source_id=src.id, module="calendar", external_id="k1",
                          title="old calendar", published_at=now - timedelta(days=3),
                          fetched_at=(now - timedelta(days=3)).replace(tzinfo=None)))
    return TestClient(create_app())


def test_image_url_exposed(client):
    items = client.get("/api/v1/content/news").json()
    assert items[0]["image_url"] == "https://cdn.example.com/a.jpg"


def test_company_logo_injected_from_symbol(client):
    items = client.get("/api/v1/content/company").json()
    assert items[0]["payload"]["logo_url"] == (
        "https://images.financialmodelingprep.com/symbol/AAPL.png"
    )


def test_source_icon_and_avatar(client):
    src = client.get("/api/v1/sources").json()[0]
    assert src["icon_url"] == (
        "https://www.google.com/s2/favicons?domain=feeds.example.com&sz=64"
    )
    assert src["avatar_url"] == src["icon_url"]


def test_low_frequency_module_falls_back_to_latest(client):
    # default (date omitted): today's window is empty -> latest N overall
    for by in ("published", "fetched"):
        items = client.get("/api/v1/content/calendar", params={"by": by}).json()
        assert [it["title"] for it in items] == ["old calendar"]
    # explicit date never falls back
    today = datetime.now(timezone.utc).date().isoformat()
    assert client.get("/api/v1/content/calendar", params={"date": today}).json() == []
