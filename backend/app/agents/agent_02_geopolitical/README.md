# 🌍 GeoKG-RAG — Geopolitical Knowledge Graph RAG Agent

> **Autonomous intelligence system** that ingests geopolitical news continuously, builds a structured knowledge graph, and answers complex analytical queries about conflicts, hidden actor relationships, and historical patterns — powered by **Google Gemini 2.5 Flash**.

---

## What This System Does

Unlike standard RAG (which retrieves text chunks), **GeoKG-RAG retrieves structured relational context** — entities, relationships across time, proxy chains, conflict genealogies — then combines this with raw news passages to produce grounded intelligence reports.

| Standard RAG | GeoKG-RAG |
|---|---|
| Retrieves text chunks | Retrieves entity-relation subgraphs |
| No relationship memory | Full temporal graph of who-does-what-since-when |
| Cannot detect patterns | Matches conflict signatures against 70+ years of history |
| Rebuilt from scratch | Incremental UPSERT — history never lost |
| Single-perspective | Multi-perspective: US/Russia/local framing captured |

---

## What You Need (Prerequisites)

### Required — Must have these before starting:

| Requirement | What it is | Get it here |
|---|---|---|
| **Python 3.10+** | Programming runtime | https://python.org |
| **Docker Desktop** | Runs Neo4j + Weaviate databases | https://docker.com |
| **Gemini API Key** | Powers all AI reasoning + embeddings | https://aistudio.google.com/app/apikey |

### Optional — For full production features:

| Requirement | What it is | Get it here |
|---|---|---|
| ACLED data | Historical conflict events (1997–present) | https://acleddata.com/download/ (free academic registration) |
| UN Sanctions XML | Sanctioned actors list | https://scsanctions.un.org/resources/xml/en/consolidated.xml (free) |
| GDELT BigQuery | Large-scale historical events | https://cloud.google.com/bigquery (free tier available) |

---

## Step-by-Step Setup

### Step 1 — Get Your Gemini API Key

1. Go to **https://aistudio.google.com/app/apikey**
2. Sign in with a Google account
3. Click **"Create API key"**
4. Copy the key — it starts with `AIza...`

> **Cost:** Gemini 2.5 Flash has a generous free tier — 1,500 requests/day at no cost. More than enough for development and moderate use.

---

### Step 2 — Download and Install

```bash
# Unzip the project (if you downloaded the zip)
unzip geokg-rag.zip
cd geokg-rag

# Install all Python dependencies
pip install -r requirements.txt

# Download the spaCy language model for NLP
python -m spacy download en_core_web_sm
```

> **Note:** If you see "ERROR: Could not build wheels for..." errors on first install, run:
> `pip install --upgrade pip setuptools wheel` then retry.

---

### Step 3 — Configure Your Environment

```bash
# Copy the example config
cp .env.example .env

# Open .env in any text editor and fill in your keys
nano .env   # or: notepad .env  (Windows)  or: open .env (Mac)
```

**Minimum required settings in `.env`:**
```bash
# The ONE key you must set:
GEMINI_API_KEY=AIza...YOUR_KEY_HERE...

# Neo4j password (any password you choose):
NEO4J_PASSWORD=choose_a_password_here
```

Everything else can stay at the default values.

---

### Step 4 — Start the Databases

```bash
# Start Neo4j (Knowledge Graph) and Weaviate (Vector Store)
docker compose up -d neo4j weaviate

# Check they started successfully (wait ~30 seconds first)
docker compose ps
```

You should see both `geokg_neo4j` and `geokg_weaviate` showing status `healthy`.

**Verify Neo4j is running:** Open http://localhost:7474 in your browser. Log in with username `neo4j` and the password you set in `.env`.

---

### Step 5 — Test Your Gemini Connection

```bash
python scripts/test_gemini.py
```

Expected output:
```
✅ Chat: GEMINI_OK
✅ Classification: 'Who funds the militia...' → 'proxy'
✅ Embedding dim: 768
✅ Extracted 2 relations
```

If this passes, everything is working.

---

### Step 6 — Seed the Knowledge Graph

This loads built-in actors, territories, and known relationships into the graph.

