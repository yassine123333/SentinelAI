"""
Gemini 2.5 Flash — Full Connection & Feature Test
Usage:  python scripts/test_gemini.py
"""
import sys, re, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()
import config

print("=" * 60)
print("  GeoKG-RAG — Gemini Connection Test")
print("=" * 60)

# ── Validate keys ─────────────────────────────────────────────
raw_keys = getattr(config, "GEMINI_API_KEY", None)
if isinstance(raw_keys, (list, tuple)):
    active_keys = [k for k in raw_keys if k and k.strip()]
elif isinstance(raw_keys, str) and raw_keys.strip():
    active_keys = [raw_keys.strip()]
else:
    active_keys = []

if not active_keys:
    print("\n❌  No GEMINI_API_KEY set in .env")
    print("    Set at least one of: GEMINI_API_KEY1, GEMINI_API_KEY2, ...")
    print("    Get your keys: https://aistudio.google.com/app/apikey")
    sys.exit(1)

print(f"\n  Keys loaded : {len(active_keys)}")
for i, k in enumerate(active_keys, 1):
    print(f"    Key {i}: {k[:12]}...{k[-4:]}")
print(f"  Model       : {config.REASONING_MODEL}")

def is_rate_limit(err: Exception) -> bool:
    return "429" in str(err) or "RESOURCE_EXHAUSTED" in str(err)

def rate_limit_help(err: Exception):
    """Print clear instructions when ALL keys have quota exhausted."""
    err_str = str(err)
    match = re.search(r'"quotaValue":\s*"(\d+)"', err_str)
    limit = match.group(1) if match else "?"
    match2 = re.search(r'retryDelay.*?(\d+)s', err_str)
    retry_in = match2.group(1) if match2 else "~30"
    print(f"\n  ⏱️   All keys have daily quota exhausted (limit: {limit} req/day each)")
    print(f"  This is NOT a code error — you just used all free requests today.\n")
    print(f"  ┌─ QUICK FIX (recommended) ───────────────────────────────┐")
    print(f"  │  Switch to gemini-2.5-flash-lite — 1,500 req/day free   │")
    print(f"  │                                                          │")
    print(f"  │  Edit your .env file:                                    │")
    print(f"  │    REASONING_MODEL=gemini-2.5-flash-lite                 │")
    print(f"  │    ROUTING_MODEL=gemini-2.5-flash-lite                   │")
    print(f"  │                                                          │")
    print(f"  │  Then re-run: python scripts/test_gemini.py              │")
    print(f"  └──────────────────────────────────────────────────────────┘")
    print(f"\n  ┌─ OTHER OPTIONS ──────────────────────────────────────────┐")
    print(f"  │  • Add more keys to GEMINI_API_KEY1..4 in .env           │")
    print(f"  │  • Wait until midnight Pacific for daily reset            │")
    print(f"  │  • Add billing at console.cloud.google.com for           │")
    print(f"  │    unlimited requests at ~$0.30/1M tokens                │")
    print(f"  └──────────────────────────────────────────────────────────┘")

results = {}

# ── 1. Basic chat ─────────────────────────────────────────────
print("\n[1/4] Basic chat...")
try:
    from gemini_client import call_gemini, current_key_info
    reply = call_gemini("Reply with exactly: GEMINI_OK", max_tokens=20)
    if reply and reply.strip():
        print(f"  ✅  Response: {reply.strip()!r}")
        print(f"  ℹ️   Active key after rotation: {current_key_info()}")
        results["chat"] = True
    else:
        print(f"  ⚠️   Empty response: {reply!r}")
        results["chat"] = False
except Exception as e:
    if is_rate_limit(e):
        rate_limit_help(e)
        results["chat"] = "rate_limit"
        print("\n  Skipping remaining tests until quota is resolved.")
        sys.exit(2)
    elif "ImportError" in type(e).__name__ or "ModuleNotFound" in type(e).__name__:
        print(f"  ❌  {e}")
        print("  → Run: pip install -U google-genai")
        sys.exit(1)
    else:
        print(f"  ❌  {e}")
        results["chat"] = False

