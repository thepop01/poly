"""Deterministic 3-tier tag resolver for Polymarket Gamma API event tags.

Hierarchy:
  Category    -> e.g. Sports, Politics, Crypto, Culture, Economics, Finance, Tech, Weather, Esports
  Subcategory -> e.g. Soccer, Basketball, Football, Baseball, Elections, Bitcoin
  League      -> e.g. UEFA Champions League, Premier League, La Liga, Serie A, NBA, NFL, FIFA World Cup
"""

import re
from typing import Optional

# ── LEAGUE CANONICAL MAPPINGS ─────────────────────────────────────────────
# Maps raw tag variants (case-insensitive) to clean display names
LEAGUE_MAP: dict[str, tuple[str, str, str, int]] = {
    # tag_lower -> (Category, Subcategory, Canonical League Name, Specificity Score)

    # ── Soccer Leagues ──
    "ucl": ("Sports", "Soccer", "UEFA Champions League", 10),
    "uefa champions league": ("Sports", "Soccer", "UEFA Champions League", 10),
    "champions league": ("Sports", "Soccer", "UEFA Champions League", 9),
    "europa league": ("Sports", "Soccer", "Europa League", 10),
    "uefa europa league": ("Sports", "Soccer", "Europa League", 10),
    "conference league": ("Sports", "Soccer", "Conference League", 10),
    "premier league": ("Sports", "Soccer", "Premier League", 10),
    "epl": ("Sports", "Soccer", "Premier League", 10),
    "la liga": ("Sports", "Soccer", "La Liga", 10),
    "laliga": ("Sports", "Soccer", "La Liga", 10),
    "serie a": ("Sports", "Soccer", "Serie A", 10),
    "bundesliga": ("Sports", "Soccer", "Bundesliga", 10),
    "ligue 1": ("Sports", "Soccer", "Ligue 1", 10),
    "2026 fifa world cup": ("Sports", "Soccer", "FIFA World Cup", 10),
    "fifa world cup": ("Sports", "Soccer", "FIFA World Cup", 9),
    "world cup": ("Sports", "Soccer", "FIFA World Cup", 5),
    "copa america": ("Sports", "Soccer", "Copa America", 10),
    "euro 2024": ("Sports", "Soccer", "Euro Championship", 10),
    "euro 2028": ("Sports", "Soccer", "Euro Championship", 10),
    "euro 2026": ("Sports", "Soccer", "Euro Championship", 10),
    "afcon": ("Sports", "Soccer", "AFCON", 10),
    "mls": ("Sports", "Soccer", "MLS", 10),
    "major league soccer": ("Sports", "Soccer", "MLS", 10),
    "eredivisie": ("Sports", "Soccer", "Eredivisie", 10),
    "k league 1": ("Sports", "Soccer", "K League 1", 10),
    "k league": ("Sports", "Soccer", "K League 1", 9),
    "club friendlies": ("Sports", "Soccer", "Club Friendlies", 8),
    "danish superliga": ("Sports", "Soccer", "Danish Superliga", 10),
    "superliga": ("Sports", "Soccer", "Danish Superliga", 8),
    "brasileirao": ("Sports", "Soccer", "Brasileirao", 10),
    "liga mx": ("Sports", "Soccer", "Liga MX", 10),
    "scottish premiership": ("Sports", "Soccer", "Scottish Premiership", 10),
    "primeira liga": ("Sports", "Soccer", "Primeira Liga", 10),
    "fa cup": ("Sports", "Soccer", "FA Cup", 10),
    "copa del rey": ("Sports", "Soccer", "Copa del Rey", 10),
    "coppa italia": ("Sports", "Soccer", "Coppa Italia", 10),
    "dfb pokal": ("Sports", "Soccer", "DFB Pokal", 10),

    # ── Basketball Leagues ──
    "nba": ("Sports", "Basketball", "NBA", 10),
    "wnba": ("Sports", "Basketball", "WNBA", 10),
    "ncaab": ("Sports", "Basketball", "NCAA Basketball", 10),
    "ncaa basketball": ("Sports", "Basketball", "NCAA Basketball", 10),
    "college basketball": ("Sports", "Basketball", "NCAA Basketball", 9),
    "euroleague": ("Sports", "Basketball", "EuroLeague", 10),

    # ── Football Leagues ──
    "nfl": ("Sports", "Football", "NFL", 10),
    "ncaaf": ("Sports", "Football", "NCAA Football", 10),
    "ncaa football": ("Sports", "Football", "NCAA Football", 10),
    "college football": ("Sports", "Football", "NCAA Football", 9),
    "cfl": ("Sports", "Football", "CFL", 10),
    "super bowl": ("Sports", "Football", "Super Bowl", 10),

    # ── Baseball Leagues ──
    "mlb": ("Sports", "Baseball", "MLB", 10),
    "npb": ("Sports", "Baseball", "NPB", 10),
    "world series": ("Sports", "Baseball", "World Series", 10),

    # ── Hockey Leagues ──
    "nhl": ("Sports", "Hockey", "NHL", 10),
    "stanley cup": ("Sports", "Hockey", "Stanley Cup", 10),
    "khl": ("Sports", "Hockey", "KHL", 10),

    # ── Tennis Tournaments ──
    "wimbledon": ("Sports", "Tennis", "Wimbledon", 10),
    "us open tennis": ("Sports", "Tennis", "US Open", 10),
    "roland garros": ("Sports", "Tennis", "Roland Garros", 10),
    "french open": ("Sports", "Tennis", "Roland Garros", 10),
    "australian open": ("Sports", "Tennis", "Australian Open", 10),
    "atp": ("Sports", "Tennis", "ATP", 9),
    "wta": ("Sports", "Tennis", "WTA", 9),

    # ── Golf Tournaments ──
    "pga": ("Sports", "Golf", "PGA Tour", 10),
    "pga tour": ("Sports", "Golf", "PGA Tour", 10),
    "masters": ("Sports", "Golf", "The Masters", 10),
    "the masters": ("Sports", "Golf", "The Masters", 10),
    "us open golf": ("Sports", "Golf", "US Open Golf", 10),
    "the open": ("Sports", "Golf", "The Open Championship", 10),
    "liv golf": ("Sports", "Golf", "LIV Golf", 10),

    # ── Combat Sports ──
    "ufc": ("Sports", "MMA", "UFC", 10),
    "bellator": ("Sports", "MMA", "Bellator", 10),
    "pfl": ("Sports", "MMA", "PFL", 10),
    "one championship": ("Sports", "MMA", "ONE Championship", 10),
    "boxing": ("Sports", "Boxing", "Championship Boxing", 8),

    # ── Motorsports ──
    "formula 1": ("Sports", "Motorsport", "Formula 1", 10),
    "f1": ("Sports", "Motorsport", "Formula 1", 10),
    "nascar": ("Sports", "Motorsport", "NASCAR", 10),
    "motogp": ("Sports", "Motorsport", "MotoGP", 10),
    "indycar": ("Sports", "Motorsport", "IndyCar", 10),

    # ── Cricket ──
    "ipl": ("Sports", "Cricket", "IPL", 10),
    "indian premier league": ("Sports", "Cricket", "IPL", 10),
    "t20 world cup": ("Sports", "Cricket", "T20 World Cup", 10),
    "icc world cup": ("Sports", "Cricket", "ICC World Cup", 10),
    "the ashes": ("Sports", "Cricket", "The Ashes", 10),

    # ── Esports titles (series-level; subcategory comes from SUBCATEGORY_MAP) ──
    "china evolution series": ("Esports", "Valorant", "China Evolution Series", 10),
    "the pokal": ("Esports", "Valorant", "THE POKAL", 10),

    # ── Esports Leagues ──
    "league of legends": ("Esports", "League of Legends", "LoL Worlds", 8),
    "lck": ("Esports", "League of Legends", "LCK", 10),
    "lpl": ("Esports", "League of Legends", "LPL", 10),
    "lec": ("Esports", "League of Legends", "LEC", 10),
    "lcs": ("Esports", "League of Legends", "LCS", 10),
    "cs2": ("Esports", "Counter-Strike", "CS2 Majors", 10),
    "counter-strike": ("Esports", "Counter-Strike", "CS2 Majors", 9),
    "counter strike 2": ("Esports", "Counter-Strike", "CS2 Majors", 10),
    "counter strike": ("Esports", "Counter-Strike", "CS2 Majors", 9),
    "dota": ("Esports", "Dota 2", "The International", 9),
    "dota 2": ("Esports", "Dota 2", "The International", 10),
    "valorant": ("Esports", "Valorant", "VCT", 10),
    "vct": ("Esports", "Valorant", "VCT", 10),

    # ── Politics Leagues / Events ──
    "2024 presidential election": ("Politics", "Elections", "US Presidential 2024", 10),
    "presidential election 2024": ("Politics", "Elections", "US Presidential 2024", 10),
    "2024 us presidential election": ("Politics", "Elections", "US Presidential 2024", 10),
    "us presidential election": ("Politics", "Elections", "US Presidential", 8),
    "us election": ("Politics", "Elections", "US Elections", 5),
    "deprec usa election": ("Politics", "Elections", "US Elections", 4),
    "midterms": ("Politics", "Elections", "US Midterms", 10),
    "uk election": ("Politics", "Elections", "UK General Election", 10),
    "french election": ("Politics", "Elections", "French Election", 10),

    # ── Finance / Economics Sub-groups ──
    "fed": ("Finance", "Federal Reserve", "FOMC", 8),
    "fed rates": ("Finance", "Federal Reserve", "FOMC Rates", 10),
    "fomc": ("Finance", "Federal Reserve", "FOMC Rates", 10),
    "cpi release": ("Economics", "Inflation", "CPI", 10),
    "cpi": ("Economics", "Inflation", "CPI", 8),
}

