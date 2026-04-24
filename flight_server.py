import os
import json
import asyncio
from typing import Dict, Any, Optional, List
from datetime import datetime
from mcp.server.fastmcp import FastMCP

# Reaproveita o estilo do seu server atual (host/port via env)
def _listen_host() -> str:
    if os.environ.get("MCP_TRANSPORT", "").lower() == "sse":
        return os.environ.get("FASTMCP_HOST", "0.0.0.0")
    return "127.0.0.1"

def _listen_port() -> int:
    port_str = os.environ.get("PORT") or os.environ.get("FASTMCP_PORT")
    return int(port_str) if port_str else 8000

mcp = FastMCP("travel-mock-assistant", host=_listen_host(), port=_listen_port())

def get_serpapi_key() -> str:
    """Get SerpAPI key from environment variable."""
    api_key = os.getenv("SERPAPI_KEY")
    if not api_key:
        raise ValueError("SERPAPI_KEY environment variable is required")
    return api_key


def normalize_location_id(location_id: str) -> str:
    """Normalize SerpAPI location IDs (uppercase 3-letter IATA); keep Google kgmid paths."""
    trimmed = location_id.strip()
    if len(trimmed) == 3 and trimmed.isalpha():
        return trimmed.upper()
    return trimmed

FLIGHTS_DIR = "flights"     # segue a mesma ideia do seu arquivo atual
TRIPS_DIR = "trips"         # novo: onde vamos salvar planos

# ----------------------------
# Helpers de persistência
# ----------------------------
def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)

def _read_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _write_json(path: str, data: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ----------------------------
# 1) Resolver local (texto livre) -> candidatos (IATA mock)
# ----------------------------
@mcp.tool()
def resolve_location(query: str, country_hint: str = "BR") -> Dict[str, Any]:
    """
    Resolve um texto livre (ex.: 'São Paulo', 'NYC', 'GRU') em candidatos de aeroportos/cidades.
    Retorna dados mock (bom para testar roteamento e validação).
    """
    q = (query or "").strip().lower()

    # Base mock pequena, determinística
    db = [
        {"type": "airport", "name": "São Paulo/Guarulhos", "iata": "GRU", "city": "São Paulo", "country": "BR"},
        {"type": "airport", "name": "São Paulo/Congonhas", "iata": "CGH", "city": "São Paulo", "country": "BR"},
        {"type": "airport", "name": "Rio de Janeiro/Galeão", "iata": "GIG", "city": "Rio de Janeiro", "country": "BR"},
        {"type": "airport", "name": "New York/JFK", "iata": "JFK", "city": "New York", "country": "US"},
        {"type": "airport", "name": "New York/LaGuardia", "iata": "LGA", "city": "New York", "country": "US"},
        {"type": "airport", "name": "Paris/Charles de Gaulle", "iata": "CDG", "city": "Paris", "country": "FR"},
    ]

    # Match simples por substring
    candidates = []
    for item in db:
        hay = " ".join([item["name"], item["iata"], item["city"], item["country"]]).lower()
        if q and q in hay:
            candidates.append(item)

    # fallback: se digitou 3 letras, tenta match exato por IATA
    if not candidates and len(q) == 3 and q.isalpha():
        for item in db:
            if item["iata"].lower() == q:
                candidates.append(item)

    return {
        "query": query,
        "country_hint": country_hint,
        "candidates": candidates[:5],
        "note": "Dados mock para teste (não é lookup em tempo real)."
    }

# ----------------------------
# 2) Listar opções de voos a partir de um search_id salvo (UX para escolher)
#    (o seu server já salva JSON em flights/{search_id}.json)
# ----------------------------
@mcp.tool()
def list_flight_options(search_id: str, limit: int = 10, prefer: str = "best") -> Dict[str, Any]:
    """
    Lê o arquivo flights/{search_id}.json e gera uma lista curta e estável de opções com option_id.
    Útil para o usuário escolher 'livremente' um voo.
    """
    _ensure_dir(FLIGHTS_DIR)
    path = os.path.join(FLIGHTS_DIR, f"{search_id}.json")
    if not os.path.exists(path):
        return {"error": f"Nenhuma busca encontrada para search_id={search_id}"}

    data = _read_json(path)
    currency = (data.get("search_metadata", {}) or {}).get("currency", "USD")

    best = data.get("best_flights", []) or []
    other = data.get("other_flights", []) or []

    flights = best if prefer == "best" else other if prefer == "other" else (best + other)

    options = []
    for idx, f in enumerate(flights[: max(1, limit)]):
        flights_legs = f.get("flights", []) or []
        airlines = sorted({(leg.get("airline") or "").strip() for leg in flights_legs if leg.get("airline")})
        options.append({
            "option_id": f"{prefer}-{idx}",
            "price": f.get("price"),
            "currency": currency,
            "total_duration_minutes": f.get("total_duration"),
            "segments": len(flights_legs),
            "airlines": airlines,
        })

    return {
        "search_id": search_id,
        "prefer": prefer,
        "limit": limit,
        "options": options,
        "note": "option_id é estável apenas para a lista gerada (bom para teste de seleção)."
    }

# ----------------------------
# 3) Criar um plano de viagem (para o Supervisor manter estado entre agentes)
# ----------------------------
@mcp.tool()
def create_trip_plan(
    origin: str,
    destination: str,
    outbound_date: str,
    return_date: str = "",
    passengers: int = 1,
    budget: str = ""
) -> Dict[str, Any]:
    """
    Cria um 'trip plan' mínimo e salva em trips/{trip_id}.json.
    """
    _ensure_dir(TRIPS_DIR)

    trip_id = f"trip_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    plan = {
        "trip_id": trip_id,
        "created_at": datetime.now().isoformat(),
        "origin": origin,
        "destination": destination,
        "outbound_date": outbound_date,
        "return_date": return_date,
        "passengers": passengers,
        "budget": budget,
        "selected_flight": None,
        "selected_stay": None
    }

    _write_json(os.path.join(TRIPS_DIR, f"{trip_id}.json"), plan)
    return plan