```bash
# Quick start — loads 16 built-in actors + known relations (takes ~5 seconds)
python main.py seed --static-only
```

**Optional: Load historical conflict data (recommended for richer answers):**

```bash
# Download ACLED data (free, requires registration at acleddata.com)
# Then load it:
python main.py seed --acled path/to/acled_global.csv --limit 100000

# Download UN Sanctions XML:
# wget https://scsanctions.un.org/resources/xml/en/consolidated.xml
python main.py seed --un-sanctions consolidated.xml
```

---

### Step 7 — Run Your First Query

```bash
python main.py query "Who is really funding the armed group in Eastern Ukraine?"
```

```bash
python main.py query "Is the Middle East approaching a conflict threshold?"
```

```bash
python main.py query "What historical patterns does the current Iran situation match?"
```

---

### Step 8 — Start the API Server (Optional)

```bash
python main.py server
```

Open http://localhost:8000/docs for the interactive API documentation.

---

## All Commands

### Intelligence Queries

```bash
# Ask an intelligence question
python main.py query "Your question here"

# With verbose logging (shows processing steps)
python main.py query "Your question here" --verbose
```

### API Server

```bash
# Start API server
python main.py server

# Custom port
python main.py server --port 9000

# With auto-reload (development mode)
python main.py server --reload
```

### News Ingestion

```bash
# Ingest last 1 hour of geopolitical news from GDELT
python main.py ingest

# Ingest last 6 hours
python main.py ingest --hours-back 6

# Run continuously every 15 minutes
python main.py ingest --loop --interval 15
```

### Pattern Scanning

```bash
# Scan all regions for conflict signatures once
python main.py scan

# Scan specific region
python main.py scan --region "Middle East"

# Run hourly in loop
python main.py scan --loop
```

### Data Seeding

```bash
# Seed only built-in actors/relations
python main.py seed --static-only

# Full seed with all available data
python main.py seed --acled data/acled.csv --gdelt data/gdelt.csv --un-sanctions data/consolidated.xml

# With limit (for testing)
python main.py seed --acled data/acled.csv --limit 10000
```

### GNN Training (Proxy Inference)

```bash
# Train the RotatE model and infer hidden proxy relationships
python main.py train-gnn

# Custom settings
python main.py train-gnn --epochs 200 --confidence 0.7
```

---

## REST API Reference

Once the server is running at http://localhost:8000:

### Submit Intelligence Query
```bash
POST /query
Content-Type: application/json

{
  "query": "Who funds the militia in Region X?",
  "region": "Middle East",       # optional
  "depth": 2,                    # graph traversal depth (1-4)
  "include_historical": true
}
```

### Get Active Pattern Alerts
```bash
GET /alerts
GET /alerts?region=Middle+East
GET /alerts?level=ALERT
```

### Actor Network Graph
```bash
GET /graph/actor/{actor_id}/network?depth=2
GET /graph/actor/Q794/network       # Iran's network
GET /graph/actor/Q159/network       # Russia's network
```

### Proxy Chain Mapping
```bash
GET /graph/actor/{actor_id}/proxy-chains
GET /graph/actor/Q1520118/proxy-chains   # ISIS proxy chains
```

### Conflict Timeline
```bash
GET /graph/conflict/{region}/timeline?days_back=365
GET /graph/conflict/Syria/timeline
```

### Search Actors
```bash
GET /graph/actor/search?q=Hezbollah
GET /graph/actor/search?q=Iran&limit=20
```

### Trigger Ingestion
```bash
POST /ingest/trigger
{"hours_back": 2}
```

### System Health
```bash
GET /health       # Check all services
GET /graph/stats  # Count nodes + edges
GET /metrics      # Prometheus metrics
```

---

## Query Types

The agent automatically detects what kind of analysis you need:

| Query Type | What it does | Example query |
|---|---|---|
| **proxy** | Maps hidden patron-proxy relationships with confidence scoring | "Who is really behind the militia in X?" |
| **genealogy** | Traces conflict causal chains back through history | "What caused the conflict in Y?" |
| **pattern** | Detects conflict signature matches and escalation risk | "Is Region Z approaching a threshold?" |
| **leverage** | Maps economic/military/energy dependencies | "What leverage does A have over B?" |
| **intent** | Decodes what actors are NOT saying | "What signal is Iran sending?" |
| **general** | Full analytical synthesis | Any other question |