# ── SUBCATEGORY LOOKUP ───────────────────────────────────────────────────
SUBCATEGORY_MAP: dict[str, tuple[str, str, int]] = {
    # tag_lower -> (Category, Subcategory, Specificity Score)
    # Higher score wins
    "soccer": ("Sports", "Soccer", 10),
    "football": ("Sports", "Football", 10),
    "basketball": ("Sports", "Basketball", 10),
    "baseball": ("Sports", "Baseball", 10),
    "hockey": ("Sports", "Hockey", 10),
    "tennis": ("Sports", "Tennis", 10),
    "golf": ("Sports", "Golf", 10),
    "mma": ("Sports", "MMA", 10),
    "cricket": ("Sports", "Cricket", 10),
    "rugby": ("Sports", "Rugby", 10),
    "motorsport": ("Sports", "Motorsport", 10),
    "racing": ("Sports", "Motorsport", 9),

    # Politics
    "elections": ("Politics", "Elections", 10),
    "election": ("Politics", "Elections", 9),
    "president": ("Politics", "Presidency", 9),
    "potus": ("Politics", "Presidency", 8),
    "potusbanner": ("Politics", "Presidency", 7),
    "congress": ("Politics", "Congress", 10),
    "senate": ("Politics", "Senate", 10),
    "supreme court": ("Politics", "Supreme Court", 10),
    "geopolitics": ("Politics", "Geopolitics", 10),
    "foreign policy": ("Politics", "Foreign Policy", 10),
    "iran": ("Politics", "Geopolitics", 8),
    "middle east": ("Politics", "Geopolitics", 8),
    "ukraine": ("Politics", "Geopolitics", 8),
    "russia": ("Politics", "Geopolitics", 8),
    "china": ("Politics", "Geopolitics", 8),
    "israel": ("Politics", "Geopolitics", 8),
    "war": ("Politics", "Geopolitics", 7),

    # Crypto
    "bitcoin": ("Crypto", "Bitcoin", 10),
    "btc": ("Crypto", "Bitcoin", 10),
    "ethereum": ("Crypto", "Ethereum", 10),
    "eth": ("Crypto", "Ethereum", 10),
    "solana": ("Crypto", "Solana", 10),
    "sol": ("Crypto", "Solana", 10),
    "defi": ("Crypto", "DeFi", 10),
    "nft": ("Crypto", "NFT", 10),
    "memecoin": ("Crypto", "Memecoins", 10),
    "meme coins": ("Crypto", "Memecoins", 10),
    "airdrop": ("Crypto", "Airdrops", 10),
    "token launch": ("Crypto", "Token Launches", 10),
    "crypto": ("Crypto", "Cryptocurrency", 2),

    # Culture
    "movies": ("Culture", "Movies", 10),
    "movie": ("Culture", "Movies", 10),
    "film": ("Culture", "Movies", 10),
    "cinema": ("Culture", "Movies", 10),
    "music": ("Culture", "Music", 10),
    "tv": ("Culture", "TV Shows", 10),
    "tv shows": ("Culture", "TV Shows", 10),
    "celebrity": ("Culture", "Celebrities", 10),
    "celebrity news": ("Culture", "Celebrities", 10),
    "oscars": ("Culture", "Awards", 10),
    "grammys": ("Culture", "Awards", 10),
    "awards": ("Culture", "Awards", 9),
    "pop culture": ("Culture", "Pop Culture", 5),
    "culture": ("Culture", "Pop Culture", 2),

    # Economics & Finance
    "inflation": ("Economics", "Inflation", 10),
    "gdp": ("Economics", "GDP", 10),
    "tariffs": ("Economics", "Trade & Tariffs", 10),
    "economy": ("Economics", "Economy", 5),
    "economic policy": ("Economics", "Economy", 6),
    "stocks": ("Finance", "Markets", 10),
    "interest rates": ("Finance", "Interest Rates", 10),
    "ipo": ("Finance", "IPOs", 10),
    "finance": ("Finance", "Markets", 2),

    # Tech
    "ai": ("Tech", "Artificial Intelligence", 10),
    "artificial intelligence": ("Tech", "Artificial Intelligence", 10),
    "openai": ("Tech", "AI Labs", 10),
    "space": ("Tech", "Space", 10),
    "spacex": ("Tech", "Space", 10),
    "tech": ("Tech", "Technology", 2),

    # Weather
    "climate": ("Weather", "Climate", 10),
    "hurricane": ("Weather", "Hurricanes", 10),
    "weather": ("Weather", "Weather", 2),

    # Esports
    "gaming": ("Esports", "Gaming", 8),
    "esports": ("Esports", "Esports", 2),
    "honor of kings": ("Esports", "Honor of Kings", 10),
    "rainbow six siege": ("Esports", "Rainbow Six Siege", 10),
    "rainbow six": ("Esports", "Rainbow Six Siege", 9),
    "mobile legends: bang bang": ("Esports", "Mobile Legends", 10),
    "mobile legends": ("Esports", "Mobile Legends", 10),
    "counter strike 2": ("Esports", "Counter-Strike", 10),
    "counter strike": ("Esports", "Counter-Strike", 10),
    "overwatch": ("Esports", "Overwatch", 10),
    "rocket league": ("Esports", "Rocket League", 10),
    "call of duty": ("Esports", "Call of Duty", 10),
    "starcraft ii": ("Esports", "StarCraft II", 10),
    "starcraft 2": ("Esports", "StarCraft II", 10),
    "sc2": ("Esports", "StarCraft II", 9),
    "starcraft: brood war": ("Esports", "StarCraft: Brood War", 10),
    "brood war": ("Esports", "StarCraft: Brood War", 10),
}

