import asyncio
import asyncpg
import os


async def main():
    pool = await asyncpg.create_pool(
        os.environ.get("DATABASE_URL", "postgresql://poly_user:poly_password@localhost:5432/poly_db"),
        min_size=1, max_size=1
    )
    async with pool.acquire() as conn:
        # Clear usernames that look like addresses
        r = await conn.execute(
            "UPDATE tracked_wallets SET username = NULL WHERE username LIKE '0x%' AND length(username) > 10"
        )
        print(f"Cleaned: {r}")
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM tracked_wallets WHERE username IS NOT NULL AND username != ''"
        )
        print(f"Wallets with valid usernames remaining: {count}")
    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
