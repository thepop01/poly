# Linked General/Analytics Views & Comprehensive Wallet Profile Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Link the General and Analytics leaderboard views to share identical wallet sequence, serial numbering (`#`), and sorting state, while keeping Parlay view independent; and construct a comprehensive, feature-rich Wallet Profile Page at `/wallet/[address]` accessible via 1-click on any wallet badge.

**Architecture:** 
- State synchronization in React Next.js frontend (`wallets/page.tsx`) ensuring General and Analytics views share identical query params (`sort_by`, `sort_order`, `category`, `subcategory`, `page`, `search`) so that wallet rankings and row serial numbers (`(page - 1) * PAGE_SIZE + i + 1`) match 1:1, with independent state reserved for the Parlay view.
- Backend FastAPI REST endpoints in `wallets_v2.py` providing complete wallet stats, category/subcategory breakdowns from `category_stats_v2`, 10-window PnLs from `wallet_metrics_v2`, and live/closed positions.
- Modern Glassmorphism Wallet Profile dashboard in `wallet/[address]/page.tsx` with executive metric cards, Category breakdown table, Price bucket trading matrix, 10-Window PnL progression, Parlay stats, and live/closed positions tables.

**Tech Stack:** Next.js 16 (App Router), React 19, Tailwind CSS, Lucide React, FastAPI, asyncpg, PostgreSQL.

---

### Task 1: Backend Categories & Enhanced Stats API Endpoints

**Files:**
- Modify: `d:\project\poly\src\api\routers\wallets_v2.py:58-95`
- Test: `d:\project\poly\scratch\test_wallet_api.py`

- [ ] **Step 1: Write verification test for wallet categories and stats endpoint**

```python
# scratch/test_wallet_api.py
import asyncio, aiohttp

async def test():
    async with aiohttp.ClientSession() as session:
        addr = "0xe2222d279d744050d28e00520010520000310f59"
        async with session.get(f"http://localhost:8000/api/v2/wallets/{addr}/categories") as r:
            assert r.status == 200, f"Categories endpoint failed: {r.status}"
            data = await r.json()
            assert isinstance(data, list)
            print(f"Categories returned: {len(data)} rows")

        async with session.get(f"http://localhost:8000/api/v2/wallets/{addr}/stats") as r:
            assert r.status == 200, f"Stats endpoint failed: {r.status}"
            stats = await r.json()
            assert "pnl" in stats or "total_pnl" in stats or "win_rate" in stats
            print(f"Stats returned: win_rate={stats.get('win_rate')}, pnl={stats.get('total_pnl')}")

if __name__ == "__main__":
    asyncio.run(test())
```

- [ ] **Step 2: Add `/categories` endpoint and enhance `/stats` in `wallets_v2.py`**

In `d:\project\poly\src\api\routers\wallets_v2.py`:

```python
# ── Stats ──────────────────────────────────────────────────────────

@router.get("/{address}/stats")
async def get_wallet_stats(request: Request, address: str) -> dict[str, Any]:
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")
    
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT w.*, m.*
            FROM wallets_v2 w
            LEFT JOIN wallet_metrics_v2 m ON w.address = m.address
            WHERE w.address = $1
        """, address.lower())
        
        if not row:
            raise HTTPException(status_code=404, detail="Wallet not found")
            
        # Get top category
        cat = await conn.fetchrow("""
            SELECT category, pnl as category_pnl, volume as category_volume, roi_pct as category_roi
            FROM category_stats_v2
            WHERE address = $1 AND window_size = 0 AND category != 'OVERALL'
            ORDER BY pnl DESC NULLS LAST, volume DESC NULLS LAST LIMIT 1
        """, address.lower())
        
    result = dict(row)
    if cat:
        result["favourite_category"] = cat["category"]
        result["top_category_pnl"] = cat["category_pnl"]
        
    return result


@router.get("/{address}/categories")
async def get_wallet_categories(request: Request, address: str) -> list[dict[str, Any]]:
    pool = getattr(request.app.state, "pool", None)
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT category, subcategory, win_rate, winning_count, losing_count, resolved_count, pnl, volume, roi_pct
            FROM category_stats_v2
            WHERE address = $1 AND window_size = 0
            ORDER BY 
                CASE WHEN category = 'OVERALL' THEN 0 ELSE 1 END,
                pnl DESC NULLS LAST, 
                volume DESC NULLS LAST
        """, address.lower())
    return [dict(r) for r in rows]
```

- [ ] **Step 3: Run verification test to verify endpoints return HTTP 200 with structured data**

