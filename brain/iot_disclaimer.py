"""The IoT safety statement: its version, what counts as IoT, and whether the person accepted it.

Amika reaches real devices only after the person has read and accepted docs/IOT_DISCLAIMER.md (English, Japanese,
Simplified Chinese, Korean) on the Tools page. The acceptance is kept in config/tools.json:

    "iot_disclaimer": {"version": "2026-11-03", "accepted_at": "2026-11-03T21:04:05Z"}

and counts only for IOT_DISCLAIMER_VERSION. When the statement changes, its version changes here and in the
document; IoT is then held off until the new version is accepted. Everyone applies the same rules from this file:
the brain (brain/f_tools.py: saving the tool config, the MCP hub that starts and connects servers), the speech gateway
(speech/api.py: the statement for the Tools page, the config proxy) and the launcher (launch.py: the MQTT broker and
zigbee2mqtt services). The bridge checks the version once more on its own start
(servers/openamika-iot/openamika_iot/disclaimer.py). Standard library only: speech/api.py and launch.py load this
file by its path.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

IOT_DISCLAIMER_VERSION = "2026-11-03"
RECORD_KEY = "iot_disclaimer"                     # where config/tools.json keeps the acceptance
ENV_VAR = "OPENAMIKA_IOT_DISCLAIMER_ACCEPTED"     # the accepted version, handed to the bridge the brain starts
REQUIRED_CODE = "iot_disclaimer_required"         # the refusal the Tools page answers with the statement
DOC_NAME = "docs/IOT_DISCLAIMER.md"
ROOT = Path(__file__).resolve().parent.parent
DOC_PATH = ROOT / "docs" / "IOT_DISCLAIMER.md"
TOOLS_PATH = ROOT / "config" / "tools.json"
LANGUAGES = ("en", "ja", "zh", "ko")
REQUIRED_MESSAGE = (f"IoT stays off until you accept the IoT safety statement ({DOC_NAME}, version "
                    f"{IOT_DISCLAIMER_VERSION}). Turn IoT on from the Tools page to read it.")

# launcher services (settings.json "services") that belong to the smart home
IOT_SERVICE_NAMES = frozenset({"mqtt", "mosquitto", "zigbee2mqtt", "z2m"})
_BRIDGE = re.compile(r"openamika[-_]iot", re.I)
_HOME_ASSISTANT_NAME = re.compile(r"home[\s_-]?assistant|(?<![a-z])hass(?![a-z])|^ha$", re.I)
_HOME_ASSISTANT_URL = re.compile(r"/mcp_server\b|home-?assistant|:8123(?:/|$)", re.I)


# ── which servers and services are IoT ──────────────────────────────────────────────────

def is_iot_bridge(name, scfg) -> bool:
    """OpenAmika's own smart-home server (servers/openamika-iot): named "iot", or started as openamika_iot /
    openamika-iot."""
    scfg = scfg if isinstance(scfg, dict) else {}
    started_as = json.dumps([scfg.get("command") or "", *(scfg.get("args") or [])], ensure_ascii=False)
    return name == "iot" or bool(_BRIDGE.search(started_as))


def is_smart_home(name, scfg) -> bool:
    """A tool server that can reach devices, so it stays off until the statement is accepted: OpenAmika's IoT bridge,
    any server marked "kind": "iot", and Home Assistant's MCP server (recognised by its name or its URL)."""
    scfg = scfg if isinstance(scfg, dict) else {}
    if is_iot_bridge(name, scfg) or scfg.get("kind") == "iot":
        return True
    return bool(_HOME_ASSISTANT_NAME.search(str(name or "")) or _HOME_ASSISTANT_URL.search(str(scfg.get("url") or "")))


def smart_home_servers(doc, enabled_only: bool = True) -> list:
    """Names of the smart-home servers in a tools.json document (only the enabled ones unless enabled_only=False)."""
    servers = doc.get("mcpServers") if isinstance(doc, dict) else None
    if not isinstance(servers, dict):
        return []
    return [name for name, scfg in servers.items()
            if isinstance(scfg, dict) and is_smart_home(name, scfg) and (scfg.get("enabled") or not enabled_only)]


def turns_on_iot(doc) -> bool:
    """True when this tools.json document has a smart-home server switched on."""
    return bool(smart_home_servers(doc))


def is_iot_service(name, command=None, cwd=None) -> bool:
    """A launcher service from settings.json that belongs to the smart home: the MQTT broker or zigbee2mqtt."""
    if str(name or "").lower() in IOT_SERVICE_NAMES:
        return True
    text = " ".join(str(part) for part in [*(command or []), cwd or ""]).lower()
    return "mosquitto" in text or "zigbee2mqtt" in text


# ── the acceptance ──────────────────────────────────────────────────────────────────────

