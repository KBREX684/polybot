from __future__ import annotations

import re

from src.polybot.schemas import MarketCategory, MarketCandidate

# Compiled regex rules — zero LLM cost
_CLASSIFIER_RULES: list[tuple[re.Pattern[str], MarketCategory]] = [
    # MACRO
    (re.compile(r"\b(inflation|cpi|gdp|unemployment|fed|fomc|interest rate|treasury|recession|fiscal|monetary)\b", re.I), "MACRO"),
    (re.compile(r"\b(federal reserve|central bank|bond yield|quantitative|stimulus|deficit)\b", re.I), "MACRO"),
    # ELECTION
    (re.compile(r"\b(election|vote|ballot|primary|poll|senat|congress|governor|president|campaign)\b", re.I), "ELECTION"),
    (re.compile(r"\b(republican|democrat|trump|biden|harris|swing state|electoral)\b", re.I), "ELECTION"),
    (re.compile(r"\b(brexit|parliament|chancellor|prime minister)\b", re.I), "ELECTION"),
    # CORPORATE
    (re.compile(r"\b(earnings|revenue|profit|ipo|stock|share|dividend|merger|acquisition|buyout)\b", re.I), "CORPORATE"),
    (re.compile(r"\b(apple|google|tesla|meta|microsoft|amazon|nvidia|openai|netflix)\b", re.I), "CORPORATE"),
    (re.compile(r"\b(ceo|cfo|board of director|quarterly|sec filing|10-k|10-q)\b", re.I), "CORPORATE"),
    # LEGAL
    (re.compile(r"\b(supreme court|lawsuit|indict|verdict|ruling|appeal|convict|acquitt|sentenc)\b", re.I), "LEGAL"),
    (re.compile(r"\b(department of justice|doj|sec charge|ftc|antitrust|guilty|plea)\b", re.I), "LEGAL"),
    (re.compile(r"\b(trial|hearing|gag order|subpoena|arrest|prosecutor)\b", re.I), "LEGAL"),
    # TECHNOLOGY (check before CORPORATE to catch openai/gpt/ai correctly)
    (re.compile(r"\b(openai.*(?:gpt|release|launch|announce))\b", re.I), "TECHNOLOGY"),
    (re.compile(r"\b(ai|artificial intelligence|llm|chatgpt|gpt-\d|machine learning|deep learning)\b", re.I), "TECHNOLOGY"),
    (re.compile(r"\b(chip|semiconductor|amd|intel|tsmc|quantum computing|blockchain)\b", re.I), "TECHNOLOGY"),
    (re.compile(r"\b(regulate ai|ai safety|open source model|robot|autonomous|self-driving)\b", re.I), "TECHNOLOGY"),
    # SCIENCE
    (re.compile(r"\b(nasa|spacex|rocket|moon|mars|space station|launch|orbit)\b", re.I), "SCIENCE"),
    (re.compile(r"\b(climate|temperature|carbon|emission|hurricane|earthquake|weather)\b", re.I), "SCIENCE"),
    (re.compile(r"\b(covid|pandemic|vaccine|fda|clinical trial|disease|outbreak|who health)\b", re.I), "SCIENCE"),
    # SPORTS
    (re.compile(r"\b(super bowl|world cup|olympics|nba|nfl|mlb|nhl|ufc|championship game)\b", re.I), "SPORTS"),
    (re.compile(r"\b(win the (game|match|series|cup|title|final|trophy))\b", re.I), "SPORTS"),
    (re.compile(r"\b(score|goal|touchdown|home run|knockout|penalty kick)\b", re.I), "SPORTS"),
    # CRYPTO
    (re.compile(r"\b(bitcoin|btc|ethereum|eth|crypto|token|defi|nft|airdrop|wallet)\b", re.I), "CRYPTO"),
    (re.compile(r"\b(sec.*crypto|etf.*bitcoin|spot.*etf|halving|staking|stablecoin)\b", re.I), "CRYPTO"),
    # GEOPOLITICS
    (re.compile(r"\b(war|conflict|invasion|sanction|treaty|nato|eu |european union|ceasefire)\b", re.I), "GEOPOLITICS"),
    (re.compile(r"\b(ukraine|russia|china|iran|israel|taiwan|north korea|gaza)\b", re.I), "GEOPOLITICS"),
    (re.compile(r"\b(diplomat|ambassador|peace talk|summit|foreign minister)\b", re.I), "GEOPOLITICS"),
    # CULTURE
    (re.compile(r"\b(oscar|emmy|grammy|box office|movie|album|song|celebrity|award)\b", re.I), "CULTURE"),
    (re.compile(r"\b(record|billboard|streaming|spotify|netflix.*show|release date)\b", re.I), "CULTURE"),
]

# Category-specific site-restricted search domains
CATEGORY_SEARCH_SITES: dict[MarketCategory, list[str]] = {
    "MACRO": ["site:bls.gov", "site:federalreserve.gov", "site:treasury.gov", "site:reuters.com"],
    "ELECTION": ["site:fec.gov", "site:270towin.com", "site:realclearpollitics.com", "site:reuters.com"],
    "CORPORATE": ["site:sec.gov", "site:investor.com", "site:bloomberg.com", "site:reuters.com"],
    "LEGAL": ["site:law.cornell.edu", "site:reuters.com", "site:apnews.com"],
    "TECHNOLOGY": ["site:arxiv.org", "site:techcrunch.com", "site:theverge.com", "site:reuters.com"],
    "SCIENCE": ["site:nasa.gov", "site:nature.com", "site:science.org", "site:reuters.com"],
    "SPORTS": ["site:espn.com", "site:sports-reference.com", "site:reuters.com"],
    "CRYPTO": ["site:coindesk.com", "site:cointelegraph.com", "site:reuters.com"],
    "GEOPOLITICS": ["site:reuters.com", "site:apnews.com", "site:bbc.com"],
    "CULTURE": ["site:variety.com", "site:hollywoodreporter.com", "site:billboard.com"],
    "OTHER": ["site:reuters.com", "site:apnews.com"],
}


def classify_market(market: MarketCandidate) -> MarketCategory:
    """Classify a market into a category using regex rules. Zero LLM cost."""
    text = f"{market.question}"
    scores: dict[MarketCategory, int] = {}
    for pattern, category in _CLASSIFIER_RULES:
        if pattern.search(text):
            scores[category] = scores.get(category, 0) + 1
    if not scores:
        return "OTHER"
    return max(scores, key=scores.get)  # type: ignore[arg-type]


def build_category_queries(market: MarketCandidate, category: MarketCategory) -> list[str]:
    """Build category-specific search queries for GraphRAG."""
    q = market.question.strip()
    sites = CATEGORY_SEARCH_SITES.get(category, CATEGORY_SEARCH_SITES["OTHER"])
    site_clause = " OR ".join(sites[:3])

    return [
        f"{q} {site_clause}",
        f"{q} latest official confirmation evidence",
        f"{q} evidence against outcome contradictory analysis",
    ]