Run: `.venv\Scripts\python scratch/test_wallet_api.py`
Expected: Output showing categories rows and stats dictionary without errors.

---

### Task 2: Frontend API Helpers

**Files:**
- Modify: `d:\project\poly\frontend\src\utils\api.ts:85-115`

- [ ] **Step 1: Add `getWalletCategories` and `getWalletClosedPositions` to `frontend/src/utils/api.ts`**

```typescript
export async function getWalletCategories(address: string) {
  return fetchAuthData(`/api/v2/wallets/${address}/categories`);
}

export async function getWalletClosedPositions(address: string, limit = 100, offset = 0) {
  return fetchAuthData(`/api/v2/wallets/${address}/closed-positions?limit=${limit}&offset=${offset}`);
}
```

---

### Task 3: Clickable WalletCell with Direct Navigation

**Files:**
- Modify: `d:\project\poly\frontend\src\components\wallets\WalletCell.tsx`

- [ ] **Step 1: Update `WalletCell.tsx` to make address and username clickable links to `/wallet/${address}`**

```tsx
"use client";

import Link from "next/link";
import { Globe, Copy, Check, Info } from "lucide-react";
import { formatAddress } from "@/utils/format";
import type { WatchlistStatus } from "@/hooks/useWatchlistAdd";
import { LikeButton } from "@/components/ui/LikeButton";

export function WalletCell({
  address,
  username,
  copiedAddress,
  onCopy,
  watchlistStatus,
  onAddToWatchlist,
  favoriteCount,
  isLiked,
  onToggleLike,
}: {
  address: string;
  username?: string | null;
  copiedAddress: string | null;
  onCopy: (e: React.MouseEvent, address: string) => void;
  watchlistStatus?: Record<string, WatchlistStatus>;
  onAddToWatchlist?: (e: React.MouseEvent, address: string) => void;
  favoriteCount?: number;
  isLiked?: boolean;
  onToggleLike?: (e: React.MouseEvent, address: string) => void;
}) {
  const isCurrentlyLiked = isLiked || (watchlistStatus && watchlistStatus[address] === "success");

  const handleLike = (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    if (onToggleLike) {
      onToggleLike(e, address);
    } else if (onAddToWatchlist) {
      onAddToWatchlist(e, address);
    }
  };

  const handleActionClick = (e: React.MouseEvent) => {
    e.stopPropagation();
  };

  return (
    <div className="flex items-center gap-1.5 group">
      {username && username.length <= 20 && (
        <Link
          href={`/wallet/${address}`}
          className="text-muted-fg hover:text-primary text-xs font-semibold truncate max-w-[90px] transition-colors"
          title={username}
        >
          {username}
        </Link>
      )}
      <Link
        href={`/wallet/${address}`}
        className="font-mono bg-primary/5 hover:bg-primary/15 px-2 py-0.5 rounded border border-primary/10 hover:border-primary/30 whitespace-nowrap text-xs text-foreground hover:text-primary transition-all duration-150 cursor-pointer shadow-sm hover:shadow-[0_0_8px_rgba(59,130,246,0.2)]"
        title="View Wallet Profile & Analytics"
      >
        {formatAddress(address)}
      </Link>
      <button
        onClick={(e) => {
          handleActionClick(e);
          onCopy(e, address);
        }}
        className="p-1 hover:bg-surface-2 rounded text-muted-fg hover:text-foreground transition-colors cursor-pointer"
        title="Copy Address"
      >
        {copiedAddress === address ? <Check size={11} className="text-green-500" /> : <Copy size={11} />}
      </button>
      <a
        href={`https://polymarket.com/profile/${address}`}
        target="_blank"
        rel="noopener noreferrer"
        onClick={handleActionClick}
        className="p-1 hover:bg-surface-2 rounded text-muted-fg hover:text-primary transition-colors cursor-pointer"
        title="View on Polymarket"
      >
        <Globe size={11} />
      </a>
      <a
        href={`https://activity.polymarket-tools.com/?address=${address}`}
        target="_blank"
        rel="noopener noreferrer"
        onClick={handleActionClick}
        className="p-1 hover:bg-surface-2 rounded text-muted-fg hover:text-primary transition-colors cursor-pointer"
        title="PolyTools Activity"
      >
        <Info size={11} />
      </a>

      {/* Like / Favorite Button */}
      <LikeButton
        isLiked={Boolean(isCurrentlyLiked)}
        onToggle={handleLike}
        favoriteCount={favoriteCount}
        size={13}
      />
    </div>
  );
}
```

---

### Task 4: Link General & Analytics Views with Independent Parlay View

**Files:**
- Modify: `d:\project\poly\frontend\src\app\wallets\page.tsx:110-230`

- [ ] **Step 1: Implement shared state between General and Analytics, separate state for Parlay**

In `frontend/src/app/wallets/page.tsx`:
1. Shared state for General & Analytics:
   - `sortField`, `sortOrder`, `page`, `category`, `filterSubcategory`, `pnlWindow`, `searchQuery`, `sourceFilter`.
2. Independent state for Parlay:
   - `parlaySortField` (default `"parlay_pnl"`), `parlaySortOrder` (default `"desc"`), `parlayPage` (default `1`).
3. Ensure when `viewMode` changes between `"general"` and `"analytics"`, the sort field and page are NEVER reset or changed.
4. When `handleSort` or `handleTradeSort` is called in either General or Analytics, it modifies the shared `sortField` and `sortOrder`.
5. Pass `rowOffset={(isParlayView ? parlayPage - 1 : page - 1) * PAGE_SIZE}` to `WalletTable` so serial numbers `#1`, `#2`, ..., `#50` reflect exact rank across both General and Analytics views.

