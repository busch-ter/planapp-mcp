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
# UTILITÁRIOS DE COORDENADAS
# ============================================================

def _validar_coordenadas(
    lat,
    lon,
    nome="ponto",
):
    """
    Valida e converte latitude/longitude para float.
    """

    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Coordenadas inválidas para {nome}."
        ) from exc

    if not (-90.0 <= lat <= 90.0):
        raise ValueError(
            f"Latitude inválida para {nome}: {lat}"
        )

    if not (-180.0 <= lon <= 180.0):
        raise ValueError(
            f"Longitude inválida para {nome}: {lon}"
        )

    return lat, lon


def _extrair_ponto(
    hop,
    prefixo,
):
    """
    Extrai coordenadas de TX/RX de um hop.

    São aceitos os formatos:

        {
            "tx_lat": ...,
            "tx_lon": ...,
            "rx_lat": ...,
            "rx_lon": ...
        }

    ou:

        {
            "tx": {
                "lat": ...,
                "lon": ...
            },
            "rx": {
                "lat": ...,
                "lon": ...
            }
        }

    ou:

        {
            "tx": {
                "latitude": ...,
                "longitude": ...
            },
            "rx": {
                "latitude": ...,
                "longitude": ...
            }
        }

    Retorna:
        (lat, lon)
    """

    # --------------------------------------------------------
    # Formato direto
    # --------------------------------------------------------

    lat_key = f"{prefixo}_lat"
    lon_key = f"{prefixo}_lon"

    if (
        lat_key in hop
        and lon_key in hop
    ):
        return _validar_coordenadas(
            hop[lat_key],
            hop[lon_key],
            prefixo.upper(),
        )

    # --------------------------------------------------------
    # Formato tx/rx -> lat/lon
    # --------------------------------------------------------

    ponto = hop.get(prefixo)

    if isinstance(
        ponto,
        dict,
    ):

        lat = ponto.get("lat")

        if lat is None:
            lat = ponto.get("latitude")

        lon = ponto.get("lon")

        if lon is None:
            lon = ponto.get("longitude")

        if (
            lat is not None
            and lon is not None
        ):
            return _validar_coordenadas(
                lat,
                lon,
                prefixo.upper(),
            )

    raise ValueError(
        f"Não foi possível localizar "
        f"as coordenadas de {prefixo.upper()} "
        f"no hop: {hop}"
    )


def _normalizar_hops(
    hops,
):
    """
    Normaliza uma lista de hops para uma estrutura interna
    uniforme.

    Estrutura retornada:

        [
            {
                "hop_index": 1,
                "tx_lat": ...,
                "tx_lon": ...,
                "rx_lat": ...,
                "rx_lon": ...,
            },
            ...
        ]

    Também aceita uma única estrutura do tipo dict contendo
    uma lista em 'hops'.
    """

    if hops is None:
        raise ValueError(
            "Nenhum hop foi fornecido."
        )

    # --------------------------------------------------------
    # Caso seja um resultado contendo {"hops": [...]}
    # --------------------------------------------------------

    if isinstance(
        hops,
        dict,
    ):

        if isinstance(
            hops.get("hops"),
            list,
        ):

            hops = hops["hops"]

        else:

            # Permite também passar um único hop.
            hops = [hops]

    if not isinstance(
        hops,
        (list, tuple),
    ):

        raise ValueError(
            "Os hops devem ser fornecidos "
            "como lista ou tupla."
        )

    if not hops:

        raise ValueError(
            "A lista de hops está vazia."
        )

    resultado = []

    for index, hop in enumerate(
        hops,
        start=1,
    ):

        if not isinstance(
            hop,
            dict,
        ):

            raise ValueError(
                f"Hop {index} inválido: "
                "esperado um dicionário."
            )

        tx_lat, tx_lon = _extrair_ponto(
            hop,
            "tx",
        )

        rx_lat, rx_lon = _extrair_ponto(
            hop,
            "rx",
        )

        resultado.append(
            {
                "hop_index": index,
                "tx_lat": tx_lat,
                "tx_lon": tx_lon,
                "rx_lat": rx_lat,
                "rx_lon": rx_lon,
            }
        )

    return resultado