# ── CATEGORY FALLBACK MAP ────────────────────────────────────────────────
CATEGORY_MAP: dict[str, str] = {
    "sports": "Sports",
    "politics": "Politics",
    "crypto": "Crypto",
    "culture": "Culture",
    "economics": "Economics",
    "economy": "Economics",
    "finance": "Finance",
    "tech": "Tech",
    "weather": "Weather",
    "esports": "Esports",
    "mentions": "Mentions",
}


def resolve_gamma_tags(tags: list[str]) -> tuple[str, str, str]:
    """Resolve a list of Gamma API tag labels into (category, subcategory, league).

    Returns:
        tuple[str, str, str]: (Category, Subcategory, League)
        e.g. ("Sports", "Soccer", "UEFA Champions League")
             ("Sports", "Basketball", "NBA")
             ("Politics", "Elections", "US Presidential 2024")
             ("Crypto", "Bitcoin", "")
    """
    if not tags:
        return ("Other", "", "")

    cat_candidate: Optional[str] = None
    subcat_candidate: Optional[str] = None
    league_candidate: Optional[str] = None
    best_league_score = -1
    best_subcat_score = -1

    # Step 1: Look for highest specificity League matches
    for tag in tags:
        clean = tag.strip().lower()
        if clean in LEAGUE_MAP:
            cat, subcat, league, score = LEAGUE_MAP[clean]
            if score > best_league_score:
                best_league_score = score
                cat_candidate = cat
                subcat_candidate = subcat
                league_candidate = league

    # Step 2: If no subcategory from league, look for subcategory match
    if not subcat_candidate:
        for tag in tags:
            clean = tag.strip().lower()
            if clean in SUBCATEGORY_MAP:
                cat, subcat, score = SUBCATEGORY_MAP[clean]
                if score > best_subcat_score:
                    best_subcat_score = score
                    cat_candidate = cat
                    subcat_candidate = subcat

    # Step 3: If no category, look for top-level category match
    if not cat_candidate:
        for tag in tags:
            clean = tag.strip().lower()
            if clean in CATEGORY_MAP:
                cat_candidate = CATEGORY_MAP[clean]
                break

    category = cat_candidate or "Other"
    subcategory = subcat_candidate or ""
    league = league_candidate or ""

    return (category, subcategory, league)


