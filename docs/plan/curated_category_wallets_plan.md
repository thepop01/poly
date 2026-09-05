# New: Category-Based Curated Wallet Tags

## Overview

Right now, `is_curated` on a wallet is a single global boolean — a wallet either meets the global threshold or it doesn't. You want a richer system where a wallet can be curated **specifically for a category or subcategory**. For example:

- A wallet might not be globally elite, but it could be a **Sports specialist** with 90% win rate in NFL markets.
- A wallet could be tagged **Crypto > Bitcoin** because it specifically profits from Bitcoin price markets.

This requires a new **DB table**, a **worker/refresher** to compute tags, a new **API endpoint**, and a new **frontend page** (or additional tabs on the existing Curated page).

---

## Curation Thresholds (As You Described)

| Level       | Minimum Volume | ROI OR Win Rate OR PnL |
|-------------|----------------|------------------------|
| **Category** (e.g., Sports) | > $100k in that category | ROI > 30% OR Win Rate > 60% OR PnL > $10k in that category |
| **Subcategory** (e.g., NFL, Cricket) | Any volume | ROI > 30% OR Win Rate > 60% OR PnL > $10k in that subcategory |

> [!NOTE]
> The category thresholds are checked against `wallet_category_stats` (which already exists).
> The subcategory thresholds are checked against `wallet_tags` (which already has `trade_count` and top markets).
> **However**, `wallet_tags` currently does NOT store PnL/ROI/Win Rate at the subcategory level. We will need to compute this from the `trades` table.

---

## Data Gap: Subcategory-Level Metrics

> [!IMPORTANT]
> Currently the `wallet_tags` table only stores `trade_count` and `top_markets`. It does **NOT** have PnL, ROI or win rate at the subcategory level.
> To properly curate at the subcategory level, we need one of two approaches:
>
> **Option A (Recommended — Simpler):** Add columns `subcategory_pnl`, `subcategory_win_rate`, `subcategory_roi` to `wallet_tags`, and populate them in the existing `stats_refresher.py`.
>
> **Option B (Complex):** Create a brand new `wallet_subcategory_stats` table mirroring `wallet_category_stats` but with a subcategory dimension.
>
> **I recommend Option A** since the wallet_tags table already exists and the stats_refresher already touches it.

---

## Proposed Changes

### Layer 1: Database

#### [MODIFY] `wallet_tags` table — Add subcategory metrics
Add 3 new columns via SQL migration:
```sql
ALTER TABLE wallet_tags
  ADD COLUMN IF NOT EXISTS subcategory_pnl    NUMERIC DEFAULT 0,
  ADD COLUMN IF NOT EXISTS subcategory_roi    NUMERIC DEFAULT 0,
  ADD COLUMN IF NOT EXISTS subcategory_win_rate NUMERIC DEFAULT 0;
```

#### [NEW] `curated_category_tags` table — Stores who is curated for what
```sql
CREATE TABLE IF NOT EXISTS curated_category_tags (
  address         VARCHAR NOT NULL,
  category        VARCHAR NOT NULL,  -- e.g., 'Sports'
  subcategory     VARCHAR,           -- e.g., 'Cricket', NULL for category-level tags
  tag_type        VARCHAR NOT NULL,  -- 'category' or 'subcategory'
  category_pnl    NUMERIC,
  category_roi    NUMERIC,
  category_win_rate NUMERIC,
  category_volume NUMERIC,
  computed_at     TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (address, category, COALESCE(subcategory, ''))
);
```

---

### Layer 2: Backend Worker (Python)

#### [MODIFY] `src/workers/stats_refresher.py`
Add a new pass to the stats refresh worker to:
1. Compute subcategory PnL/ROI/Win Rate from `trades` table grouped by wallet + subcategory (using market title pattern matching).
2. Update `wallet_tags` with the new metrics columns.
3. Upsert into `curated_category_tags` for wallets that meet the thresholds.

---

### Layer 3: API

#### [NEW] `GET /api/leaderboard/category-curated` endpoint in `leaderboard.py`
This endpoint queries the new `curated_category_tags` table.

**Query params:**
- `category` — Filter by category (e.g., `Sports`)
- `subcategory` — Filter by subcategory (e.g., `Cricket`)
- `sort_by`, `sort_order`, `limit`, `offset` — Standard pagination

**Returns:** List of wallets tagged as curated for that specific niche, with their category-specific metrics.

---

### Layer 4: Frontend

#### [NEW] New page or tabs on the existing Curated page (`/wallets/curated`)
The existing curated page already has Category tabs (Sports, Crypto, etc.). We can **extend** this with a 3rd axis:

```
[All] [Sports] [Politics] [Crypto] ...   ← Category tabs (already exist)
[All] [Cricket] [NFL] [NBA] [Soccer] ... ← Subcategory pills (new pills row — just added!)
```

The key change: instead of pulling from `curated-wallets` API filtered by `category`, we now pull from the new `category-curated` API which only returns wallets that were **specifically curated for that category**, showing their category-specific metrics rather than global stats.

---

## What the User Sees (End State)

| Tab | Sub-tab | Table Shows |
|-----|---------|-------------|
| Sports | All | Wallets curated for Sports (>$100k vol, >30% ROI, etc.) with their Sports-specific PnL |
| Sports | Cricket | Wallets that specifically profit from Cricket markets |
| Sports | NFL | Wallets that specifically profit from NFL markets |
| Crypto | Bitcoin | Wallets that specifically profit from Bitcoin markets |
| All | — | All globally curated wallets (existing behavior) |

---

## Open Questions

> [!IMPORTANT]
> 1. **Same page or separate page?** Do you want this to replace the current Curated page tabs, or be a brand new `/wallets/category-curated` page?
> 2. **Subcategory thresholds:** For subcategory curation, what's the minimum trade count? (currently wallet_tags only stores trade_count, not PnL at subcategory level)
> 3. **Run timing:** The new stats computation for subcategory metrics can be added to the existing `stats_refresher` worker — is that OK, or do you want a dedicated worker?

---

## Verification Plan

1. Run `stats_refresher.py` (or a new migration script) to populate `curated_category_tags`.
2. Query `curated_category_tags` to verify wallets are correctly bucketed into categories/subcategories.
3. Test the new API endpoint with different `category` and `subcategory` parameters.
4. Verify the frontend correctly loads different data for each category/subcategory tab.
