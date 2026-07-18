import asyncio
import httpx
import logging
import os
import json
from datetime import datetime, timezone
from dotenv import load_dotenv
import asyncpg
from statsbombpy import sb

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def get_db_pool():
    return await asyncpg.create_pool(
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgres"),
        database=os.getenv("DB_NAME", "polymarket_clone"),
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
    )

async def seed_statsbomb_data(pool):
    """Seeds database with free historical statsbomb data (e.g., FIFA World Cup 2022)."""
    logger.info("Fetching free competitions from StatsBomb...")
    try:
        # 43 = FIFA World Cup, 106 = 2022 season
        matches = sb.matches(competition_id=43, season_id=106)
        logger.info(f"Fetched {len(matches)} World Cup matches from StatsBomb")
        
        async with pool.acquire() as conn:
            for _, match in matches.iterrows():  # type: ignore
                fixture_id = f"statsbomb_{match['match_id']}"
                home_team = match['home_team']
                away_team = match['away_team']
                
                # StatsBomb provides match_date as string "YYYY-MM-DD" and match_time "HH:MM:SS"
                date_str = f"{match['match_date']}T{match.get('match_time', '00:00:00.000')}"
                try:
                    match_date = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=timezone.utc)
                except ValueError:
                    match_date = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                
                status = "post" # Historical data is completed
                
                query = """
                INSERT INTO fixtures (fixture_id, sport, league, team_home, team_away, match_date, status, last_updated)
                VALUES ($1, 'Soccer', 'FIFA World Cup 2022', $2, $3, $4, $5, NOW())
                ON CONFLICT (fixture_id) DO NOTHING;
                """
                await conn.execute(query, fixture_id, home_team, away_team, match_date, status)
        logger.info("Successfully seeded StatsBomb historical matches!")
    except Exception as e:
        logger.error(f"Failed to seed StatsBomb data: {e}")

async def seed_openfootball_data(pool):
    """Seeds database with historical matches from openfootball/football.json (EPL 23/24)."""
    url = "https://raw.githubusercontent.com/openfootball/football.json/master/2023-24/en.1.json"
    logger.info("Fetching historical EPL data from openfootball...")
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
            matches = data.get("matches", [])
            
            logger.info(f"Fetched {len(matches)} historical EPL matches from openfootball")
            
            async with pool.acquire() as conn:
                for idx, match in enumerate(matches):
                    fixture_id = f"openfootball_epl2324_{idx}"
                    home_team = match.get("team1")
                    away_team = match.get("team2")
                    
                    date_str = match.get("date")
                    match_date = datetime.now(timezone.utc)
                    if date_str:
                        match_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                        
                    status = "post"
                    
                    query = """
                    INSERT INTO fixtures (fixture_id, sport, league, team_home, team_away, match_date, status, last_updated)
                    VALUES ($1, 'Soccer', 'EPL 23/24', $2, $3, $4, $5, NOW())
                    ON CONFLICT (fixture_id) DO NOTHING;
                    """
                    await conn.execute(query, fixture_id, home_team, away_team, match_date, status)
            logger.info("Successfully seeded openfootball historical matches!")
        except Exception as e:
            logger.error(f"Failed to fetch openfootball data: {e}")

async def main():
    logger.info("Starting historical soccer seeder...")
    pool = await get_db_pool()
    await seed_statsbomb_data(pool)
    await seed_openfootball_data(pool)
    await pool.close()
    logger.info("Seeding complete.")

if __name__ == "__main__":
    asyncio.run(main())
