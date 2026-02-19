"""
Historical Seed Data Loader
Loads structured historical geopolitical data into Neo4j.

Usage:
    python scripts/seed_historical.py --acled acled_global.csv --gdelt gdelt.csv

Data sources (all free/open):
  - ACLED: https://acleddata.com/download/
  - GDELT: https://api.gdeltproject.org (or BigQuery)
  - UN Sanctions XML: https://scsanctions.un.org/resources/xml/en/consolidated.xml
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import logging
import sys
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from models import Actor, Territory, GeoEvent, Relation
from graph.neo4j_client import get_neo4j_client
from graph.delta_writer import DeltaGraphWriter

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def load_acled(filepath: str, writer: DeltaGraphWriter, limit: int = 100_000):
    """Load ACLED conflict events into the graph."""
    logger.info(f"Loading ACLED data from {filepath}...")
    count = 0
    with open(filepath, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if count >= limit:
                break
            try:
                # Parse actors
                for actor_field in ("actor1", "actor2", "assoc_actor_1", "assoc_actor_2"):
                    actor_name = row.get(actor_field, "").strip()
                    if actor_name and len(actor_name) > 2:
                        actor = Actor(
                            id=hashlib.md5(actor_name.lower().encode()).hexdigest()[:12],
                            name=actor_name,
                            actor_type=_classify_actor_type(actor_name),
                            aliases=[actor_name],
                            country=row.get("country", ""),
                            confidence=0.9,
                        )
                        writer.neo4j.upsert_actor(actor)

                # Parse territory
                admin1 = row.get("admin1", "")
                country = row.get("country", "")
                if country:
                    territory = Territory(
                        id=hashlib.md5(f"{country}:{admin1}".lower().encode()).hexdigest()[:12],
                        name=admin1 or country,
                        country=country,
                    )
                    writer.neo4j.upsert_territory(territory)

                # Parse event
                date_str = row.get("event_date", "")
                try:
                    date = datetime.strptime(date_str, "%d %B %Y")
                except Exception:
                    try:
                        date = datetime.strptime(date_str, "%Y-%m-%d")
                    except Exception:
                        date = datetime.utcnow()

                fatalities = int(row.get("fatalities", 0) or 0)
                intensity = min(10.0, 1.0 + fatalities / 100.0)

                event = GeoEvent(
                    id=row.get("data_id") or hashlib.sha256(str(row).encode()).hexdigest()[:16],
                    event_type=_acled_event_type(row.get("event_type", "")),
                    description=row.get("notes", "")[:500],
                    actors=[
                        hashlib.md5(row.get("actor1", "").lower().encode()).hexdigest()[:12]
                    ],
                    date_start=date,
                    intensity=intensity,
                    military_intensity=intensity if "Battle" in row.get("event_type", "") else 1.0,
                    confidence=0.95,
                )
                writer.neo4j.upsert_event(event)
                count += 1

                if count % 5000 == 0:
                    logger.info(f"  ACLED: {count} events loaded...")

            except Exception as e:
                logger.debug(f"Row skip: {e}")

    logger.info(f"ACLED loading complete: {count} events.")


def load_un_sanctions(filepath: str, writer: DeltaGraphWriter):
    """Load UN Consolidated Sanctions List."""
    logger.info(f"Loading UN Sanctions from {filepath}...")
    tree = ET.parse(filepath)
    root = tree.getroot()
    count = 0

    ns = {"un": "https://scsanctions.un.org/core"}

    for individual in root.findall(".//INDIVIDUAL", ns):
        try:
            first_name = individual.findtext("FIRST_NAME", "", ns)
            last_name = individual.findtext("SECOND_NAME", "", ns)
            name = f"{first_name} {last_name}".strip()
            if not name:
                continue

            actor = Actor(
                id="un_" + hashlib.md5(name.lower().encode()).hexdigest()[:10],
                name=name,
                actor_type="sanctioned individual",
                aliases=[name],
                confidence=1.0,
            )
            writer.neo4j.upsert_actor(actor)
            count += 1
        except Exception as e:
            logger.debug(f"UN individual parse error: {e}")

    for entity in root.findall(".//ENTITY", ns):
        try:
            name = entity.findtext("FIRST_NAME", "", ns)
            if not name:
                continue
            actor = Actor(
                id="un_" + hashlib.md5(name.lower().encode()).hexdigest()[:10],
                name=name,
                actor_type="sanctioned entity",
                aliases=[name],
                confidence=1.0,
            )
            writer.neo4j.upsert_actor(actor)
            count += 1
        except Exception as e:
            logger.debug(f"UN entity parse error: {e}")

    logger.info(f"UN Sanctions loading complete: {count} entries.")


def load_gdelt_csv(filepath: str, writer: DeltaGraphWriter, limit: int = 50_000):
    """Load GDELT event CSV (simplified schema)."""
    logger.info(f"Loading GDELT data from {filepath}...")
    count = 0
    with open(filepath, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            if count >= limit:
                break
            try:
                # GDELT schema: GLOBALEVENTID, Day, Actor1Name, Actor2Name, GoldsteinScale
                actor1 = row.get("Actor1Name", "").strip()
                actor2 = row.get("Actor2Name", "").strip()

                for name in [actor1, actor2]:
                    if name and len(name) > 2:
                        actor = Actor(
                            id=hashlib.md5(name.lower().encode()).hexdigest()[:12],
                            name=name,
                            actor_type=_classify_actor_type(name),
                            confidence=0.7,
                        )
                        writer.neo4j.upsert_actor(actor)

                goldstein = float(row.get("GoldsteinScale", 0) or 0)
                # Goldstein scale: -10 (most violent) to +10 (most cooperative)
                intensity = max(1.0, min(10.0, (10 - goldstein) / 2))

                day_str = row.get("Day", "")
                try:
                    date = datetime.strptime(str(day_str)[:8], "%Y%m%d")
                except Exception:
                    date = datetime.utcnow()

                event_id = row.get("GLOBALEVENTID") or hashlib.sha256(str(row).encode()).hexdigest()[:16]
                event = GeoEvent(
                    id=f"gdelt_{event_id}",
                    event_type="GDELT_EVENT",
                    description=f"{actor1} → {actor2} [{row.get('EventCode', '')}]",
                    actors=[
                        hashlib.md5(actor1.lower().encode()).hexdigest()[:12],
                    ] if actor1 else [],
                    date_start=date,
                    intensity=intensity,
                    confidence=0.7,
                )
                writer.neo4j.upsert_event(event)
                count += 1

                if count % 10000 == 0:
                    logger.info(f"  GDELT: {count} events loaded...")

            except Exception as e:
                logger.debug(f"GDELT row skip: {e}")

    logger.info(f"GDELT loading complete: {count} events.")


def seed_static_actors(writer: DeltaGraphWriter):
    """Seed the graph with well-known state and non-state actors."""
    STATIC_ACTORS = [
        # Major state actors
        Actor(id="Q30",  name="United States", actor_type="state actor",
              aliases=["USA", "US", "Washington", "America"], country="USA", confidence=1.0),
        Actor(id="Q159", name="Russia", actor_type="state actor",
              aliases=["Russian Federation", "Kremlin", "Moscow"], country="Russia", confidence=1.0),
        Actor(id="Q794", name="Iran", actor_type="state actor",
              aliases=["Islamic Republic of Iran", "Tehran"], country="Iran", confidence=1.0),
        Actor(id="Q148", name="China", actor_type="state actor",
              aliases=["PRC", "Beijing", "People's Republic of China"], country="China", confidence=1.0),
        Actor(id="Q212", name="Ukraine", actor_type="state actor",
              aliases=["Kyiv"], country="Ukraine", confidence=1.0),
        Actor(id="Q36",  name="Poland", actor_type="state actor",
              aliases=["Warsaw"], country="Poland", confidence=1.0),
        Actor(id="Q858", name="Syria", actor_type="state actor",
              aliases=["Damascus", "Assad regime"], country="Syria", confidence=1.0),
        Actor(id="Q79",  name="Egypt", actor_type="state actor",
              aliases=["Cairo"], country="Egypt", confidence=1.0),
        Actor(id="Q801", name="Israel", actor_type="state actor",
              aliases=["Tel Aviv", "Jerusalem", "IDF"], country="Israel", confidence=1.0),
        Actor(id="Q1028", name="Morocco", actor_type="state actor",
              aliases=["Rabat"], country="Morocco", confidence=1.0),
        # International organizations
        Actor(id="Q1065", name="United Nations", actor_type="international organization",
              aliases=["UN", "UN Security Council", "UNSC"], confidence=1.0),
        Actor(id="Q8908", name="NATO", actor_type="international organization",
              aliases=["North Atlantic Treaty Organization"], confidence=1.0),
        # Non-state armed groups
        Actor(id="Q1520118", name="Islamic State", actor_type="non-state armed group",
              aliases=["ISIS", "ISIL", "Daesh", "IS"], confidence=1.0),
        Actor(id="Q134366", name="Hezbollah", actor_type="non-state armed group",
              aliases=["Hizballah", "Party of God"], country="Lebanon", confidence=1.0),
        Actor(id="Q43585",  name="Hamas", actor_type="non-state armed group",
              aliases=["Harakat al-Muqawamah al-Islamiyyah"], country="Palestine", confidence=1.0),
        Actor(id="Q216439", name="Wagner Group", actor_type="non-state armed group",
              aliases=["PMC Wagner", "Wagner PMC"], country="Russia", confidence=1.0),
    ]

    logger.info(f"Seeding {len(STATIC_ACTORS)} static actors...")
    for actor in STATIC_ACTORS:
        writer.neo4j.upsert_actor(actor)

    # Seed some known relations
    STATIC_RELATIONS = [
        Relation(subject_id="Q134366", relation_type="PROXY_OF", object_id="Q794",
                 valid_from=datetime(1982, 1, 1), confidence=0.95, source="historical_record"),
        Relation(subject_id="Q43585",  relation_type="FUNDS",    object_id="Q794",
                 valid_from=datetime(2000, 1, 1), confidence=0.75, source="historical_record"),
        Relation(subject_id="Q794",    relation_type="ALLIED_WITH", object_id="Q159",
                 valid_from=datetime(2015, 1, 1), confidence=0.85, source="historical_record"),
        Relation(subject_id="Q30",     relation_type="SANCTIONS",   object_id="Q794",
                 valid_from=datetime(1979, 1, 1), confidence=1.0,  source="historical_record"),
    ]

    logger.info(f"Seeding {len(STATIC_RELATIONS)} static relations...")
    for rel in STATIC_RELATIONS:
        writer.neo4j.upsert_relation(rel)

    logger.info("Static data seeding complete.")


def _classify_actor_type(name: str) -> str:
    name_lower = name.lower()
    if any(w in name_lower for w in ("government", "ministry", "military", "army", "force")):
        return "state actor"
    if any(w in name_lower for w in ("militia", "rebel", "insurgent", "terrorist", "jihadist")):
        return "non-state armed group"
    if any(w in name_lower for w in ("party", "faction", "movement", "coalition")):
        return "political faction"
    return "state actor"


def _acled_event_type(acled_type: str) -> str:
    mapping = {
        "Battles": "ARMED_CONFLICT",
        "Explosions/Remote violence": "ARMED_CONFLICT",
        "Violence against civilians": "ARMED_CONFLICT",
        "Riots": "POLITICAL_CRISIS",
        "Protests": "POLITICAL_CRISIS",
        "Strategic developments": "DIPLOMATIC",
    }
    return mapping.get(acled_type, "CONFLICT_EVENT")


def main():
    parser = argparse.ArgumentParser(description="Seed Neo4j with historical geopolitical data")
    parser.add_argument("--acled", help="Path to ACLED CSV file")
    parser.add_argument("--gdelt", help="Path to GDELT CSV file")
    parser.add_argument("--un-sanctions", help="Path to UN Consolidated Sanctions XML")
    parser.add_argument("--limit", type=int, default=50000, help="Max events per source")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("GeoKG-RAG Historical Seed Loader")
    logger.info("=" * 60)

    neo4j = get_neo4j_client()
    if not neo4j.verify_connectivity():
        logger.error("Cannot connect to Neo4j. Please start Neo4j and check credentials.")
        sys.exit(1)

    neo4j.initialize_schema()
    writer = DeltaGraphWriter(neo4j)

    # Always seed static actors
    seed_static_actors(writer)

    if args.acled:
        load_acled(args.acled, writer, limit=args.limit)

    if args.gdelt:
        load_gdelt_csv(args.gdelt, writer, limit=args.limit)

    if args.un_sanctions:
        load_un_sanctions(args.un_sanctions, writer)

    # Final stats
    try:
        for label in ("Actor", "Territory", "GeoEvent"):
            result = neo4j.run(f"MATCH (n:{label}) RETURN count(n) AS count")
            count = result[0]["count"] if result else 0
            logger.info(f"  {label}: {count:,} nodes")
    except Exception as e:
        logger.warning(f"Could not fetch final stats: {e}")

    logger.info("Seed loading complete! ✅")


if __name__ == "__main__":
    main()
