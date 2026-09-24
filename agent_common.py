# ============================================================
# PLANAPP AI — COMMON
#
# ETAPA 2 — MULTI-HOP
#
# Este módulo contém a lógica compartilhada pelos:
#
#   agent_ollama.py
#   agent_openai.py
#   agent_openrouter.py
#
# Arquitetura:
#
#   LLM
#      |
#      +--> geocode_place
#      |
#      v
#   aplicação
#      |
#      +--> evaluate_link
#      |
#      +--> multi-hop
#      |
#      +--> mapa
#      |
#      +--> visualizações
#
# IMPORTANTE:
#
# evaluate_link continua representando UM enlace.
#
# A lógica multi-hop somente orquestra várias chamadas
# independentes de evaluate_link:
#
#   A -> B
#   B -> C
#   C -> D
#
# A lógica específica de cada LLM permanece nos respectivos
# arquivos:
#
#   Ollama       -> agent_ollama.py
#   OpenAI       -> agent_openai.py
#   OpenRouter   -> agent_openrouter.py
#
# ============================================================

import asyncio
import base64
import json
import logging
import os
import re

from contextlib import AsyncExitStack
from datetime import datetime

import ipywidgets as widgets

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


# ============================================================
# CONFIGURAÇÕES COMUNS
# ============================================================

MCP_URL = os.getenv(
    "PLANAPP_MCP_URL",
    "http://172.17.0.1:8010/mcp",
)

USER_ID = os.getenv(
    "PLANAPP_USER_ID",
    "jupyter-user",
)

DEFAULT_FREQ_MHZ = 900
DEFAULT_TX_HA = 7
DEFAULT_RX_HA = 7
DEFAULT_ON_ROOFTOP = False

MAX_AGENT_ITERATIONS = 12

LOG_DIR = os.path.expanduser(
    "~/work/planapp-mcp/logs"
)


# ============================================================
# FERRAMENTAS CONTROLADAS PELA APLICAÇÃO
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
# CLASSE BASE
# ============================================================

