"""
blocker.py — Defense-in-Depth IP Blocking: Azure NSG + Nginx
=============================================================

This module implements a **2-layer blocking strategy** for production
deployments running on **Azure + Docker/Nginx**:

┌─────────────────────────────────────────────────────────────────┐
│  LAYER 1 — Azure Network Security Group (NSG)                  │
│  ─────────────────────────────────────────────────────────────  │
│  Uses the Azure SDK to add a DENY inbound rule to the NSG      │
│  attached to your VM/subnet. This blocks the IP at the          │
│  **network level** — packets are dropped before they ever reach │
│  your container or Nginx process.                               │
│                                                                 │
│  Pros:  Most effective; zero load on your server                │
│  Cons:  ~2-5 second propagation delay on Azure                  │
│                                                                 │
│  Requires:                                                      │
│    • Azure credentials (Service Principal or Managed Identity)  │
│    • azure-identity + azure-mgmt-network SDKs                   │
│    • Env vars: AZURE_SUBSCRIPTION_ID, AZURE_RESOURCE_GROUP,     │
│      AZURE_NSG_NAME (+ auth: AZURE_CLIENT_ID, etc. or MI)      │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│  LAYER 2 — Nginx deny directive                                 │
│  ─────────────────────────────────────────────────────────────  │
│  Writes "deny <ip>;" lines to /etc/nginx/conf.d/blocklist.conf  │
│  then sends SIGHUP to Nginx (graceful reload).                  │
│  This blocks at the **HTTP reverse-proxy level** — the TCP      │
│  connection is accepted but Nginx immediately returns 403.      │
│                                                                 │
│  Pros:  Instant effect (<100ms); works without any cloud SDK    │
│  Cons:  IP already reached your server (just not your app)      │
│                                                                 │
│  Requires:                                                      │
│    • Write access to NGINX_BLOCKLIST_PATH                       │
│    • Permission to send SIGHUP to Nginx (or run nginx -s)       │
│    • Your nginx.conf must include the blocklist file:            │
│        http { include /etc/nginx/conf.d/blocklist.conf; }       │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│  STRATEGY                                                       │
│  ─────────────────────────────────────────────────────────────  │
│  Both layers fire in parallel on every BLOCK decision:          │
│                                                                 │
│    1. Nginx deny  → immediate effect (HTTP 403)                 │
│    2. Azure NSG   → takes a few seconds but then blocks at L3   │
│                                                                 │
│  If either layer fails, the other still protects you.           │
│  Both are idempotent — re-blocking the same IP is a no-op.      │
└─────────────────────────────────────────────────────────────────┘

Environment variables
---------------------
BLOCK_LAYER_AZURE     "true" to enable Azure NSG blocking   (default: "false")
BLOCK_LAYER_NGINX     "true" to enable Nginx deny blocking  (default: "false")

Azure-specific:
    AZURE_SUBSCRIPTION_ID    Your Azure subscription ID
    AZURE_RESOURCE_GROUP     Resource group containing the NSG
    AZURE_NSG_NAME           Name of the Network Security Group
    AZURE_NSG_RULE_PREFIX    Prefix for auto-created rules (default: "SOC-BLOCK-")
    AZURE_NSG_PRIORITY_START Starting priority number       (default: 4000)

    Authentication (Service Principal):
        AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_CLIENT_SECRET
    Or use Managed Identity (auto-detected on Azure VMs/ACI/AKS).

Nginx-specific:
    NGINX_BLOCKLIST_PATH     Path to blocklist.conf  (default: /etc/nginx/conf.d/blocklist.conf)
    NGINX_RELOAD_CMD         Reload command           (default: "nginx -s reload")

Dry-run mode:
    BLOCK_DRY_RUN            "true" to log actions without executing (default: "false")
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Configuration from environment
# ═══════════════════════════════════════════════════════════════════════════

def _env_bool(key: str, default: str = "false") -> bool:
    return os.environ.get(key, default).lower() in ("true", "1", "yes")


# Feature flags
LAYER_AZURE_ENABLED: bool = _env_bool("BLOCK_LAYER_AZURE")
LAYER_NGINX_ENABLED: bool = _env_bool("BLOCK_LAYER_NGINX")
DRY_RUN: bool = _env_bool("BLOCK_DRY_RUN")

# Azure config
AZURE_SUBSCRIPTION_ID: str = os.environ.get("AZURE_SUBSCRIPTION_ID", "")
AZURE_RESOURCE_GROUP: str = os.environ.get("AZURE_RESOURCE_GROUP", "")
AZURE_NSG_NAME: str = os.environ.get("AZURE_NSG_NAME", "")
AZURE_NSG_RULE_PREFIX: str = os.environ.get("AZURE_NSG_RULE_PREFIX", "SOC-BLOCK-")
AZURE_NSG_PRIORITY_START: int = int(os.environ.get("AZURE_NSG_PRIORITY_START", "4000"))

# Nginx config
NGINX_BLOCKLIST_PATH: Path = Path(
    os.environ.get("NGINX_BLOCKLIST_PATH", "/etc/nginx/conf.d/blocklist.conf")
)
NGINX_RELOAD_CMD: str = os.environ.get("NGINX_RELOAD_CMD", "nginx -s reload")

# Local blocklist file — ALWAYS written (even in simulation mode)
# This file lives next to the script so you can inspect blocked IPs.
LOCAL_BLOCKLIST_PATH: Path = Path(
    os.environ.get("LOCAL_BLOCKLIST_PATH",
                   str(Path(__file__).resolve().parent / "blocklist.conf"))
)

# Thread-safe state
_lock = threading.Lock()
_blocked_ips: set[str] = set()
_nsg_priority_counter: int = AZURE_NSG_PRIORITY_START


# ═══════════════════════════════════════════════════════════════════════════
# LOCAL BLOCKLIST — always written regardless of layer config
# ═══════════════════════════════════════════════════════════════════════════

def _write_local_blocklist(ip: str, reason: str) -> None:
    """
    Append the blocked IP to the local blocklist.conf file in the project
    directory.  This file is always written (even in simulation mode) so
    you have a persistent record of every blocked IP.

    Format per line:   deny <ip>;  # <reason> — <timestamp>
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    deny_line = f"deny {ip};  # SOC: {reason[:120]} — {timestamp}\n"

    with _lock:
        # Idempotency: don't duplicate
        try:
            existing = LOCAL_BLOCKLIST_PATH.read_text(encoding="utf-8")
        except FileNotFoundError:
            existing = ""

        pattern = rf"^\s*deny\s+{re.escape(ip)}\s*;"
        if re.search(pattern, existing, re.MULTILINE):
            logger.debug("Local blocklist: %s already present — skipping.", ip)
            return

        try:
            LOCAL_BLOCKLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
            with LOCAL_BLOCKLIST_PATH.open("a", encoding="utf-8") as fh:
                fh.write(deny_line)
            logger.info(
                "📝 Local blocklist: appended 'deny %s;' → %s",
                ip, LOCAL_BLOCKLIST_PATH,
            )
        except Exception as exc:
            logger.error("Failed to write local blocklist: %s", exc)


