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
    agent,
    margin=0.20,
    min_span=0.005,
    min_zoom=10,
    max_zoom=18,
):
    """
    Cria e retorna o mapa do enlace.

    Esta função NÃO executa display().
    """

    points = getattr(
        agent,
        "geocoded_points",
        []
    )

    if len(points) < 2:

        raise ValueError(
            "São necessários pelo menos dois "
            "pontos geocodificados."
        )

    # ========================================================
    # TX / RX
    # ========================================================

    tx = points[0]
    rx = points[1]

    tx_lat = float(
        tx["lat"]
    )

    tx_lon = float(
        tx["lon"]
    )

    rx_lat = float(
        rx["lat"]
    )

    rx_lon = float(
        rx["lon"]
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
        rx_lat
    )

    lat_max = max(
        tx_lat,
        rx_lat
    )

    lon_min = min(
        tx_lon,
        rx_lon
    )

    lon_max = max(
        tx_lon,
        rx_lon
    )

    lat_span = max(
        lat_max - lat_min,
        min_span
    )

    lon_span = max(
        lon_max - lon_min,
        min_span
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
            center_lon
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
            tx_lon
        ),
        draggable=False,
        title=tx.get(
            "name",
            "TX"
        ),
    )

    # ========================================================
    # MARCADOR RX
    # ========================================================

    marker_rx = Marker(
        location=(
            rx_lat,
            rx_lon
        ),
        draggable=False,
        title=rx.get(
            "name",
            "RX"
        ),
    )

    # ========================================================
    # LINHA
    # ========================================================

    line = Polyline(
        locations=[
            (
                tx_lat,
                tx_lon
            ),
            (
                rx_lat,
                rx_lon
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
    # BOUNDS
    # ========================================================

    m.fit_bounds(
        bounds
    )

    # ========================================================
    # METADADOS
    # ========================================================

    m.tx = marker_tx

    m.rx = marker_rx

    m.link = line

    m.link_bounds = bounds

    # ========================================================
    # RETORNO
    # ========================================================

    return m
