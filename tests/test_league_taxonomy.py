"""League taxonomy: series extraction, cricket title rules, tag mappings.

All tests are offline (no Gamma API calls).
"""

from src.utils.category_classifier import classify_market_title
from src.utils.gamma_tag_resolver import (
    SERIES_LEAGUE_CATEGORIES,
    extract_series_league,
    extract_series_subcategory,
    resolve_gamma_tags,
)


def test_indian_premier_league_tag_maps_to_canonical_ipl():
    assert resolve_gamma_tags(["Indian Premier League"]) == ("Sports", "Cricket", "IPL")


def test_series_title_collapses_to_canonical_league():
    event = {"series": [{"title": "Indian Premier League", "slug": "indian-premier-league"}]}
    assert extract_series_league(event) == "IPL"


def test_unknown_series_keeps_raw_title():
    assert extract_series_league({"series": [{"title": "JCL T20"}]}) == "JCL T20"


def test_series_extraction_handles_missing_shapes():
    assert extract_series_league({}) == ""
    assert extract_series_league({"series": []}) == ""
    assert extract_series_league({"series": [{"slug": "no-title"}]}) == ""
    assert extract_series_league({"series": "not-a-list"}) == ""
    assert extract_series_league(None) == ""


def test_cricket_title_rules():
    assert classify_market_title(
        "Indian Premier League: Kolkata Knight Riders vs Delhi Capitals"
    ) == ("SPORTS", "Cricket", "IPL")
    assert classify_market_title("Will England win the T20 World Cup?") == (
        "SPORTS", "Cricket", "T20 World Cup")
    assert classify_market_title("The Ashes: Australia vs England") == (
        "SPORTS", "Cricket", "The Ashes")


def test_unrelated_titles_unaffected_by_cricket_rules():
    assert classify_market_title("Will Real Madrid win the Champions League?")[2] == \
        "UEFA Champions League"
    assert classify_market_title("NBA Finals: Celtics vs Mavericks")[2] == "NBA"


def test_esports_tags_resolve_new_games():
    assert resolve_gamma_tags(["Esports", "Honor of Kings"]) == (
        "Esports", "Honor of Kings", "")
    assert resolve_gamma_tags(["Esports", "Rainbow Six Siege"]) == (
        "Esports", "Rainbow Six Siege", "")
    assert resolve_gamma_tags(["Esports", "Mobile Legends: Bang Bang"]) == (
        "Esports", "Mobile Legends", "")
    assert resolve_gamma_tags(["Esports", "counter strike 2"]) == (
        "Esports", "Counter-Strike", "CS2 Majors")


def test_series_subcategory_names_the_game():
    assert extract_series_subcategory({"series": [{"title": "Honor of Kings"}]}) == \
        "Honor of Kings"
    assert extract_series_subcategory({"series": [{"title": "Counter Strike"}]}) == \
        "Counter-Strike"
    assert extract_series_subcategory({}) == ""


def test_series_league_skips_subcategory_duplicates():
    event = {"series": [{"title": "Honor of Kings"}]}
    assert extract_series_league(event, subcategory="Honor of Kings") == ""
    # A series that only restates a known genre yields no league; the genre
    # itself is picked up as subcategory by extract_series_subcategory.
    assert extract_series_league(event, subcategory="") == ""
    assert extract_series_subcategory(event) == "Honor of Kings"


def test_series_fallback_categories_cover_sports_and_esports():
    assert SERIES_LEAGUE_CATEGORIES >= {"SPORTS", "ESPORTS"}


def test_new_esports_games_resolve():
    assert resolve_gamma_tags(["Esports", "StarCraft II"]) == (
        "Esports", "StarCraft II", "")
    assert resolve_gamma_tags(["Esports", "Call of Duty"]) == (
        "Esports", "Call of Duty", "")
    assert resolve_gamma_tags(["China Evolution Series"]) == (
        "Esports", "Valorant", "China Evolution Series")
    assert resolve_gamma_tags(["THE POKAL"]) == (
        "Esports", "Valorant", "THE POKAL")


def test_new_esports_title_rules():
    assert classify_market_title("StarCraft II: Serral vs Maru") == (
        "ESPORTS", "StarCraft II", "")
    assert classify_market_title("Call of Duty League Major") == (
        "ESPORTS", "Call of Duty", "")
    assert classify_market_title("Honor of Kings: eArena vs SOLYX") == (
        "ESPORTS", "Honor of Kings", "")


def test_refined_series_rules():
    # Genre restatements yield no league; real competitions keep raw titles.
    assert extract_series_league({"series": [{"title": "Mobile Legends: Bang Bang"}]},
                                 subcategory="Mobile Legends") == ""
    assert extract_series_league({"series": [{"title": "JCL T20"}]},
                                 subcategory="Cricket") == "JCL T20"
    assert extract_series_league({"series": [{"title": "Counter Strike"}]},
                                 subcategory="Counter-Strike") == "CS2 Majors"


def test_resolve_market_object_prefers_tags_then_series():
    import sys
    sys.path.insert(0, "src")
    from src.scripts.backfill_missing_markets import resolve_market_object

    market = {
        "question": "JCL T20: Team A vs Team B",
        "events": [{
            "slug": "jcl-t20-a-b",
            "tags": [{"label": "Sports"}, {"label": "Cricket"}],
            "series": [{"title": "JCL T20", "slug": "jcl-t20"}],
        }],
    }
    title, slug, cat, sub, league = resolve_market_object(market)
    assert (cat, sub, league) == ("SPORTS", "Cricket", "JCL T20")
    assert slug == "jcl-t20-a-b"


def test_resolve_market_object_handles_bare_payloads():
    import sys
    sys.path.insert(0, "src")
    from src.scripts.backfill_missing_markets import resolve_market_object

    assert resolve_market_object({}) == ("", "", "OTHER", "", "")
    title, _, cat, _, _ = resolve_market_object({"question": "Will Bitcoin hit $100k?"})
    assert title.startswith("Will Bitcoin") and cat == "CRYPTO"