# Categories where a Gamma event `series` is a trustworthy league-level label.
# Sports/Esports series are stable competitions ("JCL T20", "LCK"); other
# categories use per-question series ("Gold Card") that would pollute filters.
SERIES_LEAGUE_CATEGORIES = frozenset({"SPORTS", "ESPORTS"})


def _normalized(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def extract_series_league(event: dict, subcategory: str = "") -> str:
    """Derive a league label from a Gamma API event's `series` payload.

    Polymarket groups events into series (e.g. "JCL T20", "Indian Premier
    League") that carry finer league detail than tags. The series title is
    first passed through :func:`resolve_gamma_tags` so known competitions
    collapse to their canonical league (e.g. "Indian Premier League" ->
    "IPL"). A series that only restates a known genre (e.g. "Mobile Legends:
    Bang Bang" when "Mobile Legends" is already the subcategory) yields "",
    as does one duplicating the subcategory; anything else keeps its raw
    title (max 100 chars for the ``markets_v2.league`` column).
    """
    title = _first_series_title(event)
    if not title:
        return ""
    _, series_sub, canonical = resolve_gamma_tags([title])
    if canonical:
        league = canonical
    elif series_sub:
        return ""
    else:
        league = title
    if subcategory and _normalized(league) == _normalized(subcategory):
        return ""
    return league[:100]


def extract_series_subcategory(event: dict) -> str:
    """Derive a subcategory from a Gamma event series for games-as-genres.

    Used only when tags left the subcategory blank: for Esports the series
    ("Honor of Kings", ...) names the game, which is the subcategory level
    in our taxonomy. Canonicalized through the tag maps first.
    """
    title = _first_series_title(event)
    if not title:
        return ""
    cat, subcat, _ = resolve_gamma_tags([title])
    if subcat:
        return subcat
    return title[:100]


def _first_series_title(event: dict) -> str:
    if not isinstance(event, dict):
        return ""
    series = event.get("series")
    if not isinstance(series, list):
        return ""
    for entry in series:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or "").strip()
        if title:
            return title
    return ""
