# ============================================================
# PLANAPP AI — OPENROUTER
#
# Arquitetura:
#
#   Jupyter
#      |
#      v
#   OpenRouter
#      |
#      v
#   geocode_place
#      |
#      v
#   aplicação executa evaluate_link automaticamente
#      |
#      +--> mapa
#      |
#      +--> visualizações
#      |
#      +--> resposta final em português
#      |
#      v
#   PlanApp MCP
#
# ============================================================

import asyncio
import base64
import json
import os
import re
from contextlib import AsyncExitStack
from datetime import datetime

from openai import AsyncOpenAI

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

import ipywidgets as widgets

from ipyleaflet import Map, Marker, Polyline


# ============================================================
# CONFIGURAÇÕES
# ============================================================

MCP_URL = os.getenv(
    "PLANAPP_MCP_URL",
    "http://172.17.0.1:8010/mcp",
)

OPENROUTER_URL = os.getenv(
    "OPENROUTER_URL",
    "https://openrouter.ai/api/v1",
)

OPENROUTER_MODEL = os.getenv(
    "OPENROUTER_MODEL",
    "openrouter/free",
)

OPENROUTER_API_KEY = os.getenv(
    "OPENROUTER_API_KEY",
)

USER_ID = os.getenv(
    "PLANAPP_USER_ID",
    "jupyter-user",
)


# ============================================================
# PARÂMETROS PADRÃO DO PLANAPP
# ============================================================

DEFAULT_FREQ_MHZ = 900
DEFAULT_TX_HA = 7
DEFAULT_RX_HA = 7
DEFAULT_ON_ROOFTOP = False


MAX_AGENT_ITERATIONS = 8


# ============================================================
# FERRAMENTAS CONTROLADAS PELA APLICAÇÃO
#
# O modelo NÃO executa estas ferramentas.
# ============================================================

APPLICATION_CONTROLLED_TOOLS = {
    "register",
    "evaluate_link",
    "link_area",
    "link_profile",
    "lulc_fresnel",
    "bldg_prepare",
    "bldg_fresnel",
    "bldg_profile",
}


# ============================================================
# FERRAMENTAS QUE O MODELO PODE UTILIZAR
# ============================================================

MODEL_ALLOWED_TOOLS = {
    "geocode_place",
}


# ============================================================
# AGENTE
# ============================================================