---

## Project Structure

```
geokg-rag/
│
├── main.py                    ← CLI entry point (start here)
├── config.py                  ← All configuration (reads from .env)
├── models.py                  ← Data models (Actor, GeoEvent, Relation...)
├── gemini_client.py           ← ★ Gemini 2.5 Flash client (LLM + embeddings)
├── requirements.txt           ← All Python dependencies
├── .env.example               ← Copy this to .env and fill in your keys
├── docker-compose.yml         ← Infrastructure: Neo4j + Weaviate + Kafka + Monitoring
├── Dockerfile                 ← Container build for the API
│
├── agent/
│   ├── geokg_agent.py         ← LangGraph 9-node workflow (main orchestration)
│   └── prompts.py             ← System prompt + 5 query-specific sub-prompts
│
├── api/
│   └── main.py                ← FastAPI REST API (all endpoints)
│
├── extraction/
│   └── pipeline.py            ← GLiNER NER → Gemini RE → Event classification
│
├── graph/
│   ├── neo4j_client.py        ← Neo4j connection, schema, all Cypher queries
│   └── delta_writer.py        ← Incremental UPSERT writer (never rebuilds)
│
├── intelligence/
│   ├── pattern_scanner.py     ← Conflict signature detection (3 signatures)
│   └── proxy_detector.py      ← PyKEEN RotatE GNN for hidden relation inference
│
├── retrieval/
│   ├── hybrid.py              ← Parallel graph + vector retrieval + fusion
│   └── weaviate_client.py     ← Weaviate vector store (Gemini embeddings)
│
├── sources/
│   └── gdelt_connector.py     ← GDELT news ingestion + dedup + bias detection
│
├── scripts/
│   ├── test_gemini.py         ← ★ Run this first to verify your setup
│   ├── seed_historical.py     ← ACLED/GDELT/UN data loader
│   ├── run_ingestion.py       ← Scheduled ingestion runner
│   └── run_pattern_scan.py    ← Pattern scan runner
│
└── monitoring/
    └── prometheus.yml         ← Prometheus scrape config
```

---

## Technology Stack

| Component | Technology | Purpose |
|---|---|---|
| **LLM & Embeddings** | **Google Gemini 2.5 Flash** | All reasoning, classification, extraction, vectors |
| Knowledge Graph | Neo4j 5.x | Temporal entity-relation store |
| Vector Store | Weaviate | Semantic article search |
| Message Queue | Apache Kafka | Real-time news streaming (optional) |
| NER | GLiNER (zero-shot) | Named entity recognition |
| Agent Framework | LangGraph | Stateful multi-step workflow |
| API | FastAPI + Uvicorn | REST interface |
| Monitoring | Prometheus + Grafana | Metrics dashboard |

---

## How Gemini 2.5 Flash Is Used

The system uses Gemini for **five distinct tasks**, all through `gemini_client.py`:

1. **Query Classification** (`classify_query`) — Fast routing: "is this a proxy query or a pattern query?"
2. **Relation Extraction** (`extract_relations`) — Extracts structured triples from news articles
3. **Intelligence Report** (`generate_report`) — Full analytical synthesis with the system prompt
4. **Graph Feedback** (`extract_relations_from_report`) — Mines new facts from generated reports
5. **Embeddings** (`embed_text`, `embed_query`) — Converts text to 768-dim vectors for semantic search

---

## Conflict Signatures Detected

The pattern scanner runs hourly and checks three signatures:

### PRE_INVASION_PATTERN
Fires when 3+ of these indicators are active:
- `troop_buildup` — military movements near a territory in last 7 days
- `rhetoric_spike` — escalation language intensity > 7 in last 14 days
- `economic_decouple` — trade declining between adversaries
- `proxy_activated` — proxy forces engaged against target
- `disinfo_campaign` — disinformation targeting detected in last 30 days
- `historical_grievance` — high-intensity grievance narrative active

Historical match: Russia-Ukraine Nov 2021–Feb 2022 | Estimated timeline: 3–8 weeks

