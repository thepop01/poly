from datetime import datetime, timezone

import pytest

from src.pnl.ledger import (
    PRICE_BUCKETS,
    bucket_for_price,
    closed_ledger_contribution,
    is_parlay_position,
    normalize_closed_row,
    open_mark_to_market_contribution,
    ordered_positions,
    position_identity,
    redeemable_ledger_contribution,
    roi_pct,
    row_volume_usd,
    row_win,
)


def test_first_non_null_alias_and_nullable_source_pnl_fallback():
    row = normalize_closed_row(
        {
            "conditionId": "0xcondition",
            "realized_pnl": "12.5",
            "source_realized_pnl": None,
            "avg_buy_price": 0.25,
            "total_bought": 4,
            "total_sold": 0,
        }
    )
    assert row["source_realized_pnl"] == pytest.approx(12.5)
    assert row["avg_buy_price"] == pytest.approx(0.25)


def test_normalize_api_and_legacy_database_shapes_into_one_contract():
    row = normalize_closed_row(
        {
            "wallet_address": "0xabc",
            "conditionId": "0xcondition",
            "outcome": "Yes",
            "asset": "12345678901234567890",
            "totalBought": "1000",
            "totalSold": "25",
            "avgPrice": "0.25",
            "avgSellPrice": "0.50",
            "initialValue": "240.0",
            "currentValue": "500.0",
            "realizedPnl": "10.5",
            "redeemable": "true",
            "metricsEligible": 1,
            "category": "SPORTS",
            "eventSlug": "event",
            "isCombo": False,
            "closedAt": "2026-09-01T12:00:00Z",
        }
    )
    assert row["address"] == "0xabc"
    assert row["condition_id"] == "0xcondition"
    assert row["source_asset"] == "12345678901234567890"
    assert row["asset_token_id"] == "12345678901234567890"
    assert row["avg_buy_price"] == pytest.approx(0.25)
    assert row["avg_sell_price"] == pytest.approx(0.50)
    assert row["source_realized_pnl"] == pytest.approx(10.5)
    assert row["is_redeemable"] is True
    assert row["metrics_eligible"] is True
    assert row["closed_at"] == datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
    assert row["closed_at"] == datetime(2026, 9, 1, 12, tzinfo=timezone.utc)


def test_asyncpg_like_record_is_accepted_without_mapping_inheritance():
    class Record:
        def __init__(self, **values):
            self.values = values

        def keys(self):
            return self.values.keys()

        def __getitem__(self, key):
            return self.values[key]

    row = normalize_closed_row(
        Record(condition_id="0xc", outcome="Yes", total_bought=10, avg_buy_price=0.2, realized_pnl=3)
    )
    assert row["condition_id"] == "0xc"
    assert closed_ledger_contribution(
        Record(condition_id="0xc", outcome="Yes", total_bought=10, avg_buy_price=0.2, realized_pnl=3)
    ) == pytest.approx(3)


def test_malformed_missing_negative_and_ambiguous_values_are_no_data():
    malformed = normalize_closed_row(
        {"avgPrice": "not-a-price", "totalBought": -1, "realizedPnl": "bad"}
    )
    assert malformed["avg_buy_price"] is None
    assert malformed["total_bought"] is None
    assert "avg_buy_price" in malformed["invalid_fields"]
    assert bucket_for_price("not-a-price") is None
    assert bucket_for_price(-0.1) is None
    assert bucket_for_price(25) is None
    assert row_volume_usd({"totalBought": 10, "avgPrice": "25"}) is None
    assert roi_pct(10, -2) is None


def test_explicit_cents_policy_is_required_for_conversion():
    assert bucket_for_price(25) is None
    row = normalize_closed_row(
        {"avgPrice": 25, "price_unit": "cents", "totalBought": 10, "realizedPnl": 1}
    )
    assert row["avg_buy_price"] == pytest.approx(0.25)
    assert row_volume_usd(row) == pytest.approx(2.5)


@pytest.mark.parametrize(
    ("price", "expected"),
    [
        (0.149999, "below_15c"),
        (0.15, "15_30c"),
        (0.299999, "15_30c"),
        (0.30, "30_45c"),
        (0.449999, "30_45c"),
        (0.45, "45_60c"),
        (0.599999, "45_60c"),
        (0.60, "60_75c"),
        (0.749999, "60_75c"),
        (0.75, "above_75c"),
    ],
)
def test_price_bucket_boundaries(price, expected):
    assert bucket_for_price(price) == expected


def test_price_buckets_are_canonical():
    assert tuple(PRICE_BUCKETS) == (
        "below_15c", "15_30c", "30_45c", "45_60c", "60_75c", "above_75c"
    )


def test_volume_uses_uncapped_entry_cost_while_loss_floor_uses_capped_cost():
    row = {
        "totalBought": 1000,
        "avgPrice": 0.90,
        "initialValue": 400,
        "realizedPnl": -1000,
    }
    assert row_volume_usd(row) == pytest.approx(900)
    assert closed_ledger_contribution(row) == pytest.approx(-400)


@pytest.mark.parametrize(
    ("value", "expected"), [(10, True), (0, False), (-1, False), ("bad", False)]
)
def test_row_win_is_strictly_positive(value, expected):
    assert row_win(value) is expected


