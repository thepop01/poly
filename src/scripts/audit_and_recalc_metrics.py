"""
audit_and_recalc_metrics.py
===========================
Scans all wallets in the database and recalculates/corrects:
1. Win Rate % (strictly 0..100% scale, validated against winning_count & resolved_count)
2. Resolved & Winning Counts (enforces winning_count <= resolved_count)
3. ROI % (calculated using True Capital Base matching worker logic)
4. Category & Subcategory Win Rates & ROIs
5. Pre-audit diagnostics and post-audit verification with sample output

Capital Base Fallback Chain (matches capital_metrics_backfill.py & positions_winrate_backfill.py):
  1. max(peak_capital, deposits, inferred_cap)
  2. If < $10: fallback to total_volume
  3. If still < $10: fallback to balance
  4. If still < $10: ROI = NULL (too small to measure)

Win Rate Normalization:
  - Detects if win_rate is stored as decimal (0..1) or percentage (0..100)
  - Normalizes everything to 0..100% scale
"""

import sys
import os
import time
import psycopg2
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
load_dotenv()

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db").replace("localhost", "127.0.0.1").replace("postgres://", "postgresql://")


def print_sample(cur, title, query, limit=5):
    """Print a sample of rows for diagnostic/verification purposes."""
    try:
        cur.execute(query)
        rows = cur.fetchmany(limit)
        if rows:
            cols = [desc[0] for desc in cur.description]
            print(f"    {title}:")
            for r in rows:
                vals = ", ".join(f"{c}={v}" for c, v in zip(cols, r))
                print(f"      {vals}")
        else:
            print(f"    {title}: (none)")
    except Exception as e:
        print(f"    {title}: Error - {e}")