# ═══════════════════════════════════════════════════════════════════════════
# LAYER 1 — Azure NSG Blocking
# ═══════════════════════════════════════════════════════════════════════════
#
# How it works:
#   1. Authenticate using DefaultAzureCredential (supports Service Principal,
#      Managed Identity, Azure CLI, etc.)
#   2. Get or create a NetworkManagementClient for the subscription
#   3. Create a new security rule in the NSG:
#        Name:       "SOC-BLOCK-<ip_with_dashes>"
#        Direction:  Inbound
#        Action:     Deny
#        Source:     <malicious IP>/32
#        Priority:   Auto-incrementing from 4000
#   4. The rule propagates in ~2-5 seconds
#
# Idempotent: if the rule name already exists, Azure returns it as-is.
# ═══════════════════════════════════════════════════════════════════════════

# Lazy-init Azure clients (only imported if LAYER_AZURE_ENABLED)
_azure_credential = None
_azure_network_client = None


def _init_azure_client() -> bool:
    """
    Lazy-initialize the Azure Network Management client.
    Returns True if the client is ready, False otherwise.
    """
    global _azure_credential, _azure_network_client

    if _azure_network_client is not None:
        return True

    if not all([AZURE_SUBSCRIPTION_ID, AZURE_RESOURCE_GROUP, AZURE_NSG_NAME]):
        logger.error(
            "Azure NSG blocking enabled but missing env vars. Need: "
            "AZURE_SUBSCRIPTION_ID, AZURE_RESOURCE_GROUP, AZURE_NSG_NAME"
        )
        return False

    try:
        from azure.identity import DefaultAzureCredential
        from azure.mgmt.network import NetworkManagementClient

        _azure_credential = DefaultAzureCredential()
        _azure_network_client = NetworkManagementClient(
            credential=_azure_credential,
            subscription_id=AZURE_SUBSCRIPTION_ID,
        )
        logger.info("Azure NetworkManagementClient initialized successfully.")
        return True

    except ImportError:
        logger.error(
            "Azure SDKs not installed. Run:\n"
            "  pip install azure-identity azure-mgmt-network"
        )
        return False

    except Exception as exc:
        logger.error("Failed to initialize Azure client: %s", exc)
        return False