# ============================================================
# MAPA INTERATIVO — ETAPA 1
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

    center_lat = (
        tx_lat + rx_lat
    ) / 2.0

    center_lon = (
        tx_lon + rx_lon
    ) / 2.0

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

    marker_tx = Marker(
        location=(
            tx_lat,
            tx_lon,
        ),
        draggable=False,
        title="TX",
    )

    marker_rx = Marker(
        location=(
            rx_lat,
            rx_lon,
        ),
        draggable=False,
        title="RX",
    )

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

    m.add_layer(
        marker_tx
    )

    m.add_layer(
        marker_rx
    )

    m.add_layer(
        line
    )

    m.fit_bounds(
        bounds
    )

    # Mantém referências utilizadas pelo restante do PlanApp.
    m.tx = marker_tx
    m.rx = marker_rx
    m.link = line
    m.link_bounds = bounds

    return m


# ============================================================
# MAPA INTERATIVO — MULTI-HOP
#
# ETAPA 2
#
# A -> B -> C -> D
#
# Um único mapa contendo todos os hops.
# ============================================================

def mostrar_mapa_multihop(
    hops,
    margin=0.20,
    min_span=0.005,
    min_zoom=10,
    max_zoom=18,
):
    """
    Cria um mapa interativo contendo todos os hops.

    Exemplo:

        Hop 1: A -> B
        Hop 2: B -> C
        Hop 3: C -> D

    O mapa contém:
        - todos os pontos;
        - uma linha para cada hop;
        - identificação dos pontos;
        - enquadramento automático da rota inteira.

    O argumento 'hops' pode ser:
        - lista de dicionários;
        - dict contendo {"hops": [...]};
        - um único dict representando um hop.

    Cada hop pode utilizar:

        {
            "tx_lat": ...,
            "tx_lon": ...,
            "rx_lat": ...,
            "rx_lon": ...
        }

    ou:

        {
            "tx": {
                "lat": ...,
                "lon": ...
            },
            "rx": {
                "lat": ...,
                "lon": ...
            }
        }

    Retorna:
        ipyleaflet.Map
    """

    hops_normalizados = _normalizar_hops(
        hops
    )

    # --------------------------------------------------------
    # Calcula extensão total da rota
    # --------------------------------------------------------

    todas_latitudes = []
    todas_longitudes = []

    for hop in hops_normalizados:

        todas_latitudes.extend(
            [
                hop["tx_lat"],
                hop["rx_lat"],
            ]
        )

        todas_longitudes.extend(
            [
                hop["tx_lon"],
                hop["rx_lon"],
            ]
        )

    lat_min = min(
        todas_latitudes
    )

    lat_max = max(
        todas_latitudes
    )

    lon_min = min(
        todas_longitudes
    )

    lon_max = max(
        todas_longitudes
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

    center_lat = (
        lat_min + lat_max
    ) / 2.0

    center_lon = (
        lon_min + lon_max
    ) / 2.0

    # --------------------------------------------------------
    # Cria mapa
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Armazena referências
    # --------------------------------------------------------

    m.hops = []
    m.markers = []
    m.links = []
    m.link_bounds = bounds

    # --------------------------------------------------------
    # Cria os hops
    # --------------------------------------------------------

    for hop in hops_normalizados:

        index = hop["hop_index"]

        tx_lat = hop["tx_lat"]
        tx_lon = hop["tx_lon"]

        rx_lat = hop["rx_lat"]
        rx_lon = hop["rx_lon"]

        # ----------------------------------------------------
        # Marker TX
        # ----------------------------------------------------

        marker_tx = Marker(
            location=(
                tx_lat,
                tx_lon,
            ),
            draggable=False,
            title=(
                f"Hop {index} — TX"
            ),
        )

        # ----------------------------------------------------
        # Marker RX
        # ----------------------------------------------------

        marker_rx = Marker(
            location=(
                rx_lat,
                rx_lon,
            ),
            draggable=False,
            title=(
                f"Hop {index} — RX"
            ),
        )

        # ----------------------------------------------------
        # Linha do hop
        # ----------------------------------------------------

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

        m.add_layer(
            marker_tx
        )

        m.add_layer(
            marker_rx
        )

        m.add_layer(
            line
        )

        # ----------------------------------------------------
        # Referências
        # ----------------------------------------------------

        m.markers.append(
            {
                "hop": index,
                "tx": marker_tx,
                "rx": marker_rx,
            }
        )

        m.links.append(
            {
                "hop": index,
                "link": line,
            }
        )

        m.hops.append(
            {
                **hop,
                "tx_marker": marker_tx,
                "rx_marker": marker_rx,
                "link": line,
            }
        )

    # --------------------------------------------------------
    # Enquadramento
    # --------------------------------------------------------

    m.fit_bounds(
        bounds
    )

    # --------------------------------------------------------
    # Compatibilidade
    #
    # Se houver somente um hop, também disponibilizamos
    # referências semelhantes às do mapa antigo.
    # --------------------------------------------------------

    if len(hops_normalizados) == 1:

        primeiro = m.hops[0]

        m.tx = primeiro[
            "tx_marker"
        ]

        m.rx = primeiro[
            "rx_marker"
        ]

        m.link = primeiro[
            "link"
        ]

    return m


# ============================================================
# FUNÇÕES AUXILIARES — OpenStreetMap
# ============================================================

def _latlon_to_tile(
    lat,
    lon,
    zoom,
):
    """
    Converte latitude/longitude para coordenadas de tile
    no sistema Web Mercator utilizado pelo OpenStreetMap.
    """

    lat = max(
        min(
            lat,
            85.05112878,
        ),
        -85.05112878,
    )

    n = 2 ** zoom

    x = (
        (lon + 180.0)
        / 360.0
        * n
    )

    lat_rad = math.radians(
        lat
    )

    y = (
        1.0
        - math.asinh(
            math.tan(
                lat_rad
            )
        )
        / math.pi
    ) / 2.0 * n

    return x, y


def _download_osm_tile(
    x,
    y,
    zoom,
    timeout=15,
):
    """
    Baixa um tile do OpenStreetMap.

    Retorna:
        PIL.Image
    """

    from PIL import Image

    n = 2 ** zoom

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
        BytesIO(
            response.content
        )
    ).convert(
        "RGB"
    )


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

    tile_x_min = math.floor(
        x1
    )

    tile_y_min = math.floor(
        y1
    )

    tile_x_max = math.floor(
        x2
    )

    tile_y_max = math.floor(
        y2
    )

    width_tiles = (
        tile_x_max
        - tile_x_min
        + 1
    )

    height_tiles = (
        tile_y_max
        - tile_y_min
        + 1
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
                    tile_x
                    - tile_x_min
                ) * tile_size

                py = (
                    tile_y
                    - tile_y_min
                ) * tile_size

                mosaic.paste(
                    tile,
                    (
                        px,
                        py,
                    ),
                )

            except Exception:
                # Se um tile falhar, mantém o espaço
                # em branco e continua com os demais.
                continue

    origin_x = (
        tile_x_min
        * tile_size
    )

    origin_y = (
        tile_y_min
        * tile_size
    )

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

    px = (
        x * tile_size
        - origin_x
    )

    py = (
        y * tile_size
        - origin_y
    )

    return px, py


