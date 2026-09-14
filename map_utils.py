# ============================================================
# PLANAPP AI
# map_utils.py
# ============================================================

from ipyleaflet import (
    Map,
    Marker,
    Polyline,
)


def mostrar_mapa_enlace(
    tx_lat,
    tx_lon,
    rx_lat,
    rx_lon,
    margin=0.20,
    min_span=0.005,
    min_zoom=10,
    max_zoom=18,
):
    """
    Cria e retorna o mapa do enlace.

    Parâmetros
    ----------
    tx_lat : float
        Latitude do transmissor.

    tx_lon : float
        Longitude do transmissor.

    rx_lat : float
        Latitude do receptor.

    rx_lon : float
        Longitude do receptor.

    margin : float
        Margem percentual aplicada aos limites do mapa.

    min_span : float
        Extensão mínima dos limites em graus.

    min_zoom : int
        Zoom inicial do mapa.

    max_zoom : int
        Reservado para controle futuro do zoom máximo.

    Retorno
    -------
    ipyleaflet.Map
        Widget de mapa pronto para ser exibido pelo Jupyter.

    IMPORTANTE
    ----------
    Esta função NÃO executa display().
    """

    # ========================================================
    # COORDENADAS
    # ========================================================

    try:

        tx_lat = float(tx_lat)
        tx_lon = float(tx_lon)

        rx_lat = float(rx_lat)
        rx_lon = float(rx_lon)

    except (TypeError, ValueError) as exc:

        raise ValueError(
            "Coordenadas TX/RX inválidas."
        ) from exc

    # ========================================================
    # VALIDAÇÃO
    # ========================================================

    if not (
        -90.0 <= tx_lat <= 90.0
    ):
        raise ValueError(
            f"Latitude TX inválida: {tx_lat}"
        )

    if not (
        -180.0 <= tx_lon <= 180.0
    ):
        raise ValueError(
            f"Longitude TX inválida: {tx_lon}"
        )

    if not (
        -90.0 <= rx_lat <= 90.0
    ):
        raise ValueError(
            f"Latitude RX inválida: {rx_lat}"
        )

    if not (
        -180.0 <= rx_lon <= 180.0
    ):
        raise ValueError(
            f"Longitude RX inválida: {rx_lon}"
        )

    # ========================================================
    # CENTRO
    # ========================================================

    center_lat = (
        tx_lat + rx_lat
    ) / 2.0

    center_lon = (
        tx_lon + rx_lon
    ) / 2.0

    # ========================================================
    # BOUNDS
    # ========================================================

    lat_min = min(
        tx_lat,
        rx_lat,
    )

    lat_max = max(
        tx_lat,
        rx_lat,
    )

    lon_min = min(
        tx_lon,
        rx_lon,
    )

    lon_max = max(
        tx_lon,
        rx_lon,
    )

    lat_span = max(
        lat_max - lat_min,
        min_span,
    )

    lon_span = max(
        lon_max - lon_min,
        min_span,
    )

    lat_margin = (
        lat_span * margin
    )

    lon_margin = (
        lon_span * margin
    )

    bounds = [
        [
            lat_min - lat_margin,
            lon_min - lon_margin,
        ],
        [
            lat_max + lat_margin,
            lon_max + lon_margin,
        ],
    ]

    # ========================================================
    # MAPA
    # ========================================================

    m = Map(
        center=(
            center_lat,
            center_lon,
        ),
        zoom=min_zoom,
        scroll_wheel_zoom=True,
        layout={
            "width": "100%",
            "height": "600px",
        },
    )

    # ========================================================
    # MARCADOR TX
    # ========================================================

    marker_tx = Marker(
        location=(
            tx_lat,
            tx_lon,
        ),
        draggable=False,
        title="TX",
    )

    # ========================================================
    # MARCADOR RX
    # ========================================================

    marker_rx = Marker(
        location=(
            rx_lat,
            rx_lon,
        ),
        draggable=False,
        title="RX",
    )

    # ========================================================
    # LINHA DO ENLACE
    # ========================================================

    line = Polyline(
        locations=[
            (
                tx_lat,
                tx_lon,
            ),
            (
                rx_lat,
                rx_lon,
            ),
        ],
        weight=4,
    )

    # ========================================================
    # CAMADAS
    # ========================================================

    m.add_layer(
        marker_tx
    )

    m.add_layer(
        marker_rx
    )

    m.add_layer(
        line
    )

    # ========================================================
    # AJUSTE AUTOMÁTICO DOS LIMITES
    # ========================================================

    m.fit_bounds(
        bounds
    )

    # ========================================================
    # METADADOS
    #
    # Mantemos referências aos objetos para que possam ser
    # acessados posteriormente pela aplicação.
    # ========================================================

    m.tx = marker_tx
    m.rx = marker_rx
    m.link = line
    m.link_bounds = bounds

    # ========================================================
    # RETORNO
    # ========================================================

    return m