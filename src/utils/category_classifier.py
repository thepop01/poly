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
         "tennis", "wimbledon", "wta", "atp", "roland garros", "us open",
         "australian open", "davis cup", "fed cup",
         "mma", "ufc", "boxing", "baseball", "hockey", "basketball", "rugby",
         "fifa", "world cup", "olympics", "formula 1", "f1", "golf",
         "pga", "masters", "champions league", "premier league", "la liga",
         "bundesliga", "serie a", "ligue 1", "cric", "ipl"],
        ["soccer", "football", "nfl", "nba", "mlb", "nhl", "cricket", "tennis",
         "wimbledon", "wta", "atp", "roland garros", "us open",
         "australian open", "davis cup",
         "mma", "ufc", "boxing", "baseball", "hockey", "basketball", "rugby",
         "fifa", "world cup", "olympics", "formula 1", "f1", "golf",
         "pga", "masters", "champions league", "premier league", "la liga",
         "bundesliga", "serie a", "ipl"],
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
         "foreign policy", "sanction", "military", "war", "nato",
         "iran", "ukraine", "russia", "china", "israel", "gaza",
         "taiwan", "north korea", "south korea", "syria", "iraq",
         "afghanistan", "pakistan", "india", "turkey", "saudi",
         "venezuela", "cuba", "mexico", "colombia", "brazil",
         "argentina", "european union", "eu", "united nations", "un"],
    ),
]


def classify_tags(tag_labels: list[str]) -> tuple[str, str]:
    """Return (category, subcategory) derived from a list of Gamma API tag labels.

    Tags are matched case-insensitively.  Uses majority voting: the category
    with the most matching tags wins.  Within the winning category, the
    *last* matching subcategory keyword becomes the subcategory (so more-specific
    tags win over generic ones).
    """
    if not tag_labels:
        return ("Other", "General")

    lower_tags = [t.lower() for t in tag_labels]

    # Count matches per category
    category_scores: dict[str, int] = {}
    category_sub_matches: dict[str, list[str]] = {}

    for category, cat_subs, sub_subs in _CATEGORY_RULES:
        score = 0
        subs_found: list[str] = []
        for t in lower_tags:
            if any(_word_match(kw, t) for kw in cat_subs):
                score += 1
                for kw in sub_subs:
                    if _word_match(kw, t):
                        subs_found.append(kw)
        if score > 0:
            category_scores[category] = score
            category_sub_matches[category] = subs_found

    if not category_scores:
        return ("Other", "General")

    # Pick the category with the highest score
    best_category = max(category_scores, key=lambda k: category_scores[k])

    # Pick the most specific subcategory keyword (last match wins)
    subs = category_sub_matches.get(best_category, [])
    subcategory = best_category  # fallback
    if subs:
        subcategory = subs[-1].title()

    return (best_category, subcategory)


# ── Flatten mappings: map detailed subcategories to top-level types ──────
# Used for filter dropdowns. Stored in wallet_tags.subcategory.
# Detailed subcategory (NFL, NBA, EPL) stored in global_wallet_trades.

SPORTS_FLATTEN: dict[str, str] = {
    # Football family
    "nfl": "Football", "cfl": "Football", "cfb": "Football",
    "ncaaf": "Football", "ncaa football": "Football", "football": "Football",
    # Basketball family
    "nba": "Basketball", "wnba": "Basketball", "ncaab": "Basketball",
    "basketball": "Basketball",
    # Baseball family
    "mlb": "Baseball", "baseball": "Baseball",
    # Hockey family
    "nhl": "Hockey", "hockey": "Hockey",
    # Soccer family
    "soccer": "Soccer", "epl": "Soccer", "ucl": "Soccer",
    "laliga": "Soccer", "la liga": "Soccer", "bundesliga": "Soccer",
    "serie a": "Soccer", "ligue 1": "Soccer", "eredivisie": "Soccer",
    "mls": "Soccer", "copa america": "Soccer", "world cup": "Soccer",
    "europa league": "Soccer", "champions league": "Soccer",
    "fifa": "Soccer", "premier league": "Soccer",
    # Other sports
    "tennis": "Tennis", "wta": "Tennis", "atp": "Tennis",
    "wimbledon": "Tennis", "roland garros": "Tennis",
    "us open": "Tennis", "australian open": "Tennis",
    "davis cup": "Tennis",
    "cricket": "Cricket", "ipl": "Cricket", "major league cricket": "Cricket",
    "big bash": "Cricket",
    "mma": "MMA", "ufc": "MMA", "combat": "MMA",
    "f1": "Formula 1", "formula 1": "Formula 1", "formula one": "Formula 1",
    "golf": "Golf", "pga": "Golf", "masters": "Golf",
    "rugby": "Rugby", "six nations": "Rugby",
    "table tennis": "Table Tennis",
    "pickleball": "Pickleball",
    "lacrosse": "Lacrosse",
    "chess": "Chess",
    "olympics": "Olympics",
}

ESPORTS_FLATTEN: dict[str, str] = {
    "cs2": "Esports", "counter-strike": "Esports", "counter strike": "Esports",
    "dota2": "Esports", "dota": "Esports",
    "lol": "Esports", "league of legends": "Esports",
    "valorant": "Esports", "overwatch": "Esports", "fortnite": "Esports",
    "esports": "Esports", "e-sports": "Esports",
}


def flatten_subcategory(category: str, subcategory: str) -> str:
    """Map detailed subcategory to top-level type for filter dropdowns.

    Sports: NFL -> Football, NBA -> Basketball, EPL -> Soccer, etc.
    Esports: CS2 -> Esports, LoL -> Esports, etc.
    Other categories: returned as-is.
    """
    if not subcategory:
        return subcategory
    key = subcategory.lower().strip()
    if category == "Sports":
        return SPORTS_FLATTEN.get(key, subcategory)
    elif category == "Esports":
        return ESPORTS_FLATTEN.get(key, subcategory)
    return subcategory
