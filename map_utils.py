from io import BytesIO
import math

import matplotlib.pyplot as plt
import requests

from ipyleaflet import (
    Map,
    Marker,
    Polyline,
)


# ============================================================
# MAPA INTERATIVO — usado no notebook
# ============================================================

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
    try:
        tx_lat = float(tx_lat)
        tx_lon = float(tx_lon)
        rx_lat = float(rx_lat)
        rx_lon = float(rx_lon)
    except (TypeError, ValueError) as exc:
        raise ValueError("Coordenadas TX/RX inválidas.") from exc

    if not (-90.0 <= tx_lat <= 90.0):
        raise ValueError(f"Latitude TX inválida: {tx_lat}")

    if not (-180.0 <= tx_lon <= 180.0):
        raise ValueError(f"Longitude TX inválida: {tx_lon}")

    if not (-90.0 <= rx_lat <= 90.0):
        raise ValueError(f"Latitude RX inválida: {rx_lat}")

    if not (-180.0 <= rx_lon <= 180.0):
        raise ValueError(f"Longitude RX inválida: {rx_lon}")

    center_lat = (tx_lat + rx_lat) / 2.0
    center_lon = (tx_lon + rx_lon) / 2.0

    lat_min = min(tx_lat, rx_lat)
    lat_max = max(tx_lat, rx_lat)
    lon_min = min(tx_lon, rx_lon)
    lon_max = max(tx_lon, rx_lon)

    lat_span = max(lat_max - lat_min, min_span)
    lon_span = max(lon_max - lon_min, min_span)

    lat_margin = lat_span * margin
    lon_margin = lon_span * margin

    bounds = [
        [lat_min - lat_margin, lon_min - lon_margin],
        [lat_max + lat_margin, lon_max + lon_margin],
    ]

    m = Map(
        center=(center_lat, center_lon),
        zoom=min_zoom,
        scroll_wheel_zoom=True,
        layout={"width": "100%", "height": "600px"},
    )

    marker_tx = Marker(
        location=(tx_lat, tx_lon),
        draggable=False,
        title="TX",
    )

    marker_rx = Marker(
        location=(rx_lat, rx_lon),
        draggable=False,
        title="RX",
    )

    line = Polyline(
        locations=[
            (tx_lat, tx_lon),
            (rx_lat, rx_lon),
        ],
        weight=4,
    )

    m.add_layer(marker_tx)
    m.add_layer(marker_rx)
    m.add_layer(line)

    m.fit_bounds(bounds)

    # Mantém referências utilizadas pelo restante do PlanApp
    m.tx = marker_tx
    m.rx = marker_rx
    m.link = line
    m.link_bounds = bounds

    return m


# ============================================================
# FUNÇÕES AUXILIARES — OpenStreetMap
# ============================================================

def _latlon_to_tile(lat, lon, zoom):
    """
    Converte latitude/longitude para coordenadas de tile
    no sistema Web Mercator utilizado pelo OpenStreetMap.
    """

    lat = max(min(lat, 85.05112878), -85.05112878)

    n = 2 ** zoom

    x = (lon + 180.0) / 360.0 * n

    lat_rad = math.radians(lat)

    y = (
        1.0
        - math.asinh(math.tan(lat_rad)) / math.pi
    ) / 2.0 * n

    return x, y


def _download_osm_tile(x, y, zoom, timeout=15):
    """
    Baixa um tile do OpenStreetMap.

    Retorna:
        PIL.Image
    """

    from PIL import Image

    n = 2 ** zoom

    # Mantém os índices dentro do mundo de tiles
    x = x % n

    if y < 0 or y >= n:
        return None

    url = (
        f"https://tile.openstreetmap.org/"
        f"{zoom}/{x}/{y}.png"
    )

    headers = {
        "User-Agent": (
            "PlanApp-AI/1.0 "
            "(radio-link-planning application)"
        )
    }

    response = requests.get(
        url,
        headers=headers,
        timeout=timeout,
    )

    response.raise_for_status()

    return Image.open(
        BytesIO(response.content)
    ).convert("RGB")


