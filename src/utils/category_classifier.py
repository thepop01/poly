"""Map Polymarket Gamma API event tags to category + subcategory."""

import re


def _word_match(keyword: str, text: str) -> bool:
    """Match keyword as a whole word (or at start/end of text) to avoid
    false positives like 'ai' inside 'geopolitics'."""
    if len(keyword) <= 3:
        return bool(re.search(r'(?<![a-z])' + re.escape(keyword) + r'(?![a-z])', text))
    return keyword in text


# ── Category rules (order matters: first match wins) ──────────────────────
_CATEGORY_RULES: list[tuple[str, list[str], list[str]]] = [
    # (category, [tag substrings], [subcategory tag substrings])
    (
        "Esports",
        ["esport", "e-sport", "league of legends", "dota", "cs2", "counter-strike",
         "valorant", "fortnite", "overwatch", "gaming tournament"],
        ["league of legends", "dota", "cs2", "counter-strike", "valorant",
         "fortnite", "overwatch"],
    ),
    (
        "Sports",
        ["sports", "soccer", "football", "nfl", "nba", "mlb", "nhl", "cricket",
         "tennis", "mma", "ufc", "baseball", "hockey", "basketball", "rugby",
         "fifa", "world cup", "olympics", "formula 1", "f1", "golf"],
        ["soccer", "football", "nfl", "nba", "mlb", "nhl", "cricket", "tennis",
         "mma", "ufc", "baseball", "hockey", "basketball", "rugby", "fifa",
         "world cup", "olympics", "formula 1", "f1", "golf"],
    ),
    (
        "Crypto",
        ["crypto", "bitcoin", "ethereum", "defi", "nft", "airdrop", "stablecoin",
         "token", "blockchain", "solana", "memecoin", "meme coin", "binance",
         "coinbase", "exchange", "altcoin"],
        ["bitcoin", "ethereum", "solana", "defi", "nft", "airdrop", "stablecoin",
         "token launch", "memecoin", "meme coin", "binance", "coinbase",
         "altcoin", "crypto prices", "crypto listings", "crypto legal"],
    ),
    (
        "Finance",
        ["finance", "ipo", "bank", "fed", "interest rate", "stock", "s&p",
         "nasdaq", "dow", "wall street", "hedge fund", "credit", "loan"],
        ["ipo", "bank", "fed", "fed rates", "interest rate", "stock",
         "hedge fund", "credit"],
    ),
    (
        "Economics",
        ["econom", "gdp", "inflation", "deflation", "recession", "unemploy",
         "trade war", "tariff", "fiscal", "monetary", "labor", "wage",
         "cpi", "ppi", "consumer price"],
        ["gdp", "inflation", "deflation", "recession", "unemploy", "tariff",
         "fiscal", "monetary", "labor", "wage", "cpi", "trade"],
    ),
    (
        "Culture",
        ["pop culture", "celebrit", "music", "movie", "film", "tv show",
         "entertainment", "taylor swift", "kardashian", "oscar", "grammy",
         "netflix", "gaming", "video game", "gta"],
        ["music", "movie", "film", "celebrit", "tv show", "gaming",
         "video game", "taylor swift", "oscar", "grammy", "netflix", "gta"],
    ),
    (
        "Tech",
        ["tech", "artificial intelligence", "robot", "tesla", "openai",
         "gpt", "apple", "google", "meta", "amazon", "spacex", "space",
         "autonom", "software", "hardware", "chip", "semiconductor"],
        ["artificial intelligence", "robot", "tesla", "openai", "gpt",
         "spacex", "space", "autonom", "chip", "semiconductor"],
    ),
    (
        "Weather",
        ["weather", "hurricane", "tornado", "flood", "drought", "climate",
         "storm", "cyclone", "typhoon", "wildfire", "earthquake", "volcano"],
        ["hurricane", "tornado", "flood", "drought", "climate", "storm",
         "cyclone", "typhoon", "wildfire", "earthquake"],
    ),
    (
        "Mentions",
        ["mention", "celebrity mention"],
        ["trump", "biden", "putin", "zelensky", "macron", "musk", "bezos",
         "xi jinping", "modi", "erdogan", "kim jong", "pope"],
    ),
    (
        "Politics",
        ["politic", "election", "president", "congress", "senate", "governor",
         "democrat", "republican", "primary", "midterm", "ballot", "vote",
         "legislat", "court", "supreme court", "diplomat", "sanction",
         "geopolit", "military", "nato", "foreign policy", "war",
         "ukraine", "russia", "china", "israel", "gaza", "iran",
         "world", "resign", "impeach"],
        ["election", "geopolit", "president", "congress", "senate",
         "governor", "primary", "midterm", "supreme court", "diplomat",
         "foreign policy", "sanction", "military", "war", "nato"],
    ),
]


def classify_tags(tag_labels: list[str]) -> tuple[str, str]:
    """Return (category, subcategory) derived from a list of Gamma API tag labels.

    Tags are matched case-insensitively.  The first matching category rule wins.
    Within a rule the *last* matching subcategory tag becomes the subcategory
    (so more-specific tags win over generic ones).
    """
    if not tag_labels:
        return ("Other", "General")

    lower_tags = [t.lower() for t in tag_labels]

    for category, cat_subs, sub_subs in _CATEGORY_RULES:
        # Check if ANY tag matches this category
        cat_match = any(
            any(_word_match(kw, t) for kw in cat_subs) for t in lower_tags
        )
        if not cat_match:
            continue

        # Find the most specific subcategory tag (last match wins)
        subcategory = category  # fallback to category name
        for t in reversed(lower_tags):
            if any(_word_match(kw, t) for kw in sub_subs):
                # Title-case the matched tag for display
                subcategory = t.title()
                break

        return (category, subcategory)

    return ("Other", "General")