# ----------------------------
# 4) Selecionar voo no plano (handoff do agente de voos -> Supervisor)
# ----------------------------
@mcp.tool()
def set_selected_flight(trip_id: str, search_id: str, option_id: str) -> Dict[str, Any]:
    """
    Salva no plano a referência do voo escolhido (search_id + option_id).
    """
    _ensure_dir(TRIPS_DIR)
    path = os.path.join(TRIPS_DIR, f"{trip_id}.json")
    if not os.path.exists(path):
        return {"error": f"Plano não encontrado: trip_id={trip_id}"}

    plan = _read_json(path)
    plan["selected_flight"] = {
        "search_id": search_id,
        "option_id": option_id,
        "selected_at": datetime.now().isoformat()
    }
    _write_json(path, plan)
    return plan

# ----------------------------
# 5) Busca mock de hospedagem (rápida) para substituir o seu search_hotels de timeout
# ----------------------------
@mcp.tool()
def search_stays_mock(city: str, check_in: str, check_out: str, guests: int = 1) -> Dict[str, Any]:
    """
    Retorna opções mock de hospedagem (não depende de API externa).
    Serve para testar o roteamento do agente de hotéis sem gerar timeout.
    """
    stays = [
        {"stay_id": "stay_001", "name": "Hotel Central", "neighborhood": "Centro", "price_per_night": 120},
        {"stay_id": "stay_002", "name": "Garden Inn", "neighborhood": "Jardins", "price_per_night": 180},
        {"stay_id": "stay_003", "name": "Budget Stay", "neighborhood": "Próximo ao metrô", "price_per_night": 80},
    ]

    return {
        "city": city,
        "check_in": check_in,
        "check_out": check_out,
        "guests": guests,
        "results": stays,
        "currency": "USD",
        "note": "Lista mock fixa para teste."
    }

# ----------------------------
# 6) Selecionar hospedagem no plano
# ----------------------------
@mcp.tool()
def set_selected_stay(trip_id: str, stay_id: str) -> Dict[str, Any]:
    """
    Salva no plano a hospedagem escolhida.
    """
    _ensure_dir(TRIPS_DIR)
    path = os.path.join(TRIPS_DIR, f"{trip_id}.json")
    if not os.path.exists(path):
        return {"error": f"Plano não encontrado: trip_id={trip_id}"}

    plan = _read_json(path)
    plan["selected_stay"] = {"stay_id": stay_id, "selected_at": datetime.now().isoformat()}
    _write_json(path, plan)
    return plan

# ----------------------------
# 7) Simulador de timeout/erro controlado (para testar robustez do Supervisor)
# ----------------------------
@mcp.tool()
async def simulate_provider_timeout(seconds: int = 15) -> Dict[str, Any]:
    """
    Simula lentidão. Útil para validar cancelamento, timeout e fallback no roteamento do agente.
    """
    await asyncio.sleep(max(0, seconds))
    return {"ok": True, "slept_seconds": seconds}

# ----------------------------
# (Opcional) manter a tool problemática comentada (se você quiser)
# ----------------------------
# @mcp.tool()
# async def search_hotels(city: str, check_in: str, check_out: str, guests: int) -> str:
#     await asyncio.sleep(180)
#     return f"search_hotels finished after 180s — city={city!r}, check_in={check_in!r}, check_out={check_out!r}, guests={guests}"
