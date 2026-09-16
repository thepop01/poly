"""Map Polymarket Gamma API event tags & market titles to category + subcategory + league."""

import re

def _word_match(keyword: str, text: str) -> bool:
    """Match keyword as a whole word (or at start/end of text) to avoid
    false positives like 'ai' inside 'geopolitics'."""
    if len(keyword) <= 3:
        return bool(re.search(r'(?<![a-z])' + re.escape(keyword) + r'(?![a-z])', text))
    return keyword in text


# ── Sports Team & League Matchers ─────────────────────────────────────────

MLB_TEAMS = [
    'cardinals', 'cubs', 'red sox', 'yankees', 'dodgers', 'braves', 'blue jays', 'mets',
    'phillies', 'astros', 'padres', 'angels', 'marlins', 'white sox', 'tigers',
    'twins', 'brewers', 'athletics', 'rays', 'mariners', 'royals', 'diamondbacks', 'nationals',
    'pirates', 'reds', 'guardians', 'orioles', 'rangers', 'rockies', 'san francisco giants', 'sf giants'
]
MLB_KEYWORDS = [
    'mlb', 'baseball', 'world series', 'home run', 'home runs', 'strikeout', 'strikeouts',
    'pitcher', 'innings', 'grand slam', 'rbi', 'shohei ohtani', 'aaron judge'
]

NFL_TEAMS = [
    'vikings', 'browns', 'bears', 'chiefs', 'eagles', 'cowboys', '49ers', 'niners', 'bills',
    'packers', 'lions', 'ravens', 'dolphins', 'jets', 'patriots', 'steelers', 'texans',
    'jaguars', 'colts', 'titans', 'broncos', 'raiders', 'chargers', 'seahawks', 'rams',
    'saints', 'buccaneers', 'bucs', 'falcons', 'panthers', 'commanders', 'ny giants', 'new york giants'
]
NFL_MATCHUP_REGEX = r'\b(cle|chi|car|buf|det|cin|gb|pit|ind|ne|ari|lv|lac|hou|kc|la|phi|dal|sf|bal|mia|nyj|ten|jax|den|sea|was|atl|no|tb)\s+vs\.?\s+(cle|chi|car|buf|det|cin|gb|pit|ind|ne|ari|lv|lac|hou|kc|la|phi|dal|sf|bal|mia|nyj|ten|jax|den|sea|was|atl|no|tb)\b'
NFL_KEYWORDS = [
    'nfl', 'touchdown', 'touchdowns', 'passing yards', 'rushing yards', 'super bowl',
    'interception', 'quarterback', 'afc', 'nfc'
]

WNBA_TEAMS = [
    'fever', 'sky', 'aces', 'liberty', 'lynx', 'mercury', 'storm', 'sun', 'sparks',
    'wings', 'dream', 'mystics', 'valkyries', 'indiana fever', 'chicago sky', 'las vegas aces',
    'new york liberty', 'minnesota lynx', 'phoenix mercury', 'seattle storm', 'connecticut sun',
    'los angeles sparks', 'dallas wings', 'atlanta dream', 'washington mystics', 'golden state valkyries'
]

NBA_TEAMS = [
    'lakers', 'celtics', 'warriors', 'bulls', 'knicks', 'heat', 'nuggets', 'bucks', 'suns',
    '76ers', 'sixers', 'mavericks', 'mavs', 'clippers', 'thunder', 'timberwolves', 'wolves',
    'pacers', 'cavaliers', 'cavs', 'magic', 'sacramento kings', 'pelicans', 'rockets', 'hawks',
    'raptors', 'spurs', 'grizzlies', 'jazz', 'trail blazers', 'blazers', 'hornets', 'pistons', 'wizards'
]
BASKETBALL_KEYWORDS = [
    'nba', 'wnba', 'ncaab', 'triple-double', 'double-double', 'rebounds', 'assists',
    'points scored', 'three-pointers', 'march madness', 'college basketball'
]

NHL_TEAMS = [
    'bruins', 'maple leafs', 'canadiens', 'oilers', 'florida panthers', 'golden knights',
    'avalanche', 'hurricanes', 'canes', 'lightning', 'bolts', 'devils', 'islanders', 'isles',
    'penguins', 'pens', 'capitals', 'caps', 'red wings', 'flyers', 'canucks', 'flames',
    'predators', 'preds', 'blues', 'kraken', 'wild', 'sabres', 'senators', 'coyotes', 'ducks',
    'sharks', 'blackhawks'
]
HOCKEY_KEYWORDS = [
    'nhl', 'hockey', 'stanley cup', 'puck', 'power play', 'hat trick', 'goalie'
]