def test_zero_cash_redeemable_negative_source_does_not_create_phantom_loss():
    row = {
        "totalBought": 0,
        "avgPrice": 0.50,
        "initialValue": 1_010_133.42,
        "realizedPnl": -1_010_133.42,
        "currentValue": 0,
        "redeemable": True,
    }
    assert redeemable_ledger_contribution(row) == 0
    assert open_mark_to_market_contribution(row) == 0


def test_ordinary_zero_cost_negative_open_row_is_not_silently_suppressed():
    row = {
        "totalBought": 0,
        "avgPrice": 0.50,
        "currentValue": 0,
        "realizedPnl": -10,
        "redeemable": False,
    }
    assert open_mark_to_market_contribution(row) == -10


def test_synthetic_artifact_zero_cost_negative_open_row_is_suppressed():
    row = {
        "totalBought": 0,
        "avgPrice": 0.50,
        "currentValue": 0,
        "realizedPnl": -10,
        "synthetic_artifact": True,
    }
    assert open_mark_to_market_contribution(row) == 0


def test_redeemable_settlement_is_added_once():
    row = {
        "totalBought": 1000,
        "avgPrice": 0.30,
        "initialValue": 300,
        "realizedPnl": 25,
        "settlementValue": 1000,
        "redeemable": True,
    }
    assert redeemable_ledger_contribution(row) == pytest.approx(725)


def test_legacy_transformed_row_returns_stored_materialized_contribution_exactly():
    row = {
        "total_bought": 100,
        "avg_buy_price": 0.40,
        "initial_value": 40,
        "realized_pnl": 20,
        "materialized_contribution": 7.25,
        "current_value": 100,
        "settlement_included": True,
        "legacy_transformed": True,
        "is_redeemable": True,
    }
    assert redeemable_ledger_contribution(row) == pytest.approx(7.25)
    assert open_mark_to_market_contribution(row) == pytest.approx(7.25)


def test_legacy_marker_materializes_realized_value_without_recounting():
    row = {
        "total_bought": 100,
        "avg_buy_price": 0.40,
        "realized_pnl": 7.25,
        "current_value": 100,
        "provenance": "legacy_redeemable_transformed",
        "is_redeemable": True,
    }
    assert redeemable_ledger_contribution(row) == pytest.approx(7.25)


def test_partial_sell_source_pnl_and_current_value_are_both_accounted_for():
    row = {
        "totalBought": 1000,
        "avgPrice": 0.50,
        "initialValue": 200,
        "realizedPnl": 75,
        "currentValue": 250,
    }
    assert open_mark_to_market_contribution(row) == pytest.approx(125)


def test_parlay_detector_requires_explicit_marker_or_deliberate_title_marker():
    assert is_parlay_position({"isCombo": True}) is True
    assert is_parlay_position({"combo_id": "combo-1"}) is True
    assert is_parlay_position({"title": "3-Leg NBA Parlay #1"}) is True
    assert is_parlay_position({"title": "Will Trump AND Harris debate?"}) is False
    assert is_parlay_position({"is_parlay": False, "title": "NBA Parlay"}) is False


def test_identity_prefers_exact_normalized_asset_token_over_source_asset():
    first = {"address": "0x1", "conditionId": "c", "outcome": "Yes", "asset_token_id": "000123", "source_asset": "other"}
    second = {"address": "0x1", "conditionId": "c", "outcome": "Yes", "asset_token_id": "000124", "source_asset": "other"}
    assert position_identity(first) == ("0x1", "c", "Yes", "000123")
    assert position_identity(first) != position_identity(second)


def test_identity_uses_source_asset_only_when_token_is_absent():
    row = {"address": "0x1", "conditionId": "c", "outcome": "Yes", "source_asset": "fallback"}
    assert position_identity(row)[-1] == "fallback"


def test_missing_asset_identifiers_use_stable_empty_identity_not_sentinel_repr():
    first = {"address": "0x1", "conditionId": "c", "outcome": "Yes"}
    second = {"address": "0x1", "conditionId": "c", "outcome": "Yes"}
    identity = position_identity(first)
    assert identity == ("0x1", "c", "Yes", "")
    assert position_identity(first) == position_identity(second)
    assert "object at" not in repr(identity)


def test_ordering_is_closed_at_descending_nulls_last_without_resolved_fallback():
    rows = [
        {"address": "0x1", "conditionId": "missing", "outcome": "Yes", "resolvedAt": "2099-01-01T00:00:00Z"},
        {"address": "0x1", "conditionId": "old", "outcome": "Yes", "closedAt": "2026-01-01T00:00:00Z"},
        {"address": "0x1", "conditionId": "new", "outcome": "Yes", "closedAt": "2026-02-01T00:00:00Z"},
    ]
    assert [row["condition_id"] for row in ordered_positions(rows)] == ["new", "old", "missing"]


def test_roi_is_suppressed_for_small_volume_and_bounded():
    assert roi_pct(1, 9) is None
    assert roi_pct(20, 10) == pytest.approx(200)
    assert roi_pct(-1000, 10) == -100
    assert roi_pct(10_000, 10) == 10_000
