from client.fastapi_client import FastAPIClient


def register_link_tools(mcp, client: FastAPIClient):
    """
    Registra no MCP as ferramentas relacionadas à avaliação
    de enlaces do PlanApp.
    """

    # ========================================================
    # Evaluate Link
    # ========================================================

    @mcp.tool()
    def evaluate_link(
        tx_lat: float,
        tx_lon: float,
        rx_lat: float,
        rx_lon: float,
        tx_ha: float = 7,
        rx_ha: float = 7,
        freq_mhz: float = 900,
        tx_ha_abs: float | None = None,
        rx_ha_abs: float | None = None,
        on_rooftop: bool = False,
    ) -> dict:
        """
        Avalia um enlace ponto-a-ponto no PlanApp.

        O processo executado é:

            set_link
                ↓
            prepare_profiles
                ↓
            link_features

        Retorna os link_features calculados pelo PlanApp.
        """

        # ----------------------------------------------------
        # 1. Define o enlace
        # ----------------------------------------------------

        set_result = client.set_link(
            tx_lat=tx_lat,
            tx_lon=tx_lon,
            rx_lat=rx_lat,
            rx_lon=rx_lon,
            tx_ha=tx_ha,
            rx_ha=rx_ha,
            freq_mhz=freq_mhz,
            tx_ha_abs=tx_ha_abs,
            rx_ha_abs=rx_ha_abs,
            on_rooftop=on_rooftop,
        )

        # ----------------------------------------------------
        # 2. Prepara os perfis
        # ----------------------------------------------------

        prepare_result = client.prepare_profiles()

        # ----------------------------------------------------
        # 3. Avalia o enlace
        # ----------------------------------------------------

        features_result = client.link_features()

        # ----------------------------------------------------
        # 4. Retorna resultado
        # ----------------------------------------------------

        return {
            "set_link": set_result,
            "prepare_profiles": prepare_result,
            "link_features": features_result,
        }
