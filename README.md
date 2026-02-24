# OpenDTU MCP Server

Ein MCP-Server (Model Context Protocol) für [OpenDTU](https://github.com/tbnobody/OpenDTU), mit dem KI-Assistenten (z.B. Claude) Wechselrichter-Limits über die OpenDTU REST-API **abfragen und temporär setzen** können.

## Verfügbare Tools

| Tool | Beschreibung |
|---|---|
| `opendtu_get_inverters` | Listet alle Wechselrichter mit Livedaten auf |
| `opendtu_get_limit_status` | Zeigt das aktuelle Leistungslimit aller oder eines Wechselrichters |
| `opendtu_set_limit` | Setzt ein (temporäres) Leistungslimit für einen Wechselrichter |

## Limit-Typen

| Wert | Bedeutung | Empfehlung |
|---|---|---|
| `0` | Absolut, temporär (Watt) | ✅ Empfohlen |
| `1` | Relativ, temporär (%) | ✅ Empfohlen (Standard) |
| `256` | Absolut, dauerhaft (Watt) | ⚠️ Schreibt EEPROM |
| `257` | Relativ, dauerhaft (%) | ⚠️ Schreibt EEPROM |

> **Hinweis:** Persistente Limits schreiben in den EEPROM des Wechselrichters. Häufige Änderungen verkürzen dessen Lebensdauer. Bevorzuge immer temporäre Limits.

## Installation

```bash
pip install mcp httpx
```

## Konfiguration

Der Server wird über Umgebungsvariablen konfiguriert:

| Variable | Standard | Beschreibung |
|---|---|---|
| `OPENDTU_HOST` | *(leer)* | **Pflichtfeld.** IP oder Hostname der OpenDTU (z.B. `192.168.1.100` oder `opendtu.local`) |
| `OPENDTU_USER` | `admin` | Benutzername für die OpenDTU-Weboberfläche |
| `OPENDTU_PASSWORD` | `openDTU42` | Passwort |

## Claude Desktop / Claude.ai Konfiguration

In der `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "opendtu": {
      "command": "python",
      "args": ["/pfad/zu/opendtu_mcp/server.py"],
      "env": {
        "OPENDTU_HOST": "192.168.1.100",
        "OPENDTU_USER": "admin",
        "OPENDTU_PASSWORD": "deinPasswort"
      }
    }
  }
}
```

## Starten (lokal testen)

```bash
export OPENDTU_HOST=192.168.1.100
export OPENDTU_USER=admin
export OPENDTU_PASSWORD=openDTU42

python server.py
```

## Beispiel-Dialoge mit Claude

**Alle Wechselrichter anzeigen:**
> "Zeig mir alle Wechselrichter und ihre aktuelle Leistung."

**Limit abfragen:**
> "Wie ist das aktuelle Limit meines Wechselrichters?"

**Limit setzen (relativ):**
> "Setze den Wechselrichter 114181800001 auf 70 %."

**Limit setzen (absolut):**
> "Begrenze den Wechselrichter auf 300 Watt."

## OpenDTU API-Endpunkte

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `GET` | `/api/livedata/status` | Livedaten aller Wechselrichter |
| `GET` | `/api/limit/status` | Aktuelles Limit aller Wechselrichter |
| `POST` | `/api/limit/config` | Limit setzen (erfordert Auth) |

## Voraussetzungen

- OpenDTU läuft im lokalen Netzwerk und ist erreichbar
- Python 3.10+
- Pakete: `mcp`, `httpx`, `pydantic`
