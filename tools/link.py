from client.fastapi_client import FastAPIClient


def register_link_tools(mcp, client: FastAPIClient):

    @mcp.tool()
    def evaluate_link(
        tx_lat: float,
        tx_lon: float,
        rx_lat: float,
        rx_lon: float,
        tx_ha: float = 7,
        rx_ha: float = 7,
        freq_mhz: float = 900,
        on_rooftop: bool = False,
    ) -> dict:
        """
        Avalia um enlace ponto-a-ponto no PlanApp.

        Executa:

            set_link
                ↓
            prepare_profiles
                ↓
            link_features

        Retorna os resultados calculados pelo PlanApp.

        Em caso de erro, retorna também a etapa e a exceção
        original para facilitar o diagnóstico.
        """

        # ====================================================
        # 1. SET LINK
        # ====================================================

        try:

            set_result = client.set_link(
                tx_lat=tx_lat,
                tx_lon=tx_lon,
                rx_lat=rx_lat,
                rx_lon=rx_lon,
                tx_ha=tx_ha,
                rx_ha=rx_ha,
                freq_mhz=freq_mhz,
                on_rooftop=on_rooftop,
            )

        except Exception as e:

            return {
                "status": "ERROR",
                "stage": "set_link",
                "error_type": type(e).__name__,
                "error": str(e),
            }

        # ====================================================
        # 2. PREPARE PROFILES
        # ====================================================

        try:

            prepare_result = client.prepare_profiles()

        except Exception as e:

            return {
                "status": "ERROR",
                "stage": "prepare_profiles",
                "error_type": type(e).__name__,
                "error": str(e),
                "set_link": set_result,
            }

        # ====================================================
        # 3. LINK FEATURES
        # ====================================================

        try:

            features_result = client.link_features()

        except Exception as e:

            return {
                "status": "ERROR",
                "stage": "link_features",
                "error_type": type(e).__name__,
                "error": str(e),
                "set_link": set_result,
                "prepare_profiles": prepare_result,
            }

        # ====================================================
        # SUCESSO
        # ====================================================

        return {
            "status": "OK",
            "set_link": set_result,
            "prepare_profiles": prepare_result,
            "link_features": features_result,
        }
