"""Recompute BreakTheBank closed rows from verified fills (dry-run default).

Reads tmp_btb_verdict (per-leg verdicts + fill economics). For DIRECT groups
with acquisition basis, recomputes totals/avgs/realized from fills. Anything
without basis is flagged, never faked. DEAD groups (zero evidence anywhere)
are proposed for metrics exclusion.

- Default: dry-run report only.
- --apply: snapshots rows to tmp_btb_closed_backup, then writes corrections
  and flags in one transaction.

Usage:
    python src/scripts/recompute_btb_corrected.py
    python src/scripts/recompute_btb_corrected.py --apply
"""

import argparse
import asyncio
import asyncpg
import os
import sys

W = "0xf0318c32136c2db7fec88b84869aee6a1106c80c"

REPORT_SQL = """
SELECT verdict,
       COUNT(*) AS groups, SUM(rows) AS rows,
       ROUND(SUM(realized)::numeric, 2) AS old_realized,
       ROUND(SUM(d_sellp + d_red - d_buyc)::numeric, 2) AS fills_cash
FROM tmp_btb_verdict GROUP BY 1 ORDER BY 4
"""


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    pool = await asyncpg.create_pool(
        "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db",
        timeout=60, command_timeout=600)
    async with pool.acquire() as conn:
        print("--- current verdict economics ---")
        for r in await conn.fetch(REPORT_SQL):
            print("  ", dict(r))

        # Proposed per-row corrections. ADOPT_FULL requires a fully-exited
        # leg (fills net ~0 with $1 redemptions counted as shares) and no
        # valued open mirror; otherwise the buys also support inventory
        # elsewhere and cash math would double-charge them (the partial-sell
        # bug in a new form).
        preview = await conn.fetch(
            """SELECT v.cid, v.onorm, v.outcome_raw, v.rows, v.verdict,
                      v.realized AS old_realized,
                      v.bought_sh AS old_bought, v.d_buy AS fills_bought,
                      v.d_buyc AS fills_cost, v.d_sellp + v.d_red AS fills_proc,
                      v.open_value,
                      CASE
                        WHEN v.verdict = 'DIRECT' AND COALESCE(v.d_buy, 0) > 0
                             AND v.d_buy >= COALESCE(v.bought_sh, 0)
                             AND ABS(v.d_buy - v.d_sell - v.d_red)
                                 <= GREATEST(1, 0.05 * v.d_buy)
                             AND COALESCE(v.open_value, 0) <= 25
                          THEN (v.d_sellp + v.d_red - v.d_buyc)
                        ELSE v.realized
                      END AS new_realized,
                      CASE
                        WHEN v.verdict = 'DIRECT' AND COALESCE(v.d_buy, 0) > 0
                             AND v.d_buy >= COALESCE(v.bought_sh, 0)
                             AND ABS(v.d_buy - v.d_sell - v.d_red)
                                 <= GREATEST(1, 0.05 * v.d_buy)
                             AND COALESCE(v.open_value, 0) <= 25
                          THEN 'ADOPT_FULL'
                        WHEN v.verdict = 'DIRECT' AND COALESCE(v.open_value, 0) > 25
                          THEN 'MIRROR_OPEN'
                        WHEN v.verdict = 'DIRECT' AND COALESCE(v.d_buy, 0) > 0
                             AND ABS(v.d_buy - v.d_sell - v.d_red)
                                 > GREATEST(1, 0.05 * v.d_buy)
                          THEN 'PARTIAL_EXIT'
                        WHEN v.verdict = 'DIRECT' AND COALESCE(v.d_buy, 0) > 0
                          THEN 'KEEP_FLAG_EXCESS'
                        WHEN v.verdict = 'DIRECT' THEN 'NO_BASIS'
                        WHEN v.verdict = 'DEAD' THEN 'EXCLUDE_PROPOSED'
                        ELSE 'FLAG_ONLY'
                      END AS action
               FROM tmp_btb_verdict v
               ORDER BY ABS((v.d_sellp + v.d_red - v.d_buyc) - v.realized) DESC""")
        from collections import Counter
        print("--- action counts ---")
        print("  ", dict(Counter((r["action"],) for r in preview)))
        new_total = sum(float(r["new_realized"] or 0) for r in preview)
        old_total = sum(float(r["old_realized"] or 0) for r in preview)
        print(f"--- bridge: old {old_total:,.2f} -> proposed {new_total:,.2f} "
              f"(DEAD excluded would add back {sum(float(r['old_realized'] or 0) for r in preview if r['action'] == 'EXCLUDE_PROPOSED'):,.2f}) ---")
        print("--- top 12 changes ---")
        for r in preview[:12]:
            print("  ", r["cid"][:12], (r["outcome_raw"] or "")[:16], r["verdict"],
                  r["action"], f"old={float(r['old_realized'] or 0):,.2f}",
                  f"new={float(r['new_realized'] or 0):,.2f}")

        if not args.apply:
            print("DRY RUN ONLY. Re-run with --apply to write (with backup).")
            return

        async with conn.transaction():
            await conn.execute("DROP TABLE IF EXISTS tmp_btb_closed_backup")
            await conn.execute(
                "CREATE TABLE tmp_btb_closed_backup AS "
                "SELECT * FROM wallet_closed_positions_v2 WHERE address=$1", W)
            # 1a. Fills dominate, fully exited, no valued mirror: adopt.
            await conn.execute(
                """UPDATE wallet_closed_positions_v2 p SET
                     total_bought = v.d_buy,
                     avg_buy_price = CASE WHEN v.d_buy > 0 THEN v.d_buyc / v.d_buy ELSE avg_buy_price END,
                     total_sold = v.d_sell,
                     avg_sell_price = CASE WHEN v.d_sell > 0 THEN v.d_sellp / v.d_sell ELSE avg_sell_price END,
                     realized_pnl = v.d_sellp + v.d_red - v.d_buyc,
                     data_quality_flag = 'FILLS_VERIFIED'
                   FROM (SELECT cid, onorm, d_buy, d_buyc, d_sell, d_sellp, d_red
                         FROM tmp_btb_verdict
                         WHERE verdict='DIRECT' AND COALESCE(d_buy,0) > 0
                           AND d_buy >= COALESCE(bought_sh, 0)
                           AND ABS(d_buy - d_sell - d_red) <= GREATEST(1, 0.05 * d_buy)
                           AND COALESCE(open_value, 0) <= 25) v
                   WHERE p.address=$1 AND lower(p.condition_id)=v.cid
                     AND regexp_replace(lower(trim(p.outcome)), '[^a-z0-9]+', '', 'g')=v.onorm""",
                W)
            # 1b. Valued open mirror: allocation ambiguous, flag only.
            await conn.execute(
                """UPDATE wallet_closed_positions_v2 p SET data_quality_flag='MIRROR_OPEN'
                   FROM (SELECT cid, onorm FROM tmp_btb_verdict
                         WHERE verdict='DIRECT' AND COALESCE(open_value,0) > 25) v
                   WHERE p.address=$1 AND lower(p.condition_id)=v.cid
                     AND regexp_replace(lower(trim(p.outcome)), '[^a-z0-9]+', '', 'g')=v.onorm
                     AND COALESCE(p.data_quality_flag, '') = ''""",
                W)
            # 1c. Partial exit: proceeds real but cost split unknown, flag only.
            await conn.execute(
                """UPDATE wallet_closed_positions_v2 p SET data_quality_flag='PARTIAL_EXIT'
                   FROM (SELECT cid, onorm FROM tmp_btb_verdict
                         WHERE verdict='DIRECT' AND COALESCE(d_buy,0) > 0
                           AND ABS(d_buy - d_sell - d_red) > GREATEST(1, 0.05 * d_buy)
                           AND COALESCE(open_value,0) <= 25) v
                   WHERE p.address=$1 AND lower(p.condition_id)=v.cid
                     AND regexp_replace(lower(trim(p.outcome)), '[^a-z0-9]+', '', 'g')=v.onorm
                     AND COALESCE(p.data_quality_flag, '') = ''""",
                W)
            # 1b. Stored exceeds fills: keep numbers, flag unproven excess.
            await conn.execute(
                """UPDATE wallet_closed_positions_v2 p SET data_quality_flag='UNPROVEN_EXCESS'
                   FROM (SELECT cid, onorm FROM tmp_btb_verdict
                         WHERE verdict='DIRECT' AND COALESCE(d_buy,0) > 0
                           AND d_buy < COALESCE(bought_sh, 0)) v
                   WHERE p.address=$1 AND lower(p.condition_id)=v.cid
                     AND regexp_replace(lower(trim(p.outcome)), '[^a-z0-9]+', '', 'g')=v.onorm
                     AND COALESCE(p.data_quality_flag, '') = ''""",
                W)
            # 2. Flag no-basis rows.
            await conn.execute(
                """UPDATE wallet_closed_positions_v2 p SET data_quality_flag='NO_BASIS'
                   FROM (SELECT cid, onorm FROM tmp_btb_verdict
                         WHERE verdict='DIRECT' AND COALESCE(d_buy,0)=0
                           AND (COALESCE(d_sellp,0)+COALESCE(d_red,0))>0) v
                   WHERE p.address=$1 AND lower(p.condition_id)=v.cid
                     AND regexp_replace(lower(trim(p.outcome)), '[^a-z0-9]+', '', 'g')=v.onorm
                     AND COALESCE(p.data_quality_flag, '') = ''""",
                W)
            # 3. Flag slug-linked / minted / reward-only.
            await conn.execute(
                """UPDATE wallet_closed_positions_v2 p SET data_quality_flag='NEEDS_SPLIT_ATTRIBUTION'
                   FROM (SELECT cid, onorm FROM tmp_btb_verdict WHERE verdict='SLUG_LINKED') v
                   WHERE p.address=$1 AND lower(p.condition_id)=v.cid
                     AND regexp_replace(lower(trim(p.outcome)), '[^a-z0-9]+', '', 'g')=v.onorm
                     AND COALESCE(p.data_quality_flag, '') = ''""",
                W)
            # 4. Exclude dead rows from metrics (recorded, reversible via backup).
            await conn.execute(
                """UPDATE wallet_closed_positions_v2 p
                   SET metrics_eligible=FALSE, exclusion_reason='NO_ACTIVITY_BASIS',
                       data_quality_flag='NO_ACTIVITY'
                   FROM (SELECT cid, onorm FROM tmp_btb_verdict WHERE verdict='DEAD') v
                   WHERE p.address=$1 AND lower(p.condition_id)=v.cid
                     AND regexp_replace(lower(trim(p.outcome)), '[^a-z0-9]+', '', 'g')=v.onorm""",
                W)
        check = await conn.fetchrow(
            "SELECT SUM(realized_pnl)::numeric AS s, COUNT(*) n FROM wallet_closed_positions_v2 WHERE address=$1", W)
        print(f"APPLIED. Backup: tmp_btb_closed_backup. New closed sum: {check['s']} over {check['n']} rows.")
    await pool.close()


asyncio.run(main())
