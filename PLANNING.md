# SentinelAI — Project Planning

**Multi-Agent Geopolitical Market Intelligence Platform**

---

## 📋 Executive Summary

SentinelAI provides geopolitical and macroeconomic risk analysis for financial assets using 7 specialized AI agents.

**Target Assets:** Gold, Oil, S&P 500, Bitcoin, Ethereum

**Core Goals:**
- Zero infrastructure cost (free LLM tiers: Groq, OpenRouter, together.ai)
- Full source attribution
- 7 specialized agents via LangGraph
- 5 user roles with RBAC
- < 30s response time, < $0.01 per analysis

---

## 🏗️ System Architecture

### Presentation Layer
- **Frontend:** React 18 + Vite + Tailwind CSS
- **Visualization:** Recharts + D3.js
- **Auth:** Auth0 (OAuth2 + JWT)

### API Gateway
- **Backend:** FastAPI with async endpoints
- **Queue:** Celery + Redis
- **Features:** Pydantic v2 validation, rate limiting

### 7 AI Agents (LangGraph)

| Agent | Model | Provider | Purpose |
|-------|-------|----------|---------|
| **01 Routing** | Mistral 7B | Groq | Parse query, manage pipeline |
| **02 Geopolitical** | DeepSeek-V3 | OpenRouter | GDELT events, FRED data |
| **03 Sentiment** | Qwen2.5-72B | together.ai | News clustering, signals |
| **04 Asset Analyst** | DeepSeek-R1 Distill | Groq | Per-asset modeling |
| **05 Quant & Risk** | DeepSeek-R1 Full | OpenRouter | Monte Carlo, GARCH |
| **06 Critic** | Llama 3.3 70B | Groq | Quality validation |
| **07 Synthesis** | Mistral Small 3 | Groq | Dashboard + PDF |

### Data & Persistence

- **MongoDB Atlas:** Users, sessions, query history
- **Qdrant:** News embeddings, semantic search
- **Redis:** Celery broker, cache, rate limits
- **AWS S3:** PDF archives

---

## 📊 Agent Pipeline Flow

**Query Example:** "Analyze geopolitical risks for Gold over the next 30 days"

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        USER QUERY SUBMISSION                                 │
│  "Analyze geopolitical risks for Gold over the next 30 days"               │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  AGENT 01: ROUTING & ORCHESTRATION                        [~0.5s]          │
├─────────────────────────────────────────────────────────────────────────────┤
│  • Parse query intent                                                       │
│  • Extract parameters: asset=Gold, timeframe=30d                           │
│  • Generate task graph for downstream agents                               │
│  • Validate with Pydantic schema                                           │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    PARALLEL INTELLIGENCE GATHERING                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                 │
                 ┌───────────────┼───────────────┐
                 │               │               │
                 ▼               ▼               ▼
        ┏━━━━━━━━━━━━━┓  ┏━━━━━━━━━━━━━┓  ┏━━━━━━━━━━━━━┓
        ┃   AGENT 02  ┃  ┃   AGENT 03  ┃  ┃   AGENT 04  ┃
        ┃ Geopolitical┃  ┃  Sentiment  ┃  ┃    Asset    ┃
        ┃   [~3-4s]   ┃  ┃   [~2-3s]   ┃  ┃  Analyst    ┃
        ┣━━━━━━━━━━━━━┫  ┣━━━━━━━━━━━━━┫  ┃   [~3-4s]   ┃
        ┃• GDELT      ┃  ┃• News feeds ┃  ┣━━━━━━━━━━━━━┫
        ┃• FRED data  ┃  ┃• Reddit WSB ┃  ┃• Gold model ┃
        ┃• Stability  ┃  ┃• Twitter    ┃  ┃• Price data ┃
        ┃  scores     ┃  ┃• Fear&Greed ┃  ┃• Patterns   ┃
        ┗━━━━━━━┳━━━━━┛  ┗━━━━━━┳━━━━━━┛  ┗━━━━━━┳━━━━━━┛
                │               │               │
                └───────────────┼───────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  AGENT 05: QUANT & RISK AGGREGATION                       [~5-7s]          │
├─────────────────────────────────────────────────────────────────────────────┤
│  • Aggregate signals from Agents 02-04                                     │
│  • Monte Carlo simulations (1000 iterations)                               │
│  • GARCH volatility modeling                                               │
│  • Correlation analysis                                                     │
│  • Probability-weighted scenario generation                                │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  AGENT 06: CRITIC & VERIFICATION (Quality Gate)           [~3-4s]          │
├─────────────────────────────────────────────────────────────────────────────┤
│  • Cross-validate internal consistency                                     │
│  • Verify 100% source attribution                                          │
│  • Flag low-confidence claims (<70%)                                       │
│  • Check for contradictions                                                │
│  • Calculate overall confidence score                                      │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │
                        ┌────────┴────────┐
                        │   PASS/FAIL?    │
                        └────────┬────────┘
                    YES │        │ NO
               ┌────────┘        └────────┐
               ▼                          ▼
    ┌──────────────────┐        ┌─────────────────┐
    │   Continue to    │        │   Re-run failed │
    │   Synthesis      │        │   agents with   │
    │                  │        │   corrections   │
    └────────┬─────────┘        └────────┬────────┘
             │                           │
             │                           └──────┐
             ▼                                  │
