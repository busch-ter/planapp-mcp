from client.fastapi_client import FastAPIClient


FASTAPI_URL = "http://localhost:8080"

_client = FastAPIClient(
    base_url=FASTAPI_URL,
    timeout=120,
)


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
    """

    set_result = _client.set_link(
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

    prepare_result = _client.prepare_profiles()

    features_result = _client.link_features()

    return {
        "set_link": set_result,
        "prepare_profiles": prepare_result,
        "link_features": features_result,
    }