class PlanAppAgent:

    def __init__(
        self,
        progress_callback=None,
        map_callback=None,
        log_callback=None,
        result_callback=None,
        visualization_callback=None,
    ):
        self.progress_callback = progress_callback
        self.map_callback = map_callback
        self.log_callback = log_callback
        self.result_callback = result_callback
        self.visualization_callback = visualization_callback

        self.exit_stack = AsyncExitStack()

        self.mcp_session = None
        self.mcp_tools = []
        self.connected = False

        self.messages = []

        self.geocoded_points = []

        self.evaluate_executed = False
        self.last_evaluate_result = None
        self.evaluate_error = None

        self.visualizations = []

        self.map = None

        self.tool_count = 0
        self.current_stage = 0

        self.link_parameters = {
            "freq_mhz": DEFAULT_FREQ_MHZ,
            "tx_ha": DEFAULT_TX_HA,
            "rx_ha": DEFAULT_RX_HA,
            "on_rooftop": DEFAULT_ON_ROOFTOP,
        }

        # --------------------------------------------------------
        # Parâmetros solicitados pelo usuário
        # --------------------------------------------------------

        self.requested_frequency = None
        self.requested_frequency_unit = None
        self.requested_frequency_text = None

        self.requested_tx_ha = None
        self.requested_rx_ha = None


        # --------------------------------------------------------
        # Cliente OpenRouter
        # --------------------------------------------------------

        self.client = None

        if OPENROUTER_API_KEY:
            self.client = AsyncOpenAI(
                api_key=OPENROUTER_API_KEY,
                base_url=OPENROUTER_URL,
                default_headers={
                    "HTTP-Referer": "https://planapp.cisei.pucpr.br",
                    "X-Title": "PlanApp AI",
                },
            )


    # ============================================================
    # STATUS
    # ============================================================

    def log(self, message):

        if self.progress_callback:

            try:
                self.progress_callback(message)

            except Exception:
                pass


    # ============================================================
    # LOG TÉCNICO
    # ============================================================

    def log_detail(self, message):

        if self.log_callback:

            try:
                self.log_callback(message)

            except Exception:
                pass


    # ============================================================
    # RESULTADO TÉCNICO
    # ============================================================

    def publish_technical_result(self, result):

        if self.result_callback:

            try:
                self.result_callback(result)

            except Exception:
                pass


    # ============================================================
    # SYSTEM PROMPT
    # ============================================================

    def system_prompt(self):

        return """
Você é o analista técnico do PlanApp AI.

Sua tarefa é produzir uma análise técnica clara, útil e objetiva do enlace avaliado pelo PlanApp, usando exclusivamente os dados retornados pela aplicação como fonte de verdade.

REGRA PRINCIPAL:
Interprete o que é claramente sustentado pelos dados, mas não invente critérios, unidades, limites, fórmulas, margens ou conclusões que não estejam disponíveis nos resultados do PlanApp.

A resposta deve:

1. Identificar os dois pontos do enlace e informar as coordenadas obtidas pelo geocoder quando disponíveis.

2. Informar os parâmetros efetivamente utilizados na avaliação:

   * frequência;
   * altura da antena TX;
   * altura da antena RX;
   * condição de instalação em telhado.

3. Apresentar os principais resultados técnicos retornados pelo PlanApp, priorizando:

   * distância;
   * FSPL;
   * delta de difração;
   * informações de terreno;
   * informações de vegetação;
   * informações de edificações;
   * picos de terreno;
   * ângulos;
   * clearances.

4. Fazer uma interpretação técnica dos dados quando ela for diretamente sustentada pelos próprios valores.

   Exemplos de interpretações permitidas:

   * informar que o enlace possui aproximadamente determinada distância;
   * destacar que determinados indicadores possuem valores não nulos;
   * destacar que determinados indicadores são zero;
   * comparar os valores TX e RX;
   * apontar quais elementos aparecem nos resultados do perfil;
   * destacar valores particularmente relevantes ou extremos dentro dos próprios dados;
   * relacionar informações diretamente evidentes entre os campos retornados.

5. NÃO atribuir significado técnico específico a campos cuja definição não esteja disponível nos dados fornecidos.

   Por exemplo, não afirmar que "core", "fresnel", "boundary", "v_v" ou "d_norm" representam determinada grandeza física específica se isso não estiver explicitamente definido pelo PlanApp.

6. NÃO inventar unidades.

   Se o PlanApp fornecer um valor sem unidade, apresente o valor sem acrescentar uma unidade por conta própria.

7. NÃO inventar critérios de engenharia.

   Não afirmar que um valor é "bom", "ruim", "aceitável", "crítico", "seguro", "insuficiente" ou semelhante sem que exista no contexto um critério explícito para essa avaliação.

8. NÃO transformar o status "OK" em uma conclusão de engenharia.

   "OK" significa que a avaliação foi executada com sucesso. Não significa, por si só, que o enlace seja viável, aprovado ou tenha margem adequada.

9. Quando os dados permitirem uma observação técnica objetiva, FAÇA essa observação. Não se limite a simplesmente copiar os valores em formato de lista.

10. Organize a resposta de forma natural, utilizando títulos e listas apenas quando ajudarem a compreensão.

11. Evite linguagem burocrática ou frases como:

* "Todos os valores foram apresentados exatamente como fornecidos";
* "Não foi realizada nenhuma interpretação";
* "Não é possível fazer qualquer conclusão".

12. A resposta deve ser escrita em português do Brasil.

13. Seja conciso, mas tecnicamente informativo. O objetivo é que o usuário compreenda o que aconteceu no enlace sem precisar interpretar sozinho todos os números.

14. Termine, quando apropriado, indicando quais aspectos merecem atenção na análise, mas sem declarar aprovação ou reprovação do enlace caso os critérios necessários não estejam disponíveis.

DADOS DO PLANAPP:
Use exclusivamente os resultados técnicos, parâmetros e coordenadas fornecidos pela aplicação nesta execução como base factual da análise.
"""


    # ============================================================
    # EXTRAÇÃO DOS PARÂMETROS
    # ============================================================

    def extract_link_parameters(self, text):

        parameters = {
            "freq_mhz": DEFAULT_FREQ_MHZ,
            "tx_ha": DEFAULT_TX_HA,
            "rx_ha": DEFAULT_RX_HA,
            "on_rooftop": DEFAULT_ON_ROOFTOP,
        }

        self.requested_frequency = None
        self.requested_frequency_unit = None
        self.requested_frequency_text = None

        self.requested_tx_ha = None
        self.requested_rx_ha = None


        # --------------------------------------------------------
        # Frequência
        # --------------------------------------------------------

        freq_pattern = re.compile(
            r"(\d+(?:[.,]\d+)?)\s*"
            r"(ghz|mhz|khz|hz)\b",
            re.IGNORECASE,
        )

        freq_match = freq_pattern.search(text)

        if freq_match:

            value_text = freq_match.group(1)

            unit = freq_match.group(2).lower()

            value = float(
                value_text.replace(",", ".")
            )

            self.requested_frequency = value
            self.requested_frequency_unit = unit
            self.requested_frequency_text = freq_match.group(0)

            if unit == "ghz":

                parameters["freq_mhz"] = value * 1000.0

            elif unit == "mhz":

                parameters["freq_mhz"] = value

            elif unit == "khz":

                parameters["freq_mhz"] = value / 1000.0

            elif unit == "hz":

                parameters["freq_mhz"] = value / 1_000_000.0


        # --------------------------------------------------------
        # Duas antenas com mesma altura
        # --------------------------------------------------------

        same_height_patterns = [

            r"duas\s+antenas?\s+de\s+"
            r"(\d+(?:[.,]\d+)?)\s*(?:m|metros?)",

            r"antenas?\s+de\s+"
            r"(\d+(?:[.,]\d+)?)\s*(?:m|metros?)",
        ]

        same_height_match = None

        for pattern in same_height_patterns:

            same_height_match = re.search(
                pattern,
                text,
                re.IGNORECASE,
            )

            if same_height_match:
                break


        if same_height_match:

            height = float(
                same_height_match.group(1)
                .replace(",", ".")
            )

            parameters["tx_ha"] = height
            parameters["rx_ha"] = height

            self.requested_tx_ha = height
            self.requested_rx_ha = height

        else:

            # ----------------------------------------------------
            # TX separado
            # ----------------------------------------------------

            tx_match = re.search(
                r"(?:tx|transmissora?|transmissor)"
                r".{0,30}?"
                r"(\d+(?:[.,]\d+)?)\s*(?:m|metros?)",
                text,
                re.IGNORECASE,
            )

            # ----------------------------------------------------
            # RX separado
            # ----------------------------------------------------

            rx_match = re.search(
                r"(?:rx|receptora?|receptor)"
                r".{0,30}?"
                r"(\d+(?:[.,]\d+)?)\s*(?:m|metros?)",
                text,
                re.IGNORECASE,
            )


            if tx_match:

                height = float(
                    tx_match.group(1)
                    .replace(",", ".")
                )

                parameters["tx_ha"] = height
                self.requested_tx_ha = height


            if rx_match:

                height = float(
                    rx_match.group(1)
                    .replace(",", ".")
                )

                parameters["rx_ha"] = height
                self.requested_rx_ha = height


        # --------------------------------------------------------
        # Rooftop
        # --------------------------------------------------------

        rooftop_patterns = [

            r"\bno\s+telhado\b",

            r"\bem\s+cima\s+do\s+telhado\b",

            r"\bsobre\s+o\s+telhado\b",

            r"\brooftop\b",
        ]

        for pattern in rooftop_patterns:

            if re.search(
                pattern,
                text,
                re.IGNORECASE,
            ):

                parameters["on_rooftop"] = True

                break


        self.link_parameters = parameters

        return parameters


    # ============================================================
    # CONEXÃO MCP
    # ============================================================

    async def connect(self):

        self.log(
            "🔌 Conectando ao PlanApp MCP..."
        )

        transport = await (
            self.exit_stack.enter_async_context(
                streamable_http_client(MCP_URL)
            )
        )

        read_stream, write_stream = transport

        self.mcp_session = await (
            self.exit_stack.enter_async_context(
                ClientSession(
                    read_stream,
                    write_stream,
                )
            )
        )

        await self.mcp_session.initialize()

        tools_result = await (
            self.mcp_session.list_tools()
        )

        self.mcp_tools = tools_result.tools

        self.connected = True

        self.log(
            f"🟢 MCP conectado — "
            f"{len(self.mcp_tools)} ferramentas disponíveis."
        )

        self.log_detail(
            "Ferramentas MCP disponíveis:"
        )

        for tool in self.mcp_tools:

            self.log_detail(
                f"  - {tool.name}"
            )


    # ============================================================
    # TOOLS PARA OPENROUTER
    # ============================================================

    def build_openrouter_tools(self):

        tools = []

        for tool in self.mcp_tools:

            if tool.name not in MODEL_ALLOWED_TOOLS:
                continue

            schema = getattr(
                tool,
                "inputSchema",
                None,
            )

            if schema is None:

                schema = getattr(
                    tool,
                    "input_schema",
                    None,
                )

            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": (
                            getattr(
                                tool,
                                "description",
                                None,
                            )
                            or ""
                        ),
                        "parameters": schema or {
                            "type": "object",
                            "properties": {},
                        },
                    },
                }
            )

        return tools


    # ============================================================
    # RESULTADO MCP
    # ============================================================

    def parse_mcp_result(self, result):

        # --------------------------------------------------------
        # Conteúdo estruturado
        # --------------------------------------------------------

        structured = getattr(
            result,
            "structuredContent",
            None,
        )

        if structured is None:

            structured = getattr(
                result,
                "structured_content",
                None,
            )

        if structured is not None:

            return structured


        # --------------------------------------------------------
        # Conteúdo textual
        # --------------------------------------------------------

        content = getattr(
            result,
            "content",
            None,
        )

        if content:

            parsed_items = []

            for item in content:

                text = getattr(
                    item,
                    "text",
                    None,
                )

                if text is None:
                    continue

                try:

                    parsed_items.append(
                        json.loads(text)
                    )

                except Exception:

                    parsed_items.append(
                        text
                    )


            if len(parsed_items) == 1:

                return parsed_items[0]


            if parsed_items:

                return parsed_items


        return result


    # ============================================================
    # ERRO MCP
    # ============================================================

    def contains_nested_error(self, value):

        if isinstance(value, dict):

            status = str(
                value.get(
                    "status",
                    "",
                )
            ).lower()

            if status in {
                "error",
                "failed",
                "failure",
            }:

                return True


            if value.get("error"):

                return True


            for child in value.values():

                if self.contains_nested_error(child):

                    return True


        elif isinstance(value, list):

            for child in value:

                if self.contains_nested_error(child):

                    return True


        return False


    def is_mcp_error(
        self,
        result,
        parsed,
    ):

        is_error = getattr(
            result,
            "isError",
            None,
        )

        if is_error is None:

            is_error = getattr(
                result,
                "is_error",
                False,
            )

        if is_error:

            return True

        return self.contains_nested_error(
            parsed
        )


    # ============================================================
    # LOG SEGURO
    # ============================================================

    def make_log_safe(self, value):

        if isinstance(value, dict):

            safe = {}

            for key, child in value.items():

                if (
                    key == "data"
                    and isinstance(child, str)
                    and value.get("kind") == "image"
                ):

                    safe[key] = (
                        "<base64 image: "
                        f"{len(child)} chars>"
                    )

                else:

                    safe[key] = (
                        self.make_log_safe(child)
                    )

            return safe


        if isinstance(value, list):

            return [
                self.make_log_safe(child)
                for child in value
            ]


        return value


    # ============================================================
    # EXTRAÇÃO DE IMAGENS DOS RESULTADOS MCP
    #
    # Importante:
    # Não transformar ImageContent em texto.
    # ============================================================

    def extract_images_from_mcp_result(
        self,
        raw_result,
        parsed_result,
    ):

        images = []


        # --------------------------------------------------------
        # Procura ImageContent diretamente no content do MCP
        # --------------------------------------------------------

        content = getattr(
            raw_result,
            "content",
            None,
        )

        if content:

            for item in content:

                item_type = getattr(
                    item,
                    "type",
                    None,
                )

                data = getattr(
                    item,
                    "data",
                    None,
                )

                mime_type = getattr(
                    item,
                    "mimeType",
                    None,
                )

                if (
                    item_type == "image"
                    and data
                ):

                    images.append(
                        {
                            "kind": "image",
                            "encoding": "base64",
                            "data": data,
                            "mimeType": (
                                mime_type
                                or "image/png"
                            ),
                            "type": "image",
                        }
                    )


        # --------------------------------------------------------
        # Alguns resultados podem chegar como JSON estruturado
        # --------------------------------------------------------

        def recursive_extract(value):

            if isinstance(value, dict):

                kind = value.get(
                    "kind"
                )

                data = value.get(
                    "data"
                )

                if (
                    kind == "image"
                    and isinstance(data, str)
                    and data
                ):

                    images.append(
                        {
                            "kind": "image",
                            "encoding": (
                                value.get(
                                    "encoding",
                                    "base64",
                                )
                            ),
                            "data": data,
                            "mimeType": (
                                value.get(
                                    "mimeType",
                                    "image/png",
                                )
                            ),
                            "type": "image",
                        }
                    )

                    return


                for child in value.values():

                    recursive_extract(child)


            elif isinstance(value, list):

                for child in value:

                    recursive_extract(child)


        recursive_extract(
            parsed_result
        )


        # --------------------------------------------------------
        # Remove duplicatas
        # --------------------------------------------------------

        unique = []

        seen = set()

        for image in images:

            key = (
                image.get("data"),
                image.get("mimeType"),
            )

            if key in seen:
                continue

            seen.add(key)

            unique.append(image)


        return unique


    # ============================================================
    # MAPA
    # ============================================================

    async def mostrar_mapa_apos_geocodificacao(
        self
    ):

        if len(self.geocoded_points) < 2:
            return


        self.log(
            "🗺️ Preparando enlace no mapa..."
        )


        try:

            p1 = self.geocoded_points[0]
            p2 = self.geocoded_points[1]


            center_lat = (
                p1["lat"] + p2["lat"]
            ) / 2.0

            center_lon = (
                p1["lon"] + p2["lon"]
            ) / 2.0


            mapa = Map(
                center=(
                    center_lat,
                    center_lon,
                ),
                zoom=14,
                scroll_wheel_zoom=True,
            )


            marker_tx = Marker(
                location=(
                    p1["lat"],
                    p1["lon"],
                ),
                title=(
                    p1.get("name")
                    or "TX"
                ),
            )


            marker_rx = Marker(
                location=(
                    p2["lat"],
                    p2["lon"],
                ),
                title=(
                    p2.get("name")
                    or "RX"
                ),
            )


            linha = Polyline(
                locations=[
                    (
                        p1["lat"],
                        p1["lon"],
                    ),
                    (
                        p2["lat"],
                        p2["lon"],
                    ),
                ],
                weight=4,
            )


            mapa.add_layer(
                marker_tx
            )

            mapa.add_layer(
                marker_rx
            )

            mapa.add_layer(
                linha
            )


            self.map = mapa


            if self.map_callback:

                try:

                    self.map_callback(
                        self.map
                    )

                except Exception as exc:

                    self.log(
                        "⚠️ Erro ao atualizar mapa: "
                        f"{exc}"
                    )


            self.log(
                "🟢 Mapa preparado."
            )


        except Exception as exc:

            self.log(
                "❌ Erro ao preparar mapa: "
                f"{exc}"
            )

            self.log_detail(
                f"Erro detalhado ao preparar mapa: "
                f"{exc}"
            )


    # ============================================================
    # GEOCODE SUMMARY
    # ============================================================

    def summarize_geocode(
        self,
        parsed,
    ):

        if not isinstance(
            parsed,
            dict,
        ):

            return None


        results = parsed.get(
            "results"
        )

        if not results:
            return None


        first = results[0]

        if not isinstance(
            first,
            dict,
        ):

            return None


        lat = first.get(
            "lat"
        )

        lon = first.get(
            "lon"
        )


        if lat is None or lon is None:

            return None


        return {
            "name": first.get(
                "name"
            ),
            "lat": float(lat),
            "lon": float(lon),
        }


    # ============================================================
    # REGISTRA PONTO GEOCODIFICADO
    # ============================================================

    def register_geocoded_point(
        self,
        parsed,
    ):

        point = self.summarize_geocode(
            parsed
        )


        if point is None:

            self.log(
                "⚠️ Não foi possível extrair "
                "coordenadas do resultado da geocodificação."
            )

            return


        self.geocoded_points.append(
            point
        )


        self.log(
            "📍 "
            f"{point['name']} — "
            f"{point['lat']:.6f}, "
            f"{point['lon']:.6f}"
        )


    # ============================================================
    # RESUMO EVALUATE
    # ============================================================

    def summarize_evaluate(
        self,
        parsed,
    ):

        if not isinstance(
            parsed,
            dict,
        ):

            return None


        if "fspl" in parsed:

            return parsed["fspl"]


        technical = parsed.get(
            "technical"
        )

        if isinstance(
            technical,
            dict,
        ):

            if "fspl" in technical:

                return technical["fspl"]


        data = parsed.get(
            "data"
        )

        if isinstance(
            data,
            dict,
        ):

            if "fspl" in data:

                return data["fspl"]


        return None


    # ============================================================
    # VISUALIZAÇÕES AUTOMÁTICAS
    # ============================================================

    async def gerar_visualizacoes(
        self
    ):

        if not self.evaluate_executed:
            return


        if self.evaluate_error is not None:
            return


        if self.mcp_session is None:

            self.log_detail(
                "⚠️ Não é possível gerar visualizações: "
                "sessão MCP inexistente."
            )

            return


        self.log(
            "📊 Gerando visualizações do enlace..."
        )


        self.visualizations = []


        # --------------------------------------------------------
        # IMPORTANTE:
        # O modelo NÃO escolhe essas ferramentas.
        #
        # Os parâmetros abaixo correspondem aos schemas reais.
        #
        # link_area exige ds_string.
        # --------------------------------------------------------

        etapas = [

            (
                "DTM",
                "link_area",
                {
                    "ds_string": "DTM",
                },
            ),

            (
                "DSM",
                "link_area",
                {
                    "ds_string": "DSM",
                },
            ),

            (
                "COVER",
                "link_area",
                {
                    "ds_string": "COVER",
                },
            ),

            (
                "Perfil do enlace",
                "link_profile",
                {},
            ),

            (
                "LULC / Fresnel",
                "lulc_fresnel",
                {},
            ),

            (
                "Preparação das edificações",
                "bldg_prepare",
                {},
            ),

            (
                "Edificações / Fresnel",
                "bldg_fresnel",
                {},
            ),

            (
                "Edificações / Perfil",
                "bldg_profile",
                {},
            ),
        ]


        for titulo, tool_name, arguments in etapas:

            self.log_detail("")

            self.log_detail(
                f"📊 Visualização: {titulo}"
            )


            try:

                raw_result = (
                    await self.execute_mcp_tool_raw(
                        tool_name,
                        arguments,
                    )
                )


            except Exception as exc:

                self.log_detail(
                    f"❌ Exceção em {titulo}: "
                    f"{exc}"
                )

                continue


            parsed = self.parse_mcp_result(
                raw_result
            )


            if self.is_mcp_error(
                raw_result,
                parsed,
            ):

                self.log_detail(
                    f"⚠️ Falha na visualização: "
                    f"{titulo}"
                )

                continue


            # ----------------------------------------------------
            # Extrai imagens sem perder ImageContent
            # ----------------------------------------------------

            images = (
                self.extract_images_from_mcp_result(
                    raw_result,
                    parsed,
                )
            )


            if not images:

                self.log_detail(
                    f"ℹ️ {titulo}: "
                    "resultado não visualizável."
                )

                continue


            for image in images:

                try:

                    data = image.get(
                        "data"
                    )

                    if not data:
                        continue


                    image_bytes = (
                        base64.b64decode(
                            data,
                            validate=True,
                        )
                    )


                    if not image_bytes:
                        continue


                    mime_type = (
                        image.get(
                            "mimeType",
                            "image/png",
                        )
                        or "image/png"
                    )


                    image_format = (
                        mime_type
                        .split("/")[-1]
                        .lower()
                    )


                    if image_format == "jpeg":

                        image_format = "jpg"


                    widget = widgets.Image(
                        value=image_bytes,
                        format=image_format,
                        layout=widgets.Layout(
                            width="100%",
                            max_width="1200px",
                            height="auto",
                        ),
                    )


                    self.visualizations.append(
                        widget
                    )


                    self.log_detail(
                        f"✅ {titulo}: "
                        "imagem recebida."
                    )


                except Exception as exc:

                    self.log_detail(
                        f"❌ Erro ao decodificar "
                        f"{titulo}: {exc}"
                    )


        # --------------------------------------------------------
        # Publica lista completa para a UI
        # --------------------------------------------------------

        if self.visualization_callback:

            try:

                self.visualization_callback(
                    self.visualizations
                )

            except Exception as exc:

                self.log_detail(
                    "❌ Erro ao atualizar "
                    f"visualizações: {exc}"
                )


        self.log(
            f"📊 {len(self.visualizations)} "
            "visualizações geradas."
        )


    # ============================================================
    # EXECUÇÃO MCP — RAW
    #
    # Mantém ImageContent.
    # ============================================================

    async def execute_mcp_tool_raw(
        self,
        tool_name,
        arguments,
    ):

        self.tool_count += 1


        self.log_detail("")

        self.log_detail(
            f"🔧 MCP TOOL: {tool_name}"
        )

        self.log_detail(
            "Argumentos:"
        )

        self.log_detail(
            json.dumps(
                arguments or {},
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )


        try:

            result = await (
                self.mcp_session.call_tool(
                    tool_name,
                    arguments or {},
                )
            )


        except Exception as exc:

            error_result = {
                "status": "error",
                "kind": "mcp_exception",
                "tool": tool_name,
                "error": str(exc),
            }


            self.log_detail(
                "❌ Exceção durante chamada MCP:"
            )

            self.log_detail(
                json.dumps(
                    error_result,
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                )
            )


            if tool_name == "evaluate_link":

                self.evaluate_executed = True

                self.evaluate_error = (
                    error_result
                )

                self.last_evaluate_result = (
                    error_result
                )

                self.publish_technical_result(
                    error_result
                )


            return error_result


        parsed = self.parse_mcp_result(
            result
        )


        self.log_detail(
            "Resultado:"
        )


        self.log_detail(
            json.dumps(
                self.make_log_safe(
                    parsed
                ),
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )


        mcp_error = self.is_mcp_error(
            result,
            parsed,
        )


        if mcp_error:

            self.log_detail(
                "❌ MCP retornou erro."
            )


        # --------------------------------------------------------
        # GEOCODE
        # --------------------------------------------------------

        if tool_name == "geocode_place":

            if not mcp_error:

                before = len(
                    self.geocoded_points
                )

                self.register_geocoded_point(
                    parsed
                )

                after = len(
                    self.geocoded_points
                )


                if (
                    before < 2
                    and after == 2
                ):

                    await (
                        self.mostrar_mapa_apos_geocodificacao()
                    )


            else:

                self.log(
                    "❌ Falha na geocodificação."
                )


        # --------------------------------------------------------
        # EVALUATE
        # --------------------------------------------------------

        elif tool_name == "evaluate_link":

            self.evaluate_executed = True

            self.last_evaluate_result = (
                parsed
            )


            if mcp_error:

                self.evaluate_error = (
                    parsed
                )

                self.log(
                    "❌ A avaliação técnica "
                    "retornou erro."
                )

                self.publish_technical_result(
                    parsed
                )


            else:

                self.evaluate_error = None

                # ----------------------------------------------
                # Resultado técnico REAL
                # ----------------------------------------------

                self.publish_technical_result(
                    parsed
                )


                # ----------------------------------------------
                # Visualizações
                # ----------------------------------------------

                await (
                    self.gerar_visualizacoes()
                )


                fspl = (
                    self.summarize_evaluate(
                        parsed
                    )
                )


                if fspl is not None:

                    try:

                        self.log(
                            f"📥 FSPL: "
                            f"{float(fspl):.2f}"
                        )

                    except Exception:

                        self.log(
                            f"📥 FSPL: {fspl}"
                        )

                else:

                    self.log(
                        "🟢 Avaliação técnica concluída."
                    )


        return result


    # ============================================================
    # EXECUÇÃO MCP — PARSED
    # ============================================================

    async def execute_mcp_tool(
        self,
        tool_name,
        arguments,
    ):

        raw = await (
            self.execute_mcp_tool_raw(
                tool_name,
                arguments,
            )
        )

        return self.parse_mcp_result(
            raw
        )


    # ============================================================
    # REGISTER
    # ============================================================

    async def register(self):

        self.log(
            "👤 Registrando usuário no PlanApp..."
        )


        result = await (
            self.execute_mcp_tool(
                "register",
                {
                    "user_id": USER_ID,
                },
            )
        )


        if isinstance(
            result,
            dict,
        ):

            status = str(
                result.get(
                    "status",
                    "",
                )
            ).lower()


            if status == "error":

                self.log(
                    "❌ Falha no registro do usuário."
                )

                return result


        self.log(
            "🟢 Usuário registrado."
        )


        return result


    # ============================================================
    # EVALUATE AUTOMÁTICO
    # ============================================================

    async def ensure_evaluate_link(
        self,
        parameters=None,
    ):

        if self.evaluate_executed:

            return self.last_evaluate_result


        if len(
            self.geocoded_points
        ) < 2:

            return None


        if parameters is None:

            parameters = (
                self.link_parameters
            )


        tx = self.geocoded_points[0]
        rx = self.geocoded_points[1]


        arguments = {

            "tx_lat": tx["lat"],

            "tx_lon": tx["lon"],

            "rx_lat": rx["lat"],

            "rx_lon": rx["lon"],

            "tx_ha": parameters.get(
                "tx_ha",
                DEFAULT_TX_HA,
            ),

            "rx_ha": parameters.get(
                "rx_ha",
                DEFAULT_RX_HA,
            ),

            "freq_mhz": parameters.get(
                "freq_mhz",
                DEFAULT_FREQ_MHZ,
            ),

            "on_rooftop": parameters.get(
                "on_rooftop",
                DEFAULT_ON_ROOFTOP,
            ),
        }


        self.log(
            "📡 Executando avaliação técnica "
            "do enlace..."
        )


        self.log_detail(
            "Parâmetros enviados ao PlanApp:"
        )


        self.log_detail(
            json.dumps(
                arguments,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )


        return await (
            self.execute_mcp_tool(
                "evaluate_link",
                arguments,
            )
        )


    # ============================================================
    # CONTEXTO TÉCNICO PARA O MODELO
    # ============================================================

    def build_technical_context(
        self,
        technical_result,
    ):

        effective = {
            "freq_mhz": (
                self.link_parameters.get(
                    "freq_mhz"
                )
            ),
            "tx_ha": (
                self.link_parameters.get(
                    "tx_ha"
                )
            ),
            "rx_ha": (
                self.link_parameters.get(
                    "rx_ha"
                )
            ),
            "on_rooftop": (
                self.link_parameters.get(
                    "on_rooftop"
                )
            ),
        }


        requested = {
            "frequency": (
                self.requested_frequency
            ),
            "frequency_unit": (
                self.requested_frequency_unit
            ),
            "frequency_text": (
                self.requested_frequency_text
            ),
            "tx_ha": (
                self.requested_tx_ha
            ),
            "rx_ha": (
                self.requested_rx_ha
            ),
        }


        conversion_text = ""


        if (
            self.requested_frequency is not None
            and self.requested_frequency_unit is not None
        ):

            conversion_text = (
                "A frequência foi informada pelo "
                f"usuário como "
                f"{self.requested_frequency_text}. "
                "A conversão para MHz foi usada "
                "somente internamente no parâmetro "
                "freq_mhz enviado ao PlanApp."
            )


        return {

            "parametros_solicitados_pelo_usuario":
                requested,

            "parametros_efetivos_enviados_ao_planapp":
                effective,

            "conversao_de_frequencia":
                conversion_text,

            "pontos_geocodificados":
                self.geocoded_points,

            "resultado_tecnico_real_do_planapp":
                technical_result,

            "regras_criticas": [

                "Responder somente em português "
                "do Brasil.",

                "Não mostrar raciocínio interno.",

                "Não inventar valores.",

                "Não inventar unidades.",

                "Não alterar valores do PlanApp.",

                "Não converter radianos para graus.",

                "Não interpretar core, fresnel, "
                "boundary, delta_diffra, VV, "
                "v_v ou d_norm sem definição "
                "explícita.",

                "Não concluir viabilidade apenas "
                "com status OK.",

                "Não transformar core, fresnel "
                "ou boundary em dB.",

                "Se houver erro, informar o erro "
                "real retornado pelo PlanApp.",

            ],
        }


    # ============================================================
    # CHAMADA OPENROUTER
    # ============================================================

    async def openrouter_chat(
        self,
        messages,
        tools=None,
    ):

        if self.client is None:

            raise RuntimeError(
                "OPENROUTER_API_KEY não está "
                "configurada no ambiente."
            )


        kwargs = {
            "model": OPENROUTER_MODEL,
            "messages": messages,
        }


        if tools:

            kwargs["tools"] = tools

            kwargs["tool_choice"] = "auto"


        else:

            # ----------------------------------------------------
            # IMPORTANTE:
            # A resposta final NÃO recebe ferramentas.
            # ----------------------------------------------------

            kwargs["tools"] = []


        response = await (
            self.client.chat.completions.create(
                **kwargs
            )
        )


        return response


    # ============================================================
    # LIMPEZA DA RESPOSTA FINAL
    # ============================================================

    def clean_final_response(
        self,
        text,
    ):

        if not text:

            return ""


        text = text.strip()


        # --------------------------------------------------------
        # Remove blocos <think>...</think>
        # --------------------------------------------------------

        text = re.sub(
            r"<think>.*?</think>",
            "",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )


        # --------------------------------------------------------
        # Remove tags de raciocínio
        # --------------------------------------------------------

        text = re.sub(
            r"<reasoning>.*?</reasoning>",
            "",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )


        text = text.strip()


        # --------------------------------------------------------
        # Caso o modelo tenha começado a expor o raciocínio.
        #
        # Tentamos localizar uma seção de resposta final.
        # --------------------------------------------------------

        lower = text.lower()


        thinking_markers = [
            "here's a thinking process:",
            "here is a thinking process:",
            "thinking process:",
            "raciocínio:",
            "processo de pensamento:",
            "let's analyze:",
            "let me analyze:",
        ]


        found_marker = None

        for marker in thinking_markers:

            if marker in lower:

                found_marker = marker

                break


        if found_marker:

            # ----------------------------------------------
            # Se houver uma resposta final explícita,
            # preserva somente essa parte.
            # ----------------------------------------------

            final_markers = [
                "final answer:",
                "resposta final:",
                "resposta:",
            ]


            for final_marker in final_markers:

                index = lower.find(
                    final_marker,
                    lower.find(found_marker),
                )

                if index >= 0:

                    text = text[
                        index
                        + len(final_marker):
                    ].strip()

                    break

            else:

                # ------------------------------------------
                # Não mostrar raciocínio interno.
                # ------------------------------------------

                return (
                    "A avaliação técnica foi executada "
                    "pelo PlanApp. Os resultados técnicos "
                    "detalhados estão disponíveis no "
                    "painel de resultados."
                )


        return text.strip()


    # ============================================================
    # RESPOSTA FINAL
    # ============================================================

    async def generate_final_response(
        self,
        original_text,
        technical_result,
    ):

        context = (
            self.build_technical_context(
                technical_result
            )
        )


        final_messages = [

            {
                "role": "system",
                "content": self.system_prompt(),
            },

            {
                "role": "user",
                "content": original_text,
            },

            {
                "role": "user",
                "content": (
                    "DADOS TÉCNICOS FINAIS DO PLANAPP.\n\n"
                    + json.dumps(
                        context,
                        ensure_ascii=False,
                        indent=2,
                        default=str,
                    )
                ),
            },

            {
                "role": "user",
                "content": """
Produza agora SOMENTE a resposta final destinada ao usuário.

REGRAS ABSOLUTAS PARA ESTA RESPOSTA:

- Português do Brasil.
- Não mostre raciocínio.
- Não mostre processo de pensamento.
- Não escreva "Here's a thinking process".
- Não escreva "Thinking process".
- Não escreva "Let's analyze".
- Não escreva "Step 1", "Step 2" etc.
- Não explique o que você está fazendo.
- Não fale sobre as instruções recebidas.
- Não faça chamadas de ferramentas.
- Não invente valores.
- Não invente unidades.
- Não transforme campos técnicos desconhecidos em conceitos conhecidos.
- Use somente os dados reais fornecidos pelo PlanApp.
- Seja objetivo.

Apresente os principais resultados técnicos de forma legível.
""",
            },
        ]


        response = await (
            self.openrouter_chat(
                final_messages,
                tools=None,
            )
        )


        message = response.choices[0].message


        content = (
            getattr(
                message,
                "content",
                None,
            )
            or ""
        )


        cleaned = (
            self.clean_final_response(
                content
            )
        )


        # --------------------------------------------------------
        # Se ainda houver sinais de raciocínio exposto,
        # fazemos uma segunda chamada específica de correção.
        # --------------------------------------------------------

        lower = cleaned.lower()


        suspicious = any(
            marker in lower
            for marker in [
                "here's a thinking process",
                "thinking process:",
                "raciocínio:",
                "processo de pensamento:",
                "let's analyze:",
                "step 1:",
                "step 2:",
            ]
        )


        if suspicious:

            repair_messages = [

                {
                    "role": "system",
                    "content": (
                        "Você é o PlanApp AI. "
                        "Responda exclusivamente em "
                        "português do Brasil. "
                        "Nunca revele raciocínio interno."
                    ),
                },

                {
                    "role": "user",
                    "content": (
                        "Gere somente uma resposta final "
                        "objetiva ao usuário usando os "
                        "dados técnicos abaixo.\n\n"
                        + json.dumps(
                            context,
                            ensure_ascii=False,
                            indent=2,
                            default=str,
                        )
                    ),
                },
            ]


            repair_response = await (
                self.openrouter_chat(
                    repair_messages,
                    tools=None,
                )
            )


            repaired_content = (
                getattr(
                    repair_response.choices[0].message,
                    "content",
                    None,
                )
                or ""
            )


            cleaned = (
                self.clean_final_response(
                    repaired_content
                )
            )


        return cleaned


    # ============================================================
    # TURNO DO AGENTE
    # ============================================================

    async def agent_turn(
        self,
        original_text,
    ):

        tools = (
            self.build_openrouter_tools()
        )


        for iteration in range(
            MAX_AGENT_ITERATIONS
        ):

            self.log_detail(
                f"🤖 Iteração do agente: "
                f"{iteration + 1}/"
                f"{MAX_AGENT_ITERATIONS}"
            )


            response = await (
                self.openrouter_chat(
                    self.messages,
                    tools=tools,
                )
            )


            message = response.choices[0].message


            content = (
                getattr(
                    message,
                    "content",
                    None,
                )
                or ""
            )


            tool_calls = (
                getattr(
                    message,
                    "tool_calls",
                    None,
                )
                or []
            )


            # ----------------------------------------------------
            # Nenhuma ferramenta solicitada
            # ----------------------------------------------------

            if not tool_calls:

                # ----------------------------------------------
                # Se já temos dois pontos e ainda não avaliamos,
                # a aplicação executa evaluate_link.
                # ----------------------------------------------

                if (
                    len(
                        self.geocoded_points
                    ) >= 2
                    and not self.evaluate_executed
                ):

                    technical_result = (
                        await self.ensure_evaluate_link(
                            self.link_parameters
                        )
                    )


                    self.messages.append(
                        {
                            "role": "user",
                            "content": (
                                "CONTEXTO TÉCNICO DO PLANAPP:\n"
                                + json.dumps(
                                    self.build_technical_context(
                                        technical_result
                                    ),
                                    ensure_ascii=False,
                                    indent=2,
                                    default=str,
                                )
                            ),
                        }
                    )


                    continue


                return content


            # ----------------------------------------------------
            # Mensagem do assistant com tool_calls
            # ----------------------------------------------------

            assistant_message = {
                "role": "assistant",
                "content": content or None,
                "tool_calls": [],
            }


            for tool_call in tool_calls:

                function = getattr(
                    tool_call,
                    "function",
                    None,
                )


                if function is None:
                    continue


                name = getattr(
                    function,
                    "name",
                    None,
                )


                arguments = getattr(
                    function,
                    "arguments",
                    "{}",
                )


                assistant_message[
                    "tool_calls"
                ].append(
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": arguments,
                        },
                    }
                )


            self.messages.append(
                assistant_message
            )


            # ----------------------------------------------------
            # Executa cada tool call
            # ----------------------------------------------------

            for tool_call in tool_calls:

                function = getattr(
                    tool_call,
                    "function",
                    None,
                )


                if function is None:
                    continue


                tool_name = getattr(
                    function,
                    "name",
                    None,
                )


                arguments = getattr(
                    function,
                    "arguments",
                    "{}",
                )


                if isinstance(
                    arguments,
                    str,
                ):

                    try:

                        arguments = json.loads(
                            arguments
                        )

                    except Exception:

                        arguments = {}


                # ----------------------------------------------
                # Segurança:
                # somente geocode_place pode ser chamado
                # pelo modelo.
                # ----------------------------------------------

                if (
                    tool_name
                    not in MODEL_ALLOWED_TOOLS
                ):

                    result = {
                        "status": "error",
                        "error": (
                            "Ferramenta não permitida "
                            "para execução pelo modelo."
                        ),
                        "tool": tool_name,
                    }

                else:

                    result = (
                        await self.execute_mcp_tool(
                            tool_name,
                            arguments,
                        )
                    )


                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": (
                            tool_call.id
                        ),
                        "content": json.dumps(
                            result,
                            ensure_ascii=False,
                            default=str,
                        ),
                    }
                )


            # ----------------------------------------------------
            # Se já temos os dois pontos,
            # execute evaluate_link automaticamente.
            # ----------------------------------------------------

            if (
                len(
                    self.geocoded_points
                ) >= 2
                and not self.evaluate_executed
            ):

                technical_result = (
                    await self.ensure_evaluate_link(
                        self.link_parameters
                    )
                )


                self.messages.append(
                    {
                        "role": "user",
                        "content": (
                            "A geocodificação foi concluída. "
                            "A aplicação executou automaticamente "
                            "evaluate_link. "
                            "Use exclusivamente os dados técnicos "
                            "abaixo para a resposta final.\n\n"
                            + json.dumps(
                                self.build_technical_context(
                                    technical_result
                                ),
                                ensure_ascii=False,
                                indent=2,
                                default=str,
                            )
                        ),
                    }
                )


                # ----------------------------------------------
                # A próxima iteração será a resposta final.
                # ----------------------------------------------

                continue


        return (
            "A análise foi executada, mas o modelo "
            "atingiu o limite de processamento da resposta."
        )


    # ============================================================
    # ASK
    # ============================================================

    async def ask(
        self,
        text,
    ):

        # --------------------------------------------------------
        # Verificação da API key
        # --------------------------------------------------------

        if not OPENROUTER_API_KEY:

            error_message = (
                "OPENROUTER_API_KEY não está configurada "
                "no ambiente do Jupyter."
            )

            self.log(
                "❌ " + error_message
            )

            return error_message


        # --------------------------------------------------------
        # Reset
        # --------------------------------------------------------

        self.messages = []

        self.geocoded_points = []

        self.evaluate_executed = False

        self.last_evaluate_result = None

        self.evaluate_error = None

        self.visualizations = []

        self.map = None

        self.tool_count = 0

        self.current_stage = 0


        # --------------------------------------------------------
        # Limpa visualizações da UI
        # --------------------------------------------------------

        if self.visualization_callback:

            try:

                self.visualization_callback(
                    []
                )

            except Exception:
                pass


        # --------------------------------------------------------
        # Parâmetros
        # --------------------------------------------------------

        parameters = (
            self.extract_link_parameters(
                text
            )
        )


        self.log(
            "🟡 Etapa 1 — Processando solicitação"
        )


        self.log_detail(
            "Parâmetros detectados:"
        )


        self.log_detail(
            json.dumps(
                parameters,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )


        # --------------------------------------------------------
        # MCP
        # --------------------------------------------------------

        await self.connect()


        register_result = (
            await self.register()
        )


        if (
            isinstance(
                register_result,
                dict,
            )
            and str(
                register_result.get(
                    "status",
                    "",
                )
            ).lower()
            == "error"
        ):

            return (
                "Não foi possível registrar o usuário "
                "no PlanApp."
            )


        # --------------------------------------------------------
        # Mensagens iniciais
        # --------------------------------------------------------

        self.messages = [

            {
                "role": "system",
                "content": self.system_prompt(),
            },

            {
                "role": "user",
                "content": text,
            },
        ]


        # --------------------------------------------------------
        # Agente
        # --------------------------------------------------------

        resultado = await (
            self.agent_turn(
                text
            )
        )


        # --------------------------------------------------------
        # Garantia final:
        # se temos dois pontos mas evaluate não foi executado,
        # executamos diretamente pela aplicação.
        # --------------------------------------------------------

        if (
            len(
                self.geocoded_points
            ) >= 2
            and not self.evaluate_executed
        ):

            technical_result = (
                await self.ensure_evaluate_link(
                    parameters
                )
            )

            # ----------------------------------------------
            # Gera resposta final diretamente.
            # ----------------------------------------------

            resultado = (
                await self.generate_final_response(
                    text,
                    technical_result,
                )
            )


        # --------------------------------------------------------
        # Se evaluate já ocorreu, sempre gera resposta final
        # baseada nos dados reais do PlanApp.
        # --------------------------------------------------------

        elif self.evaluate_executed:

            resultado = (
                await self.generate_final_response(
                    text,
                    self.last_evaluate_result,
                )
            )


        # --------------------------------------------------------
        # Garantia final do mapa
        # --------------------------------------------------------

        if (
            len(
                self.geocoded_points
            ) >= 2
            and self.map is None
        ):

            await (
                self.mostrar_mapa_apos_geocodificacao()
            )


        if self.map is not None:

            self.log(
                "🗺️ Mapa disponível."
            )


        # --------------------------------------------------------
        # Estado final
        # --------------------------------------------------------

        if self.evaluate_error is not None:

            self.current_stage = 3

            self.log(
                "🔴 Etapa 3 — Avaliação técnica "
                "não concluída"
            )

            self.log(
                "❌ A análise técnica retornou erro."
            )


        elif self.evaluate_executed:

            self.current_stage = 3

            self.log(
                "🔵 Etapa 3 — Interpretando resultados"
            )

            self.log(
                "🟢 Resultado técnico recebido "
                "do PlanApp."
            )

            self.log(
                "🟢 Análise concluída."
            )


        else:

            self.current_stage = 3

            self.log(
                "🟡 Análise concluída sem "
                "avaliação técnica."
            )


        return resultado


    # ============================================================
    # CLOSE
    # ============================================================

    async def close(self):

        try:

            await self.exit_stack.aclose()

        finally:

            self.mcp_session = None

            self.mcp_tools = []

            self.connected = False