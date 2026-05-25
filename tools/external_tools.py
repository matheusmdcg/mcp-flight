import json
import os
from datetime import datetime
from typing import Any, Callable, Dict, Optional
from urllib.parse import quote

import requests


def register_external_tools(
    mcp: Any,
    *,
    get_serpapi_key: Callable[[], str],
    normalize_location_id: Callable[[str], str],
    flights_dir: str,
) -> None:
    
    @mcp.tool()
    def search_flights(
        departure_id: str,
        arrival_id: str,
        outbound_date: str,
        return_date: Optional[str] = None,
        trip_type: int = 1,
        adults: int = 1,
        children: int = 0,
        infants_in_seat: int = 0,
        infants_on_lap: int = 0,
        travel_class: int = 1,
        currency: str = "USD",
        country: str = "us",
        language: str = "en",
        max_results: int = 10
    ) -> Dict[str, Any]:
        """
        Search for flights using SerpAPI's Google Flights API.
        
        Args:
            departure_id: Departure airport code (e.g., 'LAX', 'JFK') or location kgmid
            arrival_id: Arrival airport code (e.g., 'CDG', 'LHR') or location kgmid
            outbound_date: Departure date in YYYY-MM-DD format (e.g., '2024-12-15')
            return_date: Return date in YYYY-MM-DD format (required for round trips)
            trip_type: Flight type (1=Round trip, 2=One way, 3=Multi-city)
            adults: Number of adult passengers (default: 1)
            children: Number of child passengers (default: 0)
            infants_in_seat: Number of infants in seat (default: 0)
            infants_on_lap: Number of infants on lap (default: 0)
            travel_class: Travel class (1=Economy, 2=Premium economy, 3=Business, 4=First)
            currency: Currency for prices (default: 'USD')
            country: Country code for search (default: 'us')
            language: Language code (default: 'en')
            max_results: Maximum number of results to store (default: 10)
            
        Returns:
            Dict containing flight search results and metadata
        """
        
        try:
            api_key = get_serpapi_key()
            dep_id = normalize_location_id(departure_id)
            arr_id = normalize_location_id(arrival_id)

            # Build search parameters
            params = {
                "engine": "google_flights",
                "api_key": api_key,
                "departure_id": dep_id,
                "arrival_id": arr_id,
                "outbound_date": outbound_date,
                "type": trip_type,
                "adults": adults,
                "children": children,
                "infants_in_seat": infants_in_seat,
                "infants_on_lap": infants_on_lap,
                "travel_class": travel_class,
                "currency": currency,
                "gl": country,
                "hl": language
            }
            
            # Add return date for round trips
            if trip_type == 1 and return_date:
                params["return_date"] = return_date
            elif trip_type == 1 and not return_date:
                return {"error": "Return date is required for round trip flights"}
            
            # Make API request
            response = requests.get("https://serpapi.com/search", params=params)
            response.raise_for_status()
            
            flight_data = response.json()
            
            # Create search identifier
            search_id = f"{dep_id}_{arr_id}_{outbound_date}"
            if return_date:
                search_id += f"_{return_date}"
            search_id += f"_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            # Create directory structure
            os.makedirs(flights_dir, exist_ok=True)
            
            # Process and store flight results
            processed_results = {
                "search_metadata": {
                    "search_id": search_id,
                    "departure": dep_id,
                    "arrival": arr_id,
                    "outbound_date": outbound_date,
                    "return_date": return_date,
                    "trip_type": "Round trip" if trip_type == 1 else "One way" if trip_type == 2 else "Multi-city",
                    "passengers": {
                        "adults": adults,
                        "children": children,
                        "infants_in_seat": infants_in_seat,
                        "infants_on_lap": infants_on_lap
                    },
                    "travel_class": ["Economy", "Premium economy", "Business", "First"][travel_class - 1],
                    "currency": currency,
                    "search_timestamp": datetime.now().isoformat()
                },
                "best_flights": flight_data.get("best_flights", [])[:max_results],
                "other_flights": flight_data.get("other_flights", [])[:max_results],
                "price_insights": flight_data.get("price_insights", {}),
                "airports": flight_data.get("airports", [])
            }
            
            # Save results to file
            file_path = os.path.join(flights_dir, f"{search_id}.json")
            with open(file_path, "w") as f:
                json.dump(processed_results, f, indent=2)
            
            print(f"Flight search results saved to: {file_path}")
            
            # Return summary for the user
            summary = {
                "search_id": search_id,
                "total_best_flights": len(processed_results["best_flights"]),
                "total_other_flights": len(processed_results["other_flights"]),
                "price_range": {
                    "lowest_price": processed_results["price_insights"].get("lowest_price"),
                    "currency": currency
                },
                "search_parameters": processed_results["search_metadata"]
            }
            
            return summary
            
        except requests.exceptions.RequestException as e:
            return {"error": f"API request failed: {str(e)}"}
        except ValueError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"Unexpected error: {str(e)}"}

    @mcp.tool()
    def get_flight_details(search_id: str) -> str:
        """
        Get detailed information about a specific flight search.
        
        Args:
            search_id: The search ID returned from search_flights
            
        Returns:
            JSON string with detailed flight information
        """
        
        file_path = os.path.join(flights_dir, f"{search_id}.json")
        
        if not os.path.exists(file_path):
            return f"No flight search found with ID: {search_id}"
        
        try:
            with open(file_path, "r") as f:
                flight_data = json.load(f)
            return json.dumps(flight_data, indent=2)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            return f"Error reading flight data for {search_id}: {str(e)}"


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
    # @mcp.tool()
    def list_flight_options(search_id: str, limit: int = 10, prefer: str = "best") -> Dict[str, Any]:
        """
        Lê o arquivo flights/{search_id}.json e gera uma lista curta e estável de opções com option_id.
        Útil para o usuário escolher 'livremente' um voo.
        """
        _ensure_dir(flights_dir)
        path = os.path.join(flights_dir, f"{search_id}.json")
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
        _ensure_dir(flights_dir)

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

        _write_json(os.path.join(flights_dir, f"{trip_id}.json"), plan)
        return plan

    # ----------------------------
    # 4) Selecionar voo no plano (handoff do agente de voos -> Supervisor)
    # ----------------------------
    # @mcp.tool()
    def set_selected_flight(trip_id: str, search_id: str, option_id: str) -> Dict[str, Any]:
        """
        Salva no plano a referência do voo escolhido (search_id + option_id).
        """
        _ensure_dir(flights_dir)
        path = os.path.join(flights_dir, f"{trip_id}.json")
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
        Salva no plano a hospedagem escolhida e retorna os dados mockados da API.
        """
        # Mock de banco de dados de hotéis (Simulando a resposta de uma API externa)
        mock_stays_database = {
            "hotel_001": {
                "name": "Grand Plaza Hotel",
                "address": "Av. Paulista, 1234 - São Paulo",
                "stars": 4.5,
                "price_per_night": 450.00,
                "currency": "BRL",
                "amenities": ["Wi-Fi Grátis", "Piscina", "Café da Manhã Incluso"],
                "check_in": "14:00",
                "check_out": "12:00"
            },
            "hotel_002": {
                "name": "Copacabana Beach Resort",
                "address": "Av. Atlântica, 500 - Rio de Janeiro",
                "stars": 5.0,
                "price_per_night": 890.00,
                "currency": "BRL",
                "amenities": ["Frente para o Mar", "Spa", "Academia", "Bar no Rooftop"],
                "check_in": "15:00",
                "check_out": "11:00"
            }
        }

        # Busca o hotel no mock ou usa um fallback genérico caso o ID não exista
        stay_details = mock_stays_database.get(
            stay_id, 
            {
                "name": "Hotel Padrão Selecionado",
                "address": "Endereço em análise",
                "stars": 4.0,
                "price_per_night": 300.00,
                "currency": "BRL",
                "amenities": ["Wi-Fi"],
                "check_in": "14:00",
                "check_out": "12:00"
            }
        )

        # Retorno estruturado simulando o sucesso da operação na API
        return {
            "status": "success",
            "trip_id": trip_id,
            "stay_id": stay_id,
            "booking_status": "CONFIRMED_IN_PLAN",
            "stay_details": stay_details,
            "message": f"Hospedagem '{stay_details['name']}' vinculada com sucesso à viagem {trip_id}."
        }

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

