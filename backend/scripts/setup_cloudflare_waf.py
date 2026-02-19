"""
setup_cloudflare_waf.py — One-shot Cloudflare security configuration for SentinelAI.

Run this ONCE after you add your domain to Cloudflare:
    python backend/scripts/setup_cloudflare_waf.py --zone <ZONE_ID>

Requires env vars (already in backend/.env):
    CF_API_TOKEN  — the SentinelAI-WAF-Security token
    CF_ZONE_ID    — found in Cloudflare Dashboard → your domain → right sidebar

What it creates (aligned with the SentinelAI presentation security spec):
    1. WAF rule  — Challenge bot-flagged login requests (cf.threat_score > 5)
    2. WAF rule  — Managed challenge low-score bots on all auth endpoints
    3. Rate limit — 10 req/min per IP on /api/v1/auth/login (presentation spec)
    4. Rate limit — 5 req/min per IP on /api/v1/auth/register
    5. Rate limit — 3 req/min per IP on /api/v1/auth/resend-verification
    6. Security level → Medium (challenges IPs with threat_score > 14)
"""
from __future__ import annotations

import argparse
import os
import sys

import httpx

# ── Config ────────────────────────────────────────────────────────────────────

API_TOKEN = os.environ.get("CF_API_TOKEN", "LLf8a35t4vH_2oCf-MJ4Au4RauL1tAxMOyw-Jzog")
BASE      = "https://api.cloudflare.com/client/v4"


def headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {API_TOKEN}",
        "Content-Type":  "application/json",
    }


def die(msg: str) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr)
    sys.exit(1)


def ok(resp: httpx.Response, label: str) -> dict:
    data = resp.json()
    if not data.get("success"):
        errors = data.get("errors", [])
        die(f"{label} failed: {errors}")
    print(f"  [OK] {label}")
    return data


# ── WAF custom rules ──────────────────────────────────────────────────────────

WAF_RULES = [
    {
        "description": "SentinelAI — Challenge high-threat IPs on login",
        "expression":  (
            '(http.request.uri.path eq "/api/v1/auth/login") '
            'and (cf.threat_score gt 5)'
        ),
        "action": "managed_challenge",
        "enabled": True,
    },
    {
        "description": "SentinelAI — Managed challenge low-score bots on all auth",
        "expression":  (
            '(http.request.uri.path contains "/api/v1/auth/") '
            'and (not cf.bot_management.verified_bot) '
            'and (cf.bot_management.score lt 30)'
        ),
        "action": "managed_challenge",
        "enabled": True,
    },
]


def create_waf_rules(zone_id: str, client: httpx.Client) -> None:
    print("\n[1] Creating WAF custom rules...")
    url = f"{BASE}/zones/{zone_id}/rulesets/phases/http_request_firewall_custom/entrypoint"

    # Fetch existing ruleset (zone must have one before we can PATCH)
    resp = client.get(url, headers=headers())
    existing = resp.json().get("result", {})
    existing_rules: list[dict] = existing.get("rules", [])

    # Merge — skip any rule whose description is already present
    existing_descs = {r.get("description") for r in existing_rules}
    new_rules = [r for r in WAF_RULES if r["description"] not in existing_descs]

    if not new_rules:
        print("  [SKIP] All WAF rules already exist.")
        return

    payload = {"rules": existing_rules + new_rules}
    resp = client.put(url, headers=headers(), json=payload)
    ok(resp, f"WAF rules ({len(new_rules)} added)")


# ── Rate limiting rules ───────────────────────────────────────────────────────

RATE_LIMIT_RULES = [
    {
        "description":  "SentinelAI — Rate limit /login (10 req/min per IP)",
        "expression":   'http.request.uri.path eq "/api/v1/auth/login"',
        "action":       "block",
        "ratelimit": {
            "characteristics":   ["ip.src"],
            "period":            60,
            "requests_per_period": 10,
            "mitigation_timeout":  300,   # 5-min block
        },
        "enabled": True,
    },
    {
        "description":  "SentinelAI — Rate limit /register (5 req/min per IP)",
        "expression":   'http.request.uri.path eq "/api/v1/auth/register"',
        "action":       "block",
        "ratelimit": {
            "characteristics":   ["ip.src"],
            "period":            60,
            "requests_per_period": 5,
            "mitigation_timeout":  300,
        },
        "enabled": True,
    },
    {
        "description":  "SentinelAI — Rate limit /resend-verification (3 req/min per IP)",
        "expression":   'http.request.uri.path eq "/api/v1/auth/resend-verification"',
        "action":       "block",
        "ratelimit": {
            "characteristics":   ["ip.src"],
            "period":            60,
            "requests_per_period": 3,
            "mitigation_timeout":  300,
        },
        "enabled": True,
    },
]


def create_rate_limits(zone_id: str, client: httpx.Client) -> None:
    print("\n[2] Creating rate limiting rules...")
    url = f"{BASE}/zones/{zone_id}/rulesets/phases/http_ratelimit/entrypoint"

    resp = client.get(url, headers=headers())
    existing = resp.json().get("result", {})
    existing_rules: list[dict] = existing.get("rules", [])

    existing_descs = {r.get("description") for r in existing_rules}
    new_rules = [r for r in RATE_LIMIT_RULES if r["description"] not in existing_descs]

    if not new_rules:
        print("  [SKIP] All rate limit rules already exist.")
        return

    payload = {"rules": existing_rules + new_rules}
    resp = client.put(url, headers=headers(), json=payload)
    ok(resp, f"Rate limit rules ({len(new_rules)} added)")


# ── Security level ────────────────────────────────────────────────────────────

def set_security_level(zone_id: str, client: httpx.Client) -> None:
    print("\n[3] Setting security level to Medium...")
    url  = f"{BASE}/zones/{zone_id}/settings/security_level"
    resp = client.patch(url, headers=headers(), json={"value": "medium"})
    ok(resp, "Security level = medium")


# ── Bot Fight Mode ────────────────────────────────────────────────────────────

def enable_bot_fight_mode(zone_id: str, client: httpx.Client) -> None:
    print("\n[4] Enabling Bot Fight Mode...")
    url  = f"{BASE}/zones/{zone_id}/settings/bot_fight_mode"
    resp = client.patch(url, headers=headers(), json={"value": "on"})
    ok(resp, "Bot Fight Mode = on")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Configure Cloudflare WAF for SentinelAI")
    parser.add_argument("--zone", required=True, help="Cloudflare Zone ID")
    args = parser.parse_args()

    zone_id = args.zone
    print(f"Configuring Cloudflare WAF for zone: {zone_id}\n")

    with httpx.Client(timeout=15.0) as client:
        create_waf_rules(zone_id, client)
        create_rate_limits(zone_id, client)
        set_security_level(zone_id, client)
        enable_bot_fight_mode(zone_id, client)

    print("\nDone. All Cloudflare security rules are active.")
    print("Remember to rotate CF_API_TOKEN before 2026-05-21.")


if __name__ == "__main__":
    main()
