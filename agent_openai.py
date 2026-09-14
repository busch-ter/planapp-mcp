# ============================================================================
# PLANAPP AI — JUPYTER / OPENAI
#
# Arquitetura:
#
#   Jupyter
#      |
#      v
#   OpenAI Responses API / GPT-5.6 Luna
#      |
#      v
#   geocode_place
#      |
#      v
#   APLICAÇÃO
#      |
#      +--> evaluate_link
#      |
#      +--> mapa
#      |
#      +--> visualizações
#      |
#      v
#   OpenAI — análise técnica final
#
#
# REGRAS ARQUITETURAIS
#
# O OpenAI é responsável por:
#   - interpretar a solicitação;
#   - identificar os locais;
#   - solicitar geocodificação;
#   - interpretar o resultado técnico final.
#
# A aplicação é responsável por:
#   - evaluate_link;
#   - mapa;
#   - todas as visualizações.
#
# O LLM NÃO escolhe visualizações.
# O LLM NÃO executa evaluate_link.
#
#
# LOG:
#
#   log()
#       -> arquivo técnico
#       -> terminal quando DEBUG=True
#
#   status()
#       -> somente interface Jupyter
#
# Cada execução possui seu próprio arquivo:
#
#   ~/work/planapp-mcp/logs/
#       planapp_agent_YYYYMMDD_HHMMSS.log
#
# ============================================================================


import asyncio
import base64
import json
import os
import re

from datetime import datetime
from contextlib import AsyncExitStack

from openai import AsyncOpenAI

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

import ipywidgets as widgets

from map_utils import mostrar_mapa_enlace


# ============================================================================
# CONFIGURAÇÃO
# ============================================================================

OPENAI_MODEL = "gpt-5.6-luna"

OPENAI_REASONING_EFFORT = "medium"

MCP_URL = "http://172.17.0.1:8010/mcp"

USER_ID = "jupyter-user"

DEBUG = True

MAX_AGENT_ITERATIONS = 8


# ============================================================================
# TOOLS CONTROLADAS PELA APLICAÇÃO
# ============================================================================

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


# ============================================================================
# PLANAPP AGENT
# ============================================================================