### PROXY_WAR_FORMATION
Fires when 2+ of these are active:
- `arms_flow` — weapons supply to actors in region
- `funding_detected` — financial flows above confidence threshold
- `rhetoric_alignment` — patron-proxy messaging alignment
- `external_bases` — foreign actors controlling territory in region

Historical match: Syria 2012, Angola 1975

### COUP_PRECURSOR
Fires when 2+ of these are active:
- `military_faction` — armed faction opposing government
- `economic_collapse` — high-intensity economic crisis events
- `protest_spike` — surge in political crisis events

Historical match: Mali 2021, Myanmar 2021, Sudan 2019

---

## Graph Schema

### Node Types
- `Actor` — states, non-state groups, leaders, organizations
- `Territory` — countries, regions, disputed territories
- `GeoEvent` — conflict events, diplomatic events, covert operations
- `Resource` — strategic resources
- `Article` — source articles
- `PatternAlert` — historical alert records

### Relation Types
`ALLIED_WITH` · `HOSTILE_TO` · `PROXY_OF` · `FUNDS` · `SUPPLIES_ARMS_TO` · `CONTROLS` · `DISPUTES` · `TRADE_PARTNER` · `SANCTIONS` · `RHETORIC_ESCALATION` · `TROOP_MOVEMENT` · `DISINFORMATION_TARGET` · `HISTORICAL_GRIEVANCE` · `CAUSED` · `TRIGGERED_BY` · `IN_CONFLICT_WITH`

**All edges have:** `valid_from`, `valid_to` (temporal), `confidence`, `source_count`, `inferred` (GNN-derived)

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `GEMINI_API_KEY` | **YES** | — | Your Google Gemini API key |
| `NEO4J_URI` | Yes | `bolt://localhost:7687` | Neo4j connection URI |
| `NEO4J_USER` | Yes | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | Yes | `yourpassword` | Neo4j password |
| `WEAVIATE_URL` | Yes | `http://localhost:8080` | Weaviate URL |
| `WEAVIATE_KEY` | No | `` | Weaviate API key (cloud only) |
| `REASONING_MODEL` | No | `gemini-2.5-flash` | Model for report generation |
| `ROUTING_MODEL` | No | `gemini-2.5-flash` | Model for fast classification |
| `EMBEDDING_MODEL` | No | `models/text-embedding-004` | Gemini embedding model |
| `EMBEDDING_DIM` | No | `768` | Embedding dimensions |
| `LOG_LEVEL` | No | `INFO` | Logging verbosity |
| `API_PORT` | No | `8000` | API server port |

---

## Troubleshooting

### "GEMINI_API_KEY not set" error
→ Make sure you created a `.env` file (not just edited `.env.example`)
→ Run: `cp .env.example .env` then edit `.env`

### "Cannot connect to Neo4j"
→ Make sure Docker is running: `docker ps`
→ Start databases: `docker compose up -d neo4j weaviate`
→ Wait 30 seconds for Neo4j to fully start

### "GLiNER model not found"
→ This is fine for testing — the system falls back to spaCy NER automatically
→ GLiNER downloads on first use (~500MB), which may take a minute

### "Weaviate collection not found"
→ The schema is created automatically on first startup
→ Run: `python main.py server` once, then Ctrl+C, and retry your command

### Gemini rate limit errors
→ The free tier allows 1,500 requests/day and 15 requests/minute
→ Add `INGESTION_INTERVAL_MINUTES=5` to `.env` to slow down ingestion

### Neo4j vector index fails
→ Requires Neo4j 5.x — check version: `docker exec geokg_neo4j neo4j --version`
→ If on Neo4j 4.x, the embedding features won't work but the rest will

---

## Production Notes

- **Data sovereignty**: Set `REASONING_MODEL=gemini-2.5-flash` and run with VPN for sensitive data; for fully air-gapped, swap `gemini_client.py` for a local Ollama/vLLM wrapper
- **Scale**: Neo4j AuraDB handles billions of edges; the free tier is enough for development
- **Kafka**: Enable for >500 articles/day ingestion — the default HTTP polling works fine for moderate use
- **Airflow**: Use the `scripts/` runners as task definitions in production Airflow DAGs