class PlanAppAgentCommon:

    """
    Classe base compartilhada pelos três agentes.

    Esta classe não implementa a chamada ao LLM.

    Cada agente filho mantém sua própria implementação:

        Ollama:
            ollama_chat()

        OpenAI:
            Responses API

        OpenRouter:
            openrouter_chat()
    """

    AGENT_NAME = "PLANAPP AI"

    def __init__(
        self,
        progress_callback=None,
        map_callback=None,
        log_callback=None,
        result_callback=None,
        visualization_callback=None,
    ):

        # --------------------------------------------------------
        # Callbacks
        # --------------------------------------------------------

        self.progress_callback = progress_callback
        self.map_callback = map_callback
        self.log_callback = log_callback
        self.result_callback = result_callback
        self.visualization_callback = visualization_callback

        # --------------------------------------------------------
        # MCP
        # --------------------------------------------------------

        self.exit_stack = AsyncExitStack()
        self.mcp_session = None
        self.mcp_tools = []
        self.connected = False

        # --------------------------------------------------------
        # Conversação
        # --------------------------------------------------------

        self.messages = []

        # --------------------------------------------------------
        # Pontos geocodificados
        # --------------------------------------------------------

        self.geocoded_points = []

        # --------------------------------------------------------
        # ETAPA 2 — ESTADO MULTI-HOP
        # --------------------------------------------------------

        self.route_points = []
        self.hops = []
        self.current_hop = None
        self.global_result = None
        self.multi_hop_executed = False
        self.multi_hop_error = None

        # --------------------------------------------------------
        # Estado da avaliação
        # --------------------------------------------------------

        self.evaluate_executed = False
        self.last_evaluate_result = None
        self.evaluate_error = None

        # --------------------------------------------------------
        # Visualizações
        # --------------------------------------------------------

        self.visualizations = []

        # --------------------------------------------------------
        # Mapa
        # --------------------------------------------------------

        self.map = None

        # --------------------------------------------------------
        # Controle
        # --------------------------------------------------------

        self.tool_count = 0
        self.current_stage = 0

        # --------------------------------------------------------
        # Parâmetros do enlace
        # --------------------------------------------------------

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
        # Logging
        #
        # Data + hora:
        #
        # planapp_agent_common_YYYYMMDD_HHMMSS.log
        # --------------------------------------------------------

        os.makedirs(
            LOG_DIR,
            exist_ok=True,
        )

        timestamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )

        self.log_file_path = os.path.join(
            LOG_DIR,
            (
                "planapp_agent_common_"
                f"{timestamp}.log"
            ),
        )

        self.logger = logging.getLogger(
            f"PlanAppAgentCommon_{id(self)}"
        )

        self.logger.setLevel(
            logging.INFO
        )

        self.logger.propagate = False

        self.file_handler = logging.FileHandler(
            self.log_file_path,
            encoding="utf-8",
        )

        self.file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | "
                "%(levelname)s | "
                "%(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

        self.logger.addHandler(
            self.file_handler
        )

    # ============================================================
    # STATUS / LOG
    # ============================================================

    def log(
        self,
        message,
    ):

        text = str(message)

        try:
            self.logger.info(text)
        except Exception:
            pass

        if self.progress_callback:
            try:
                self.progress_callback(text)
            except Exception:
                pass

    def log_detail(
        self,
        message,
    ):

        text = str(message)

        try:
            self.logger.info(text)
        except Exception:
            pass

        if self.log_callback:
            try:
                self.log_callback(text)
            except Exception:
                pass

    def publish_technical_result(
        self,
        result,
    ):

        if self.result_callback:
            try:
                self.result_callback(result)
            except Exception:
                pass

    # ============================================================
    # EXTRAÇÃO DOS PARÂMETROS
    # ============================================================

    def extract_link_parameters(
        self,
        text,
    ):

        text = text or ""

        parameters = {
            "freq_mhz": DEFAULT_FREQ_MHZ,
            "tx_ha": DEFAULT_TX_HA,
            "rx_ha": DEFAULT_RX_HA,
            "on_rooftop": DEFAULT_ON_ROOFTOP,
        }

        # --------------------------------------------------------
        # Reset dos parâmetros solicitados
        # --------------------------------------------------------

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

            unit = (
                freq_match.group(2)
                .lower()
            )

            value = float(
                value_text.replace(
                    ",",
                    ".",
                )
            )

            self.requested_frequency = value
            self.requested_frequency_unit = unit
            self.requested_frequency_text = (
                freq_match.group(0)
            )

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

            (
                r"duas\s+antenas?\s+de\s+"
                r"(\d+(?:[.,]\d+)?)\s*"
                r"(?:m|metros?)"
            ),

            (
                r"antenas?\s+de\s+"
                r"(\d+(?:[.,]\d+)?)\s*"
                r"(?:m|metros?)"
            ),
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
                .replace(
                    ",",
                    ".",
                )
            )

            parameters["tx_ha"] = height
            parameters["rx_ha"] = height

            self.requested_tx_ha = height
            self.requested_rx_ha = height

        else:

            # ----------------------------------------------------
            # TX
            # ----------------------------------------------------

            tx_match = re.search(
                r"(?:tx|transmissora?|transmissor)"
                r".{0,30}?"
                r"(\d+(?:[.,]\d+)?)\s*"
                r"(?:m|metros?)",
                text,
                re.IGNORECASE,
            )

            # ----------------------------------------------------
            # RX
            # ----------------------------------------------------

            rx_match = re.search(
                r"(?:rx|receptora?|receptor)"
                r".{0,30}?"
                r"(\d+(?:[.,]\d+)?)\s*"
                r"(?:m|metros?)",
                text,
                re.IGNORECASE,
            )

            if tx_match:

                height = float(
                    tx_match.group(1)
                    .replace(
                        ",",
                        ".",
                    )
                )

                parameters["tx_ha"] = height
                self.requested_tx_ha = height

            if rx_match:

                height = float(
                    rx_match.group(1)
                    .replace(
                        ",",
                        ".",
                    )
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

    async def connect(
        self,
    ):

        if self.connected:
            return

        self.log(
            "🔌 Conectando ao PlanApp MCP..."
        )

        transport = await (
            self.exit_stack
            .enter_async_context(
                streamable_http_client(
                    MCP_URL
                )
            )
        )

        if len(transport) == 2:

            (
                read_stream,
                write_stream,
            ) = transport

        else:

            (
                read_stream,
                write_stream,
                _,
            ) = transport

        self.mcp_session = await (
            self.exit_stack
            .enter_async_context(
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

        self.mcp_tools = (
            getattr(
                tools_result,
                "tools",
                [],
            )
            or []
        )

        self.connected = True

        self.log(
            "🟢 MCP conectado — "
            f"{len(self.mcp_tools)} "
            "ferramentas disponíveis."
        )

        self.log_detail(
            "Ferramentas MCP disponíveis:"
        )

        for tool in self.mcp_tools:

            try:
                self.log_detail(
                    f"  - {tool.name}"
                )
            except Exception:
                pass

    # ============================================================
    # PARSING MCP
    # ============================================================

    def parse_mcp_result(
        self,
        result,
    ):

        if result is None:
            return None

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

                    if isinstance(
                        item,
                        dict,
                    ):

                        text = item.get(
                            "text"
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
    # DETECÇÃO DE ERROS
    # ============================================================

    def contains_nested_error(
        self,
        value,
    ):

        if isinstance(
            value,
            dict,
        ):

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

                if self.contains_nested_error(
                    child
                ):
                    return True

        elif isinstance(
            value,
            list,
        ):

            for child in value:

                if self.contains_nested_error(
                    child
                ):
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

    def make_log_safe(
        self,
        value,
    ):

        if isinstance(
            value,
            dict,
        ):

            safe = {}

            for key, child in value.items():

                if (
                    key == "data"
                    and isinstance(
                        child,
                        str,
                    )
                    and len(child) > 500
                ):

                    safe[key] = (
                        "<base64 image: "
                        f"{len(child)} chars>"
                    )

                else:

                    safe[key] = (
                        self.make_log_safe(
                            child
                        )
                    )

            return safe

        if isinstance(
            value,
            list,
        ):

            return [
                self.make_log_safe(
                    child
                )
                for child in value
            ]

        return value

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

        lat = first.get("lat")
        lon = first.get("lon")

        if lat is None or lon is None:
            return None

        try:

            lat = float(lat)
            lon = float(lon)

        except Exception:

            return None

        return {
            "name": first.get("name"),
            "lat": lat,
            "lon": lon,
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
                "coordenadas do resultado "
                "da geocodificação."
            )

            return None

        self.geocoded_points.append(
            point
        )

        self.log(
            "📍 "
            f"{point.get('name')} — "
            f"{point['lat']:.6f}, "
            f"{point['lon']:.6f}"
        )

        return point

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
    # EXECUÇÃO MCP — RAW
    # ============================================================

    async def execute_mcp_tool_raw(
        self,
        tool_name,
        arguments,
    ):

        if self.mcp_session is None:

            raise RuntimeError(
                "Sessão MCP não conectada."
            )

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
                "❌ Exceção durante "
                "chamada MCP:"
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

                    try:

                        await (
                            self.mostrar_mapa_apos_geocodificacao()
                        )

                    except Exception as exc:

                        self.log_detail(
                            "⚠️ Erro ao preparar "
                            f"mapa: {exc}"
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

                self.publish_technical_result(
                    parsed
                )

                try:

                    await (
                        self.gerar_visualizacoes()
                    )

                except Exception as exc:

                    self.log_detail(
                        "⚠️ Erro ao gerar "
                        f"visualizações: {exc}"
                    )

                fspl = (
                    self.summarize_evaluate(
                        parsed
                    )
                )

                if fspl is not None:

                    try:

                        self.log(
                            "📥 FSPL: "
                            f"{float(fspl):.2f}"
                        )

                    except Exception:

                        self.log(
                            f"📥 FSPL: {fspl}"
                        )

                else:

                    self.log(
                        "🟢 Avaliação técnica "
                        "concluída."
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

    async def register(
        self,
    ):

        self.log(
            "👤 Registrando usuário "
            "no PlanApp..."
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
                    "❌ Falha no registro "
                    "do usuário."
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

        """
        Mantém o comportamento da ETAPA 1:

            P1 -> P2

        apenas uma avaliação.

        NÃO é multi-hop.
        """

        if self.evaluate_executed:

            return (
                self.last_evaluate_result
            )

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
            "📡 Executando avaliação "
            "técnica do enlace..."
        )

        self.log_detail(
            "Parâmetros enviados "
            "ao PlanApp:"
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
    # ETAPA 2 — AVALIAÇÃO MULTI-HOP
    # ============================================================

    async def ensure_multi_hop_evaluation(
        self,
        route_points=None,
        parameters=None,
    ):

        """
        ETAPA 2 — executa uma rota composta por vários enlaces.

        Exemplo:

            A -> B -> C -> D

        gera:

            Hop 1: A -> B
            Hop 2: B -> C
            Hop 3: C -> D

        evaluate_link continua sendo uma operação de UM enlace.
        """

        if self.multi_hop_executed:

            return self.global_result

        # --------------------------------------------------------
        # Pontos da rota
        # --------------------------------------------------------

        if route_points is None:
            route_points = self.geocoded_points

        if route_points is None:
            route_points = []

        if len(route_points) < 2:

            self.multi_hop_error = {

                "status":
                    "error",

                "kind":
                    "invalid_route",

                "error":
                    (
                        "Uma rota multi-hop precisa "
                        "de pelo menos dois pontos."
                    ),
            }

            self.log(
                "❌ Rota multi-hop inválida: "
                "menos de dois pontos."
            )

            return self.multi_hop_error

        # --------------------------------------------------------
        # Parâmetros
        # --------------------------------------------------------

        if parameters is None:
            parameters = self.link_parameters

        # --------------------------------------------------------
        # Copia da rota
        # --------------------------------------------------------

        self.route_points = [
            dict(point)
            for point in route_points
        ]

        # --------------------------------------------------------
        # Monta os hops consecutivos
        # --------------------------------------------------------

        self.hops = []

        for index in range(
            len(self.route_points) - 1
        ):

            tx = self.route_points[index]
            rx = self.route_points[index + 1]

            tx_name = tx.get(
                "name",
                f"Ponto {index + 1}",
            )

            rx_name = rx.get(
                "name",
                f"Ponto {index + 2}",
            )

            hop = {

                "id":
                    f"link_{index + 1:03d}",

                "index":
                    index + 1,

                "name":
                    f"{tx_name} → {rx_name}",

                "tx":
                    dict(tx),

                "rx":
                    dict(rx),

                "parameters": {

                    "freq_mhz":
                        parameters.get(
                            "freq_mhz",
                            DEFAULT_FREQ_MHZ,
                        ),

                    "tx_ha":
                        parameters.get(
                            "tx_ha",
                            DEFAULT_TX_HA,
                        ),

                    "rx_ha":
                        parameters.get(
                            "rx_ha",
                            DEFAULT_RX_HA,
                        ),

                    "on_rooftop":
                        parameters.get(
                            "on_rooftop",
                            DEFAULT_ON_ROOFTOP,
                        ),
                },

                "result":
                    None,

                "error":
                    None,

                "visualizations":
                    [],
            }

            self.hops.append(
                hop
            )

        # --------------------------------------------------------
        # Resultado global
        # --------------------------------------------------------

        self.global_result = {

            "status":
                "running",

            "route_points": [
                dict(point)
                for point in self.route_points
            ],

            "hops":
                self.hops,

            "total_hops":
                len(self.hops),

            "completed_hops":
                0,

            "parameters": {

                "freq_mhz":
                    parameters.get(
                        "freq_mhz",
                        DEFAULT_FREQ_MHZ,
                    ),

                "tx_ha":
                    parameters.get(
                        "tx_ha",
                        DEFAULT_TX_HA,
                    ),

                "rx_ha":
                    parameters.get(
                        "rx_ha",
                        DEFAULT_RX_HA,
                    ),

                "on_rooftop":
                    parameters.get(
                        "on_rooftop",
                        DEFAULT_ON_ROOFTOP,
                    ),
            },
        }

        self.log(
            "📡 Iniciando avaliação "
            "multi-hop..."
        )

        self.log(
            "🗺️ Rota: "
            + " → ".join(
                str(
                    point.get(
                        "name",
                        "Ponto",
                    )
                )
                for point in self.route_points
            )
        )

        self.log(
            f"🔗 Total de hops: "
            f"{len(self.hops)}"
        )

        # --------------------------------------------------------
        # Executa cada hop independentemente
        # --------------------------------------------------------

        for hop in self.hops:

            self.current_hop = hop

            tx = hop["tx"]
            rx = hop["rx"]
            hop_parameters = hop["parameters"]

            arguments = {

                "tx_lat":
                    tx["lat"],

                "tx_lon":
                    tx["lon"],

                "rx_lat":
                    rx["lat"],

                "rx_lon":
                    rx["lon"],

                "tx_ha":
                    hop_parameters.get(
                        "tx_ha",
                        DEFAULT_TX_HA,
                    ),

                "rx_ha":
                    hop_parameters.get(
                        "rx_ha",
                        DEFAULT_RX_HA,
                    ),

                "freq_mhz":
                    hop_parameters.get(
                        "freq_mhz",
                        DEFAULT_FREQ_MHZ,
                    ),

                "on_rooftop":
                    hop_parameters.get(
                        "on_rooftop",
                        DEFAULT_ON_ROOFTOP,
                    ),
            }

            self.log("")

            self.log(
                "🔗 "
                f"Hop {hop['index']}/"
                f"{len(self.hops)}: "
                f"{hop['name']}"
            )

            self.log_detail(
                "Parâmetros do hop:"
            )

            self.log_detail(
                json.dumps(
                    arguments,
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                )
            )

            try:

                result = await (
                    self.execute_mcp_tool(
                        "evaluate_link",
                        arguments,
                    )
                )

                hop["result"] = result

                # ------------------------------------------------
                # Verifica erro no resultado
                # ------------------------------------------------

                hop_error = (
                    self.contains_nested_error(
                        result
                    )
                )

                if hop_error:

                    hop["error"] = result

                    self.log(
                        "❌ Erro no "
                        f"{hop['name']}"
                    )

                    self.global_result[
                        "status"
                    ] = "error"

                    self.global_result[
                        "error"
                    ] = {

                        "hop":
                            hop["index"],

                        "link":
                            hop["name"],

                        "result":
                            result,
                    }

                    self.global_result[
                        "completed_hops"
                    ] = (
                        hop["index"] - 1
                    )

                    break

                # ------------------------------------------------
                # Hop concluído
                # ------------------------------------------------

                self.global_result[
                    "completed_hops"
                ] = hop["index"]

                self.log(
                    "✅ "
                    f"Hop {hop['index']} "
                    "concluído."
                )

            except Exception as exc:

                hop["error"] = {

                    "status":
                        "error",

                    "kind":
                        "multi_hop_exception",

                    "error":
                        str(exc),
                }

                self.log(
                    "❌ Exceção no "
                    f"{hop['name']}: "
                    f"{exc}"
                )

                self.global_result[
                    "status"
                ] = "error"

                self.global_result[
                    "error"
                ] = {

                    "hop":
                        hop["index"],

                    "link":
                        hop["name"],

                    "error":
                        str(exc),
                }

                self.global_result[
                    "completed_hops"
                ] = (
                    hop["index"] - 1
                )

                break

        # --------------------------------------------------------
        # Finalização
        # --------------------------------------------------------

        if (
            self.global_result.get(
                "status"
            )
            == "running"
        ):

            self.global_result[
                "status"
            ] = "OK"

        self.multi_hop_executed = True

        self.multi_hop_error = (
            self.global_result.get(
                "error"
            )
        )

        self.current_hop = None

        if (
            self.global_result[
                "status"
            ]
            == "OK"
        ):

            self.log(
                "🟢 Avaliação "
                "multi-hop concluída: "
                f"{self.global_result['completed_hops']} "
                "hops."
            )

        else:

            self.log(
                "❌ Avaliação "
                "multi-hop encerrada com erro."
            )

        # --------------------------------------------------------
        # Publica resultado global
        # --------------------------------------------------------

        self.publish_technical_result(
            self.global_result
        )

        return self.global_result

    # ============================================================
    # CONTEXTO TÉCNICO
    # ============================================================

    def _prepare_technical_analysis_value(
        self,
        value,
        key=None,
    ):
        """
        Prepara uma cópia dos resultados do PlanApp para análise
        textual pelo LLM.

        IMPORTANTE:

        Não elimina a chave genérica "data".

        Em vários resultados do PlanApp, "data" contém justamente
        os dados técnicos do evaluate_link, incluindo:

            fspl
            dist_m
            delta_diffra
            terrain
            vegetation
            buildings
            terrain_peaks_vv
            etc.

        O agent_ollama possui uma compactação histórica que trata
        "data" como conteúdo visual. Para evitar que os dados
        técnicos desapareçam, esta função renomeia essa chave para
        "dados_tecnicos" na cópia destinada exclusivamente à
        análise textual.

        Conteúdo visual pesado/base64 é removido somente quando
        identificado como tal.
        """

        key_text = (
            str(key).lower()
            if key is not None
            else ""
        )

        # --------------------------------------------------------
        # Chaves explicitamente visuais
        # --------------------------------------------------------

        visual_keys = {
            "image",
            "image_data",
            "image_bytes",
            "base64",
            "png",
            "jpeg",
            "jpg",
        }

        if key_text in visual_keys:

            return (
                "[conteúdo visual omitido "
                "da análise textual]"
            )

        # --------------------------------------------------------
        # Dict
        # --------------------------------------------------------

        if isinstance(
            value,
            dict,
        ):

            prepared = {}

            for child_key, child_value in (
                value.items()
            ):

                child_key_text = str(
                    child_key
                ).lower()

                # ----------------------------------------------
                # A chave "data" pode conter dados técnicos.
                #
                # NÃO descartamos.
                #
                # Renomeamos somente na cópia de análise.
                # ----------------------------------------------

                if child_key_text == "data":

                    output_key = (
                        "dados_tecnicos"
                    )

                else:

                    output_key = child_key

                # ----------------------------------------------
                # Chaves visuais explícitas
                # ----------------------------------------------

                if child_key_text in visual_keys:

                    prepared[output_key] = (
                        "[conteúdo visual omitido "
                        "da análise textual]"
                    )

                    continue

                prepared[output_key] = (
                    self._prepare_technical_analysis_value(
                        child_value,
                        child_key,
                    )
                )

            return prepared

        # --------------------------------------------------------
        # List
        # --------------------------------------------------------

        if isinstance(
            value,
            list,
        ):

            return [
                self._prepare_technical_analysis_value(
                    child,
                    key,
                )
                for child in value
            ]

        # --------------------------------------------------------
        # Strings
        # --------------------------------------------------------

        if isinstance(
            value,
            str,
        ):

            # ----------------------------------------------------
            # Detecta strings que parecem base64 muito grandes.
            #
            # Não descarta textos técnicos normais.
            # ----------------------------------------------------

            if len(value) > 1000:

                compact = value.strip()

                if (
                    len(compact) > 1000
                    and re.fullmatch(
                        r"[A-Za-z0-9+/=\s]+",
                        compact,
                    )
                ):

                    return (
                        "[conteúdo codificado "
                        "omitido da análise textual]"
                    )

            # ----------------------------------------------------
            # Evita enviar blocos textuais gigantes.
            # ----------------------------------------------------

            if len(value) > 30000:

                return (
                    value[:30000]
                    + "\n[texto extenso truncado]"
                )

        return value

    # ============================================================

    def _build_multi_hop_analysis_context(
        self,
        technical_result,
    ):
        """
        Constrói uma representação explícita dos resultados
        técnicos de cada hop.

        O objetivo é impedir que o LLM receba somente o estado
        global da rota sem os dados individuais de cada enlace.
        """

        if not isinstance(
            technical_result,
            dict,
        ):

            return None

        hops = technical_result.get(
            "hops"
        )

        if not isinstance(
            hops,
            list,
        ):

            return None

        prepared_hops = []

        for hop in hops:

            if not isinstance(
                hop,
                dict,
            ):
                continue

            prepared_hop = {

                "id":
                    hop.get("id"),

                "index":
                    hop.get("index"),

                "name":
                    hop.get("name"),

                "tx":
                    hop.get("tx"),

                "rx":
                    hop.get("rx"),

                "parameters":
                    hop.get("parameters"),

                "resultado_tecnico":
                    self._prepare_technical_analysis_value(
                        hop.get("result"),
                        "result",
                    ),

                "erro":
                    self._prepare_technical_analysis_value(
                        hop.get("error"),
                        "error",
                    ),
            }

            prepared_hops.append(
                prepared_hop
            )

        return {

            "status":
                technical_result.get(
                    "status"
                ),

            "total_hops":
                technical_result.get(
                    "total_hops"
                ),

            "completed_hops":
                technical_result.get(
                    "completed_hops"
                ),

            "parameters":
                technical_result.get(
                    "parameters"
                ),

            "route_points":
                technical_result.get(
                    "route_points"
                ),

            "hops":
                prepared_hops,

            "error":
                self._prepare_technical_analysis_value(
                    technical_result.get(
                        "error"
                    ),
                    "error",
                ),
        }

    # ============================================================

    def build_technical_context(
        self,
        technical_result,
    ):
        """
        Monta o contexto técnico final enviado ao LLM.

        A versão anterior simplesmente colocava o resultado bruto
        em "resultado_tecnico_real_do_planapp".

        Isso era insuficiente para a análise final porque o
        agent_ollama possui uma etapa de compactação que trata
        chaves chamadas "data" como conteúdo visual.

        Agora mantemos:

        1. o resultado bruto original;
        2. uma representação técnica normalizada;
        3. uma representação explícita por hop em multi-hop.

        Assim os três agentes continuam recebendo o resultado real
        do PlanApp, enquanto a análise textual recebe também uma
        cópia segura dos dados técnicos.
        """

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
            self.requested_frequency
            is not None
            and
            self.requested_frequency_unit
            is not None
        ):

            conversion_text = (
                "A frequência foi informada "
                "pelo usuário como "
                f"{self.requested_frequency_text}. "
                "A conversão para MHz foi usada "
                "somente internamente no parâmetro "
                "freq_mhz enviado ao PlanApp."
            )

        # --------------------------------------------------------
        # Cópia técnica normalizada
        # --------------------------------------------------------

        technical_analysis_result = (
            self._prepare_technical_analysis_value(
                technical_result,
                "resultado_tecnico",
            )
        )

        # --------------------------------------------------------
        # Contexto explícito dos hops
        # --------------------------------------------------------

        multi_hop_context = (
            self._build_multi_hop_analysis_context(
                technical_result
            )
        )

        context = {

            "parametros_solicitados_pelo_usuario":
                requested,

            "parametros_efetivos_enviados_ao_planapp":
                effective,

            "conversao_de_frequencia":
                conversion_text,

            "pontos_geocodificados":
                self.geocoded_points,

            # ----------------------------------------------------
            # Resultado bruto.
            #
            # Preservado para compatibilidade com os agentes
            # existentes.
            # ----------------------------------------------------

            "resultado_tecnico_real_do_planapp":
                technical_result,

            # ----------------------------------------------------
            # NOVO:
            #
            # Cópia destinada explicitamente à análise textual.
            #
            # Aqui "data" foi transformado em "dados_tecnicos".
            # ----------------------------------------------------

            "resultado_tecnico_para_analise":
                technical_analysis_result,

            "regras_criticas": [

                "Não inventar valores.",

                "Não inventar unidades.",

                "Não alterar valores "
                "retornados pelo PlanApp.",

                "Não converter radianos "
                "para graus.",

                "Não interpretar core, "
                "fresnel, boundary, "
                "delta_diffra, VV, "
                "v_v ou d_norm sem "
                "definição explícita.",

                "Não concluir viabilidade "
                "apenas com status OK.",

                "Não transformar core, "
                "fresnel ou boundary "
                "em dB.",

                "Se houver erro, informar "
                "o erro real retornado "
                "pelo PlanApp.",

                "Os valores numéricos "
                "retornados pelo PlanApp "
                "devem ser preservados "
                "na análise final.",

                "Em multi-hop, analisar "
                "cada hop separadamente "
                "antes de comparar os hops.",
            ],
        }

        # --------------------------------------------------------
        # NOVO:
        #
        # Só adiciona o bloco multi-hop quando realmente existe
        # uma estrutura de hops.
        # --------------------------------------------------------

        if multi_hop_context is not None:

            context[
                "resultado_multi_hop_para_analise"
            ] = multi_hop_context

        return context

    # ============================================================
    # VISUALIZAÇÕES
    # ============================================================

    async def gerar_visualizacoes(
        self,
    ):

        return None

    # ============================================================
    # MAPA
    # ============================================================

    async def mostrar_mapa_apos_geocodificacao(
        self,
    ):

        return None

    # ============================================================
    # RESET
    # ============================================================

    def reset_common_state(
        self,
    ):

        """
        Reseta todo o estado comum, incluindo o estado
        multi-hop.

        Isso evita que uma nova chamada ask() reutilize
        pontos, hops ou resultados de uma execução anterior.
        """

        self.messages = []

        self.geocoded_points = []

        # --------------------------------------------------------
        # Estado multi-hop
        # --------------------------------------------------------

        self.route_points = []

        self.hops = []

        self.current_hop = None

        self.global_result = None

        self.multi_hop_executed = False

        self.multi_hop_error = None

        # --------------------------------------------------------
        # Estado da avaliação
        # --------------------------------------------------------

        self.evaluate_executed = False

        self.last_evaluate_result = None

        self.evaluate_error = None

        # --------------------------------------------------------
        # Visualizações
        # --------------------------------------------------------

        self.visualizations = []

        # --------------------------------------------------------
        # Mapa
        # --------------------------------------------------------

        self.map = None

        # --------------------------------------------------------
        # Controle
        # --------------------------------------------------------

        self.tool_count = 0

        self.current_stage = 0

        # --------------------------------------------------------
        # Parâmetros
        # --------------------------------------------------------

        self.link_parameters = {

            "freq_mhz":
                DEFAULT_FREQ_MHZ,

            "tx_ha":
                DEFAULT_TX_HA,

            "rx_ha":
                DEFAULT_RX_HA,

            "on_rooftop":
                DEFAULT_ON_ROOFTOP,
        }

        self.requested_frequency = None

        self.requested_frequency_unit = None

        self.requested_frequency_text = None

        self.requested_tx_ha = None

        self.requested_rx_ha = None

    # ============================================================
    # CLOSE
    # ============================================================

    async def close(
        self,
    ):

        try:

            await (
                self.exit_stack.aclose()
            )

        finally:

            self.mcp_session = None

            self.mcp_tools = []

            self.connected = False

            try:

                self.file_handler.flush()

                self.file_handler.close()

            except Exception:

                pass

            try:

                self.logger.removeHandler(
                    self.file_handler
                )

            except Exception:

                pass