def _gerar_fundo_osm(
    lat_min,
    lon_min,
    lat_max,
    lon_max,
    zoom=15,
    tile_size=256,
):
    """
    Monta um mosaico de tiles OpenStreetMap cobrindo
    a área do enlace.

    Retorna:
        imagem PIL
        origem_x
        origem_y
        zoom
    """

    from PIL import Image

    x1, y1 = _latlon_to_tile(
        lat_max,
        lon_min,
        zoom,
    )

    x2, y2 = _latlon_to_tile(
        lat_min,
        lon_max,
        zoom,
    )

    tile_x_min = math.floor(x1)
    tile_y_min = math.floor(y1)

    tile_x_max = math.floor(x2)
    tile_y_max = math.floor(y2)

    width_tiles = (
        tile_x_max - tile_x_min + 1
    )

    height_tiles = (
        tile_y_max - tile_y_min + 1
    )

    mosaic = Image.new(
        "RGB",
        (
            width_tiles * tile_size,
            height_tiles * tile_size,
        ),
        "white",
    )

    for tile_x in range(
        tile_x_min,
        tile_x_max + 1,
    ):
        for tile_y in range(
            tile_y_min,
            tile_y_max + 1,
        ):
            try:
                tile = _download_osm_tile(
                    tile_x,
                    tile_y,
                    zoom,
                )

                if tile is None:
                    continue

                px = (
                    tile_x - tile_x_min
                ) * tile_size

                py = (
                    tile_y - tile_y_min
                ) * tile_size

                mosaic.paste(
                    tile,
                    (px, py),
                )

            except Exception:
                # Se um tile falhar, mantém o espaço
                # em branco e continua com os demais.
                continue

    origin_x = tile_x_min * tile_size
    origin_y = tile_y_min * tile_size

    return (
        mosaic,
        origin_x,
        origin_y,
        zoom,
    )


def _latlon_to_pixel(
    lat,
    lon,
    zoom,
    origin_x,
    origin_y,
    tile_size=256,
):
    """
    Converte latitude/longitude para pixel dentro
    do mosaico OpenStreetMap.
    """

    x, y = _latlon_to_tile(
        lat,
        lon,
        zoom,
    )

    px = x * tile_size - origin_x
    py = y * tile_size - origin_y

    return px, py


# ============================================================
# MAPA ESTÁTICO — usado no PDF
# ============================================================