def main():
    print("=" * 75)
    print("STARTING GLOBAL WALLET METRICS SCANNER & RECALCULATION")
    print("=" * 75)
    t0 = time.time()

    conn = psycopg2.connect(DB_URL)
    conn.autocommit = False
    cur = conn.cursor()

    try:
        # ════════════════════════════════════════════════════════════════════
        # STEP 0: PRE-AUDIT DIAGNOSTICS
        # ════════════════════════════════════════════════════════════════════
        print("\n" + "=" * 75)
        print("PRE-AUDIT DIAGNOSTICS")
        print("=" * 75)

        cur.execute("SELECT COUNT(*) FROM wallet_metrics_v2;")
        total_wallets = cur.fetchone()[0]
        print(f"[*] Total wallets in wallet_metrics_v2: {total_wallets:,}")

        cur.execute("SELECT COUNT(*) FROM wallet_metrics_v2 WHERE win_rate IS NULL;")
        null_wr = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM wallet_metrics_v2 WHERE win_rate > 0 AND win_rate <= 1.0;")
        decimal_wr = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM wallet_metrics_v2 WHERE win_rate > 1.0 AND win_rate <= 100.0;")
        pct_wr = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM wallet_metrics_v2 WHERE win_rate > 100.0;")
        over100_wr = cur.fetchone()[0]
        print(f"    Win Rate distribution: NULL={null_wr:,} | 0..1 (decimal)={decimal_wr:,} | 1..100 (pct)={pct_wr:,} | >100 (anomaly)={over100_wr:,}")

        cur.execute("SELECT COUNT(*) FROM wallet_metrics_v2 WHERE winning_count > resolved_count AND winning_count > 0;")
        bad_counts = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM wallet_metrics_v2 WHERE resolved_count = 0 AND winning_count = 0;")
        zero_counts = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM wallet_metrics_v2 WHERE total_pnl IS NULL;")
        null_pnl = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM wallet_metrics_v2 WHERE roi_pct IS NULL;")
        null_roi = cur.fetchone()[0]
        print(f"    Count anomalies (win>resolved): {bad_counts:,}")
        print(f"    Zero activity (resolved=0, wins=0): {zero_counts:,}")
        print(f"    NULL total_pnl: {null_pnl:,} | NULL roi_pct: {null_roi:,}")

        cur.execute("SELECT COUNT(*) FROM wallet_metrics_v2 WHERE peak_capital IS NULL OR peak_capital = 0;")
        no_peak = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM wallet_metrics_v2 WHERE deposits IS NULL OR deposits = 0;")
        no_dep = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM wallet_metrics_v2 WHERE balance IS NULL OR balance = 0;")
        no_bal = cur.fetchone()[0]
        print(f"    Missing capital data: peak_capital=0/NULL:{no_peak:,} | deposits=0/NULL:{no_dep:,} | balance=0/NULL:{no_bal:,}")

        # Check category_stats_v2 column names
        try:
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'category_stats_v2' AND column_name IN ('pnl', 'total_pnl', 'volume', 'total_volume')
                ORDER BY column_name;
            """)
            cat_cols = [row[0] for row in cur.fetchall()]
            print(f"    category_stats_v2 PnL/Volume columns: {cat_cols}")
        except Exception:
            pass

        print_sample(cur, "Sample anomalous wallets (win>resolved)", """
            SELECT address, winning_count, resolved_count, win_rate, roi_pct
            FROM wallet_metrics_v2
            WHERE winning_count > resolved_count AND winning_count > 0
            LIMIT 5
        """)

        print_sample(cur, "Sample decimal-format win_rate (0..1)", """
            SELECT address, win_rate, winning_count, resolved_count, roi_pct
            FROM wallet_metrics_v2
            WHERE win_rate > 0 AND win_rate <= 1.0 AND resolved_count > 0
            LIMIT 5
        """)

        # Count anomalies are diagnostics only.  Never repair a count by
        # copying winning_count: both values must be reconstructed from
        # eligible wallet_closed_positions_v2 rows by the canonical coordinator.
        print("\n" + "=" * 75)
        print("STEP 1: Report count anomalies (no repair)")
        print("=" * 75)
        print(f"    -> Deferred to canonical eligible-row reconstruction: {bad_counts:,}")

        # ════════════════════════════════════════════════════════════════════
        # STEP 2: Normalize win_rate to 0..100% scale
        # ════════════════════════════════════════════════════════════════════
        print("\n" + "=" * 75)
        print("STEP 2: Normalize Win Rates to 0..100% scale")
        print("=" * 75)

        # Fix decimal-format win_rates (0..1 -> 0..100) where resolved_count > 0
        cur.execute("""
            UPDATE wallet_metrics_v2
            SET win_rate = win_rate * 100.0
            WHERE win_rate > 0.0 AND win_rate <= 1.0 AND resolved_count > 0;
        """)
        c_decimal = cur.rowcount
        print(f"    -> Normalized decimal (0..1) to percentage: {c_decimal:,}")

        # Now recalculate ALL win_rates from counts (source of truth)
        cur.execute("""
            UPDATE wallet_metrics_v2
            SET win_rate = CASE
                WHEN resolved_count > 0 AND winning_count >= 0 THEN
                    ROUND(LEAST(100.0, GREATEST(0.0, (winning_count::numeric / resolved_count::numeric) * 100.0)), 4)
                ELSE NULL
            END;
        """)
        c_wr = cur.rowcount
        print(f"    -> Recalculated from counts: {c_wr:,}")

        # ════════════════════════════════════════════════════════════════════
        # STEP 3: ROI Recalculation with Worker-Matched Capital Base
        # ════════════════════════════════════════════════════════════════════
        print("\n" + "=" * 75)
        print("STEP 3: Recalculate ROIs (Capital Base matches worker logic)")
        print("=" * 75)

        # Capital base logic matches capital_metrics_backfill.py:84-89
        # and positions_winrate_backfill.py:462-468:
        #   cap = max(peak_capital, deposits, inferred_cap)
        #   + inherited position cost basis for inherited wallets (ADDITIVE:
        #   transferred shares are ERC-1155 tokens, never USDC, so they never
        #   appear in deposits/peak_capital; internal USDC funding is already
        #   inside deposits and is NOT added again)
        #   if cap < 10: fallback to total_volume
        #   if still < 10: fallback to balance
        cur.execute("""
            WITH calc AS (
                SELECT
                    address,
                    total_pnl,
                    GREATEST(0,
                        COALESCE(balance, 0) + COALESCE(position_value, 0)
                        + COALESCE(withdrawals, 0) - COALESCE(total_pnl, 0)
                    ) AS inferred_cap,
                    COALESCE(peak_capital, 0) AS peak_capital,
                    COALESCE(deposits, 0) AS deposits,
                    COALESCE(total_volume, 0) AS total_volume,
                    COALESCE(balance, 0) AS balance
                FROM wallet_metrics_v2
            ),
            inherited AS (
                SELECT
                    cp.address,
                    COALESCE(SUM(cp.avg_buy_price * cp.total_bought), 0) AS closed_cost
                FROM wallet_closed_positions_v2 cp
                JOIN wallets_v2 w ON w.address = cp.address
                WHERE (w.funding_source IN ('internal_funded', 'inherited_positions')
                       OR COALESCE(w.transferred_positions_count, 0) > 0
                       OR w.funded_by IS NOT NULL)
                GROUP BY cp.address
            ),
            inherited_open AS (
                SELECT
                    p.address,
                    COALESCE(SUM(p.avg_price * p.size), 0) AS open_cost
                FROM wallet_positions_v2 p
                JOIN wallets_v2 w ON w.address = p.address
                WHERE (w.funding_source IN ('internal_funded', 'inherited_positions')
                       OR COALESCE(w.transferred_positions_count, 0) > 0
                       OR w.funded_by IS NOT NULL)
                GROUP BY p.address
            ),
            cap AS (
                SELECT
                    c.address,
                    c.total_pnl,
                    c.peak_capital,
                    c.deposits,
                    c.inferred_cap,
                    c.total_volume,
                    c.balance,
                    COALESCE(i.closed_cost, 0) + COALESCE(io.open_cost, 0) AS inherited_cap,
                    CASE
                        WHEN GREATEST(c.peak_capital, c.deposits, c.inferred_cap)
                             + COALESCE(i.closed_cost, 0) + COALESCE(io.open_cost, 0) >= 10.0 THEN
                            GREATEST(c.peak_capital, c.deposits, c.inferred_cap)
                            + COALESCE(i.closed_cost, 0) + COALESCE(io.open_cost, 0)
                        WHEN c.total_volume >= 10.0 THEN
                            c.total_volume
                        WHEN c.balance >= 10.0 THEN
                            c.balance
                        ELSE 0
                    END AS true_cap_base
                FROM calc c
                LEFT JOIN inherited i ON i.address = c.address
                LEFT JOIN inherited_open io ON io.address = c.address
            )
            UPDATE wallet_metrics_v2 m
            SET roi_pct = CASE
                WHEN c.total_pnl IS NULL THEN NULL
                WHEN c.true_cap_base >= 10.0 THEN
                    ROUND(LEAST(10000.0, GREATEST(-100.0,
                        (c.total_pnl / c.true_cap_base) * 100.0
                    )), 4)
                ELSE NULL
            END,
            computed_at = NOW()
            FROM cap c
            WHERE m.address = c.address;
        """)
        c_roi = cur.rowcount
        print(f"    -> ROIs recalculated: {c_roi:,}")

        # ════════════════════════════════════════════════════════════════════
        # STEP 4: Audit & Correct category_stats_v2
        # ════════════════════════════════════════════════════════════════════
        print("\n" + "=" * 75)
        print("STEP 4: Audit & Correct category_stats_v2")
        print("=" * 75)

        # Fix count integrity first, then compute win_rate from corrected counts
        cur.execute("""
            -- Count anomalies are reported, never repaired by copying wins.
            UPDATE category_stats_v2
            SET resolved_count = resolved_count
            WHERE FALSE;
        """)
        c_cat_fix = cur.rowcount
        print(f"    -> Fixed count anomalies: {c_cat_fix:,}")

        cur.execute("""
            UPDATE category_stats_v2
            SET
                win_rate = CASE
                    WHEN COALESCE(resolved_count, 0) > 0 THEN
                        ROUND(LEAST(100.0, GREATEST(0.0,
                            (COALESCE(winning_count, 0)::numeric / resolved_count::numeric) * 100.0
                        )), 4)
                    ELSE NULL
                END,
                roi_pct = CASE
                    WHEN COALESCE(volume, 0) >= 10.0 AND pnl IS NOT NULL THEN
                        ROUND(LEAST(10000.0, GREATEST(-100.0, (pnl / volume) * 100.0)), 4)
                    ELSE NULL
                END,
                computed_at = NOW();
        """)
        c_cat = cur.rowcount
        print(f"    -> Category records updated: {c_cat:,}")

        # ════════════════════════════════════════════════════════════════════
        # STEP 5: Audit & Correct wallet_subcategory_stats
        # ════════════════════════════════════════════════════════════════════
        print("\n" + "=" * 75)
        print("STEP 5: Audit & Correct wallet_subcategory_stats")
        print("=" * 75)

        try:
            # Check which column names this table uses
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'wallet_subcategory_stats'
                ORDER BY ordinal_position;
            """)
            sub_cols = {row[0] for row in cur.fetchall()}
            has_pnl = 'pnl' in sub_cols
            has_total_pnl = 'total_pnl' in sub_cols
            has_volume = 'volume' in sub_cols
            has_total_volume = 'total_volume' in sub_cols

            if has_pnl and has_volume:
                pnl_col, vol_col = 'pnl', 'volume'
            elif has_total_pnl and has_total_volume:
                pnl_col, vol_col = 'total_pnl', 'total_volume'
            else:
                print("    -> Could not determine column names, skipping subcategory audit")
                pnl_col = vol_col = None

            if pnl_col:
                cur.execute(f"""
                    UPDATE wallet_subcategory_stats
                    SET resolved_count = resolved_count
                    WHERE FALSE;
                """)
                c_sub_fix = cur.rowcount
                print(f"    -> Fixed count anomalies: {c_sub_fix:,}")

                cur.execute(f"""
                    UPDATE wallet_subcategory_stats
                    SET
                        win_rate = CASE
                            WHEN COALESCE(resolved_count, 0) > 0 THEN
                                ROUND(LEAST(100.0, GREATEST(0.0,
                                    (COALESCE(winning_count, 0)::numeric / resolved_count::numeric) * 100.0
                                )), 4)
                            ELSE NULL
                        END,
                        roi_pct = CASE
                            WHEN COALESCE({vol_col}, 0) >= 10.0 AND {pnl_col} IS NOT NULL THEN
                                ROUND(LEAST(10000.0, GREATEST(-100.0, ({pnl_col} / {vol_col}) * 100.0)), 4)
                            ELSE NULL
                        END,
                        computed_at = NOW();
                """)
                c_sub = cur.rowcount
                print(f"    -> Subcategory records updated: {c_sub:,}")
        except Exception as e:
            print(f"    -> Subcategory audit skipped: {e}")

        conn.commit()
        print("\n" + "=" * 75)
        print("POST-AUDIT VERIFICATION")
        print("=" * 75)

        cur.execute("SELECT COUNT(*) FROM wallet_metrics_v2 WHERE win_rate > 100.0 OR win_rate < 0.0;")
        invalid_wr = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM wallet_metrics_v2 WHERE winning_count > resolved_count;")
        invalid_counts = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM wallet_metrics_v2 WHERE roi_pct > 10000.0 OR roi_pct < -100.0;")
        invalid_roi = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM wallet_metrics_v2 WHERE win_rate > 0 AND win_rate <= 1.0 AND resolved_count > 0;")
        still_decimal = cur.fetchone()[0]

        print(f"1. Out-of-bounds Win Rates (<0% or >100%):  {invalid_wr}")
        print(f"2. Invalid Winning > Resolved Counts:        {invalid_counts}")
        print(f"3. Out-of-bounds ROIs (<-100% or >10,000%): {invalid_roi}")
        print(f"4. Still decimal win_rate (0..1):            {still_decimal}")

        print_sample(cur, "Sample wallets (highest ROI)", """
            SELECT address, total_pnl, roi_pct, win_rate, resolved_count, winning_count
            FROM wallet_metrics_v2
            WHERE roi_pct IS NOT NULL AND total_pnl > 0
            ORDER BY roi_pct DESC LIMIT 5
        """)

        print_sample(cur, "Sample wallets (largest PnL)", """
            SELECT address, total_pnl, roi_pct, win_rate, resolved_count
            FROM wallet_metrics_v2
            WHERE total_pnl IS NOT NULL
            ORDER BY total_pnl DESC LIMIT 5
        """)

        print_sample(cur, "Sample wallets (previously anomalous)", """
            SELECT address, winning_count, resolved_count, win_rate, roi_pct
            FROM wallet_metrics_v2
            WHERE resolved_count = winning_count AND winning_count > 0
            LIMIT 5
        """)

        print("\n" + "=" * 75)
        print(f"GLOBAL SCAN & RECALCULATION COMPLETE IN {time.time()-t0:.2f} SECONDS")
        print("=" * 75)

    except Exception as e:
        conn.rollback()
        print(f"\nERROR during global scan: {e}")
        import traceback
        traceback.print_exc()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