MMA_KEYWORDS = [
    'ufc', 'mma', 'bellator', 'pfl', 'one championship', 'welterweight', 'lightweight',
    'middleweight', 'heavyweight', 'featherweight', 'bantamweight', 'flyweight', 'strawweight',
    'rounds', 'ko or tko', 'tko', 'submission', 'fight night', 'main card', 'prelims',
    'early prelims'
]

SOCCER_COUNTRIES = [
    'argentina', 'france', 'spain', 'england', 'brazil', 'germany', 'belgium',
    'netherlands', 'portugal', 'italy', 'croatia', 'morocco', 'uruguay', 'colombia',
    'mexico', 'united states', 'switzerland', 'senegal', 'japan', 'korea republic',
    'south korea', 'norway', 'algeria', 'austria', 'dr congo', 'ghana', 'panama',
    'tunisia', 'ir iran', 'iran', 'bosnia and herzegovina', 'sweden', 'denmark',
    'poland', 'serbia', 'nigeria', 'cameroon', 'egypt', 'ivory coast', 'chile', 'peru',
    'ecuador', 'venezuela', 'paraguay', 'wales', 'scotland', 'australia', 'saudi arabia',
    'qatar', 'canada', 'costa rica', 'honduras', 'jamaica', 'new zealand', 'turkey', 'greece',
    'czech republic', 'hungary', 'romania', 'ukraine', 'slovakia', 'slovenia'
]

NCAA_FOOTBALL_TEAMS = [
    'cornhuskers', 'hawkeyes', 'buckeyes', 'wolverines', 'crimson tide', 'bulldogs',
    'longhorns', 'sooners', 'tigers', 'seminoles', 'gators', 'hurricanes', 'volunteers',
    'fighting irish', 'trojans', 'ducks', 'badgers', 'nittany lions', 'spartans',
    'tar heels', 'blue devils', 'wildcats', 'jayhawks', 'cyclones', 'boilermakers',
    'hoosiers', 'illini', 'gophers', 'huskies', 'cougars', 'beavers', 'utes',
    'buffaloes', 'sun devils', 'cardinal', 'bearcats', 'knights', 'mountaineers'
]

SOCCER_LEAGUES = [
    ('UEFA Champions League', ['champions league', 'ucl']),
    ('Europa League', ['europa league', 'uel']),
    ('Premier League', ['premier league', 'epl']),
    ('La Liga', ['la liga', 'laliga']),
    ('Serie A', ['serie a']),
    ('Bundesliga', ['bundesliga']),
    ('Ligue 1', ['ligue 1']),
    ('MLS', ['major league soccer', r'\bmls\b']),
    ('FIFA World Cup', ['fifa world cup', 'world cup', '2026 world cup']),
    ('Copa America', ['copa america']),
    ('Euro Championship', ['euro 2024', 'euro 2028', 'euro 2026']),
    ('Eredivisie', ['eredivisie']),
    ('Primeira Liga', ['primeira liga']),
    ('Brasileirao', ['brasileirao']),
    ('Liga MX', ['liga mx']),
    ('FA Cup', ['fa cup']),
    ('Copa del Rey', ['copa del rey']),
    ('Coppa Italia', ['coppa italia']),
    ('DFB Pokal', ['dfb pokal']),
]


ESPORTS_LEAGUES = [
    ('Esports', 'League of Legends', 'LCK', ['lck']),
    ('Esports', 'League of Legends', 'LPL', ['lpl']),
    ('Esports', 'League of Legends', 'LEC', ['lec']),
    ('Esports', 'League of Legends', 'LCS', ['lcs']),
    ('Esports', 'League of Legends', 'LoL Worlds', ['lol:', 'league of legends', 't1', 'gen.g', 'dplus', 'invictus']),
    ('Esports', 'Counter-Strike', 'CS2 Majors', ['cs2', 'counter-strike', 'cs:go', 'ninjas in pyjamas']),
    ('Esports', 'Dota 2', 'The International', ['dota', 'dota 2']),
    ('Esports', 'Valorant', 'VCT', ['valorant', 'vct']),
    # Game-level fallback (no known league): subcategory only, league stays "".
    ('Esports', 'StarCraft II', '', ['starcraft ii', 'starcraft 2']),
    ('Esports', 'StarCraft: Brood War', '', ['brood war']),
    ('Esports', 'Call of Duty', '', ['call of duty']),
    ('Esports', 'Honor of Kings', '', ['honor of kings']),
    ('Esports', 'Rainbow Six Siege', '', ['rainbow six']),
    ('Esports', 'Mobile Legends', '', ['mobile legends']),
    ('Esports', 'Counter-Strike', '', ['counter strike']),
    ('Esports', 'Rocket League', '', ['rocket league']),
    ('Esports', 'Overwatch', '', ['overwatch']),
]