def _ip_to_rule_name(ip: str) -> str:
    """Convert IP to a valid Azure NSG rule name: SOC-BLOCK-1-2-3-4"""
    return AZURE_NSG_RULE_PREFIX + ip.replace(".", "-")


def block_ip_azure_nsg(ip: str, reason: str) -> dict[str, Any]:
    """
    LAYER 1: Add a DENY inbound rule to the Azure NSG for the given IP.

    Parameters
    ----------
    ip:      The IP address to block (e.g. "185.220.101.34")
    reason:  Human-readable reason (stored in rule description)

    Returns
    -------
    Dict with keys: success (bool), layer ("azure_nsg"), detail (str)
    """
    global _nsg_priority_counter

    rule_name = _ip_to_rule_name(ip)
    result: dict[str, Any] = {"layer": "azure_nsg", "ip": ip, "rule_name": rule_name}

    if DRY_RUN:
        logger.info("[DRY-RUN] Azure NSG: would create rule '%s' to deny %s/32", rule_name, ip)
        result.update(success=True, detail=f"[DRY-RUN] Rule {rule_name} would be created.")
        return result

    if not _init_azure_client():
        result.update(success=False, detail="Azure client initialization failed.")
        return result

    try:
        from azure.mgmt.network.models import (
            SecurityRule,
            SecurityRuleAccess,
            SecurityRuleDirection,
            SecurityRuleProtocol,
        )

        with _lock:
            priority = _nsg_priority_counter
            _nsg_priority_counter += 1

        # ── Create the NSG deny rule ─────────────────────────────────
        #
        #   Direction:            Inbound (block traffic coming IN)
        #   Protocol:             * (all protocols — TCP, UDP, ICMP)
        #   Source address:       <ip>/32 (single host)
        #   Source port range:    * (any source port)
        #   Destination address:  * (any destination on our subnet)
        #   Destination port:     * (any port)
        #   Access:               Deny
        #   Priority:             4000+ (lower number = higher priority,
        #                         Azure allows 100-4096)
        # ─────────────────────────────────────────────────────────────
        rule_params = SecurityRule(
            protocol=SecurityRuleProtocol.ASTERISK,
            source_address_prefix=f"{ip}/32",
            source_port_range="*",
            destination_address_prefix="*",
            destination_port_range="*",
            access=SecurityRuleAccess.DENY,
            direction=SecurityRuleDirection.INBOUND,
            priority=priority,
            description=f"SOC auto-block: {reason[:200]}",
        )

        poller = _azure_network_client.security_rules.begin_create_or_update(
            resource_group_name=AZURE_RESOURCE_GROUP,
            network_security_group_name=AZURE_NSG_NAME,
            security_rule_name=rule_name,
            security_rule_parameters=rule_params,
        )
        # Wait for the rule to be provisioned (typically 2-5 seconds)
        poller.result()

        detail = (
            f"Azure NSG rule '{rule_name}' created — "
            f"DENY inbound from {ip}/32, priority {priority}."
        )
        logger.warning("🔒 LAYER 1 (Azure NSG): %s", detail)
        result.update(success=True, detail=detail, priority=priority)
        return result

    except Exception as exc:
        detail = f"Azure NSG rule creation failed: {exc}"
        logger.error("LAYER 1 (Azure NSG) FAILED: %s", detail)
        result.update(success=False, detail=detail)
        return result