def acceptance(doc):
    """The acceptance recorded in a tools.json document ({"version", "accepted_at"}), or None."""
    rec = doc.get(RECORD_KEY) if isinstance(doc, dict) else None
    if not isinstance(rec, dict) or not isinstance(rec.get("version"), str) or not isinstance(rec.get("accepted_at"), str):
        return None
    return {"version": rec["version"], "accepted_at": rec["accepted_at"]}


def accepted(doc) -> bool:
    """True only when the current version of the statement was accepted."""
    rec = acceptance(doc)
    return rec is not None and rec["version"] == IOT_DISCLAIMER_VERSION


def record(now=None) -> dict:
    """A new acceptance of the current version, timestamped in UTC."""
    now = now or datetime.now(timezone.utc)
    return {"version": IOT_DISCLAIMER_VERSION, "accepted_at": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}


def status(doc) -> dict:
    """What the Tools page needs: the current version, whether it was accepted (and which version, when), and the
    smart-home servers that are switched on but held off because it was not."""
    rec = acceptance(doc)
    ok = accepted(doc)
    return {"version": IOT_DISCLAIMER_VERSION, "accepted": ok,
            "accepted_version": rec["version"] if rec else None, "accepted_at": rec["accepted_at"] if rec else None,
            "held": [] if ok else smart_home_servers(doc), "doc": DOC_NAME}


def required_detail() -> dict:
    """The body of the refusal when a config would turn IoT on before the statement was accepted."""
    return {"code": REQUIRED_CODE, "message": REQUIRED_MESSAGE, "version": IOT_DISCLAIMER_VERSION, "doc": DOC_NAME}


def read_tools(path=None) -> dict:
    """config/tools.json as a dict; {} when it is missing or unreadable (then nothing counts as accepted)."""
    try:
        doc = json.loads(Path(path or TOOLS_PATH).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


# ── the statement itself, for the Tools page ────────────────────────────────────────────

_VERSION_MARK = re.compile(r"<!--\s*IOT_DISCLAIMER_VERSION:\s*([0-9A-Za-z.\-]+)\s*-->")
_SECTION = re.compile(r"<!--\s*iot-disclaimer:(en|ja|zh|ko)\s*-->(.*?)<!--\s*/iot-disclaimer:\1\s*-->", re.S)


def _blocks(markdown: str) -> list:
    """The small Markdown subset the statement uses, as blocks the page renders with text nodes only:
    {"type": "h", "text"} for ### headings, {"type": "ul", "items"} for "- " lists, {"type": "p", "text"} otherwise.
    Wrapped lines are joined with a space (the Japanese and Chinese texts keep each paragraph on one line);
    **bold** stays in the text for the page to render."""
    blocks = []
    for chunk in re.split(r"\n[ \t]*\n", markdown.strip()):
        lines = [line.strip() for line in chunk.splitlines() if line.strip()]
        if not lines:
            continue
        if lines[0].startswith("### "):
            blocks.append({"type": "h", "text": lines[0][4:].strip()})
            lines = lines[1:]
            if not lines:
                continue
        if lines[0].startswith("- "):
            items = []
            for line in lines:
                if line.startswith("- "):
                    items.append(line[2:].strip())
                elif items:
                    items[-1] += " " + line
            blocks.append({"type": "ul", "items": items})
        else:
            blocks.append({"type": "p", "text": " ".join(lines)})
    return blocks


def statement(path=None) -> dict:
    """docs/IOT_DISCLAIMER.md for the Tools page: {"version", "doc", "languages": {code: {"label", "blocks"}}} with
    codes en, ja, zh, ko. Raises ValueError when the file's version is not IOT_DISCLAIMER_VERSION or a language is
    missing, and OSError when it cannot be read: the page then cannot show it, and IoT stays off."""
    text = Path(path or DOC_PATH).read_text(encoding="utf-8-sig")
    mark = _VERSION_MARK.search(text)
    if not mark or mark.group(1) != IOT_DISCLAIMER_VERSION:
        raise ValueError(f"{DOC_NAME} is not version {IOT_DISCLAIMER_VERSION}")
    languages = {}
    for code, body in _SECTION.findall(text):
        heading = re.search(r"^##[ \t]+(.+?)[ \t]*$", body, re.M)
        if heading:
            body = body[:heading.start()] + body[heading.end():]
        languages[code] = {"label": heading.group(1) if heading else code, "blocks": _blocks(body)}
    missing = [code for code in LANGUAGES if not (languages.get(code) or {}).get("blocks")]
    if missing:
        raise ValueError(f"{DOC_NAME} has no text for: {', '.join(missing)}")
    # Adding a translation does not change the accepted safety obligations or create an acceptance.
    return {"version": IOT_DISCLAIMER_VERSION, "doc": DOC_NAME, "source_language": "en",
            "translation_only": True, "languages": {code: languages[code] for code in LANGUAGES}}
