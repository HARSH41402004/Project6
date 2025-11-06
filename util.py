# utils.py
import requests
import feedparser
from bs4 import BeautifulSoup
import hashlib
from datetime import datetime
import re

def fetch_newsapi_articles(query: str, from_iso: str, api_key: str, page_size: int = 100):
    """
    Fetch articles using NewsAPI.org everything endpoint.
    Returns list of dicts with keys: title, description, content, url, publishedAt, source.name
    """
    url = "https://newsapi.org/v2/everything"
    headers = {"Authorization": api_key}
    params = {
        "q": query,
        "from": from_iso,
        "language": "en",
        "pageSize": page_size,
        "sortBy": "publishedAt",
    }
    resp = requests.get(url, params=params, headers=headers, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    articles = []
    for a in data.get("articles", []):
        articles.append({
            "title": a.get("title"),
            "description": a.get("description"),
            "content": a.get("content"),
            "url": a.get("url"),
            "published": a.get("publishedAt"),
            "source": a.get("source", {}).get("name"),
        })
    return articles

def fetch_google_news_rss(query: str, limit: int = 100):
    """
    Use Google News RSS for a given query.
    Returns list of dicts with title, description, link, published.
    """
    # Construct Google News RSS query
    # NOTE: Google News RSS uses the 'q' parameter; encode query
    q = requests.utils.requote_uri(query)
    rss_url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    feed = feedparser.parse(rss_url)
    articles = []
    for entry in feed.entries[:limit]:
        # try to get full article text via link scraping (light)
        content = entry.get("summary", "")
        link = entry.get("link")
        published = entry.get("published")
        # attempt to get fuller text (lightweight)
        try:
            page = requests.get(link, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
            soup = BeautifulSoup(page.text, "html.parser")
            # pick first paragraphs
            ps = soup.find_all("p")
            if ps:
                content = " ".join([p.get_text() for p in ps[:6]])
        except Exception:
            pass
        articles.append({
            "title": entry.get("title"),
            "description": entry.get("summary"),
            "content": content,
            "url": link,
            "published": published,
            "source": entry.get("source", {}).get("title") if entry.get("source") else None,
        })
    return articles

def normalize_article(a: dict, source: str = None):
    """
    Normalize keys to a consistent schema.
    """
    out = {}
    out["title"] = a.get("title") or a.get("headline") or ""
    out["description"] = a.get("description") or ""
    out["content"] = a.get("content") or a.get("snippet") or out["description"]
    out["source_url"] = a.get("url") or a.get("link") or ""
    out["published"] = a.get("published") or a.get("publishedAt") or datetime.utcnow().isoformat()
    out["source"] = a.get("source") or source or ""
    out["summary"] = (out["description"][:300] + "...") if out["description"] else (out["content"][:300] + "...")
    # id for dedupe
    key = (out["title"] or "") + (out["source_url"] or "")
    out["id"] = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return out

def dedupe_articles(articles):
    """
    Remove duplicate articles by id (title+url hash), keep latest published.
    """
    seen = {}
    for a in articles:
        norm = normalize_article(a, source=a.get("source"))
        key = norm["id"]
        existing = seen.get(key)
        if not existing:
            seen[key] = norm
        else:
            # prefer one with longer content / later date
            existing_content_len = len(existing.get("content","") or "")
            new_content_len = len(norm.get("content","") or "")
            if new_content_len > existing_content_len:
                seen[key] = norm
    return list(seen.values())

def detect_mutual_fund_mentions(article: dict, mf_list):
    """
    Return list of mutual fund firm names found in title/description/content.
    Simple case-insensitive substring matching (can be replaced by fuzzy matching).
    """
    text = " ".join([article.get("title",""), article.get("description",""), article.get("content","")]).lower()
    found = []
    for mf in mf_list:
        if mf.lower() in text:
            found.append(mf)
    # also simple pattern match for 'AMC' or 'Mutual Fund' mentions with firm names
    # return unique
    return sorted(list(set(found)))