┌─────────────────────────────────────────────────────────────────────────────┐
│  AGENT 07: SYNTHESIS & REPORT GENERATION                  [~4-5s]          │
├─────────────────────────────────────────────────────────────────────────────┤
│  • Assemble dashboard JSON payload                                         │
│  • Generate risk heatmap data                                              │
│  • Create macro timeline events                                            │
│  • Format reasoning trace                                                  │
│  • Trigger PDF generation (WeasyPrint)                                     │
└────────────────────────────────┬────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         OUTPUTS DELIVERED                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│  ✓ Interactive Dashboard         ✓ Risk Heatmap                           │
│  ✓ Macro Timeline                 ✓ PDF Report                             │
│  ✓ Reasoning Trace (JSON)                                                  │
│                                                                             │
│  Total Time: ~20-30s  |  Cost: <$0.01  |  Attribution: 100%               │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Pipeline Summary:**

1. **Agent 01 - Routing (0.5s):** Parse query, extract parameters, generate task graph
2. **Agents 02-04 - Parallel Execution (3-4s):**
   - Agent 02: GDELT events, FRED data, geopolitical stability
   - Agent 03: News sentiment, social signals, Fear & Greed Index
   - Agent 04: Asset-specific modeling, price patterns
3. **Agent 05 - Quantification (5-7s):** Monte Carlo simulations, GARCH modeling, risk matrix
4. **Agent 06 - Validation (3-4s):** Quality gate, verify sources, check consistency
5. **Agent 07 - Synthesis (4-5s):** Generate dashboard, PDF, reasoning trace

**Total Time:** ~20-30 seconds | **Cost:** < $0.01 | **Source Attribution:** 100%

---

## � Security Architecture

**6 Security Layers:**
1. **Input Sanitization:** Pydantic v2 validation, prompt injection prevention
2. **RAG Whitelisting:** Trusted sources only
3. **Tool Restrictions:** Pre-approved functions, audit trail
4. **Secrets Management:** HashiCorp Vault
5. **Encryption:** AES-256 at rest, TLS 1.3 in transit
6. **Adversarial Testing:** PromptFoo for red team evaluation

---

## 🤖 LLM Inference Strategy

**Agents run sequentially** → Zero GPU needed locally

### Free Providers

1. **Groq** - 300+ tok/sec, 500K tokens/day free
2. **OpenRouter** - $5 free credits, 200+ models
3. **together.ai** - $25 free credits

**Cost:** ~$1 for 100 pipeline runs

### Configuration Example

```python
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI

def get_llm(agent_id: str):
    configs = {
        "agent_01": ("groq", "mistral-7b-instruct"),
        "agent_02": ("openrouter", "deepseek/deepseek-chat"),
        "agent_03": ("together", "Qwen/Qwen2.5-72B"),
        "agent_04": ("groq", "deepseek-r1-distill-llama-70b"),
        "agent_05": ("openrouter", "deepseek/deepseek-r1"),
        "agent_06": ("groq", "llama-3.3-70b"),
        "agent_07": ("groq", "mistral-small-3"),
    }
    
    provider, model = configs[agent_id]
    # Return appropriate LLM based on provider
    # ...
```

---

## 📊 Data Sources & APIs

- **Market Data:** Yahoo Finance, Alpha Vantage, CBOE VIX, FRED
- **News & Events:** GDELT, Reuters RSS, Central Bank communications
- **Macro Data:** IMF, World Bank, ECB, Federal Reserve
- **Sentiment:** Reddit, Twitter/X, Fear & Greed Index

---

## 🔭 Observability

- **LangFuse:** LLM traces, token usage, latency
- **Grafana:** System health, metrics
- **Deployment:** Docker + AWS ECS, auto-scaling
- **Testing:** Pytest, RAGAS, PromptFoo

---

## 👥 User Roles

| Role | Access |
|------|--------|
| **Institutional Investor** | Full access: scenarios, portfolio, PDF reports |
| **Risk Analyst** | Heatmaps, stress tests, volatility analysis |
| **Portfolio Manager** | Asset allocation, rebalancing signals |
| **Research Analyst** | Raw signals, citations, data export |
| **Compliance Officer** | Audit logs, source verification |

---

## 📦 Deliverables