# ═══════════════════════════════════════════════════════════════════════════
# LAYER 2 — Nginx deny Directive
# ═══════════════════════════════════════════════════════════════════════════
#
# How it works:
#   1. Read the existing blocklist.conf (or create it if missing)
#   2. Append "deny <ip>;  # <reason>" if not already present
#   3. Run "nginx -s reload" to gracefully reload config
#      (existing connections finish; new connections see the deny)
#
# Your nginx.conf MUST include this file for the deny to take effect:
#
#   http {
#       include /etc/nginx/conf.d/blocklist.conf;
#       ...
#       server { ... }
#   }
#
# What "deny" does in Nginx:
#   When a request arrives from a denied IP, Nginx immediately returns
#   HTTP 403 Forbidden without forwarding to your upstream app.
#
# Idempotent: if "deny <ip>;" already exists in the file, it's skipped.
# ═══════════════════════════════════════════════════════════════════════════

def _read_blocklist() -> str:
    """Read the current Nginx blocklist file, or return empty string."""
    try:
        return NGINX_BLOCKLIST_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except PermissionError:
        logger.error(
            "Cannot read %s — permission denied. "
            "Ensure the SOC process has read/write access.",
            NGINX_BLOCKLIST_PATH,
        )
        return ""


def _ip_already_denied(ip: str, content: str) -> bool:
    """Check if 'deny <ip>;' already exists in the blocklist content."""
    # Match "deny 1.2.3.4;" with optional whitespace
    pattern = rf"^\s*deny\s+{re.escape(ip)}\s*;"
    return bool(re.search(pattern, content, re.MULTILINE))