import functools

SPORTS_EVENT_PREFIXES: dict[str, tuple[str, str]] = {
    "arg": ("Soccer", "Argentine Primera"),
    "atp": ("Tennis", "ATP"),
    "bra": ("Soccer", "Brasileirao"),
    "bun": ("Soccer", "Bundesliga"),
    "cbb": ("Basketball", "NCAA Basketball"),
    "fif": ("Soccer", "International Soccer"),
    "fifwc": ("Soccer", "FIFA World Cup"),
    "fl1": ("Soccer", "Ligue 1"),
    "lal": ("Soccer", "La Liga"),
    "lib": ("Soccer", "Copa Libertadores"),
    "mex": ("Soccer", "Liga MX"),
    "mls": ("Soccer", "MLS"),
    "nba": ("Basketball", "NBA"),
    "nhl": ("Hockey", "NHL"),
    "sea": ("Soccer", "Serie A"),
    "sud": ("Soccer", "Copa Sudamericana"),
    "ucl": ("Soccer", "UEFA Champions League"),
    "uel": ("Soccer", "Europa League"),
    "usc": ("Soccer", "UEFA Super Cup"),
    "wnba": ("Basketball", "WNBA"),
    "wta": ("Tennis", "WTA"),
}


def classify_market(title: str, event_slug: str = "") -> tuple[str, str, str]:
    """Classify a market, preferring a known stable event-family prefix."""
    prefix = (event_slug or "").lower().split("-", 1)[0]
    if prefix in SPORTS_EVENT_PREFIXES:
        subcategory, league = SPORTS_EVENT_PREFIXES[prefix]
        return ("SPORTS", subcategory, league)
    return classify_market_title(title)

