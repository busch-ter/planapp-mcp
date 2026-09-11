import requests


def register_geocode_tools(mcp, client):

    @mcp.tool()
    def geocode_place(query: str) -> dict:
        """
        Converte um nome de lugar ou endereço em coordenadas geográficas.

        Usa o serviço Nominatim/OpenStreetMap.

        Retorna o formato esperado pelo PlanAppAgent:

            {
                "status": "OK",
                "results": [
                    {
                        "name": "...",
                        "lat": ...,
                        "lon": ...
                    }
                ]
            }

        Também preserva algumas informações adicionais do Nominatim.
        """

        # ----------------------------------------------------
        # Validação da consulta
        # ----------------------------------------------------

        if not query or not query.strip():
            return {
                "status": "ERROR",
                "error_type": "ValueError",
                "error": "A consulta de geocodificação não pode ser vazia.",
                "query": query,
            }

        query = query.strip()

        # ----------------------------------------------------
        # Nominatim / OpenStreetMap
        # ----------------------------------------------------

        url = "https://nominatim.openstreetmap.org/search"

        params = {
            "q": query,
            "format": "jsonv2",
            "limit": 1,
            "addressdetails": 1,
        }

        headers = {
            "User-Agent": (
                "PlanApp/1.0 "
                "(PlanApp geospatial planning prototype)"
            )
        }

        try:

            response = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=20,
            )

            response.raise_for_status()

            results = response.json()

        except Exception as exc:

            return {
                "status": "ERROR",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "query": query,
            }

        # ----------------------------------------------------
        # Nenhum resultado
        # ----------------------------------------------------

        if not results:

            return {
                "status": "NOT_FOUND",
                "query": query,
                "results": [],
                "message": "Nenhum local foi encontrado.",
            }

        # ----------------------------------------------------
        # Primeiro resultado
        # ----------------------------------------------------

        result = results[0]

        try:

            latitude = float(result["lat"])
            longitude = float(result["lon"])

        except (KeyError, TypeError, ValueError) as exc:

            return {
                "status": "ERROR",
                "error_type": type(exc).__name__,
                "error": (
                    "Resposta de geocodificação "
                    "sem coordenadas válidas."
                ),
                "query": query,
                "results": [],
                "raw_result": result,
            }

        # ----------------------------------------------------
        # Nome do local
        # ----------------------------------------------------

        name = (
            result.get("name")
            or result.get("display_name")
            or query
        )

        # ----------------------------------------------------
        # Formato compatível com agent_jupyter.py
        # ----------------------------------------------------

        return {
            "status": "OK",
            "query": query,

            "results": [
                {
                    "name": name,
                    "lat": latitude,
                    "lon": longitude,

                    # Informações adicionais
                    "display_name": result.get("display_name"),
                    "type": result.get("type"),
                    "category": result.get("category"),
                    "address": result.get("address", {}),
                }
            ],
        }