def _reload_nginx() -> tuple[bool, str]:
    """
    Send a graceful reload signal to Nginx.

    Uses the configured NGINX_RELOAD_CMD (default: "nginx -s reload").
    On Docker, this sends SIGHUP to the Nginx master process — existing
    connections are allowed to complete while new connections use the
    updated config.
    """
    try:
        result = subprocess.run(
            NGINX_RELOAD_CMD.split(),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return True, "Nginx reloaded successfully."
        else:
            err = result.stderr.strip() or result.stdout.strip()
            return False, f"Nginx reload failed (exit {result.returncode}): {err}"
    except FileNotFoundError:
        return False, f"Command not found: {NGINX_RELOAD_CMD}"
    except subprocess.TimeoutExpired:
        return False, "Nginx reload timed out (10s)."
    except Exception as exc:
        return False, f"Nginx reload error: {exc}"


def block_ip_nginx(ip: str, reason: str) -> dict[str, Any]:
    """
    LAYER 2: Add "deny <ip>;" to the Nginx blocklist and reload.

    Parameters
    ----------
    ip:      The IP address to block
    reason:  Human-readable reason (added as a comment)

    Returns
    -------
    Dict with keys: success (bool), layer ("nginx_deny"), detail (str)
    """
    result: dict[str, Any] = {"layer": "nginx_deny", "ip": ip}

    if DRY_RUN:
        logger.info(
            "[DRY-RUN] Nginx: would add 'deny %s;' to %s and reload.",
            ip, NGINX_BLOCKLIST_PATH,
        )
        result.update(success=True, detail=f"[DRY-RUN] Would deny {ip} in Nginx.")
        return result

    with _lock:
        # 1. Read current blocklist
        content = _read_blocklist()

        # 2. Check idempotency
        if _ip_already_denied(ip, content):
            detail = f"IP {ip} already denied in {NGINX_BLOCKLIST_PATH} — skipping."
            logger.info("LAYER 2 (Nginx): %s", detail)
            result.update(success=True, detail=detail, already_blocked=True)
            return result

        # 3. Append the deny directive
        #    Format: deny 1.2.3.4;  # SOC: <reason> — <timestamp>
        from datetime import datetime, timezone
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        new_line = f"deny {ip};  # SOC: {reason[:100]} — {timestamp}\n"

        try:
            NGINX_BLOCKLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
            with NGINX_BLOCKLIST_PATH.open("a", encoding="utf-8") as fh:
                fh.write(new_line)
        except PermissionError:
            detail = f"Cannot write to {NGINX_BLOCKLIST_PATH} — permission denied."
            logger.error("LAYER 2 (Nginx) FAILED: %s", detail)
            result.update(success=False, detail=detail)
            return result
        except Exception as exc:
            detail = f"Failed to write blocklist: {exc}"
            logger.error("LAYER 2 (Nginx) FAILED: %s", detail)
            result.update(success=False, detail=detail)
            return result

    # 4. Reload Nginx (outside the lock to avoid holding it during I/O)
    reload_ok, reload_msg = _reload_nginx()
    if reload_ok:
        detail = f"Nginx: added 'deny {ip};' and reloaded. {reload_msg}"
        logger.warning("🔒 LAYER 2 (Nginx): %s", detail)
        result.update(success=True, detail=detail)
    else:
        detail = f"Nginx: added 'deny {ip};' but reload failed — {reload_msg}"
        logger.error("LAYER 2 (Nginx) PARTIAL: %s", detail)
        result.update(success=False, detail=detail, rule_written=True)

    return result


# ═══════════════════════════════════════════════════════════════════════════
# Unified Blocking Entrypoint
# ═══════════════════════════════════════════════════════════════════════════

def block_ip(ip: str, reason: str) -> dict[str, Any]:
    """
    Execute the defense-in-depth blocking strategy.

    Fires both layers (Nginx first for speed, then Azure NSG for depth).
    Returns a summary dict with results from each active layer.

    Parameters
    ----------
    ip:      The IP to block
    reason:  Why (from ReasoningAgent)

    Returns
    -------
    {
        "ip": "1.2.3.4",
        "layers_attempted": ["nginx_deny", "azure_nsg"],
        "layers_succeeded": ["nginx_deny"],
        "results": [ { layer result dicts } ],
        "fully_blocked": True/False
    }
    """
    results: list[dict[str, Any]] = []
    layers_attempted: list[str] = []
    layers_succeeded: list[str] = []

    # Track globally
    _blocked_ips.add(ip)

    # ── ALWAYS write to local blocklist.conf ────────────────────────
    _write_local_blocklist(ip, reason)

    # ── Layer 2 first (Nginx) — instant effect ──────────────────────
    if LAYER_NGINX_ENABLED:
        layers_attempted.append("nginx_deny")
        nginx_result = block_ip_nginx(ip, reason)
        results.append(nginx_result)
        if nginx_result["success"]:
            layers_succeeded.append("nginx_deny")

    # ── Layer 1 (Azure NSG) — deep protection ──────────────────────
    if LAYER_AZURE_ENABLED:
        layers_attempted.append("azure_nsg")
        azure_result = block_ip_azure_nsg(ip, reason)
        results.append(azure_result)
        if azure_result["success"]:
            layers_succeeded.append("azure_nsg")

    # ── Fallback: no layers enabled (simulation mode) ───────────────
    if not LAYER_NGINX_ENABLED and not LAYER_AZURE_ENABLED:
        layers_attempted.append("simulation")
        layers_succeeded.append("simulation")
        results.append({
            "layer": "simulation",
            "ip": ip,
            "success": True,
            "detail": (
                f"IP {ip} blocked in-memory (simulation). "
                "Set BLOCK_LAYER_NGINX=true and/or BLOCK_LAYER_AZURE=true "
                "for real blocking."
            ),
        })

    fully_blocked = len(layers_succeeded) > 0

    summary = {
        "ip": ip,
        "layers_attempted": layers_attempted,
        "layers_succeeded": layers_succeeded,
        "results": results,
        "fully_blocked": fully_blocked,
        "total_blocked_ips": len(_blocked_ips),
    }

    if fully_blocked:
        logger.warning(
            "block_ip: %s blocked via %s (%d/%d layers succeeded).",
            ip,
            ", ".join(layers_succeeded),
            len(layers_succeeded),
            len(layers_attempted),
        )
    else:
        logger.error(
            "block_ip: FAILED to block %s — 0/%d layers succeeded!",
            ip,
            len(layers_attempted),
        )

    return summary


def get_blocked_ips() -> frozenset[str]:
    """Return the current set of all blocked IPs (read-only)."""
    return frozenset(_blocked_ips)


def get_status() -> dict[str, Any]:
    """Return a status summary of the blocker configuration."""
    return {
        "layer_azure_enabled": LAYER_AZURE_ENABLED,
        "layer_nginx_enabled": LAYER_NGINX_ENABLED,
        "dry_run": DRY_RUN,
        "blocked_ips_count": len(_blocked_ips),
        "blocked_ips": sorted(_blocked_ips),
        "azure_nsg": AZURE_NSG_NAME or "(not configured)",
        "nginx_blocklist": str(NGINX_BLOCKLIST_PATH),
        "local_blocklist": str(LOCAL_BLOCKLIST_PATH),
    }