@functools.lru_cache(maxsize=100000)
def classify_market_title(title: str) -> tuple[str, str, str]:
    """Extract (Category, Subcategory, League) from market title with high precision."""
    t = (title or "").lower().strip()
    if not t or t == "parlay bet":
        return ("SPORTS", "", "")

    # 1. Esports
    for cat, sub, lg, kws in ESPORTS_LEAGUES:
        if any(kw in t for kw in kws):
            return (cat.upper(), sub, lg)

    # 2. MMA / Combat
    if "ufc" in t:
        return ("SPORTS", "MMA", "UFC")
    if any(kw in t for kw in ["bellator", "pfl", "one championship"]):
        lg = "Bellator" if "bellator" in t else ("PFL" if "pfl" in t else "ONE Championship")
        return ("SPORTS", "MMA", lg)
    if any(kw in t for kw in ["welterweight", "lightweight", "middleweight", "heavyweight", "strawweight", "flyweight", "bantamweight", "featherweight"]):
        return ("SPORTS", "MMA", "UFC")
    if re.search(r'\bo/u\s+\d+(\.\d+)?\s+rounds\b', t) or "ko or tko" in t or "submission" in t:
        return ("SPORTS", "MMA", "MMA")
    if "boxing" in t:
        return ("SPORTS", "Boxing", "Boxing")

    # 2b. Cricket leagues (kept narrow: generic "t20" alone is ambiguous)
    if "indian premier league" in t or _word_match("ipl", t):
        return ("SPORTS", "Cricket", "IPL")
    if "t20 world cup" in t:
        return ("SPORTS", "Cricket", "T20 World Cup")
    if "the ashes" in t:
        return ("SPORTS", "Cricket", "The Ashes")

    # 3. WNBA
    for team in WNBA_TEAMS:
        if re.search(r'\b' + re.escape(team) + r'\b', t):
            return ("SPORTS", "Basketball", "WNBA")

    # 4. Baseball / MLB
    mlb_hits = sum(1 for kw in MLB_KEYWORDS if _word_match(kw, t))
    mlb_hits += sum(1 for team in MLB_TEAMS if _word_match(team, t))

    # 5. Football / NFL & NCAA
    nfl_hits = sum(1 for kw in NFL_KEYWORDS if _word_match(kw, t))
    nfl_hits += sum(1 for team in NFL_TEAMS if _word_match(team, t))
    if re.search(NFL_MATCHUP_REGEX, t):
        nfl_hits += 2

    ncaa_fb_hits = sum(1 for team in NCAA_FOOTBALL_TEAMS if _word_match(team, t))
    if "cornhuskers" in t or "hawkeyes" in t or "buckeyes" in t or "wolverines" in t:
        ncaa_fb_hits += 2

    # 6. Basketball / NBA
    nba_hits = sum(1 for kw in BASKETBALL_KEYWORDS if _word_match(kw, t))
    nba_hits += sum(1 for team in NBA_TEAMS if _word_match(team, t))

    # 7. Hockey / NHL
    nhl_hits = sum(1 for kw in HOCKEY_KEYWORDS if _word_match(kw, t))
    nhl_hits += sum(1 for team in NHL_TEAMS if _word_match(team, t))

    # 8. Soccer (Clubs & International World Cup)
    soccer_hits = 0
    soccer_league = ""
    for lg_name, kws in SOCCER_LEAGUES:
        for kw in kws:
            if _word_match(kw, t):
                soccer_hits += 2
                if not soccer_league:
                    soccer_league = lg_name
    if any(club in t for club in ["fc", "cf", "real madrid", "barcelona", "bayern", "arsenal", "chelsea", "liverpool", "manchester", "juventus", "inter milan", "ac milan", "dortmund", "psg", "atletico", "tottenham", "celtic", "rangers"]):
        soccer_hits += 2

    # Match international country soccer games (e.g. "Spain vs. Argentina", "Will France win on 2026-06-22?", "Will Norway vs. Senegal end in a draw?")
    country_matches = [c for c in SOCCER_COUNTRIES if _word_match(c, t)]
    if len(country_matches) >= 2 or (" vs. " in t and len(country_matches) >= 1) or ("end in a draw" in t and len(country_matches) >= 1) or ("team to advance" in t and len(country_matches) >= 1):
        soccer_hits += 3
        if not soccer_league:
            soccer_league = "FIFA World Cup" if ("2026" in t or "world cup" in t or len(country_matches) >= 1) else "International Soccer"

    if "end in a draw" in t or "clean sheet" in t or "both teams to score" in t:
        soccer_hits += 2
        if not soccer_league:
            soccer_league = "Soccer"

    if ncaa_fb_hits > 0 and ncaa_fb_hits >= nfl_hits:
        return ("SPORTS", "Football", "NCAA Football")

    # Compare sports scores
    scores = {
        ("SPORTS", "Baseball", "MLB"): mlb_hits,
        ("SPORTS", "Football", "NFL"): nfl_hits,
        ("SPORTS", "Basketball", "NBA"): nba_hits,
        ("SPORTS", "Hockey", "NHL"): nhl_hits,
        ("SPORTS", "Soccer", soccer_league or "Soccer"): soccer_hits,
    }

    best_tuple = max(scores, key=scores.get)
    if scores[best_tuple] > 0:
        return best_tuple

    # 9. General tags classification fallback
    cat, sub = classify_tags([title])
    flattened_sub = flatten_subcategory(cat, sub) if sub else ""
    if flattened_sub.upper() == (cat or "").upper():
        flattened_sub = ""
    return (cat.upper() if cat else "OTHER", flattened_sub, "")


