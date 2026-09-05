from src.utils.category_classifier import classify_market


def test_known_sports_event_slugs_supply_subcategory_and_league():
    assert classify_market("Will Ghana win on 2026-06-17?", "fifwc-gha-pan-2026-06-17") == (
        "SPORTS", "Soccer", "FIFA World Cup"
    )
    assert classify_market("Spread: Nets (-3.5)", "nba-was-bkn-2026-04-05") == (
        "SPORTS", "Basketball", "NBA"
    )
    assert classify_market("Player A vs Player B", "atp-player-a-player-b") == (
        "SPORTS", "Tennis", "ATP"
    )


def test_non_sports_slug_still_uses_title_classifier():
    category, _subcategory, _league = classify_market(
        "Will Gina Raimondo win the 2028 Democratic presidential nomination?",
        "democratic-presidential-nominee-2028",
    )
    assert category == "POLITICS"