1. **Interactive Dashboard:** Real-time risk scores, dynamic filtering
2. **Risk Heatmap:** Color-coded severity, correlation matrix
3. **Macro Timeline:** Event sequencing, event-to-asset impact
4. **PDF Report:** Executive summary, full citations
5. **Reasoning Trace (JSON):** Per-agent I/O, confidence scores

---

## 🗓️ Implementation Roadmap (9 Weeks)

**Phase 1 (Weeks 1-2):** Environment setup, FastAPI backend, Auth0, databases  
**Phase 2 (Weeks 3-4):** Agents 02-05 implementation (Geopolitical, Sentiment, Asset, Quant)  
**Phase 3 (Weeks 5-6):** Agents 06-07, React frontend, visualizations  
**Phase 4 (Weeks 7-8):** Security, testing (Pytest, RAGAS, PromptFoo), observability  
**Phase 5 (Week 9):** Docker + AWS deployment, CI/CD, documentation

---

## 📚 Environment Variables

```bash
# LLM Providers
GROQ_API_KEY=gsk_xxxx
OPENROUTER_API_KEY=sk-or-xxxx
TOGETHER_API_KEY=xxxx

# Databases
MONGODB_URI=mongodb+srv://...
QDRANT_URL=https://xxxxx.cloud.qdrant.io
QDRANT_API_KEY=xxxx
REDIS_URL=redis://localhost:6379/0

# Auth
AUTH0_DOMAIN=your-tenant.us.auth0.com
AUTH0_CLIENT_ID=xxxx

# Data Sources
FRED_API_KEY=xxxx
ALPHA_VANTAGE_KEY=xxxx

# Observability
LANGFUSE_PUBLIC_KEY=pk-lf-xxxx
LANGFUSE_SECRET_KEY=sk-lf-xxxx

# AWS
S3_BUCKET_NAME=sentinelai-reports
```

---

## 🚀 Quick Start

```bash
# 1. Setup
git clone https://github.com/your-org/SentinelAI.git
cd SentinelAI
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Get free API keys (Groq, OpenRouter, together.ai, MongoDB Atlas, Qdrant, FRED)

# 3. Configure
cp .env.example .env
# Edit .env with your API keys

# 4. Run
redis-server &
celery -A app.celery_app worker --loglevel=info &
uvicorn app.main:app --reload --port 8000 &
cd frontend && npm run dev

# 5. Access at http://localhost:5173
```

---

## 🛠️ Technology Stack

**Frontend:** React 18, Vite, Tailwind CSS, Recharts, D3.js  
**Backend:** FastAPI, Celery, Redis, Pydantic v2  
**AI:** LangGraph, LangChain, langchain-groq, langchain-openai  
**Databases:** MongoDB Atlas, Qdrant, Redis  
**Security:** Auth0, HashiCorp Vault, PromptFoo  
**DevOps:** Docker, AWS ECS, GitHub Actions, Pytest

---

## 📖 Project File Structure

```
SentinelAI/
│
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI entry point
│   │   ├── celery_app.py              # Celery config
│   │   ├── api/routes/                # Auth, query, reports endpoints
│   │   ├── agents/                    # 7 agent implementations
│   │   ├── orchestration/             # LangGraph pipeline
│   │   ├── config/llm.py              # LLM provider routing
│   │   ├── data_sources/              # FRED, GDELT, market data
│   │   ├── rag/                       # Embeddings, retrieval
│   │   ├── models/schemas.py          # Pydantic models
│   │   ├── services/                  # Auth, PDF generation
│   │   └── security/                  # Vault, encryption
│   ├── tests/
│   ├── requirements.txt
│   └── Dockerfile
│
├── frontend/
│   ├── src/
│   │   ├── components/                # Dashboard, Heatmap, Charts
│   │   ├── pages/                     # Home, QueryInput, Results
│   │   ├── hooks/                     # useAuth, useQuery
│   │   └── services/api.ts            # Axios client
│   ├── package.json
│   └── vite.config.ts
│
├── docs/                              # API docs, user guides
├── infrastructure/                    # Docker, Kubernetes, Terraform
├── scripts/                           # Setup, seeding, backups
├── .env.example
└── README.md
```

---

## ⚠️ Key Risks & Mitigation

| Risk | Mitigation |
|------|------------|
| **API Rate Limits** | Fallback chains, caching, monitor usage |
| **LLM Hallucination** | Agent 06 validation, source attribution |
| **Cost Overrun** | Free tiers only, daily monitoring |
| **API Downtime** | Multiple providers, pre-fetch data |

---

## 🎯 Success Criteria

- Pipeline completion > 95%, response time < 30s
- 100% source attribution, >95% verification pass rate
- 7 agents orchestrated, 5 user roles, 5 asset classes
- Complete documentation and deployment guide

---

**Last Updated: February 17, 2026**
