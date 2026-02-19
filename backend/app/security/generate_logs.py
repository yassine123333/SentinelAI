#!/usr/bin/env python3
"""
generate_logs.py — Fake Nginx access.log generator
====================================================
Generates realistic Nginx Combined Log Format lines with a mix of
normal traffic, suspicious activity, and known-malicious patterns.

Usage:
    # Generate 50 lines to stdout
    python generate_logs.py -n 50

    # Write to a file
    python generate_logs.py -n 200 -o fake_access.log

    # Append continuously (1 line/sec) — simulates a live server
    python generate_logs.py --live -o fake_access.log

    # Pipe directly into the SOC pipeline
    python generate_logs.py -n 30 | python main.py --stdin
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Pools of realistic values
# ---------------------------------------------------------------------------

# Normal user IPs — real public IPs belonging to well-known services
# (avoids RFC 5737 documentation ranges that AbuseIPDB skips)
NORMAL_IPS = [
    "8.8.8.8",            # Google DNS
    "1.1.1.1",            # Cloudflare DNS
    "172.217.14.206",     # Google
    "151.101.1.140",      # Reddit / Fastly
    "104.16.85.20",       # Cloudflare
    "52.85.132.99",       # Amazon CloudFront
    "13.107.42.14",       # Microsoft
    "35.186.224.25",      # Google Cloud
    "54.239.28.85",       # Amazon
    "17.253.144.10",      # Apple
    "23.45.67.89",        # Akamai
    "76.14.32.100",       # Comcast residential
    "140.82.121.4",       # GitHub
    "157.240.1.35",       # Facebook / Meta
    "99.84.191.50",       # Amazon CloudFront
]

# Known-malicious IPs (real Tor exits, scanners, botnets — high AbuseIPDB scores)
MALICIOUS_IPS = [
    "185.220.101.34",     # Tor exit (DE) — ~100% abuse score
    "185.220.101.1",      # Tor exit (DE)
    "93.174.95.106",      # Tor exit (NL)
    "89.248.167.131",     # Recyber scanner (NL)
    "71.6.135.131",       # Censys scanner
    "162.142.125.10",     # Censys scanner
    "45.33.32.156",       # scanme.nmap.org — reported frequently
    "178.128.23.9",       # DigitalOcean — frequent abuse reports
    "80.82.77.139",       # Dreadnought scanner (NL)
    "218.92.0.34",        # China Telecom — frequent brute-forcer
    "112.85.42.187",      # China Unicom — known scanner
]

# Bot / scanner IPs that rotate user-agents
# Using real low-reputation IPs instead of private 10.x.x.x range
ROTATION_IPS = [
    "194.26.135.1", "194.26.135.2", "194.26.135.3", "194.26.135.4",
    "194.26.135.5", "194.26.135.6", "194.26.135.7", "194.26.135.8",
]

# Brute-force IPs (many different IPs hitting /login)
# Using routable IPs instead of RFC 5737 192.0.2.x documentation range
BRUTEFORCE_IPS = [f"45.155.205.{i}" for i in range(1, 50)]

# Normal paths
NORMAL_PATHS = [
    "/", "/index.html", "/about", "/contact", "/products",
    "/blog", "/blog/post-1", "/blog/post-2", "/assets/style.css",
    "/assets/app.js", "/images/logo.png", "/api/v1/status",
    "/docs", "/faq", "/pricing",
]

# Sensitive / attack target paths
SENSITIVE_PATHS = ["/login", "/admin", "/api/auth", "/wp-login.php"]

# Scan / exploit paths
EXPLOIT_PATHS = [
    "/wp-admin/install.php", "/.env", "/config.yml",
    "/phpmyadmin/", "/actuator/health", "/.git/config",
    "/api/v1/users", "/shell.php", "/cgi-bin/test",
    "/remote/logincheck", "/solr/admin/info/system",
]

# Normal user agents
NORMAL_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0 Safari/537.36",
]

# Suspicious / bot user agents
BOT_UAS = [
    "python-requests/2.31.0",
    "curl/7.88.1",
    "Go-http-client/1.1",
    "Scrapy/2.11.0",
    "sqlmap/1.7",
    "Nikto/2.1.6",
    "masscan/1.3",
    "zgrab/0.x",
]

# The one rotating bot UA (triggers IdentityAgent)
ROTATING_BOT_UA = "RotatingProxyBot/1.0"

METHODS = ["GET", "POST", "PUT", "DELETE", "HEAD"]
NORMAL_STATUSES = [200, 200, 200, 200, 200, 301, 304, 404]
AUTH_FAIL_STATUSES = [401, 403, 401, 401, 403]


# ---------------------------------------------------------------------------
# Log line generators by scenario
# ---------------------------------------------------------------------------

def _ts(offset_seconds: int = 0) -> str:
    """Current UTC timestamp in Nginx format, with optional offset."""
    now = datetime.now(timezone.utc)
    return now.strftime("%d/%b/%Y:%H:%M:%S %z")


def _log_line(ip: str, method: str, path: str, status: int, ua: str, size: int | None = None) -> str:
    """Format a single Nginx Combined Log Format line."""
    sz = size or random.randint(200, 15000)
    return f'{ip} - - [{_ts()}] "{method} {path} HTTP/1.1" {status} {sz} "-" "{ua}"'


def gen_normal() -> str:
    """Normal legitimate traffic."""
    return _log_line(
        ip=random.choice(NORMAL_IPS),
        method="GET",
        path=random.choice(NORMAL_PATHS),
        status=random.choice(NORMAL_STATUSES),
        ua=random.choice(NORMAL_UAS),
    )


def gen_malicious_ip() -> str:
    """Request from a known-malicious IP."""
    return _log_line(
        ip=random.choice(MALICIOUS_IPS),
        method=random.choice(["GET", "POST"]),
        path=random.choice(SENSITIVE_PATHS + EXPLOIT_PATHS),
        status=random.choice(AUTH_FAIL_STATUSES + [200]),
        ua=random.choice(BOT_UAS),
    )


def gen_ip_rotation() -> str:
    """Same User-Agent from rotating IPs (triggers IdentityAgent)."""
    return _log_line(
        ip=random.choice(ROTATION_IPS),
        method="GET",
        path=random.choice(NORMAL_PATHS + SENSITIVE_PATHS),
        status=random.choice(NORMAL_STATUSES),
        ua=ROTATING_BOT_UA,
    )


def gen_bruteforce() -> str:
    """Distributed brute-force on /login (triggers PatternAgent)."""
    return _log_line(
        ip=random.choice(BRUTEFORCE_IPS),
        method="POST",
        path="/login",
        status=random.choice(AUTH_FAIL_STATUSES),
        ua=f"curl/7.{random.randint(60, 90)}.0",
    )


def gen_exploit_scan() -> str:
    """Vulnerability scanner probing exploit paths."""
    return _log_line(
        ip=random.choice(MALICIOUS_IPS + BRUTEFORCE_IPS[:10]),
        method=random.choice(["GET", "POST", "PUT"]),
        path=random.choice(EXPLOIT_PATHS),
        status=random.choice([404, 403, 500, 200]),
        ua=random.choice(BOT_UAS),
    )


# Weighted scenario selection
# ~50% normal, ~12% malicious IP, ~12% rotation, ~14% brute-force, ~12% exploit scan
SCENARIOS = [
    (gen_normal, 50),
    (gen_malicious_ip, 12),
    (gen_ip_rotation, 12),
    (gen_bruteforce, 14),
    (gen_exploit_scan, 12),
]

_generators, _weights = zip(*SCENARIOS)


def generate_line() -> str:
    """Generate a single random log line based on weighted scenarios."""
    gen = random.choices(_generators, weights=_weights, k=1)[0]
    return gen()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate fake but realistic Nginx access.log lines",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("-n", "--count", type=int, default=20,
                   help="Number of lines to generate (default: 20)")
    p.add_argument("-o", "--output", type=str, default=None,
                   help="Output file path (default: stdout)")
    p.add_argument("--live", action="store_true",
                   help="Continuous mode: append 1 line/sec (Ctrl+C to stop)")
    p.add_argument("--rate", type=float, default=1.0,
                   help="Lines per second in --live mode (default: 1.0)")
    p.add_argument("--seed", type=int, default=None,
                   help="Random seed for reproducible output")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    # ── Live / continuous mode ───────────────────────────────────────────
    if args.live:
        fh = open(args.output, "a", encoding="utf-8") if args.output else sys.stdout
        print(f"  🔄  Live mode — writing to {'stdout' if not args.output else args.output} "
              f"({args.rate} lines/sec). Ctrl+C to stop.", file=sys.stderr)
        try:
            count = 0
            while True:
                line = generate_line()
                fh.write(line + "\n")
                fh.flush()
                count += 1
                if count % 10 == 0:
                    print(f"  ... {count} lines generated", file=sys.stderr)
                time.sleep(1.0 / args.rate)
        except KeyboardInterrupt:
            print(f"\n  ⏹️  Stopped after {count} lines.", file=sys.stderr)
        finally:
            if args.output:
                fh.close()
        return

    # ── Batch mode ───────────────────────────────────────────────────────
    lines = [generate_line() for _ in range(args.count)]

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        print(f"  ✅  {args.count} lines written to {args.output}", file=sys.stderr)
    else:
        print("\n".join(lines))


if __name__ == "__main__":
    main()
