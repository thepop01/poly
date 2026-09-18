"""Repair Type-A wallets: stored metrics == eligible ledger minus redeemable rows.

For each address: re-check counts (skip if already fixed), run the canonical
3-stage compute (core + category + windows), re-verify. Idempotent/resumable.
Usage: python repair_typeA.py [--concurrency 64] [--limit 0]
Progress: logs/repair_typeA.log ; state: backtest_cache/repair_typeA_progress.jsonl
"""
import argparse, asyncio, json, logging, os, sys, time
import asyncpg
from dotenv import load_dotenv

sys.path.insert(0, "D:\\project\\poly")
load_dotenv()
from src.workers.positions_metrics_compute import compute_metrics_for_wallet

DB_URL = os.getenv("DATABASE_URL", "postgresql://poly_user:poly_password@127.0.0.1:5432/poly_db").replace("localhost", "127.0.0.1")
LIST = "C:\\Users\\shubh\\AppData\\Local\\Temp\\opencode\\typeA_wallets.json"
PROG = "D:\\project\\poly\\backtest_cache\\repair_typeA_progress.jsonl"

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s",
                    datefmt="%H:%M:%S", handlers=[logging.FileHandler("D:\\project\\poly\\logs\\repair_typeA.log"), logging.StreamHandler()])
log = logging.getLogger("repair_typeA")

async def ledger_counts(conn, addr):
    return await conn.fetchrow("""SELECT COUNT(*) n,
        COUNT(*) FILTER (WHERE realized_pnl > 0) AS w,
        COALESCE(SUM(realized_pnl),0) AS p
        FROM wallet_closed_positions_v2 WHERE address=$1 AND COALESCE(metrics_eligible,TRUE)""", addr)

async def stored_counts(conn, addr):
    return await conn.fetchrow("SELECT resolved_count r, winning_count w, total_pnl p FROM wallet_metrics_v2 WHERE address=$1", addr)

async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--concurrency", type=int, default=64)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    addrs = json.load(open(LIST))
    if a.limit:
        addrs = addrs[:a.limit]
    done_ids = set()
    if os.path.exists(PROG):
        with open(PROG) as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                    if d.get("status") in ("fixed", "skipped-ok"):
                        done_ids.add(d["address"])
                except Exception:
                    pass
    todo = [x for x in addrs if x not in done_ids]
    log.info(f"TypeA list={len(addrs)} already_done={len(done_ids)} todo={len(todo)}")
    pool = await asyncpg.create_pool(DB_URL, min_size=8, max_size=a.concurrency + 10, timeout=60, command_timeout=900)
    # order small ledgers first
    async with pool.acquire() as conn:
        counts = await conn.fetch("""SELECT m.address, COUNT(cl.*) AS n FROM wallet_metrics_v2 m
            LEFT JOIN wallet_closed_positions_v2 cl ON cl.address=m.address AND COALESCE(cl.metrics_eligible,TRUE)
            WHERE m.address = ANY($1) GROUP BY m.address""", todo)
    order = {r["address"]: r["n"] for r in counts}
    todo.sort(key=lambda x: order.get(x, 0))
    sem = asyncio.Semaphore(a.concurrency)
    fixed = skipped = failed = 0
    t0 = time.time()
    fh = open(PROG, "a")

    async def one(addr):
        nonlocal fixed, skipped, failed
        async with sem:
            try:
                async with pool.acquire() as conn:
                    s = await stored_counts(conn, addr)
                    l = await ledger_counts(conn, addr)
                sp = float(s["p"]) if s and s["p"] is not None else None
                if s and s["r"] == l["n"] and s["w"] == l["w"] and sp is not None and abs(sp - float(l["p"])) <= 1.0:
                    skipped += 1
                    fh.write(json.dumps({"address": addr, "status": "skipped-ok"}) + "\n")
                    return
                async with pool.acquire() as conn:
                    await asyncio.wait_for(compute_metrics_for_wallet(conn, None, addr), timeout=600)
                async with pool.acquire() as conn:
                    s2 = await stored_counts(conn, addr)
                sp2 = float(s2["p"]) if s2 and s2["p"] is not None else None
                ok = s2 and s2["r"] == l["n"] and s2["w"] == l["w"] and sp2 is not None and abs(sp2 - float(l["p"])) <= 1.0
                if ok:
                    fixed += 1
                    fh.write(json.dumps({"address": addr, "status": "fixed"}) + "\n")
                else:
                    failed += 1
                    fh.write(json.dumps({"address": addr, "status": "verify-failed",
                                         "stored": [s2["r"], s2["w"], sp2], "ledger": [l["n"], l["w"], float(l["p"])]}) + "\n")
            except Exception as e:
                failed += 1
                fh.write(json.dumps({"address": addr, "status": "error", "err": str(e)[:200]}) + "\n")
            n = fixed + skipped + failed
            if n % 100 == 0 or n == len(todo):
                dt = time.time() - t0
                log.info(f"{n}/{len(todo)} fixed={fixed} skipped={skipped} failed={failed} ({n/dt:.1f}/s)")
                fh.flush()

    await asyncio.gather(*[one(x) for x in todo])
    fh.close()
    log.info(f"DONE todo={len(todo)} fixed={fixed} skipped={skipped} failed={failed} in {(time.time()-t0)/60:.1f} min")
    await pool.close()

if __name__ == "__main__":
    asyncio.run(main())