---

### Task 5: Comprehensive, Premium Wallet Profile Page

**Files:**
- Modify: `d:\project\poly\frontend\src\app\wallet/[address]/page.tsx`

- [ ] **Step 1: Implement the Complete Wallet Profile Dashboard**

Construct the profile dashboard in `frontend/src/app/wallet/[address]/page.tsx` with:
1. **Header Section**:
   - Navigation Back button `<Link href="/wallets">`
   - Gradient Identicon Avatar generated from wallet address hash
   - Formatted Address + Full Address tooltip + 1-Click Copy with feedback
   - Tier Badge with glowing pill styles
   - Quick links (Polymarket, Polygonscan, PolyTools)
   - Like / Favorite toggle button
2. **Executive KPI Cards**:
   - Total PnL (with sign, bold font, colored + formatted)
   - Win Rate % & Record (e.g. `98.8% • 5,050 W / 60 L`)
   - Total Volume ($) & ROI %
   - Live Portfolio Balance & Active Positions Value
   - On-chain Peak Capital & Total Deposits (Alchemy on-chain metrics)
   - Average Buy Price (¢)
3. **Multi-Tab Deep Analysis Subsystems**:
   - **Tab: Categories (`categories`)**: Complete table & visual progress bars for all categories and subcategories (`Sports`, `Politics`, `Crypto`, etc.) with Win Rate, Wins, Losses, Resolved, PnL, Volume, ROI %.
   - **Tab: Price Buckets (`buckets`)**: Visual trading matrix across `<0.15`, `0.15-0.30`, `0.30-0.45`, `0.45-0.60`, `0.60-0.75`, `>0.75` with win rates, buy counts, win counts, and avg sell prices.
   - **Tab: 10-Window PnLs (`pnl_windows`)**: Visual progression cards for Last 100, 200, 300, 500, 750, 1000, 1500, 2000, 3500, 5000 trades.
   - **Tab: Parlay (`parlay`)**: Dedicated parlay metrics (Win Rate, Wins, Resolved, PnL, Volume, Open Bets).
   - **Tab: Open Positions (`positions`)**: Live positions table with Outcome badge, Size, Buy Price, Current Price, Value, and P&L.
   - **Tab: Closed Positions (`closed`)**: Realized PnL table with micro-USDC scale fix, Outcome, and resolution timestamps.
   - **Tab: Recent Trades (`trades`)**: Real-time trade log with side, size, price, timestamp, and Polymarket market links.

---

## Verification Plan

### Automated Verification
- Run: `.venv\Scripts\python scratch/test_wallet_api.py` -> verify HTTP 200 and valid JSON data for `/stats` and `/categories`.

### Manual & UI Verification
- Open `http://localhost:3000/wallets`:
  - Verify Wallet #1 in General view has the exact same wallet address and serial number `#1` when switching to Analytics view.
  - Sort by `pnl` in General -> switch to Analytics -> verify sort and `#` serial numbers are preserved.
  - Sort by `<0.15 W/R` or `avg_buy_price` in Analytics -> switch to General -> verify sort and `#` serial numbers are preserved.
  - Switch to Parlay view -> verify independent sort by `parlay_pnl`.
  - Click on any wallet address -> verify navigation to `/wallet/[address]`.
  - Verify all KPI cards, Category breakdown table, Price Buckets, 10-Window PnL cards, and positions tables render seamlessly.
