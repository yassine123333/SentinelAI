"""
Lists all Gemini models available to your API key.
Run this if you get 404 errors on embeddings.

Usage:  python scripts/list_gemini_models.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()
import config

if not config.GEMINI_API_KEY or config.GEMINI_API_KEY.startswith("AIza..."):
    print("❌  GEMINI_API_KEY not set in .env")
    sys.exit(1)

from google import genai
client = genai.Client(api_key=config.GEMINI_API_KEY)

print("\nAll available Gemini models for your API key:")
print("=" * 55)
all_models = list(client.models.list())
embed_models, chat_models, other = [], [], []
for m in all_models:
    name = m.name
    if "embed" in name.lower():
        embed_models.append(name)
    elif any(x in name.lower() for x in ["gemini", "flash", "pro"]):
        chat_models.append(name)
    else:
        other.append(name)

print(f"\n🔷  Embedding models ({len(embed_models)}):")
for m in embed_models:
    print(f"    {m}")

print(f"\n🔷  Chat/reasoning models ({len(chat_models)}):")
for m in chat_models[:15]:
    print(f"    {m}")

if other:
    print(f"\n🔷  Other ({len(other)}):")
    for m in other[:5]:
        print(f"    {m}")

print()
print("📋  Copy the embedding model name you want into your .env:")
print("    EMBEDDING_MODEL=<model-name-from-list-above>")
print()
if embed_models:
    print(f"✅  Recommended: {embed_models[0]}")
    print(f"    Add to .env:  EMBEDDING_MODEL={embed_models[0]}")
