from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from src.polybot.schemas import EvidenceItem, EvidencePack, GraphEdge, MarketCandidate
from src.polybot.retrieval.evidence_store import EvidenceStore


class SerperNewsClient:
    def __init__(
        self,
        api_key: str,
        endpoint: str = "https://google.serper.dev/news",
        gl: str = "us",
        hl: str = "en",
        num: int = 8,
    ) -> None:
        self.api_key = api_key.strip()
        self.endpoint = endpoint
        self.gl = gl
        self.hl = hl
        self.num = num
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "polybot-serper/1.0"})

    def search_news(self, query: str, num: int) -> list[dict[str, Any]]:
        if not self.api_key:
            return []
        payload = {"q": query, "gl": self.gl, "hl": self.hl, "num": num}
        headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json",
        }
        try:
            resp = self.session.post(self.endpoint, json=payload, headers=headers, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            news = data.get("news", [])
            return news if isinstance(news, list) else []
        except Exception:
            return []

    def fetch_article_text(self, link: str, max_paragraphs: int = 8) -> str:
        if not link:
            return ""
        try:
            resp = self.session.get(link, timeout=8)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            paragraphs = []
            for p in soup.find_all("p"):
                txt = p.get_text(" ", strip=True)
                if len(txt) >= 60:
                    paragraphs.append(txt)
                if len(paragraphs) >= max_paragraphs:
                    break
            return " ".join(paragraphs)[:3500]
        except Exception:
            return ""


class SerperNewsEvidenceStore(EvidenceStore):
    HIGH_AUTH_DOMAINS = {
        "reuters.com",
        "apnews.com",
        "bloomberg.com",
        "wsj.com",
        "ft.com",
        "nytimes.com",
        "bbc.com",
        "economist.com",
        "sec.gov",
        "federalreserve.gov",
        "bls.gov",
        "fec.gov",
    }
    MEDIUM_AUTH_DOMAINS = {
        "cnbc.com",
        "marketwatch.com",
        "axios.com",
        "politico.com",
        "thehill.com",
    }
    POSITIVE_HINTS = {"approve", "rise", "win", "pass", "supports", "strong", "boost", "outperform"}
    NEGATIVE_HINTS = {"reject", "fall", "lose", "block", "weak", "denies", "lawsuit", "delay", "cut"}

    def __init__(self, client: SerperNewsClient) -> None:
        self.client = client

    def retrieve(self, query: str, market: MarketCandidate, top_k: int) -> EvidencePack:
        rows = self.client.search_news(query=query, num=top_k)
        if not rows:
            return EvidencePack(query=query, items=[], edges=[], contradiction_score=0.0)

        items = [self._to_evidence_item(r, market.market_id, i) for i, r in enumerate(rows)]
        items = [x for x in items if x.quality_score >= 0.48]
        edges = self._build_contradiction_edges(items)
        contradiction = self._estimate_contradiction(edges)
        return EvidencePack(query=query, items=items[:top_k], edges=edges[:top_k], contradiction_score=contradiction)

    def _to_evidence_item(self, row: dict[str, Any], market_id: str, idx: int) -> EvidenceItem:
        title = str(row.get("title", "")).strip()
        snippet = str(row.get("snippet", "")).strip()
        link = str(row.get("link", "")).strip()
        source = str(row.get("source", "")).strip() or self._domain(link) or "unknown"
        date_text = str(row.get("date", "")).strip()
        published_at = self._parse_date(date_text)
        article_text = self.client.fetch_article_text(link=link)
        quality = self._quality_score(source, link, published_at, article_text)
        stance = self._stance(f"{title} {snippet} {article_text[:900]}")
        stable_id = hashlib.sha1(f"{market_id}:{link}:{idx}".encode("utf-8")).hexdigest()[:16]
        stance_label = "neutral"
        if stance > 0:
            stance_label = "positive"
        elif stance < 0:
            stance_label = "negative"

        packed_text = (
            f"title: {title}\n"
            f"snippet: {snippet}\n"
            f"url: {link}\n"
            f"stance: {stance_label}\n"
            f"article: {article_text[:2200]}"
        )
        return EvidenceItem(
            evidence_id=f"serper-{stable_id}",
            source=f"serper:{source}",
            published_at=published_at,
            text=packed_text,
            quality_score=quality,
        )

    def _build_contradiction_edges(self, items: list[EvidenceItem]) -> list[GraphEdge]:
        edges: list[GraphEdge] = []
        stances = [(item.evidence_id, self._stance(item.text), item.quality_score) for item in items]
        for i in range(len(stances)):
            for j in range(i + 1, len(stances)):
                a_id, a_s, a_q = stances[i]
                b_id, b_s, b_q = stances[j]
                if a_s == 0 or b_s == 0:
                    continue
                weight = min(1.0, max(0.2, (a_q + b_q) / 2.0))
                if a_s * b_s < 0:
                    edges.append(
                        GraphEdge(
                            from_id=a_id,
                            to_id=b_id,
                            relation="contradicts",
                            signed_weight=round(-1 * weight, 3),
                        )
                    )
                else:
                    edges.append(
                        GraphEdge(
                            from_id=a_id,
                            to_id=b_id,
                            relation="supports",
                            signed_weight=round(0.6 * weight, 3),
                        )
                    )
        return edges

    def _stance(self, text: str) -> int:
        t = text.lower()
        pos = sum(1 for k in self.POSITIVE_HINTS if k in t)
        neg = sum(1 for k in self.NEGATIVE_HINTS if k in t)
        if pos > neg:
            return 1
        if neg > pos:
            return -1
        return 0

    def _quality_score(self, source: str, link: str, published_at: datetime, article_text: str) -> float:
        domain = source.lower()
        if "serper:" in domain:
            domain = domain.replace("serper:", "")
        domain = domain or self._domain(link)
        domain_score = 0.62
        if domain in self.HIGH_AUTH_DOMAINS:
            domain_score = 0.9
        elif domain in self.MEDIUM_AUTH_DOMAINS:
            domain_score = 0.75
        elif domain.endswith(".gov"):
            domain_score = 0.92

        now = datetime.now(tz=timezone.utc)
        age_hours = max(0.0, (now - published_at).total_seconds() / 3600.0)
        if age_hours <= 24:
            recency_score = 1.0
        elif age_hours <= 72:
            recency_score = 0.88
        elif age_hours <= 168:
            recency_score = 0.74
        else:
            recency_score = 0.6

        content_len = len(article_text.strip())
        if content_len >= 2000:
            content_score = 0.95
        elif content_len >= 900:
            content_score = 0.82
        elif content_len >= 250:
            content_score = 0.68
        else:
            content_score = 0.55

        return round(0.5 * domain_score + 0.3 * recency_score + 0.2 * content_score, 4)

    def _domain(self, link: str) -> str:
        try:
            return (urlparse(link).netloc or "").lower().replace("www.", "")
        except Exception:
            return ""

    def _parse_date(self, text: str) -> datetime:
        if not text:
            return datetime.now(tz=timezone.utc)
        lower = text.lower().strip()
        now = datetime.now(tz=timezone.utc)
        rel = re.search(r"(\d+)\s+(minute|hour|day|week|month)s?\s+ago", lower)
        if rel:
            n = int(rel.group(1))
            unit = rel.group(2)
            if unit == "minute":
                return now - timedelta(minutes=n)
            if unit == "hour":
                return now - timedelta(hours=n)
            if unit == "day":
                return now - timedelta(days=n)
            if unit == "week":
                return now - timedelta(weeks=n)
            if unit == "month":
                return now - timedelta(days=30 * n)
        normalized = text.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(normalized)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return now

    def _estimate_contradiction(self, edges: list[GraphEdge]) -> float:
        if not edges:
            return 0.0
        contradictions = sum(1 for e in edges if e.relation == "contradicts" or e.signed_weight < 0)
        return round(contradictions / len(edges), 4)
