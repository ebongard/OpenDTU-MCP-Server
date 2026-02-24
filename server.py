"""
OpenDTU MCP Server

Ermöglicht KI-Assistenten, Wechselrichter-Limits via OpenDTU REST-API
abzufragen und (temporär, nicht-persistent) zu setzen.

Konfiguration via Umgebungsvariablen:
  OPENDTU_HOST      - IP oder Hostname der OpenDTU (z.B. "192.168.1.100" oder "opendtu.local")
  OPENDTU_USER      - Benutzername (Standard: "admin")
  OPENDTU_PASSWORD  - Passwort (Standard: "openDTU42")
"""

import json
import os
from enum import IntEnum
from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

OPENDTU_HOST = os.getenv("OPENDTU_HOST", "")
OPENDTU_USER = os.getenv("OPENDTU_USER", "admin")
OPENDTU_PASSWORD = os.getenv("OPENDTU_PASSWORD", "openDTU42")

REQUEST_TIMEOUT = 10.0  # Sekunden

# ---------------------------------------------------------------------------
# Limit-Typen
# ---------------------------------------------------------------------------

class LimitType(IntEnum):
    ABSOLUTE_NON_PERSISTENT = 0   # Watt, temporär (empfohlen)
    RELATIVE_NON_PERSISTENT = 1   # Prozent, temporär (empfohlen)
    ABSOLUTE_PERSISTENT = 256     # Watt, dauerhaft (schreibt EEPROM!)
    RELATIVE_PERSISTENT = 257     # Prozent, dauerhaft (schreibt EEPROM!)


LIMIT_TYPE_LABELS = {
    LimitType.ABSOLUTE_NON_PERSISTENT: "Absolut, temporär (W)",
    LimitType.RELATIVE_NON_PERSISTENT: "Relativ, temporär (%)",
    LimitType.ABSOLUTE_PERSISTENT: "⚠️ Absolut, dauerhaft (W) – schreibt EEPROM!",
    LimitType.RELATIVE_PERSISTENT: "⚠️ Relativ, dauerhaft (%) – schreibt EEPROM!",
}

# ---------------------------------------------------------------------------
# MCP-Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "opendtu_mcp",
    instructions=(
        "Dieser Server ermöglicht das Abfragen und Setzen von Wechselrichter-Limits "
        "über eine OpenDTU-Instanz. Für schreibende Operationen ist Authentifizierung "
        "erforderlich. Bevorzuge immer nicht-persistente (temporäre) Limits, um den "
        "EEPROM-Speicher der Wechselrichter zu schonen."
    ),
)

# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _base_url() -> str:
    if not OPENDTU_HOST:
        raise ValueError(
            "OPENDTU_HOST ist nicht gesetzt. Bitte Umgebungsvariable OPENDTU_HOST "
            "mit IP oder Hostname der OpenDTU setzen (z.B. '192.168.1.100')."
        )
    host = OPENDTU_HOST.rstrip("/")
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"
    return host


def _auth() -> httpx.BasicAuth:
    return httpx.BasicAuth(OPENDTU_USER, OPENDTU_PASSWORD)


def _handle_error(e: Exception) -> str:
    if isinstance(e, ValueError):
        return f"❌ Konfigurationsfehler: {e}"
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        if code == 401:
            return "❌ Authentifizierung fehlgeschlagen. Bitte OPENDTU_USER und OPENDTU_PASSWORD prüfen."
        if code == 403:
            return "❌ Zugriff verweigert. Readonly-Modus aktiv oder fehlende Rechte."
        if code == 404:
            return "❌ Endpunkt nicht gefunden. Bitte OpenDTU-Version prüfen."
        return f"❌ HTTP-Fehler {code}: {e.response.text[:200]}"
    if isinstance(e, httpx.ConnectError):
        return f"❌ Verbindung zu OpenDTU ({OPENDTU_HOST}) fehlgeschlagen. Host erreichbar?"
    if isinstance(e, httpx.TimeoutException):
        return f"❌ Zeitüberschreitung beim Verbinden mit {OPENDTU_HOST}."
    return f"❌ Unerwarteter Fehler: {type(e).__name__}: {e}"


async def _get(path: str, auth: bool = False) -> dict:
    """Führt einen GET-Request gegen die OpenDTU-API aus."""
    url = f"{_base_url()}{path}"
    kwargs: dict = {"timeout": REQUEST_TIMEOUT}
    if auth:
        kwargs["auth"] = _auth()
    async with httpx.AsyncClient() as client:
        response = await client.get(url, **kwargs)
        response.raise_for_status()
        return response.json()


async def _post_form(path: str, data: str) -> dict:
    """Führt einen POST-Request mit form-encoded Daten und Authentifizierung aus."""
    url = f"{_base_url()}{path}"
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            content=f"data={data}",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            auth=_auth(),
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()


# ---------------------------------------------------------------------------
# Pydantic-Eingabemodelle
# ---------------------------------------------------------------------------

class GetLimitStatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    serial: Optional[str] = Field(
        default=None,
        description=(
            "Seriennummer des Wechselrichters (z.B. '114181800001'). "
            "Wenn leer, werden alle Wechselrichter zurückgegeben."
        ),
    )


class SetLimitInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    serial: str = Field(
        ...,
        description="Seriennummer des Wechselrichters (z.B. '114181800001').",
        min_length=6,
        max_length=20,
    )
    limit_value: float = Field(
        ...,
        description=(
            "Limitwert: Watt (bei absoluten Limits) oder Prozent 0–100 (bei relativen Limits). "
            "Beispiel: 300 für 300 W oder 50 für 50 %."
        ),
        ge=0,
        le=100000,
    )
    limit_type: int = Field(
        default=int(LimitType.RELATIVE_NON_PERSISTENT),
        description=(
            "Typ des Limits: "
            "0 = Absolut, temporär (W) | "
            "1 = Relativ, temporär (%) – Standard | "
            "256 = Absolut, dauerhaft (W, schreibt EEPROM!) | "
            "257 = Relativ, dauerhaft (%, schreibt EEPROM!)"
        ),
    )

    @field_validator("limit_type")
    @classmethod
    def validate_limit_type(cls, v: int) -> int:
        valid = {int(t) for t in LimitType}
        if v not in valid:
            raise ValueError(f"Ungültiger limit_type '{v}'. Erlaubt: {sorted(valid)}")
        return v

    @field_validator("limit_value")
    @classmethod
    def validate_relative_range(cls, v: float) -> float:
        # Wird beim Setzen erneut geprüft, wenn limit_type bekannt ist
        return v


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool(
    name="opendtu_get_inverters",
    annotations={
        "title": "Wechselrichter auflisten",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def opendtu_get_inverters() -> str:
    """Listet alle konfigurierten Wechselrichter mit Livedaten auf.

    Gibt eine Übersicht aller in OpenDTU konfigurierten Wechselrichter zurück,
    inklusive Seriennummer, Name, Erreichbarkeit, aktueller Leistung und
    dem konfigurierten Limit.

    Returns:
        str: Markdown-formatierte Tabelle aller Wechselrichter mit:
            - serial (str): Seriennummer
            - name (str): Name
            - reachable (bool): Aktuell erreichbar
            - producing (bool): Produziert gerade Strom
            - limit_relative (float): Aktuelles Limit in Prozent
            - limit_absolute (float): Aktuelles Limit in Watt (-1 = unbekannt)
    """
    try:
        data = await _get("/api/livedata/status")
    except Exception as e:
        return _handle_error(e)

    inverters = data.get("inverters", [])
    if not inverters:
        return "ℹ️ Keine Wechselrichter in OpenDTU konfiguriert."

    total = data.get("total", {})
    total_power = total.get("Power", {}).get("v", 0)
    total_yield_day = total.get("YieldDay", {}).get("v", 0)
    total_yield_total = total.get("YieldTotal", {}).get("v", 0)

    lines = [
        "## Wechselrichter-Übersicht",
        "",
        f"**Gesamtleistung:** {total_power:.1f} W  "
        f"| **Ertrag heute:** {total_yield_day:.0f} Wh  "
        f"| **Gesamtertrag:** {total_yield_total:.3f} kWh",
        "",
        "| Seriennummer | Name | Erreichbar | Produziert | Limit (%) | Limit (W) |",
        "|---|---|---|---|---|---|",
    ]

    for inv in inverters:
        serial = inv.get("serial", "–")
        name = inv.get("name", "–")
        reachable = "✅ Ja" if inv.get("reachable") else "❌ Nein"
        producing = "✅ Ja" if inv.get("producing") else "❌ Nein"
        limit_rel = inv.get("limit_relative", "–")
        limit_abs = inv.get("limit_absolute", -1)
        limit_abs_str = f"{limit_abs:.0f}" if limit_abs >= 0 else "–"
        lines.append(f"| `{serial}` | {name} | {reachable} | {producing} | {limit_rel} % | {limit_abs_str} W |")

    return "\n".join(lines)


@mcp.tool(
    name="opendtu_get_limit_status",
    annotations={
        "title": "Limit-Status abfragen",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def opendtu_get_limit_status(params: GetLimitStatusInput) -> str:
    """Fragt den aktuellen Limit-Status aller oder eines bestimmten Wechselrichters ab.

    Gibt das aktuelle Leistungslimit jedes Wechselrichters zurück: relatives Limit (%)
    und maximale Nennleistung sowie den Status der letzten Limit-Änderung.

    Args:
        params (GetLimitStatusInput):
            - serial (Optional[str]): Seriennummer für Filterung. Wenn leer → alle.

    Returns:
        str: Markdown-Tabelle mit:
            - serial (str): Seriennummer
            - limit_relative (float): Aktuelles Limit in % der Nennleistung
            - max_power (float): Maximale Nennleistung in Watt
            - current_limit_w (float): Berechnetes aktuelles Limit in Watt
            - limit_set_status (str): Status: "Ok", "Pending", "Failure"
    """
    try:
        data = await _get("/api/limit/status")
    except Exception as e:
        return _handle_error(e)

    if not data:
        return "ℹ️ Keine Wechselrichter gefunden."

    # Optionaler Filter nach Seriennummer
    target = params.serial.strip() if params.serial else None
    if target and target not in data:
        available = ", ".join(f"`{s}`" for s in data.keys())
        return (
            f"❌ Seriennummer `{target}` nicht gefunden.\n"
            f"Verfügbare Seriennummern: {available}"
        )

    items = {target: data[target]} if target else data

    lines = [
        "## Limit-Status",
        "",
        "| Seriennummer | Limit (%) | Max. Leistung (W) | Aktuelles Limit (W) | Status |",
        "|---|---|---|---|---|",
    ]

    for serial, info in items.items():
        limit_rel = info.get("limit_relative", 0)
        max_power = info.get("max_power", 0)
        current_w = round(limit_rel / 100 * max_power, 1) if max_power else "–"
        status_raw = info.get("limit_set_status", "–")
        status = {"Ok": "✅ Ok", "Pending": "⏳ Ausstehend", "Failure": "❌ Fehler"}.get(
            status_raw, status_raw
        )
        lines.append(
            f"| `{serial}` | {limit_rel} % | {max_power} W | {current_w} W | {status} |"
        )

    return "\n".join(lines)


@mcp.tool(
    name="opendtu_set_limit",
    annotations={
        "title": "Wechselrichter-Limit setzen",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def opendtu_set_limit(params: SetLimitInput) -> str:
    """Setzt das Leistungslimit eines Wechselrichters (standardmäßig temporär/nicht-persistent).

    ⚠️ WICHTIG: Verwende bevorzugt nicht-persistente Limits (limit_type 0 oder 1), da
    persistente Limits den EEPROM des Wechselrichters beschreiben und dessen Lebensdauer
    begrenzen.

    Args:
        params (SetLimitInput):
            - serial (str): Seriennummer des Wechselrichters
            - limit_value (float): Limitwert (Watt oder Prozent je nach limit_type)
            - limit_type (int): 0=Absolut temporär, 1=Relativ temporär (Standard),
                               256=Absolut dauerhaft, 257=Relativ dauerhaft

    Returns:
        str: Bestätigung mit gesetztem Limit und Hinweis auf Pending-Status.
    """
    lt = LimitType(params.limit_type)

    # Wertebereich-Prüfung für relative Limits
    if lt in (LimitType.RELATIVE_NON_PERSISTENT, LimitType.RELATIVE_PERSISTENT):
        if not (0 <= params.limit_value <= 100):
            return (
                f"❌ Bei relativem Limit muss der Wert zwischen 0 und 100 (%) liegen. "
                f"Angegeben: {params.limit_value}"
            )

    # Warnung bei persistentem Limit
    persistent_warning = ""
    if lt in (LimitType.ABSOLUTE_PERSISTENT, LimitType.RELATIVE_PERSISTENT):
        persistent_warning = (
            "\n\n⚠️ **Warnung:** Du hast ein *dauerhaftes* Limit gesetzt, das den "
            "EEPROM des Wechselrichters beschreibt. Häufige Änderungen verkürzen dessen "
            "Lebensdauer. Bevorzuge temporäre Limits (limit_type 0 oder 1)."
        )

    payload = json.dumps({
        "serial": params.serial,
        "limit_type": params.limit_type,
        "limit_value": params.limit_value,
    })

    try:
        result = await _post_form("/api/limit/config", payload)
    except Exception as e:
        return _handle_error(e)

    result_type = result.get("type", "")
    message = result.get("message", "")

    if result_type == "success":
        unit = "%" if lt in (LimitType.RELATIVE_NON_PERSISTENT, LimitType.RELATIVE_PERSISTENT) else "W"
        limit_label = LIMIT_TYPE_LABELS[lt]
        response = (
            f"✅ Limit erfolgreich gesetzt!\n\n"
            f"- **Wechselrichter:** `{params.serial}`\n"
            f"- **Neues Limit:** {params.limit_value} {unit}\n"
            f"- **Typ:** {limit_label}\n\n"
            f"⏳ Das Limit wird an den Wechselrichter übermittelt. "
            f"Status kurz nach dem Setzen: *Ausstehend* – nach einigen Sekunden *Ok*. "
            f"Mit `opendtu_get_limit_status` prüfen."
            f"{persistent_warning}"
        )
        return response

    # Fehler oder Warnung
    return (
        f"⚠️ Antwort von OpenDTU: **{result_type}** – {message}\n\n"
        f"Payload: `{payload}`\n\n"
        f"Tipp: Seriennummer mit `opendtu_get_inverters` prüfen."
    )


# ---------------------------------------------------------------------------
# Einstiegspunkt
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if not OPENDTU_HOST:
        print(
            "⚠️  Umgebungsvariable OPENDTU_HOST nicht gesetzt!\n"
            "   Beispiel: export OPENDTU_HOST=192.168.1.100\n"
        )
    mcp.run()