class PlanAppAgent:

    # ========================================================================
    # INIT
    # ========================================================================

    def __init__(
        self,
        progress_callback=None,
        map_callback=None,
        log_callback=None,
        result_callback=None,
        visualization_callback=None,
    ):

        # --------------------------------------------------------------------
        # Callbacks
        # --------------------------------------------------------------------

        self.progress_callback = progress_callback

        self.map_callback = map_callback

        # Mantido por compatibilidade com versões anteriores.
        # A interface nova não precisa mais utilizá-lo.
        self.log_callback = log_callback

        self.result_callback = result_callback

        self.visualization_callback = (
            visualization_callback
        )

        # --------------------------------------------------------------------
        # LOG TÉCNICO
        # --------------------------------------------------------------------

        self.log_dir = os.path.expanduser(
            "~/work/planapp-mcp/logs"
        )

        os.makedirs(
            self.log_dir,
            exist_ok=True,
        )

        # --------------------------------------------------------------------
        # IMPORTANTE:
        #
        # Cada instância do agente recebe um arquivo próprio.
        #
        # Exemplo:
        #
        # planapp_agent_20260914_154237.log
        #
        # Assim múltiplas execuções no mesmo dia não compartilham
        # nem sobrescrevem o mesmo arquivo.
        # --------------------------------------------------------------------

        self.log_started_at = datetime.now()

        self.log_file = os.path.join(
            self.log_dir,
            (
                "planapp_agent_"
                f"{self.log_started_at:%Y%m%d_%H%M%S}.log"
            ),
        )

        # --------------------------------------------------------------------
        # MCP
        # --------------------------------------------------------------------

        self.exit_stack = AsyncExitStack()

        self.mcp_session = None
        self.mcp_tools = []

        # --------------------------------------------------------------------
        # OpenAI
        # --------------------------------------------------------------------

        self.openai_client = None

        # --------------------------------------------------------------------
        # Histórico
        # --------------------------------------------------------------------

        self.messages = []

        # --------------------------------------------------------------------
        # Estado
        # --------------------------------------------------------------------

        self.user_id = USER_ID

        self.registered = False

        self.geocoded_points = []

        self.evaluate_executed = False
        self.evaluate_error = None

        self.last_evaluate_result = None

        self.map = None

        self.visualizations = []

        self.technical_context_added = False

        # --------------------------------------------------------------------
        # Resposta intermediária do agente
        # --------------------------------------------------------------------

        self.last_agent_text = ""

        # --------------------------------------------------------------------
        # Parâmetros do enlace
        # --------------------------------------------------------------------

        self.requested_frequency_value = None
        self.requested_frequency_unit = None
        self.requested_frequency_mhz = None

        self.requested_tx_ha = None
        self.requested_rx_ha = None

        self.requested_on_rooftop = False

        # --------------------------------------------------------------------
        # Estado de execução
        # --------------------------------------------------------------------

        self.current_stage = None
        self.tool_count = 0

        # --------------------------------------------------------------------
        # OpenAI usage
        # --------------------------------------------------------------------

        self.input_tokens = 0
        self.output_tokens = 0
        self.cached_input_tokens = 0
        self.total_tokens = 0

        self.estimated_input_cost_usd = 0.0
        self.estimated_output_cost_usd = 0.0
        self.estimated_total_cost_usd = 0.0

        # --------------------------------------------------------------------
        # Responses API
        # --------------------------------------------------------------------

        self.last_response_id = None

        # --------------------------------------------------------------------
        # Preços GPT-5.6 Luna
        # --------------------------------------------------------------------

        self.INPUT_PRICE_PER_MILLION = 0.20
        self.OUTPUT_PRICE_PER_MILLION = 1.20

    # ========================================================================
    # LOG TÉCNICO
    # ========================================================================

    def log(
        self,
        texto,
        tipo="processing",
    ):
        """
        Registra informação técnica.

        IMPORTANTE:

        Este método NÃO envia mais mensagens para
        progress_callback.

        Portanto, logs como:

            ==================================================
            MCP TOOL
            Argumentos
            Resultado MCP
            JSON
            tokens
            custo

        não aparecem mais no painel Status.

        Eles ficam no arquivo técnico e no terminal.
        """

        if texto is None:
            return

        texto = str(texto)

        timestamp = datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        linha = (
            f"[{timestamp}] "
            f"[{str(tipo).upper()}] "
            f"{texto}"
        )

        # --------------------------------------------------------------------
        # Terminal
        # --------------------------------------------------------------------

        if DEBUG:

            print(
                linha
            )

        # --------------------------------------------------------------------
        # Arquivo
        # --------------------------------------------------------------------

        try:

            with open(
                self.log_file,
                "a",
                encoding="utf-8",
            ) as logfile:

                logfile.write(
                    linha + "\n"
                )

        except Exception as exc:

            if DEBUG:

                print(
                    "[ERRO AO ESCREVER LOG] "
                    f"{repr(exc)}"
                )

        # --------------------------------------------------------------------
        # Compatibilidade:
        #
        # log_callback antigo pode continuar sendo utilizado por código
        # externo. A nova notebook_ui não o utiliza.
        # --------------------------------------------------------------------

        if self.log_callback:

            try:

                self.log_callback(
                    texto,
                    tipo,
                )

            except TypeError:

                try:

                    self.log_callback(
                        texto
                    )

                except Exception:
                    pass

            except Exception:
                pass

    # ========================================================================
    # STATUS — SOMENTE INTERFACE
    # ========================================================================

    def status(
        self,
        mensagem,
    ):
        """
        Envia uma mensagem amigável para a interface.

        O status NÃO deve conter:
            - JSON;
            - argumentos MCP;
            - resultados MCP;
            - detalhes internos;
            - separadores;
            - informações de debug.

        A mensagem também é registrada no log técnico.
        """

        if mensagem is None:
            return

        texto = str(
            mensagem
        ).strip()

        if not texto:
            return

        # --------------------------------------------------------------------
        # Registrar no log técnico
        # --------------------------------------------------------------------

        self.log(
            texto,
            "status",
        )

        # --------------------------------------------------------------------
        # Interface
        # --------------------------------------------------------------------

        if self.progress_callback:

            try:

                self.progress_callback(
                    texto
                )

            except Exception as exc:

                self.log(
                    "Erro no progress_callback: "
                    f"{repr(exc)}",
                    "error",
                )

    # ========================================================================
    # LOG DETAIL
    # ========================================================================

    def log_detail(
        self,
        texto,
    ):

        self.log(
            texto,
            "detail",
        )

    # ========================================================================
    # CONNECT OPENAI
    # ========================================================================

    def connect_openai(self):

        api_key = os.getenv(
            "OPENAI_API_KEY"
        )

        if not api_key:

            raise RuntimeError(
                "OPENAI_API_KEY não encontrada no ambiente."
            )

        self.openai_client = AsyncOpenAI(
            api_key=api_key
        )

        self.log(
            "Cliente OpenAI inicializado."
        )

        self.log_detail(
            f"Modelo: {OPENAI_MODEL}"
        )

    # ========================================================================
    # CONNECT MCP
    # ========================================================================

    async def connect(self):

        self.current_stage = (
            "Conectando ao OpenAI/MCP"
        )

        self.status(
            "🔌 Conectando ao PlanApp..."
        )

        self.log(
            "1️⃣ Inicializando OpenAI..."
        )

        self.connect_openai()

        self.log(
            "2️⃣ Conectando ao MCP..."
        )

        transport = (
            await self.exit_stack.enter_async_context(
                streamable_http_client(
                    MCP_URL
                )
            )
        )

        self.log(
            "3️⃣ streamable_http_client conectado."
        )

        read_stream, write_stream = transport

        self.log(
            "4️⃣ Transporte MCP separado."
        )

        self.mcp_session = (
            await self.exit_stack.enter_async_context(
                ClientSession(
                    read_stream,
                    write_stream,
                )
            )
        )

        self.log(
            "5️⃣ ClientSession criada."
        )

        try:

            self.log(
                "6️⃣ Enviando initialize() ao MCP..."
            )

            await asyncio.wait_for(
                self.mcp_session.initialize(),
                timeout=30,
            )

            self.log(
                "7️⃣ MCP inicializado."
            )

        except asyncio.TimeoutError:

            self.log(
                "Timeout de 30s aguardando initialize().",
                "error",
            )

            raise

        except Exception as exc:

            self.log(
                f"Erro no initialize(): {exc}",
                "error",
            )

            raise

        self.log(
            "8️⃣ Consultando ferramentas MCP..."
        )

        tools_result = (
            await self.mcp_session.list_tools()
        )

        self.mcp_tools = (
            tools_result.tools
        )

        self.log(
            f"MCP conectado: "
            f"{len(self.mcp_tools)} ferramentas."
        )

        for tool in self.mcp_tools:

            self.log_detail(
                f"   • {tool.name}"
            )

        self.status(
            "🟢 Conexão com o PlanApp estabelecida."
        )

    # ========================================================================
    # BUILD OPENAI TOOLS
    # ========================================================================

    def build_openai_tools(self):

        tools = []

        for tool in self.mcp_tools:

            if tool.name in APPLICATION_CONTROLLED_TOOLS:
                continue

            schema = getattr(
                tool,
                "input_schema",
                None,
            )

            if schema is None:

                schema = getattr(
                    tool,
                    "inputSchema",
                    None,
                )

            if schema is None:

                schema = {
                    "type": "object",
                    "properties": {},
                }

            description = getattr(
                tool,
                "description",
                ""
            ) or ""

            tools.append(
                {
                    "type": "function",
                    "name": tool.name,
                    "description": description,
                    "parameters": schema,
                }
            )

            self.log_detail(
                f"🧩 Tool OpenAI: {tool.name}"
            )

        return tools

    # ========================================================================
    # RESET
    # ========================================================================

    def reset_state(self):

        self.registered = False

        self.geocoded_points = []

        self.evaluate_executed = False
        self.evaluate_error = None

        self.last_evaluate_result = None

        self.map = None

        self.visualizations = []

        self.technical_context_added = False

        self.last_agent_text = ""

        self.current_stage = None

        self.tool_count = 0

        self.messages = []

        self.last_response_id = None

        self.requested_frequency_value = None
        self.requested_frequency_unit = None
        self.requested_frequency_mhz = None

        self.requested_tx_ha = None
        self.requested_rx_ha = None

        self.requested_on_rooftop = False

        self.input_tokens = 0
        self.output_tokens = 0
        self.cached_input_tokens = 0
        self.total_tokens = 0

        self.estimated_input_cost_usd = 0.0
        self.estimated_output_cost_usd = 0.0
        self.estimated_total_cost_usd = 0.0

    # ========================================================================
    # EXTRACT LINK PARAMETERS
    # ========================================================================

    def extract_link_parameters(
        self,
        text,
    ):

        if not text:
            return

        # --------------------------------------------------------------------
        # FREQUÊNCIA
        # --------------------------------------------------------------------

        frequency_patterns = [

            r"(\d+(?:[.,]\d+)?)\s*(GHz|MHz|kHz|Hz)\b",

            r"freq(?:uência|uency)?\s*[:=]?\s*"
            r"(\d+(?:[.,]\d+)?)\s*"
            r"(GHz|MHz|kHz|Hz)\b",
        ]

        for pattern in frequency_patterns:

            match = re.search(
                pattern,
                text,
                re.IGNORECASE,
            )

            if not match:
                continue

            value = float(
                match.group(1).replace(
                    ",",
                    ".",
                )
            )

            unit = match.group(2)

            unit_lower = unit.lower()

            if unit_lower == "ghz":
                mhz = value * 1000.0

            elif unit_lower == "mhz":
                mhz = value

            elif unit_lower == "khz":
                mhz = value / 1000.0

            elif unit_lower == "hz":
                mhz = value / 1_000_000.0

            else:
                continue

            self.requested_frequency_value = value
            self.requested_frequency_unit = unit
            self.requested_frequency_mhz = mhz

            self.log_detail(
                f"📡 Frequência detectada: "
                f"{value:g} {unit} → {mhz:g} MHz"
            )

            break

        # --------------------------------------------------------------------
        # ALTURA TX
        # --------------------------------------------------------------------

        tx_patterns = [

            r"tx(?:_?ha| antenna height| height)?"
            r"\s*[:=]?\s*"
            r"(\d+(?:[.,]\d+)?)\s*m\b",

            r"transmissor.*?"
            r"(\d+(?:[.,]\d+)?)\s*m\b",

            r"tx.*?"
            r"(\d+(?:[.,]\d+)?)\s*m\b",
        ]

        for pattern in tx_patterns:

            match = re.search(
                pattern,
                text,
                re.IGNORECASE,
            )

            if match:

                self.requested_tx_ha = float(
                    match.group(1).replace(
                        ",",
                        ".",
                    )
                )

                break

        # --------------------------------------------------------------------
        # ALTURA RX
        # --------------------------------------------------------------------

        rx_patterns = [

            r"rx(?:_?ha| antenna height| height)?"
            r"\s*[:=]?\s*"
            r"(\d+(?:[.,]\d+)?)\s*m\b",

            r"receptor.*?"
            r"(\d+(?:[.,]\d+)?)\s*m\b",

            r"rx.*?"
            r"(\d+(?:[.,]\d+)?)\s*m\b",
        ]

        for pattern in rx_patterns:

            match = re.search(
                pattern,
                text,
                re.IGNORECASE,
            )

            if match:

                self.requested_rx_ha = float(
                    match.group(1).replace(
                        ",",
                        ".",
                    )
                )

                break

        # --------------------------------------------------------------------
        # ALTURA ÚNICA
        # --------------------------------------------------------------------

        if (
            self.requested_tx_ha is None
            and self.requested_rx_ha is None
        ):

            generic_height = re.search(
                r"(?:altura|height)"
                r"\s*[:=]?\s*"
                r"(\d+(?:[.,]\d+)?)\s*m\b",
                text,
                re.IGNORECASE,
            )

            if generic_height:

                value = float(
                    generic_height.group(1).replace(
                        ",",
                        ".",
                    )
                )

                self.requested_tx_ha = value
                self.requested_rx_ha = value

        # --------------------------------------------------------------------
        # ROOFTOP
        # --------------------------------------------------------------------

        rooftop_patterns = [

            r"\brooftop\b",
            r"\bno\s+teto\b",
            r"\bno\s+telhado\b",
            r"\bsobre\s+o\s+telhado\b",
        ]

        self.requested_on_rooftop = any(
            re.search(
                pattern,
                text,
                re.IGNORECASE,
            )
            for pattern in rooftop_patterns
        )

    # ========================================================================
    # PARSE MCP RESULT
    # ========================================================================

    def parse_mcp_result(
        self,
        result,
    ):

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

            if isinstance(structured, str):

                try:
                    return json.loads(
                        structured
                    )
                except Exception:
                    return structured

            return structured

        content = getattr(
            result,
            "content",
            None,
        )

        if content:

            for item in content:

                text = getattr(
                    item,
                    "text",
                    None,
                )

                if not text:
                    continue

                try:

                    return json.loads(
                        text
                    )

                except Exception:

                    return text

        return None

    # ========================================================================
    # NORMALIZE RESULT
    # ========================================================================

    def normalize_result(
        self,
        value,
    ):

        if isinstance(value, str):

            text = value.strip()

            if not text:
                return value

            try:
                return json.loads(text)
            except Exception:
                return value

        return value

    # ========================================================================
    # FIND NESTED ERROR
    # ========================================================================

    def contains_nested_error(
        self,
        value,
    ):

        value = self.normalize_result(
            value
        )

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

                if self.contains_nested_error(
                    child
                ):
                    return True

        elif isinstance(value, list):

            for child in value:

                if self.contains_nested_error(
                    child
                ):
                    return True

        return False

    # ========================================================================
    # MCP ERROR
    # ========================================================================

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

    # ========================================================================
    # SAFE LOG
    # ========================================================================

    def make_log_safe(
        self,
        value,
    ):

        value = self.normalize_result(
            value
        )

        if isinstance(value, dict):

            result = {}

            for key, item in value.items():

                if (
                    key == "data"
                    and isinstance(item, str)
                    and len(item) > 500
                ):

                    result[key] = (
                        f"<base64: {len(item)} caracteres>"
                    )

                else:

                    result[key] = (
                        self.make_log_safe(
                            item
                        )
                    )

            return result

        if isinstance(value, list):

            return [
                self.make_log_safe(item)
                for item in value
            ]

        return value

    # ========================================================================
    # EXTRACT COORDINATES
    # ========================================================================

    def extract_coordinates(
        self,
        value,
    ):

        value = self.normalize_result(
            value
        )

        if isinstance(value, dict):

            lat = None
            lon = None

            # ---------------------------------------------------------------
            # Latitude
            # ---------------------------------------------------------------

            for key in (
                "lat",
                "latitude",
                "y",
            ):

                if key in value:

                    try:

                        candidate = float(
                            value[key]
                        )

                        if -90 <= candidate <= 90:

                            lat = candidate

                            break

                    except Exception:
                        pass

            # ---------------------------------------------------------------
            # Longitude
            # ---------------------------------------------------------------

            for key in (
                "lon",
                "lng",
                "longitude",
                "x",
            ):

                if key in value:

                    try:

                        candidate = float(
                            value[key]
                        )

                        if -180 <= candidate <= 180:

                            lon = candidate

                            break

                    except Exception:
                        pass

            # ---------------------------------------------------------------
            # Coordenadas encontradas
            # ---------------------------------------------------------------

            if (
                lat is not None
                and lon is not None
            ):

                return lat, lon

            # ---------------------------------------------------------------
            # Procurar recursivamente
            # ---------------------------------------------------------------

            for child in value.values():

                result = (
                    self.extract_coordinates(
                        child
                    )
                )

                if result:
                    return result

        elif isinstance(value, list):

            for child in value:

                result = (
                    self.extract_coordinates(
                        child
                    )
                )

                if result:
                    return result

        return None

    # ========================================================================
    # REGISTER GEOCODED POINT
    # ========================================================================

    def register_geocoded_point(
        self,
        result,
        query=None,
    ):

        result = self.normalize_result(
            result
        )

        coordinates = (
            self.extract_coordinates(
                result
            )
        )

        if not coordinates:

            self.log(
                "⚠️ geocode_place não retornou "
                "coordenadas válidas.",
                "error",
            )

            self.log_detail(
                "Resultado geocoding:"
            )

            self.log_detail(
                json.dumps(
                    self.make_log_safe(result),
                    indent=2,
                    ensure_ascii=False,
                    default=str,
                )
            )

            return False

        lat, lon = coordinates

        point = {
            "query": query,
            "lat": lat,
            "lon": lon,
        }

        # --------------------------------------------------------------------
        # Evita duplicação
        # --------------------------------------------------------------------

        for existing in self.geocoded_points:

            if (
                abs(
                    existing["lat"] - lat
                ) < 1e-9
                and
                abs(
                    existing["lon"] - lon
                ) < 1e-9
            ):

                self.log_detail(
                    "ℹ️ Coordenada já registrada."
                )

                return False

        self.geocoded_points.append(
            point
        )

        self.status(
            f"📍 Ponto identificado: "
            f"{query or 'local'}"
        )

        self.log_detail(
            f"Coordenadas: "
            f"{lat:.6f}, {lon:.6f}"
        )

        self.log_detail(
            f"Total de pontos: "
            f"{len(self.geocoded_points)}"
        )

        # --------------------------------------------------------------------
        # MAPA É ATUALIZADO IMEDIATAMENTE
        # --------------------------------------------------------------------

        self.mostrar_mapa_apos_geocodificacao()

        return True

    # ========================================================================
    # MAPA
    # ========================================================================

    def mostrar_mapa_apos_geocodificacao(
        self,
    ):

        count = len(
            self.geocoded_points
        )

        if count == 0:
            return

        self.log_detail(
            f"🗺️ Atualizando mapa — "
            f"{count} ponto(s)."
        )

        try:

            if count >= 2:

                p1 = self.geocoded_points[0]
                p2 = self.geocoded_points[1]

                self.log_detail(
                    f"TX = "
                    f"{p1['lat']}, {p1['lon']}"
                )

                self.log_detail(
                    f"RX = "
                    f"{p2['lat']}, {p2['lon']}"
                )

                self.map = mostrar_mapa_enlace(
                    p1["lat"],
                    p1["lon"],
                    p2["lat"],
                    p2["lon"],
                )

            else:

                p1 = self.geocoded_points[0]

                self.map = mostrar_mapa_enlace(
                    p1["lat"],
                    p1["lon"],
                    p1["lat"],
                    p1["lon"],
                )

            self.log_detail(
                f"🗺️ Objeto mapa criado: "
                f"{type(self.map)}"
            )

            if self.map_callback:

                self.log_detail(
                    "🗺️ Chamando map_callback..."
                )

                self.map_callback(
                    self.map
                )

                self.log_detail(
                    "🗺️ map_callback executado."
                )

            else:

                self.log_detail(
                    "⚠️ map_callback inexistente."
                )

        except Exception as exc:

            self.log(
                f"❌ Erro ao gerar mapa: {exc}",
                "error",
            )

    # ========================================================================
    # FIND RECURSIVE
    # ========================================================================

    def find_recursive(
        self,
        value,
        keys,
    ):

        value = self.normalize_result(
            value
        )

        if isinstance(value, dict):

            for key in keys:

                if key in value:
                    return value[key]

            for child in value.values():

                found = self.find_recursive(
                    child,
                    keys,
                )

                if found is not None:
                    return found

        elif isinstance(value, list):

            for child in value:

                found = self.find_recursive(
                    child,
                    keys,
                )

                if found is not None:
                    return found

        return None

    # ========================================================================
    # SUMMARIZE EVALUATE
    # ========================================================================

    def summarize_evaluate(
        self,
        result,
    ):

        result = self.normalize_result(
            result
        )

        if not isinstance(
            result,
            dict,
        ):
            return "Avaliação concluída."

        parts = []

        fspl = self.find_recursive(
            result,
            [
                "fspl",
                "free_space_path_loss",
            ],
        )

        distance = self.find_recursive(
            result,
            [
                "distance",
                "distance_m",
                "link_distance",
            ],
        )

        if distance is not None:

            parts.append(
                f"distância={distance}"
            )

        if fspl is not None:

            parts.append(
                f"FSPL={fspl}"
            )

        if parts:

            return " | ".join(parts)

        return "Avaliação concluída."

    # ========================================================================
    # USAGE
    # ========================================================================

    def update_usage(
        self,
        response,
    ):

        usage = getattr(
            response,
            "usage",
            None,
        )

        if usage is None:
            return

        input_tokens = getattr(
            usage,
            "input_tokens",
            0,
        ) or 0

        output_tokens = getattr(
            usage,
            "output_tokens",
            0,
        ) or 0

        total_tokens = getattr(
            usage,
            "total_tokens",
            None,
        )

        if total_tokens is None:

            total_tokens = (
                input_tokens
                + output_tokens
            )

        self.input_tokens += int(
            input_tokens
        )

        self.output_tokens += int(
            output_tokens
        )

        self.total_tokens += int(
            total_tokens
        )

        details = getattr(
            usage,
            "input_tokens_details",
            None,
        )

        if details is not None:

            cached = getattr(
                details,
                "cached_tokens",
                0,
            ) or 0

            self.cached_input_tokens += int(
                cached
            )

        self.estimated_input_cost_usd = (
            self.input_tokens
            / 1_000_000
            * self.INPUT_PRICE_PER_MILLION
        )

        self.estimated_output_cost_usd = (
            self.output_tokens
            / 1_000_000
            * self.OUTPUT_PRICE_PER_MILLION
        )

        self.estimated_total_cost_usd = (
            self.estimated_input_cost_usd
            + self.estimated_output_cost_usd
        )

        self.log_detail(
            "💰 OpenAI usage: "
            f"in={self.input_tokens}, "
            f"out={self.output_tokens}, "
            f"total={self.total_tokens}"
        )

    # ========================================================================
    # TECHNICAL RESULT
    # ========================================================================

    def publish_technical_result(
        self,
        result,
    ):

        self.last_evaluate_result = (
            self.normalize_result(result)
        )

        if self.result_callback:

            try:

                self.result_callback(
                    self.last_evaluate_result
                )

            except Exception as exc:

                self.log_detail(
                    f"⚠️ Erro result_callback: {exc}"
                )

    # ========================================================================
    # BUILD TECHNICAL ANALYSIS CONTEXT
    # ========================================================================

    def build_technical_analysis_context(
        self,
    ):
        """
        Monta um contexto técnico estruturado para o GPT.

        O backend continua sendo a fonte de verdade.
        Este método apenas organiza os dados para que o modelo
        possa interpretá-los de forma mais útil.
        """

        result = self.normalize_result(
            self.last_evaluate_result
        )

        context = {

            "link_parameters": {
                "frequency_mhz":
                    self.requested_frequency_mhz
                    if self.requested_frequency_mhz
                    is not None
                    else 900,

                "tx_height_m":
                    self.requested_tx_ha
                    if self.requested_tx_ha
                    is not None
                    else 7,

                "rx_height_m":
                    self.requested_rx_ha
                    if self.requested_rx_ha
                    is not None
                    else 7,

                "on_rooftop":
                    self.requested_on_rooftop,
            },

            "endpoints": (
                self.geocoded_points[:2]
            ),

            "official_planapp_result":
                result,
        }

        return context

    # ========================================================================
    # EXECUTE MCP TOOL
    # ========================================================================

    async def execute_mcp_tool(
        self,
        tool_name,
        arguments,
    ):

        if self.mcp_session is None:

            raise RuntimeError(
                "Sessão MCP não está conectada."
            )

        self.tool_count += 1

        self.log("")
        self.log(
            f"🔧 MCP TOOL: {tool_name}"
        )

        self.log_detail(
            "Argumentos:"
        )

        self.log_detail(
            json.dumps(
                arguments,
                indent=2,
                ensure_ascii=False,
                default=str,
            )
        )

        try:

            result = (
                await self.mcp_session.call_tool(
                    tool_name,
                    arguments,
                )
            )

        except Exception as exc:

            self.log(
                f"❌ MCP {tool_name}: {exc}",
                "error",
            )

            if tool_name == "evaluate_link":

                self.evaluate_error = str(
                    exc
                )

            raise

        parsed = (
            self.parse_mcp_result(
                result
            )
        )

        parsed = self.normalize_result(
            parsed
        )

        safe_result = (
            self.make_log_safe(
                parsed
            )
        )

        self.log_detail(
            "Resultado MCP:"
        )

        try:

            self.log_detail(
                json.dumps(
                    safe_result,
                    indent=2,
                    ensure_ascii=False,
                    default=str,
                )
            )

        except Exception:

            self.log_detail(
                str(safe_result)
            )

        # --------------------------------------------------------------------
        # ERRO
        # --------------------------------------------------------------------

        if self.is_mcp_error(
            result,
            parsed,
        ):

            self.log(
                f"❌ MCP informou erro em "
                f"{tool_name}.",
                "error",
            )

            if tool_name == "evaluate_link":

                self.evaluate_error = (
                    json.dumps(
                        safe_result,
                        ensure_ascii=False,
                        default=str,
                    )
                )

            return parsed

        # --------------------------------------------------------------------
        # GEOCODE
        # --------------------------------------------------------------------

        if tool_name == "geocode_place":

            query = arguments.get(
                "query"
            )

            self.register_geocoded_point(
                parsed,
                query=query,
            )

        # --------------------------------------------------------------------
        # EVALUATE
        # --------------------------------------------------------------------

        elif tool_name == "evaluate_link":

            self.status(
                "📊 Avaliação técnica do enlace concluída."
            )

            self.log(
                "📡 evaluate_link retornou com sucesso."
            )

            self.evaluate_executed = True

            self.evaluate_error = None

            self.publish_technical_result(
                parsed
            )

            summary = (
                self.summarize_evaluate(
                    parsed
                )
            )

            self.log(
                f"📡 Enlace avaliado: {summary}"
            )

            # ----------------------------------------------------------------
            # VISUALIZAÇÕES
            # ----------------------------------------------------------------

            await self.gerar_visualizacoes()

        return parsed

    # ========================================================================
    # EVALUATE LINK — CONTROLADO 100% PELA APLICAÇÃO
    # ========================================================================

    async def ensure_evaluate_link(
        self,
    ):

        self.log("")
        self.log(
            "========== EVALUATE CONTROLLER =========="
        )

        self.log(
            f"geocoded_points = "
            f"{len(self.geocoded_points)}"
        )

        self.log(
            f"evaluate_executed = "
            f"{self.evaluate_executed}"
        )

        self.log(
            f"evaluate_error = "
            f"{self.evaluate_error}"
        )

        # --------------------------------------------------------------------
        # Já executado
        # --------------------------------------------------------------------

        if self.evaluate_executed:

            self.log(
                "ℹ️ evaluate_link já executado."
            )

            return self.last_evaluate_result

        # --------------------------------------------------------------------
        # Erro anterior
        # --------------------------------------------------------------------

        if self.evaluate_error is not None:

            self.log(
                "⚠️ evaluate_link possui erro anterior.",
                "error",
            )

            return None

        # --------------------------------------------------------------------
        # Precisamos de dois pontos
        # --------------------------------------------------------------------

        if len(
            self.geocoded_points
        ) < 2:

            self.log(
                "⚠️ Menos de dois pontos. "
                "evaluate_link não será executado."
            )

            return None

        tx = self.geocoded_points[0]
        rx = self.geocoded_points[1]

        # --------------------------------------------------------------------
        # Defaults
        # --------------------------------------------------------------------

        tx_ha = (
            self.requested_tx_ha
            if self.requested_tx_ha is not None
            else 7
        )

        rx_ha = (
            self.requested_rx_ha
            if self.requested_rx_ha is not None
            else 7
        )

        freq_mhz = (
            self.requested_frequency_mhz
            if self.requested_frequency_mhz is not None
            else 900
        )

        on_rooftop = (
            self.requested_on_rooftop
        )

        arguments = {

            "tx_lat": tx["lat"],
            "tx_lon": tx["lon"],

            "rx_lat": rx["lat"],
            "rx_lon": rx["lon"],

            "tx_ha": tx_ha,
            "rx_ha": rx_ha,

            "freq_mhz": freq_mhz,

            "on_rooftop": on_rooftop,
        }

        self.status(
            "📡 Avaliando o enlace..."
        )

        self.log(
            "📡 APLICAÇÃO executará evaluate_link."
        )

        self.log_detail(
            "📡 Parâmetros finais:"
        )

        self.log_detail(
            json.dumps(
                arguments,
                indent=2,
                ensure_ascii=False,
            )
        )

        result = (
            await self.execute_mcp_tool(
                "evaluate_link",
                arguments,
            )
        )

        self.log(
            "========== FIM EVALUATE CONTROLLER =========="
        )

        return result

    # ========================================================================
    # VISUALIZAÇÕES
    # ========================================================================

    async def gerar_visualizacoes(
        self,
    ):

        if not self.evaluate_executed:

            self.log_detail(
                "⚠️ Visualizações canceladas: "
                "evaluate_link não executado."
            )

            return

        if self.evaluate_error:

            self.log_detail(
                "⚠️ Visualizações canceladas: "
                "evaluate_link apresentou erro."
            )

            return

        if self.mcp_session is None:

            self.log_detail(
                "⚠️ Sessão MCP inexistente."
            )

            return

        self.status(
            "📈 Gerando visualizações técnicas..."
        )

        self.log("")
        self.log(
            "📊 Gerando visualizações..."
        )

        self.visualizations = []

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

        for (
            titulo,
            tool_name,
            arguments,
        ) in etapas:

            self.log_detail("")
            self.log_detail(
                f"📊 Visualização: {titulo}"
            )

            try:

                result = (
                    await self.execute_mcp_tool(
                        tool_name,
                        arguments,
                    )
                )

            except Exception as exc:

                self.log_detail(
                    f"❌ {titulo}: {exc}"
                )

                continue

            result = self.normalize_result(
                result
            )

            if not isinstance(
                result,
                dict,
            ):

                self.log_detail(
                    f"⚠️ {titulo}: "
                    "resultado não é dict."
                )

                continue

            status = str(
                result.get(
                    "status",
                    "",
                )
            ).lower()

            if status in {
                "error",
                "failed",
                "failure",
            }:

                self.log_detail(
                    f"⚠️ {titulo}: MCP retornou erro."
                )

                continue

            if result.get("kind") != "image":

                self.log_detail(
                    f"ℹ️ {titulo}: "
                    "não retornou imagem."
                )

                continue

            data = result.get(
                "data"
            )

            if not data:

                self.log_detail(
                    f"⚠️ {titulo}: imagem vazia."
                )

                continue

            try:

                image_bytes = (
                    base64.b64decode(
                        data,
                        validate=True,
                    )
                )

                widget = widgets.Image(
                    value=image_bytes,
                    format="png",
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
                    f"✅ {titulo}: imagem recebida."
                )

            except Exception as exc:

                self.log_detail(
                    f"❌ {titulo}: "
                    f"erro base64: {exc}"
                )

        # --------------------------------------------------------------------
        # CALLBACK
        # --------------------------------------------------------------------

        self.log(
            f"📊 Total de visualizações: "
            f"{len(self.visualizations)}"
        )

        if self.visualization_callback:

            try:

                self.log_detail(
                    "📊 Chamando visualization_callback..."
                )

                self.visualization_callback(
                    self.visualizations
                )

                self.log_detail(
                    "📊 visualization_callback executado."
                )

            except Exception as exc:

                self.log(
                    f"❌ Erro visualization_callback: "
                    f"{exc}",
                    "error",
                )

        else:

            self.log_detail(
                "⚠️ visualization_callback inexistente."
            )

        self.status(
            "📈 Visualizações técnicas concluídas."
        )

    # ========================================================================
    # REGISTER
    # ========================================================================

    async def register_session(
        self,
    ):

        if self.registered:
            return

        self.log(
            f"📝 Registrando sessão: "
            f"{self.user_id}"
        )

        result = (
            await self.execute_mcp_tool(
                "register",
                {
                    "user_id": self.user_id,
                },
            )
        )

        self.registered = True

        self.status(
            "🟢 Sessão PlanApp iniciada."
        )

        self.log(
            "Sessão PlanApp registrada."
        )

        return result

    # ========================================================================
    # TECHNICAL CONTEXT
    # ========================================================================

    def append_technical_context(
        self,
    ):

        if not self.last_evaluate_result:
            return

        if self.technical_context_added:
            return

        technical_context = (
            self.build_technical_analysis_context()
        )

        self.messages.append(
            {
                "role": "user",

                "content": (
                    "A avaliação técnica já foi "
                    "executada pela aplicação PlanApp.\n\n"

                    "A seguir está o contexto técnico "
                    "oficial da execução:\n\n"

                    +
                    json.dumps(
                        technical_context,
                        ensure_ascii=False,
                        indent=2,
                        default=str,
                    )

                    +

                    "\n\n"
                    "Use estes dados como fonte de "
                    "verdade para sua resposta final.\n\n"

                    "IMPORTANTE:\n"
                    "- Não invente valores.\n"
                    "- Não recalcule o enlace.\n"
                    "- Não altere os valores fornecidos.\n"
                    "- Não execute nenhuma ferramenta.\n"
                    "- Interprete tecnicamente os resultados.\n"
                    "- Explique o significado dos principais "
                    "indicadores.\n"
                    "- Considere frequência, alturas TX/RX "
                    "e rooftop.\n"
                    "- Considere distância, FSPL, difração, "
                    "clearance, terreno, vegetação, "
                    "edificações e picos de terreno quando "
                    "esses dados estiverem disponíveis.\n"
                    "- O status do PlanApp deve ser tratado "
                    "como a classificação oficial da avaliação.\n"
                    "- Não transforme 'OK' em uma garantia "
                    "absoluta de qualidade ou disponibilidade "
                    "do enlace."
                ),
            }
        )

        self.technical_context_added = True

        self.log_detail(
            "🧠 Resultado técnico estruturado "
            "adicionado ao contexto do OpenAI."
        )

    # ========================================================================
    # SYSTEM PROMPT
    # ========================================================================

    def system_prompt(
        self,
    ):

        return """
Você é o PlanApp AI, assistente técnico especializado
em planejamento e avaliação de enlaces de rádio.

Sua função é auxiliar o usuário na interpretação técnica
de resultados produzidos pelo PlanApp.

======================================================================
ARQUITETURA
======================================================================

O PlanApp possui duas responsabilidades distintas:

OPENAI:
- interpretar a solicitação;
- identificar os locais;
- solicitar geocodificação;
- interpretar o resultado técnico final.

APLICAÇÃO:
- executar evaluate_link;
- gerar o mapa;
- gerar todas as visualizações;
- calcular os resultados técnicos.

======================================================================
REGRAS FUNDAMENTAIS
======================================================================

1. O PlanApp é a fonte de verdade para resultados técnicos.

2. Nunca invente coordenadas.

3. Nunca invente distância, FSPL, frequência,
   altura, perda, clearance, difração ou qualquer
   outro resultado técnico.

4. Use geocode_place para encontrar coordenadas
   dos locais mencionados pelo usuário.

5. NÃO execute evaluate_link.
   evaluate_link é controlado exclusivamente pela aplicação.

6. NÃO execute ferramentas de visualização.
   As visualizações são controladas exclusivamente pela aplicação.

7. Quando a solicitação contiver dois locais,
   obtenha os dois pontos usando geocode_place.

8. Se apenas um ponto estiver disponível,
   continue a interação e tente identificar/geocodificar
   o segundo local quando ele estiver presente na solicitação.

9. Depois que dois locais forem geocodificados,
   a aplicação executará automaticamente evaluate_link.

10. Depois de evaluate_link,
    a aplicação gerará automaticamente
    as visualizações disponíveis.

11. Quando receber o resultado técnico oficial,
    use-o como fonte de verdade.

12. Se uma ferramenta retornar erro,
    informe o erro de forma objetiva.

======================================================================
PARÂMETROS
======================================================================

13. Frequência:
    - 450 MHz = 450 MHz
    - 450 GHz = 450000 MHz
    - 450 kHz = 0.45 MHz
    - 450 Hz = 0.00045 MHz

14. Se nenhuma frequência for informada,
    a aplicação usa 900 MHz.

15. Se nenhuma altura for informada:
    TX = 7 m
    RX = 7 m.

16. Se uma altura única for informada,
    aplique-a a TX e RX.

17. Preserve alturas TX/RX separadas quando informadas.

18. Preserve rooftop/telhado/teto quando informado.

======================================================================
ANÁLISE TÉCNICA FINAL
======================================================================

Quando o resultado técnico oficial estiver disponível,
NÃO se limite a repetir os números retornados pelo PlanApp.

Sua tarefa é transformar os resultados numéricos
em uma análise técnica clara e útil.

A resposta deve:

1. Apresentar o status oficial do PlanApp.

2. Informar os principais parâmetros da execução:
   - frequência;
   - altura TX;
   - altura RX;
   - rooftop;
   - distância.

3. Interpretar o FSPL.

4. Interpretar o resultado de difração,
   sem inventar um limite de aprovação que não
   esteja definido pelo PlanApp.

5. Interpretar os valores de clearance.

6. Analisar separadamente:
   - terreno;
   - vegetação;
   - edificações.

7. Quando existirem picos de terreno,
   indicar sua posição normalizada no percurso
   e explicar sua relevância.

8. Se não houver contribuição de edificações,
   informar explicitamente que não foram identificadas
   obstruções por edificações no perfil analisado.

9. Se houver contribuição de terreno ou vegetação,
   explicar que esses elementos influenciam o perfil
   de propagação.

10. Não afirmar que todo o enlace está livre de obstrução
    apenas porque o clearance em TX e RX é positivo.

11. Não afirmar que um enlace é "excelente",
    "garantido", "perfeito" ou equivalente sem
    suporte explícito nos dados.

12. Não transformar "OK" em garantia absoluta.
    Diga que o enlace foi classificado como OK
    segundo os critérios do PlanApp.

13. Não diga que a avaliação apenas "foi processada
    com sucesso". Interprete o resultado.

14. Se frequência ou alturas estiverem disponíveis
    no contexto da execução, informe-as.
    Não diga que estão ausentes.

======================================================================
ESTRUTURA RECOMENDADA
======================================================================

Use uma estrutura semelhante a:

## Análise do enlace

Apresente:
- Status
- Distância
- Frequência
- Alturas TX/RX
- Rooftop
- FSPL
- Difração
- Clearance

## Perfil do enlace

Explique:
- terreno;
- vegetação;
- edificações;
- relação desses fatores com o perfil.

## Pontos críticos

Explique:
- principais picos de terreno;
- posição normalizada;
- clearance;
- outros fatores relevantes disponíveis.

## Conclusão

Faça uma conclusão objetiva de 2 ou 3 frases,
respondendo essencialmente:

"O que os resultados do PlanApp indicam
sobre este enlace?"

======================================================================
ESTILO
======================================================================

- Português técnico e claro.
- Evite texto excessivamente genérico.
- Evite repetir números sem explicação.
- Prefira frases que relacionem o número ao
  comportamento do enlace.
- Não faça recomendações de engenharia que não
  possam ser sustentadas pelos dados.
- Não invente margem de enlace, potência,
  sensibilidade, disponibilidade ou modulação.
- Não invente critérios de aprovação.

======================================================================
OUTRAS REGRAS
======================================================================

19. Não diga que uma visualização foi gerada
    sem confirmação da aplicação.

20. Se o resultado técnico estiver presente,
    considere a avaliação concluída.

21. Se a solicitação não fornecer dois locais,
    explique o que está faltando em vez de afirmar
    que houve falha de avaliação.

22. Não diga que "não foram obtidos dois pontos"
    se você ainda não tentou geocodificar os locais
    presentes na solicitação.
"""

    # ========================================================================
    # OPENAI CHAT
    # ========================================================================

    async def openai_chat(
        self,
        allow_tools=True,
    ):

        if self.openai_client is None:

            raise RuntimeError(
                "Cliente OpenAI não inicializado."
            )

        tools = (
            self.build_openai_tools()
            if allow_tools
            else []
        )

        response = (
            await self.openai_client.responses.create(

                model=OPENAI_MODEL,

                input=self.messages,

                tools=tools,

                tool_choice=(
                    "auto"
                    if allow_tools
                    else "none"
                ),

                reasoning={
                    "effort":
                        OPENAI_REASONING_EFFORT,
                },
            )
        )

        self.update_usage(
            response
        )

        self.last_response_id = getattr(
            response,
            "id",
            None,
        )

        return response

    # ========================================================================
    # RESPONSE TEXT
    # ========================================================================

    def response_text(
        self,
        response,
    ):

        text = getattr(
            response,
            "output_text",
            None,
        )

        if text:
            return text

        output = getattr(
            response,
            "output",
            None,
        )

        if not output:
            return ""

        texts = []

        for item in output:

            if getattr(
                item,
                "type",
                None,
            ) != "message":

                continue

            content = getattr(
                item,
                "content",
                None,
            )

            if not content:
                continue

            for part in content:

                if getattr(
                    part,
                    "type",
                    None,
                ) == "output_text":

                    value = getattr(
                        part,
                        "text",
                        None,
                    )

                    if value:
                        texts.append(
                            value
                        )

        return "\n".join(
            texts
        )

    # ========================================================================
    # NORMALIZE FUNCTION CALL
    # ========================================================================

    def normalize_function_call(
        self,
        item,
    ):

        if isinstance(
            item,
            dict,
        ):

            if item.get(
                "type"
            ) != "function_call":

                return None

            call_id = item.get(
                "call_id"
            )

            name = item.get(
                "name"
            )

            arguments = item.get(
                "arguments",
                "{}",
            )

        else:

            if getattr(
                item,
                "type",
                None
            ) != "function_call":

                return None

            call_id = getattr(
                item,
                "call_id",
                None,
            )

            name = getattr(
                item,
                "name",
                None,
            )

            arguments = getattr(
                item,
                "arguments",
                "{}",
            )

        if isinstance(
            arguments,
            dict,
        ):

            arguments_dict = arguments

        else:

            try:

                arguments_dict = json.loads(
                    arguments or "{}"
                )

            except Exception as exc:

                self.log(
                    f"❌ Erro interpretando "
                    f"argumentos de {name}: {exc}",
                    "error",
                )

                arguments_dict = {}

        if not isinstance(
            arguments_dict,
            dict,
        ):

            arguments_dict = {}

        return {

            "type":
                "function_call",

            "call_id":
                call_id,

            "name":
                name,

            "arguments":
                json.dumps(
                    arguments_dict,
                    ensure_ascii=False,
                ),

            "arguments_dict":
                arguments_dict,
        }

    # ========================================================================
    # SANITIZE MESSAGES
    # ========================================================================

    def sanitize_messages(
        self,
    ):

        sanitized = []

        for item in self.messages:

            if not isinstance(
                item,
                dict,
            ):
                continue

            item_type = item.get(
                "type"
            )

            if item_type == "function_call":

                sanitized.append(
                    {
                        "type":
                            "function_call",

                        "call_id":
                            item.get(
                                "call_id"
                            ),

                        "name":
                            item.get(
                                "name"
                            ),

                        "arguments":
                            item.get(
                                "arguments",
                                "{}",
                            ),
                    }
                )

                continue

            if item_type == "function_call_output":

                sanitized.append(
                    {
                        "type":
                            "function_call_output",

                        "call_id":
                            item.get(
                                "call_id"
                            ),

                        "output":
                            item.get(
                                "output",
                                "",
                            ),
                    }
                )

                continue

            sanitized.append(
                item
            )

        self.messages = sanitized

    # ========================================================================
    # AGENT TURN
    #
    # O OpenAI conduz SOMENTE a geocodificação.
    #
    # Quando dois pontos são obtidos:
    #
    #       OpenAI
    #          |
    #          v
    #       2 pontos
    #          |
    #          v
    #     APPLICATION
    #          |
    #          v
    #   evaluate_link
    #
    # ========================================================================

    async def agent_turn(
        self,
    ):

        self.last_agent_text = ""

        for iteration in range(
            MAX_AGENT_ITERATIONS
        ):

            self.current_stage = (
                f"OpenAI — iteração {iteration + 1}"
            )

            self.log("")
            self.log(
                f"🤖 OpenAI — iteração "
                f"{iteration + 1}"
            )

            self.sanitize_messages()

            response = (
                await self.openai_chat(
                    allow_tools=True
                )
            )

            output = getattr(
                response,
                "output",
                [],
            )

            function_calls = []

            # ----------------------------------------------------------------
            # FUNCTION CALLS
            # ----------------------------------------------------------------

            for item in output:

                normalized = (
                    self.normalize_function_call(
                        item
                    )
                )

                if normalized is None:
                    continue

                self.log(
                    f"📌 Function call: "
                    f"{normalized['name']}"
                )

                self.log_detail(
                    f"arguments = "
                    f"{normalized['arguments']}"
                )

                self.messages.append(
                    {
                        "type":
                            "function_call",

                        "call_id":
                            normalized[
                                "call_id"
                            ],

                        "name":
                            normalized[
                                "name"
                            ],

                        "arguments":
                            normalized[
                                "arguments"
                            ],
                    }
                )

                function_calls.append(
                    normalized
                )

            # ----------------------------------------------------------------
            # EXECUTA SOMENTE TOOLS NÃO CONTROLADAS
            # ----------------------------------------------------------------

            for call in function_calls:

                tool_name = call["name"]

                call_id = call["call_id"]

                arguments = call[
                    "arguments_dict"
                ]

                if tool_name in (
                    APPLICATION_CONTROLLED_TOOLS
                ):

                    self.log(
                        f"⚠️ {tool_name} "
                        "é controlada pela aplicação."
                    )

                    tool_result = {
                        "status": "ERROR",
                        "error": (
                            "Ferramenta controlada "
                            "pela aplicação."
                        ),
                    }

                else:

                    try:

                        self.log(
                            f"🚀 Enviando para MCP: "
                            f"{tool_name}"
                        )

                        tool_result = (
                            await self.execute_mcp_tool(
                                tool_name,
                                arguments,
                            )
                        )

                        self.log(
                            f"📥 MCP retornou: "
                            f"{tool_name}"
                        )

                    except Exception as exc:

                        self.log(
                            f"❌ Erro {tool_name}: "
                            f"{exc}",
                            "error",
                        )

                        tool_result = {
                            "status": "ERROR",
                            "error": str(exc),
                        }

                self.messages.append(
                    {
                        "type":
                            "function_call_output",

                        "call_id":
                            call_id,

                        "output":
                            json.dumps(
                                tool_result,
                                ensure_ascii=False,
                                default=str,
                            ),
                    }
                )

            # ----------------------------------------------------------------
            # DOIS PONTOS
            # ----------------------------------------------------------------

            if len(
                self.geocoded_points
            ) >= 2:

                self.status(
                    "📍 Os dois pontos do enlace foram identificados."
                )

                self.log("")
                self.log(
                    "📍 Dois pontos geocodificados."
                )

                self.log_detail(
                    json.dumps(
                        self.geocoded_points,
                        indent=2,
                        ensure_ascii=False,
                    )
                )

                self.log(
                    "📡 Transferindo controle "
                    "para a aplicação."
                )

                await self.ensure_evaluate_link()

                self.log(
                    "📡 Retorno de evaluate_link "
                    "recebido pelo controlador."
                )

                return ""

            # ----------------------------------------------------------------
            # NENHUMA FUNCTION CALL
            # ----------------------------------------------------------------

            if not function_calls:

                text = (
                    self.response_text(
                        response
                    )
                )

                if text:

                    self.last_agent_text = text

                    self.messages.append(
                        {
                            "role":
                                "assistant",

                            "content":
                                text,
                        }
                    )

                    self.log_detail(
                        "🤖 OpenAI respondeu sem "
                        "chamar ferramentas."
                    )

                return text

        self.log(
            "⚠️ MAX_AGENT_ITERATIONS atingido."
        )

        return self.last_agent_text

    # ========================================================================
    # ASK
    # ========================================================================

    async def ask(
        self,
        user_text,
    ):

        self.reset_state()

        # --------------------------------------------------------------------
        # Limpa visualizações anteriores
        # --------------------------------------------------------------------

        if self.visualization_callback:

            try:

                self.visualization_callback(
                    []
                )

            except Exception:
                pass

        # --------------------------------------------------------------------
        # Extrai parâmetros diretamente da solicitação
        # --------------------------------------------------------------------

        self.extract_link_parameters(
            user_text
        )

        self.log("")
        self.log(
            "================================================"
        )
        self.log(
            "🚀 PLANAPP AI — NOVA EXECUÇÃO"
        )
        self.log(
            "================================================"
        )

        # --------------------------------------------------------------------
        # Identificação da execução no log
        # --------------------------------------------------------------------

        self.log(
            f"📁 Log da execução: "
            f"{self.log_file}"
        )

        self.log_detail(
            f"🕒 Início da execução: "
            f"{self.log_started_at:%Y-%m-%d %H:%M:%S}"
        )

        try:

            # ----------------------------------------------------------------
            # CONNECT
            # ----------------------------------------------------------------

            await self.connect()

            # ----------------------------------------------------------------
            # REGISTER
            # ----------------------------------------------------------------

            await self.register_session()

            # ----------------------------------------------------------------
            # HISTÓRICO
            # ----------------------------------------------------------------

            self.messages = [

                {
                    "role":
                        "system",

                    "content":
                        self.system_prompt(),
                },

                {
                    "role":
                        "user",

                    "content":
                        user_text,
                },
            ]

            # ----------------------------------------------------------------
            # OPENAI + GEOCODE
            # ----------------------------------------------------------------

            self.status(
                "📍 Identificando os locais do enlace..."
            )

            agent_text = (
                await self.agent_turn()
            )

            # ----------------------------------------------------------------
            # ESTADO IMEDIATAMENTE APÓS AGENT TURN
            # ----------------------------------------------------------------

            self.log("")
            self.log(
                "========== ESTADO APÓS AGENT TURN =========="
            )

            self.log(
                f"geocoded_points = "
                f"{len(self.geocoded_points)}"
            )

            self.log(
                f"evaluate_executed = "
                f"{self.evaluate_executed}"
            )

            self.log(
                f"evaluate_error = "
                f"{self.evaluate_error}"
            )

            self.log(
                f"last_evaluate_result = "
                f"{self.last_evaluate_result is not None}"
            )

            self.log(
                f"last_agent_text = "
                f"{bool(self.last_agent_text)}"
            )

            self.log(
                "============================================"
            )

            # ----------------------------------------------------------------
            # FALLBACK DETERMINÍSTICO
            # ----------------------------------------------------------------

            if (
                len(self.geocoded_points) >= 2
                and not self.evaluate_executed
                and self.evaluate_error is None
            ):

                self.log(
                    "📡 Fallback determinístico: "
                    "executando evaluate_link."
                )

                await self.ensure_evaluate_link()

            # ----------------------------------------------------------------
            # MAPA FINAL
            # ----------------------------------------------------------------

            if len(
                self.geocoded_points
            ) >= 2:

                self.log(
                    "🗺️ Atualizando mapa final..."
                )

                self.mostrar_mapa_apos_geocodificacao()

            # ----------------------------------------------------------------
            # EVALUATE OK
            # ----------------------------------------------------------------

            if self.evaluate_executed:

                self.append_technical_context()

                self.status(
                    "🤖 Preparando a resposta final..."
                )

                self.log("")
                self.log(
                    "🧠 Gerando análise técnica final..."
                )

                self.sanitize_messages()

                final_response = (
                    await self.openai_chat(
                        allow_tools=False
                    )
                )

                final_text = (
                    self.response_text(
                        final_response
                    )
                )

                if final_text:

                    self.messages.append(
                        {
                            "role":
                                "assistant",

                            "content":
                                final_text,
                        }
                    )

                else:

                    final_text = (
                        self.last_agent_text
                        or
                        "A avaliação do enlace "
                        "foi concluída."
                    )

            # ----------------------------------------------------------------
            # EVALUATE COM ERRO
            # ----------------------------------------------------------------

            elif self.evaluate_error:

                self.log(
                    "⚠️ Avaliação não concluída "
                    "por erro do PlanApp."
                )

                final_text = (
                    "Não foi possível concluir "
                    "a avaliação do enlace. "
                    "O PlanApp retornou um erro."
                )

            # ----------------------------------------------------------------
            # SEM AVALIAÇÃO
            # ----------------------------------------------------------------

            else:

                if self.last_agent_text:

                    final_text = (
                        self.last_agent_text
                    )

                elif agent_text:

                    final_text = agent_text

                else:

                    final_text = (
                        "Não foi possível identificar "
                        "dois locais válidos para realizar "
                        "a avaliação do enlace."
                    )

            # ----------------------------------------------------------------
            # STATUS FINAL
            # ----------------------------------------------------------------

            self.log("")

            if self.evaluate_error:

                self.log(
                    "❌ Avaliação terminou com erro.",
                    "error",
                )

                self.status(
                    "❌ A avaliação não pôde ser concluída."
                )

            elif self.evaluate_executed:

                self.log(
                    "✅ Avaliação do enlace concluída."
                )

                self.status(
                    "🟢 Análise concluída."
                )

            else:

                self.log(
                    "⚠️ Nenhuma avaliação foi executada."
                )

                self.status(
                    "⚠️ A análise não foi executada."
                )

            # ----------------------------------------------------------------
            # CUSTO
            # ----------------------------------------------------------------

            self.log(
                "💰 Custo estimado da execução: "
                f"US$ "
                f"{self.estimated_total_cost_usd:.6f}"
            )

            self.log(
                f"Input tokens: "
                f"{self.input_tokens}"
            )

            self.log(
                f"Output tokens: "
                f"{self.output_tokens}"
            )

            self.log(
                f"Total tokens: "
                f"{self.total_tokens}"
            )

            self.log(
                "================================================"
            )

            return final_text

        except Exception as exc:

            self.log(
                f"❌ Erro no PlanApp AI: {exc}",
                "error",
            )

            self.status(
                f"❌ Erro na execução: {exc}"
            )

            raise

    # ========================================================================
    # CLOSE
    # ========================================================================

    async def close(
        self,
    ):

        try:

            await self.exit_stack.aclose()

        finally:

            self.mcp_session = None

            self.openai_client = None

            self.log_detail(
                "🔌 PlanApp AI encerrado."
            )


# ============================================================================
# FUNÇÃO DE CONVENIÊNCIA
# ============================================================================

async def run_agent(
    user_text,
    progress_callback=None,
    map_callback=None,
    log_callback=None,
    result_callback=None,
    visualization_callback=None,
):

    agent = PlanAppAgent(

        progress_callback=
            progress_callback,

        map_callback=
            map_callback,

        log_callback=
            log_callback,

        result_callback=
            result_callback,

        visualization_callback=
            visualization_callback,
    )

    try:

        return await agent.ask(
            user_text
        )

    finally:

        await agent.close()