# ── Category rules (order matters: first match wins) ──────────────────────
_CATEGORY_RULES: list[tuple[str, list[str], list[str]]] = [
    # (category, [tag substrings], [subcategory tag substrings])
    (
        "Esports",
        ["esport", "e-sport", "league of legends", "dota", "cs2", "counter-strike",
         "counter strike", "valorant", "fortnite", "overwatch", "gaming tournament",
         "honor of kings", "rainbow six", "mobile legends", "call of duty",
         "starcraft", "brood war", "rocket league"],
        ["league of legends", "dota", "cs2", "counter-strike", "counter strike",
         "valorant", "fortnite", "overwatch", "honor of kings", "rainbow six",
         "mobile legends", "call of duty", "starcraft", "brood war",
         "rocket league"],
    ),
    (
        "Sports",
        ["sports", "soccer", "football", "nfl", "nba", "mlb", "nhl", "cricket",
         "tennis", "wimbledon", "wta", "atp", "roland garros", "us open",
         "australian open", "davis cup", "fed cup",
         "mma", "ufc", "boxing", "baseball", "hockey", "basketball", "rugby",
         "fifa", "world cup", "olympics", "formula 1", "f1", "golf",
         "pga", "masters", "champions league", "premier league", "la liga",
         "bundesliga", "serie a", "ligue 1", "cric", "ipl",
         "ncaa", "ncaab", "ncaaf", "cwbb", "college basketball", "college football",
         "o/u", "over/under", "moneyline", "spread", "btts", "both teams to score",
         "team to advance", "goalscorer",
         "fc", "cf", "sc", "ac", "united", "city", "real madrid", "barcelona",
         "paris saint-germain", "psg", "bayern", "arsenal", "chelsea", "liverpool",
         "manchester", "juventus", "inter milan", "ac milan", "dortmund", "atletico",
         "tottenham", "inter miami", "al hilal", "al nassr", "sporting", "benfica",
         "porto", "ajax", "celtic", "rangers", "copa america", "afcon", "asian cup",
         "super bowl", "stanley cup", "world series", "euro 2024", "euro 2028", "euro 2026",
         "clean sheet", "total goals", "total points", "match winner", "game winner",
         "will win on", "win on"],
        ["soccer", "football", "nfl", "nba", "mlb", "nhl", "cricket", "tennis",
         "wimbledon", "wta", "atp", "roland garros", "us open",
         "australian open", "davis cup",
         "mma", "ufc", "boxing", "baseball", "hockey", "basketball", "rugby",
         "fifa", "world cup", "olympics", "formula 1", "f1", "golf",
         "pga", "masters", "champions league", "premier league", "la liga",
         "bundesliga", "serie a", "ligue 1", "ipl"],
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


_NON_SPORTS_KEYWORDS = [
    "trump", "biden", "harris", "election", "president", "congress", "senate",
    "democrat", "republican", "fed", "rate", "inflation", "cpi", "gdp",
    "bitcoin", "ethereum", "solana", "crypto", "token", "ai", "openai", "gpt",
    "musk", "bezos", "movie", "oscar", "grammy", "gaza", "israel", "russia", "ukraine"
]


def _is_sports_matchup_title(title: str) -> bool:
    """Return True if title contains a sports matchup pattern like 'Team A vs Team B'."""
    text = title.lower()
    if any(kw in text for kw in _NON_SPORTS_KEYWORDS):
        return False
    if re.search(r'\bvs\.?\b', text) or re.search(r'\b(o/u|over/under|spread|moneyline|btts|\(w\)|\(m\)|\(u\d+\))\b', text):
        return True
    if re.search(r'\bwill\b.+\b(win|draw|tie|score|advance|qualify|beat|prevail)\b.+\b(on|at|against|in)\b', text):
        return True
    if re.search(r'\b(win on|draw on|tie on)\s+\d{4}-\d{2}-\d{2}\b', text) or re.search(r'\b(win on|draw on|tie on)\s+[a-z]+ \d{1,2}\b', text):
        return True
    if re.search(r'\b(fc|afc|cf|sc|ac|psg)\b', text):
        return True
    return False


def classify_tags(tag_labels: list[str]) -> tuple[str, str]:
    """Return (category, subcategory) derived from a list of Gamma API tag labels."""
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
        combined_text = " ".join(lower_tags)
        if _is_sports_matchup_title(combined_text):
            return ("Sports", "")
        return ("Other", "")

    best_category = max(category_scores, key=lambda k: category_scores[k])
    subs = category_sub_matches.get(best_category, [])
    subcategory = ""
    if subs:
        subcategory = subs[-1].title()
    if subcategory.upper() == best_category.upper():
        subcategory = ""
    return (best_category, subcategory)


# ── Flatten mappings ──────────────────────────────────────────────────────

SPORTS_FLATTEN: dict[str, str] = {
    "nfl": "Football", "cfl": "Football", "cfb": "Football",
    "ncaaf": "Football", "ncaa football": "Football", "football": "Football",
    "nba": "Basketball", "wnba": "Basketball", "ncaab": "Basketball",
    "basketball": "Basketball",
    "mlb": "Baseball", "baseball": "Baseball",
    "nhl": "Hockey", "hockey": "Hockey",
    "soccer": "Soccer", "epl": "Soccer", "ucl": "Soccer",
    "laliga": "Soccer", "la liga": "Soccer", "bundesliga": "Soccer",
    "serie a": "Soccer", "ligue 1": "Soccer", "eredivisie": "Soccer",
    "mls": "Soccer", "copa america": "Soccer", "world cup": "Soccer",
    "europa league": "Soccer", "champions league": "Soccer",
    "fifa": "Soccer", "premier league": "Soccer",
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
    """Map detailed subcategory to top-level type for filter dropdowns."""
    if not subcategory:
        return ""
    key = subcategory.lower().strip()
    if key == (category or "").lower().strip() or key in ("sports", "crypto", "general", "other"):
        return ""
    if category.upper() == "SPORTS":
        return SPORTS_FLATTEN.get(key, subcategory)
    elif category.upper() == "ESPORTS":
        return ESPORTS_FLATTEN.get(key, subcategory)
    return subcategory
