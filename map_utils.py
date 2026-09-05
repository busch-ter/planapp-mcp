# ============================================================
# map_utils.py — Utilitários para visualização de enlaces
# ============================================================

from ipyleaflet import Map, Marker, Polyline
from IPython.display import display


def _extrair_coordenadas_enlace(agent):
    """
    Procura as duas coordenadas geocodificadas armazenadas pelo agente.

    Retorna:
        tx = (lat, lon)
        rx = (lat, lon)

    Levanta ValueError caso não encontre um enlace válido.
    """

    pontos = getattr(agent, "geocoded_points", None)

    if not pontos:
        raise ValueError(
            "Nenhum ponto geocodificado foi encontrado no agente."
        )

    if len(pontos) < 2:
        raise ValueError(
            "O agente possui menos de dois pontos geocodificados."
        )

    def extrair_lat_lon(ponto):
        """
        Aceita diferentes formatos possíveis de ponto.
        """

        if isinstance(ponto, dict):

            # Formato direto:
            # {"lat": ..., "lon": ...}
            if "lat" in ponto and "lon" in ponto:
                return (
                    float(ponto["lat"]),
                    float(ponto["lon"]),
                )

            # Formato latitude/longitude
            if "latitude" in ponto and "longitude" in ponto:
                return (
                    float(ponto["latitude"]),
                    float(ponto["longitude"]),
                )

        # Caso o ponto seja uma tupla/lista
        if isinstance(ponto, (tuple, list)) and len(ponto) >= 2:
            return (
                float(ponto[0]),
                float(ponto[1]),
            )

        raise ValueError(
            f"Formato de coordenada não reconhecido: {ponto!r}"
        )

    tx = extrair_lat_lon(pontos[0])
    rx = extrair_lat_lon(pontos[1])

    return tx, rx


def mostrar_mapa_enlace(
    agent,
    margin=0.20,
    min_span=0.005,
    min_zoom=10,
    max_zoom=18,
):
    """
    Mostra o último enlace analisado pelo agente.

    Parâmetros
    ----------
    agent :
        Instância atual de PlanAppAgent.

    margin :
        Margem proporcional ao redor do enlace.
        0.20 = 20%.

    min_span :
        Extensão geográfica mínima para evitar zoom excessivo
        em enlaces muito curtos.

    min_zoom :
        Zoom mínimo permitido.

    max_zoom :
        Zoom máximo permitido.

    Retorna
    -------
    Map
        Objeto ipyleaflet.Map criado.
    """

    # --------------------------------------------------------
    # 1. Recupera TX e RX
    # --------------------------------------------------------

    tx, rx = _extrair_coordenadas_enlace(agent)

    tx_lat, tx_lon = tx
    rx_lat, rx_lon = rx

    # --------------------------------------------------------
    # 2. Calcula o bounding box do enlace
    # --------------------------------------------------------

    lat_min = min(tx_lat, rx_lat)
    lat_max = max(tx_lat, rx_lat)

    lon_min = min(tx_lon, rx_lon)
    lon_max = max(tx_lon, rx_lon)

    lat_span = lat_max - lat_min
    lon_span = lon_max - lon_min

    # --------------------------------------------------------
    # 3. Garante uma dimensão mínima
    # --------------------------------------------------------

    lat_span = max(lat_span, min_span)
    lon_span = max(lon_span, min_span)

    # --------------------------------------------------------
    # 4. Adiciona margem proporcional
    # --------------------------------------------------------

    lat_margin = lat_span * margin
    lon_margin = lon_span * margin

    south = lat_min - lat_margin
    north = lat_max + lat_margin

    west = lon_min - lon_margin
    east = lon_max + lon_margin

    bounds = [
        [south, west],
        [north, east],
    ]

    # --------------------------------------------------------
    # 5. Centro inicial
    # --------------------------------------------------------

    center = (
        (south + north) / 2,
        (west + east) / 2,
    )

    # --------------------------------------------------------
    # 6. Cria o mapa
    # --------------------------------------------------------

    m = Map(
        center=center,
        zoom=min_zoom,
        scroll_wheel_zoom=True,
    )

    # --------------------------------------------------------
    # 7. Marcador TX
    # --------------------------------------------------------

    marker_tx = Marker(
        location=(tx_lat, tx_lon),
        title="TX",
    )

    # --------------------------------------------------------
    # 8. Marcador RX
    # --------------------------------------------------------

    marker_rx = Marker(
        location=(rx_lat, rx_lon),
        title="RX",
    )

    # --------------------------------------------------------
    # 9. Linha do enlace
    # --------------------------------------------------------

    linha = Polyline(
        locations=[
            (tx_lat, tx_lon),
            (rx_lat, rx_lon),
        ],
        weight=4,
    )

    # --------------------------------------------------------
    # 10. Adiciona elementos ao mapa
    # --------------------------------------------------------

    m.add_layer(linha)
    m.add_layer(marker_tx)
    m.add_layer(marker_rx)

    # --------------------------------------------------------
    # 11. Enquadra automaticamente TX e RX
    # --------------------------------------------------------

    m.fit_bounds(bounds)

    # --------------------------------------------------------
    # 12. Guarda informações no objeto mapa
    # --------------------------------------------------------

    m.tx = tx
    m.rx = rx
    m.link_bounds = bounds

    # --------------------------------------------------------
    # 13. Mostra o mapa
    # --------------------------------------------------------

    display(m)

    return m