# ============================================================
# MAPA ESTÁTICO — ETAPA 1
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
        tx_lat = float(
            tx_lat
        )

        tx_lon = float(
            tx_lon
        )

        rx_lat = float(
            rx_lat
        )

        rx_lon = float(
            rx_lon
        )

    except (TypeError, ValueError) as exc:

        raise ValueError(
            "Coordenadas TX/RX inválidas."
        ) from exc

    if not (
        -90.0
        <= tx_lat
        <= 90.0
    ):

        raise ValueError(
            f"Latitude TX inválida: {tx_lat}"
        )

    if not (
        -180.0
        <= tx_lon
        <= 180.0
    ):

        raise ValueError(
            f"Longitude TX inválida: {tx_lon}"
        )

    if not (
        -90.0
        <= rx_lat
        <= 90.0
    ):

        raise ValueError(
            f"Latitude RX inválida: {rx_lat}"
        )

    if not (
        -180.0
        <= rx_lon
        <= 180.0
    ):

        raise ValueError(
            f"Longitude RX inválida: {rx_lon}"
        )

    # --------------------------------------------------------
    # Área do enlace
    # --------------------------------------------------------

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

    (
        mosaic,
        origin_x,
        origin_y,
        zoom_used,
    ) = _gerar_fundo_osm(
        map_lat_min,
        map_lon_min,
        map_lat_max,
        map_lon_max,
        zoom=zoom,
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

        ax.imshow(
            mosaic
        )

        # ----------------------------------------------------
        # Linha do enlace
        # ----------------------------------------------------

        ax.plot(
            [
                tx_x,
                rx_x,
            ],
            [
                tx_y,
                rx_y,
            ],
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
            (
                tx_x,
                tx_y,
            ),
            xytext=(
                8,
                -8,
            ),
            textcoords="offset points",
            fontsize=10,
            fontweight="bold",
            zorder=30,
        )

        ax.annotate(
            "RX",
            (
                rx_x,
                rx_y,
            ),
            xytext=(
                8,
                -8,
            ),
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

        plt.close(
            fig
        )


# ============================================================
# MAPA ESTÁTICO — MULTI-HOP
#
# ETAPA 2
#
# Gera UMA imagem contendo todos os enlaces.
#
# As imagens técnicas individuais dos hops continuam sendo
# responsabilidade das demais partes do PlanApp.
# ============================================================

def gerar_imagem_mapa_multihop(
    hops,
    margin=0.20,
    min_span=0.005,
    zoom=15,
    figsize=(10, 6),
    dpi=150,
):
    """
    Gera uma imagem PNG contendo todos os hops da rota.

    Exemplo:

        A -> B
        B -> C
        C -> D

    A imagem contém:
        - mapa OpenStreetMap;
        - todos os pontos;
        - todos os enlaces;
        - identificação dos hops;
        - enquadramento automático da rota inteira.

    Retorna:
        bytes contendo uma imagem PNG.
    """

    hops_normalizados = _normalizar_hops(
        hops
    )

    # --------------------------------------------------------
    # Extensão total
    # --------------------------------------------------------

    todas_latitudes = []
    todas_longitudes = []

    for hop in hops_normalizados:

        todas_latitudes.extend(
            [
                hop["tx_lat"],
                hop["rx_lat"],
            ]
        )

        todas_longitudes.extend(
            [
                hop["tx_lon"],
                hop["rx_lon"],
            ]
        )

    lat_min = min(
        todas_latitudes
    )

    lat_max = max(
        todas_latitudes
    )

    lon_min = min(
        todas_longitudes
    )

    lon_max = max(
        todas_longitudes
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
    # Mosaico OSM
    # --------------------------------------------------------

    (
        mosaic,
        origin_x,
        origin_y,
        zoom_used,
    ) = _gerar_fundo_osm(
        map_lat_min,
        map_lon_min,
        map_lat_max,
        map_lon_max,
        zoom=zoom,
    )

    # --------------------------------------------------------
    # Figura
    # --------------------------------------------------------

    fig, ax = plt.subplots(
        figsize=figsize,
        dpi=dpi,
    )

    try:

        ax.imshow(
            mosaic
        )

        # ----------------------------------------------------
        # Todos os hops
        # ----------------------------------------------------

        for hop in hops_normalizados:

            index = hop[
                "hop_index"
            ]

            tx_x, tx_y = _latlon_to_pixel(
                hop["tx_lat"],
                hop["tx_lon"],
                zoom_used,
                origin_x,
                origin_y,
            )

            rx_x, rx_y = _latlon_to_pixel(
                hop["rx_lat"],
                hop["rx_lon"],
                zoom_used,
                origin_x,
                origin_y,
            )

            # ------------------------------------------------
            # Linha
            # ------------------------------------------------

            ax.plot(
                [
                    tx_x,
                    rx_x,
                ],
                [
                    tx_y,
                    rx_y,
                ],
                linewidth=3,
                label=(
                    f"Hop {index}"
                ),
                zorder=10,
            )

            # ------------------------------------------------
            # TX
            # ------------------------------------------------

            ax.scatter(
                tx_x,
                tx_y,
                s=120,
                marker="^",
                edgecolors="black",
                linewidths=1.2,
                zorder=20,
            )

            # ------------------------------------------------
            # RX
            # ------------------------------------------------

            ax.scatter(
                rx_x,
                rx_y,
                s=120,
                marker="o",
                edgecolors="black",
                linewidths=1.2,
                zorder=20,
            )

            # ------------------------------------------------
            # Identificação do hop
            # ------------------------------------------------

            meio_x = (
                tx_x + rx_x
            ) / 2.0

            meio_y = (
                tx_y + rx_y
            ) / 2.0

            ax.annotate(
                f"Hop {index}",
                (
                    meio_x,
                    meio_y,
                ),
                xytext=(
                    0,
                    -12,
                ),
                textcoords="offset points",
                ha="center",
                fontsize=9,
                fontweight="bold",
                zorder=30,
                bbox={
                    "boxstyle": "round,pad=0.25",
                    "facecolor": "white",
                    "alpha": 0.85,
                    "edgecolor": "black",
                },
            )

        # ----------------------------------------------------
        # Pontos extremos e intermediários
        #
        # Evita deixar o mapa sem identificação dos pontos.
        # ----------------------------------------------------

        pontos = []

        for hop in hops_normalizados:

            pontos.append(
                (
                    hop["tx_lat"],
                    hop["tx_lon"],
                )
            )

        ultimo = hops_normalizados[-1]

        pontos.append(
            (
                ultimo["rx_lat"],
                ultimo["rx_lon"],
            )
        )

        # ----------------------------------------------------
        # Rótulos da sequência
        #
        # A estrutura esperada de uma rota contínua é:
        #
        # A -> B -> C -> D
        #
        # Portanto os RX intermediários coincidem com os TX
        # seguintes.
        # ----------------------------------------------------

        pontos_unicos = []

        for ponto in pontos:

            if not pontos_unicos:

                pontos_unicos.append(
                    ponto
                )

                continue

            anterior = (
                pontos_unicos[-1]
            )

            if (
                abs(
                    anterior[0]
                    - ponto[0]
                )
                > 1e-10
                or
                abs(
                    anterior[1]
                    - ponto[1]
                )
                > 1e-10
            ):

                pontos_unicos.append(
                    ponto
                )

        letras = []

        for index, ponto in enumerate(
            pontos_unicos
        ):

            x, y = _latlon_to_pixel(
                ponto[0],
                ponto[1],
                zoom_used,
                origin_x,
                origin_y,
            )

            # ------------------------------------------------
            # Primeiro ponto = A
            # Segundo = B
            # etc.
            #
            # Para rotas longas, após Z continuamos como
            # P27, P28 etc.
            # ------------------------------------------------

            if index < 26:

                nome = chr(
                    ord("A")
                    + index
                )

            else:

                nome = f"P{index + 1}"

            letras.append(
                nome
            )

            ax.annotate(
                nome,
                (
                    x,
                    y,
                ),
                xytext=(
                    8,
                    -8,
                ),
                textcoords="offset points",
                fontsize=10,
                fontweight="bold",
                zorder=40,
                bbox={
                    "boxstyle": "round,pad=0.20",
                    "facecolor": "white",
                    "alpha": 0.85,
                    "edgecolor": "black",
                },
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
            "Mapa dos enlaces — rota multi-hop — OpenStreetMap",
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

        plt.close(
            fig
        )