def gerar_imagem_mapa_enlace(
    tx_lat,
    tx_lon,
    rx_lat,
    rx_lon,
    margin=0.20,
    min_span=0.005,
    zoom=15,
    figsize=(10, 6),
    dpi=150,
):
    """
    Gera uma imagem PNG do enlace sobre mapa OpenStreetMap.

    Esta função é destinada principalmente ao relatório PDF.

    O mapa contém:
        - base OpenStreetMap;
        - ponto TX;
        - ponto RX;
        - linha do enlace;
        - enquadramento automático.

    Retorna:
        bytes contendo uma imagem PNG.
    """

    try:
        tx_lat = float(tx_lat)
        tx_lon = float(tx_lon)
        rx_lat = float(rx_lat)
        rx_lon = float(rx_lon)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Coordenadas TX/RX inválidas."
        ) from exc

    if not (-90.0 <= tx_lat <= 90.0):
        raise ValueError(
            f"Latitude TX inválida: {tx_lat}"
        )

    if not (-180.0 <= tx_lon <= 180.0):
        raise ValueError(
            f"Longitude TX inválida: {tx_lon}"
        )

    if not (-90.0 <= rx_lat <= 90.0):
        raise ValueError(
            f"Latitude RX inválida: {rx_lat}"
        )

    if not (-180.0 <= rx_lon <= 180.0):
        raise ValueError(
            f"Longitude RX inválida: {rx_lon}"
        )

    # --------------------------------------------------------
    # Área do enlace
    # --------------------------------------------------------

    lat_min = min(tx_lat, rx_lat)
    lat_max = max(tx_lat, rx_lat)

    lon_min = min(tx_lon, rx_lon)
    lon_max = max(tx_lon, rx_lon)

    lat_span = max(
        lat_max - lat_min,
        min_span,
    )

    lon_span = max(
        lon_max - lon_min,
        min_span,
    )

    lat_margin = lat_span * margin
    lon_margin = lon_span * margin

    map_lat_min = max(
        -85.0,
        lat_min - lat_margin,
    )

    map_lat_max = min(
        85.0,
        lat_max + lat_margin,
    )

    map_lon_min = max(
        -180.0,
        lon_min - lon_margin,
    )

    map_lon_max = min(
        180.0,
        lon_max + lon_margin,
    )

    # --------------------------------------------------------
    # Baixa/monta os tiles OSM
    # --------------------------------------------------------

    mosaic, origin_x, origin_y, zoom_used = (
        _gerar_fundo_osm(
            map_lat_min,
            map_lon_min,
            map_lat_max,
            map_lon_max,
            zoom=zoom,
        )
    )

    # --------------------------------------------------------
    # Coordenadas em pixels
    # --------------------------------------------------------

    tx_x, tx_y = _latlon_to_pixel(
        tx_lat,
        tx_lon,
        zoom_used,
        origin_x,
        origin_y,
    )

    rx_x, rx_y = _latlon_to_pixel(
        rx_lat,
        rx_lon,
        zoom_used,
        origin_x,
        origin_y,
    )

    # --------------------------------------------------------
    # Cria figura
    # --------------------------------------------------------

    fig, ax = plt.subplots(
        figsize=figsize,
        dpi=dpi,
    )

    try:
        ax.imshow(mosaic)

        # ----------------------------------------------------
        # Linha do enlace
        # ----------------------------------------------------

        ax.plot(
            [tx_x, rx_x],
            [tx_y, rx_y],
            linewidth=3,
            label="Enlace",
            zorder=10,
        )

        # ----------------------------------------------------
        # TX
        # ----------------------------------------------------

        ax.scatter(
            tx_x,
            tx_y,
            s=120,
            marker="^",
            edgecolors="black",
            linewidths=1.2,
            label="TX",
            zorder=20,
        )

        # ----------------------------------------------------
        # RX
        # ----------------------------------------------------

        ax.scatter(
            rx_x,
            rx_y,
            s=120,
            marker="o",
            edgecolors="black",
            linewidths=1.2,
            label="RX",
            zorder=20,
        )

        # ----------------------------------------------------
        # Rótulos
        # ----------------------------------------------------

        ax.annotate(
            "TX",
            (tx_x, tx_y),
            xytext=(8, -8),
            textcoords="offset points",
            fontsize=10,
            fontweight="bold",
            zorder=30,
        )

        ax.annotate(
            "RX",
            (rx_x, rx_y),
            xytext=(8, -8),
            textcoords="offset points",
            fontsize=10,
            fontweight="bold",
            zorder=30,
        )

        # ----------------------------------------------------
        # Aparência
        # ----------------------------------------------------

        ax.set_xlim(
            0,
            mosaic.width,
        )

        ax.set_ylim(
            mosaic.height,
            0,
        )

        ax.set_axis_off()

        ax.set_title(
            "Mapa do enlace — OpenStreetMap",
            fontsize=13,
            fontweight="bold",
            pad=10,
        )

        ax.legend(
            loc="lower left",
            framealpha=0.9,
        )

        # ----------------------------------------------------
        # Atribuição OSM
        # ----------------------------------------------------

        fig.text(
            0.99,
            0.01,
            "© OpenStreetMap contributors",
            ha="right",
            va="bottom",
            fontsize=7,
        )

        # ----------------------------------------------------
        # Exporta PNG
        # ----------------------------------------------------

        buffer = BytesIO()

        fig.savefig(
            buffer,
            format="png",
            dpi=dpi,
            bbox_inches="tight",
            pad_inches=0.05,
        )

        buffer.seek(0)

        return buffer.getvalue()

    finally:
        plt.close(fig)