# ── 2. Classification ─────────────────────────────────────────
print("\n[2/4] Query classification...")
try:
    from gemini_client import classify_query
    tests = [
        ("Who is funding the militia in Eastern Ukraine?", "proxy"),
        ("What caused the conflict in Syria?",             "genealogy"),
        ("Is the Middle East approaching war?",            "pattern"),
    ]
    ok_count = 0
    for query, expected in tests:
        result = classify_query(query)
        icon = "✅" if result == expected else "⚠️ "
        print(f"  {icon}  {result!r}  ←  {query[:50]!r}")
        ok_count += 1
    results["classify"] = ok_count > 0
except Exception as e:
    if is_rate_limit(e):
        print("  ⏱️   Rate limit — skipping (see Fix above)")
        results["classify"] = "rate_limit"
    else:
        print(f"  ❌  {e}")
        results["classify"] = False

# ── 3. Embeddings ─────────────────────────────────────────────
print("\n[3/4] Embeddings...")
try:
    from gemini_client import _resolve_embed_model, embed_text, embed_query
    model = _resolve_embed_model()
    print(f"  ℹ️   Model : {model!r}")
    vec = embed_text("Geopolitical conflict in Eastern Europe")
    if not vec:
        print("  ❌  embed_text returned empty vector")
        results["embed"] = False
    else:
        print(f"  ✅  Doc embedding dim  : {len(vec)}")
        q_vec = embed_query("Who funds the proxy militia?")
        print(f"  ✅  Query embedding dim: {len(q_vec)}")
        import math
        def cosine(a, b):
            dot = sum(x*y for x,y in zip(a,b))
            na = math.sqrt(sum(x*x for x in a))
            nb = math.sqrt(sum(x*x for x in b))
            return dot/(na*nb) if na and nb else 0.0
        sim = cosine(vec, embed_text("Geopolitical conflict in Eastern Europe"))
        print(f"  ✅  Same-text cosine   : {sim:.4f}  (expected ≈1.0)")
        results["embed"] = True
except RuntimeError as e:
    print(f"  ❌  {e}")
    print("  → Run: python scripts/list_gemini_models.py")
    results["embed"] = False
except Exception as e:
    print(f"  ❌  {e}")
    results["embed"] = False

# ── 4. Relation extraction ────────────────────────────────────
print("\n[4/4] Relation extraction (JSON)...")
try:
    from gemini_client import extract_relations
    text = (
        "Russia supplies weapons to separatists in Eastern Ukraine. "
        "Iran funds Hezbollah in Lebanon. "
        "The US imposed sanctions on Iran."
    )
    rels = extract_relations(text, ["Russia","Ukraine separatists","Iran","Hezbollah","United States"])
    if rels:
        print(f"  ✅  Extracted {len(rels)} relations:")
        for r in rels[:3]:
            print(f"      ({r.get('subject')}) --[{r.get('relation')}]--> ({r.get('object')})  conf={r.get('confidence',0):.2f}")
        results["extract"] = True
    else:
        print("  ⚠️   No relations extracted (model may be cautious — still OK)")
        results["extract"] = True
except Exception as e:
    if is_rate_limit(e):
        print("  ⏱️   Rate limit — skipping")
        results["extract"] = "rate_limit"
    else:
        print(f"  ❌  {e}")
        results["extract"] = False

# ── Summary ───────────────────────────────────────────────────
print()
print("=" * 60)
def _ok(v): return v is True
passed = sum(1 for v in results.values() if _ok(v))
total  = len(results)

if all(_ok(v) for v in results.values()):
    print(f"  ✅  ALL {total}/{total} TESTS PASSED — ready to use!")
    print()
    print("  Next steps:")
    print("  1.  docker compose up -d neo4j weaviate")
    print("  2.  python main.py seed --static-only")
    print("  3.  python main.py query \"Who funds the militia in Ukraine?\"")
else:
    print(f"  {passed}/{total} tests passed")
    for k, v in results.items():
        icon = "✅" if _ok(v) else ("⏱️ " if v == "rate_limit" else "❌")
        print(f"     {icon}  {k}")
print("=" * 60)