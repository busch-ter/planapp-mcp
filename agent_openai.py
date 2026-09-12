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
#   PlanApp MCP
#      |
#      v
#   PlanApp FastAPI
#
# Este agente mantém a mesma lógica funcional do agent_ollama.py.
#
# IMPORTANTE:
# - O LLM NÃO executa evaluate_link diretamente.
# - O LLM NÃO escolhe quais visualizações devem ser geradas.
# - A aplicação controla evaluate_link.
# - Depois de um evaluate_link bem-sucedido, a aplicação gera
#   deterministicamente todas as visualizações disponíveis.
#

import asyncio
import base64
import json
import os
import re

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

# Para a POC, medium oferece uma boa relação entre capacidade e custo.
OPENAI_REASONING_EFFORT = "medium"

MCP_URL = "http://172.17.0.1:8010/mcp"

USER_ID = "jupyter-user"

DEBUG = False

MAX_AGENT_ITERATIONS = 12


# ============================================================================
# TOOLS CONTROLADAS PELA APLICAÇÃO
# ============================================================================
#
# Estas ferramentas NÃO são expostas ao LLM.
#
# O agente Python decide quando executá-las.
#

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

    def __init__(
        self,
        progress_callback=None,
        map_callback=None,
        log_callback=None,
        result_callback=None,
        visualization_callback=None,
    ):
        # ------------------------------------------------------------------
        # Callbacks
        # ------------------------------------------------------------------

        self.progress_callback = progress_callback
        self.map_callback = map_callback
        self.log_callback = log_callback
        self.result_callback = result_callback
        self.visualization_callback = visualization_callback

        # ------------------------------------------------------------------
        # MCP / OpenAI
        # ------------------------------------------------------------------

        self.exit_stack = AsyncExitStack()

        self.mcp_session = None
        self.mcp_tools = []

        self.openai_client = None

        # ------------------------------------------------------------------
        # Conversação
        # ------------------------------------------------------------------

        self.messages = []
        self.user_id = USER_ID

        # ------------------------------------------------------------------
        # Estado
        # ------------------------------------------------------------------

        self.registered = False

        self.evaluate_executed = False
        self.evaluate_error = None

        self.geocoded_points = []

        self.map = None

        self.current_stage = None
        self.tool_count = 0

        self.last_evaluate_result = None

        self.visualizations = []

        # ------------------------------------------------------------------
        # Parâmetros do enlace
        # ------------------------------------------------------------------

        self.requested_frequency_value = None
        self.requested_frequency_unit = None
        self.requested_frequency_mhz = None

        self.requested_tx_ha = None
        self.requested_rx_ha = None

        self.requested_on_rooftop = False

        # ------------------------------------------------------------------
        # Estatísticas OpenAI
        # ------------------------------------------------------------------

        self.input_tokens = 0
        self.output_tokens = 0
        self.cached_input_tokens = 0
        self.total_tokens = 0

        self.estimated_input_cost_usd = 0.0
        self.estimated_output_cost_usd = 0.0
        self.estimated_total_cost_usd = 0.0

        # ------------------------------------------------------------------
        # Responses API
        # ------------------------------------------------------------------

        self.last_response_id = None

        # ------------------------------------------------------------------
        # Configuração de custo
        # ------------------------------------------------------------------

        self.INPUT_PRICE_PER_MILLION = 0.20
        self.OUTPUT_PRICE_PER_MILLION = 1.20

    # ========================================================================
    # LOG
    # ========================================================================

    def log(self, texto, tipo="processing"):
        """
        Envia mensagem para o callback da interface.

        Compatibilidade:
        - callback(texto, tipo)
        - callback(texto)
        """

        if DEBUG:
            print(texto)

        if self.progress_callback:
            try:
                self.progress_callback(texto)
            except Exception:
                pass

        if self.log_callback:
            try:
                self.log_callback(texto, tipo)
            except TypeError:
                try:
                    self.log_callback(texto)
                except Exception:
                    pass
            except Exception:
                pass

    def log_detail(self, texto):
        self.log(texto, "detail")

    # ========================================================================
    # OPENAI
    # ========================================================================

    def connect_openai(self):
        api_key = os.getenv("OPENAI_API_KEY")

        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY não encontrada no ambiente."
            )

        self.openai_client = AsyncOpenAI(
            api_key=api_key
        )

        self.log("✅ Cliente OpenAI inicializado.")

    # ========================================================================
    # CONNECT MCP + OPENAI
    # ========================================================================

    async def connect(self):

        self.current_stage = "Conectando ao OpenAI"

        self.connect_openai()

        self.log("🔌 Conectando ao PlanApp MCP...")

        transport = await self.exit_stack.enter_async_context(
            streamable_http_client(MCP_URL)
        )

        read_stream, write_stream, _ = transport

        self.mcp_session = await self.exit_stack.enter_async_context(
            ClientSession(
                read_stream,
                write_stream,
            )
        )

        await self.mcp_session.initialize()

        tools_result = await self.mcp_session.list_tools()

        self.mcp_tools = tools_result.tools

        self.log(
            f"🔧 MCP conectado: {len(self.mcp_tools)} ferramentas disponíveis."
        )

        for tool in self.mcp_tools:
            self.log_detail(
                f"   • {tool.name}"
            )

    # ========================================================================
    # OPENAI TOOLS
    # ========================================================================

    def build_openai_tools(self):

        tools = []

        for tool in self.mcp_tools:

            if tool.name in APPLICATION_CONTROLLED_TOOLS:
                continue

            schema = getattr(tool, "inputSchema", None)

            if schema is None:
                schema = {
                    "type": "object",
                    "properties": {},
                }

            description = getattr(
                tool,
                "description",
                None,
            )

            openai_tool = {
                "type": "function",
                "name": tool.name,
                "description": description or "",
                "parameters": schema,
            }

            tools.append(openai_tool)

        return tools

    # ========================================================================
    # RESET
    # ========================================================================

    def reset_state(self):

        self.registered = False

        self.evaluate_executed = False
        self.evaluate_error = None

        self.geocoded_points = []

        self.map = None

        self.current_stage = None
        self.tool_count = 0

        self.last_evaluate_result = None

        self.visualizations = []

        self.requested_frequency_value = None
        self.requested_frequency_unit = None
        self.requested_frequency_mhz = None

        self.requested_tx_ha = None
        self.requested_rx_ha = None

        self.requested_on_rooftop = False

        self.messages = []

        self.last_response_id = None

        self.input_tokens = 0
        self.output_tokens = 0
        self.cached_input_tokens = 0
        self.total_tokens = 0

        self.estimated_input_cost_usd = 0.0
        self.estimated_output_cost_usd = 0.0
        self.estimated_total_cost_usd = 0.0

    # ========================================================================
    # REGEX / PARÂMETROS DO ENLACE
    # ========================================================================

    def extract_link_parameters(self, text):

        if not text:
            return

        # ------------------------------------------------------------------
        # Frequência
        # ------------------------------------------------------------------

        frequency_patterns = [
            r"(\d+(?:[.,]\d+)?)\s*(GHz|MHz|kHz|Hz)\b",
            r"freq(?:uência|uency)?\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*(GHz|MHz|kHz|Hz)\b",
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
                match.group(1).replace(",", ".")
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

        # ------------------------------------------------------------------
        # TX / RX height
        # ------------------------------------------------------------------

        tx_patterns = [
            r"tx(?:_?ha| antenna height| height)?\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*m\b",
            r"transmissor.*?(\d+(?:[.,]\d+)?)\s*m\b",
            r"tx.*?(\d+(?:[.,]\d+)?)\s*m\b",
        ]

        rx_patterns = [
            r"rx(?:_?ha| antenna height| height)?\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*m\b",
            r"receptor.*?(\d+(?:[.,]\d+)?)\s*m\b",
            r"rx.*?(\d+(?:[.,]\d+)?)\s*m\b",
        ]

        for pattern in tx_patterns:

            match = re.search(
                pattern,
                text,
                re.IGNORECASE,
            )

            if match:
                self.requested_tx_ha = float(
                    match.group(1).replace(",", ".")
                )
                break

        for pattern in rx_patterns:

            match = re.search(
                pattern,
                text,
                re.IGNORECASE,
            )

            if match:
                self.requested_rx_ha = float(
                    match.group(1).replace(",", ".")
                )
                break

        # ------------------------------------------------------------------
        # Caso o usuário informe uma altura única
        # ------------------------------------------------------------------

        if (
            self.requested_tx_ha is None
            and self.requested_rx_ha is None
        ):

            generic_height = re.search(
                r"(?:altura|height)\s*[:=]?\s*(\d+(?:[.,]\d+)?)\s*m\b",
                text,
                re.IGNORECASE,
            )

            if generic_height:

                value = float(
                    generic_height.group(1).replace(",", ".")
                )

                self.requested_tx_ha = value
                self.requested_rx_ha = value

        # ------------------------------------------------------------------
        # Rooftop
        # ------------------------------------------------------------------

        rooftop_patterns = [
            r"\brooftop\b",
            r"\bno\s+telhado\b",
            r"\bno\s+teto\b",
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
    # PARSE MCP
    # ========================================================================

    def parse_mcp_result(self, result):

        # ------------------------------------------------------------------
        # structuredContent
        # ------------------------------------------------------------------

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

        # ------------------------------------------------------------------
        # content
        # ------------------------------------------------------------------

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
                    return json.loads(text)
                except Exception:
                    return text

        return None

    # ========================================================================
    # ERROS MCP
    # ========================================================================

    def contains_nested_error(self, value):

        if isinstance(value, dict):

            status = str(
                value.get("status", "")
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

    def is_mcp_error(self, result, parsed):

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

        return self.contains_nested_error(parsed)

    # ========================================================================
    # LOG SAFE
    # ========================================================================

    def make_log_safe(self, value):

        try:
            if isinstance(value, dict):

                result = {}

                for key, item in value.items():

                    if key == "data" and isinstance(item, str):

                        if len(item) > 500:
                            result[key] = (
                                f"<base64: {len(item)} caracteres>"
                            )
                        else:
                            result[key] = item

                    else:
                        result[key] = self.make_log_safe(item)

                return result

            if isinstance(value, list):

                return [
                    self.make_log_safe(item)
                    for item in value
                ]

            return value

        except Exception:

            return "<objeto não serializável>"

    # ========================================================================
    # GEOCODING
    # ========================================================================

    def extract_coordinates(self, value):

        if not isinstance(value, dict):
            return None

        lat = None
        lon = None

        possible_lat_keys = [
            "lat",
            "latitude",
            "y",
        ]

        possible_lon_keys = [
            "lon",
            "lng",
            "longitude",
            "x",
        ]

        for key in possible_lat_keys:

            if key in value:

                try:
                    lat = float(value[key])
                    break
                except Exception:
                    pass

        for key in possible_lon_keys:

            if key in value:

                try:
                    lon = float(value[key])
                    break
                except Exception:
                    pass

        if lat is not None and lon is not None:
            return lat, lon

        # Busca recursiva
        for child in value.values():

            result = self.extract_coordinates(child)

            if result:
                return result

        return None

    def register_geocoded_point(
        self,
        result,
        query=None,
    ):

        coordinates = self.extract_coordinates(result)

        if not coordinates:
            return

        lat, lon = coordinates

        point = {
            "query": query,
            "lat": lat,
            "lon": lon,
        }

        # Evita duplicação
        for existing in self.geocoded_points:

            if (
                abs(existing["lat"] - lat) < 1e-9
                and
                abs(existing["lon"] - lon) < 1e-9
            ):
                return

        self.geocoded_points.append(point)

        self.log(
            f"📍 Ponto geocodificado: "
            f"{query or 'local'} "
            f"({lat:.6f}, {lon:.6f})"
        )

        self.mostrar_mapa_apos_geocodificacao()

    def summarize_geocode(self, result):

        coordinates = self.extract_coordinates(result)

        if coordinates:

            lat, lon = coordinates

            return (
                f"Coordenadas encontradas: "
                f"latitude={lat:.6f}, longitude={lon:.6f}"
            )

        return "Geocodificação concluída."

    # ========================================================================
    # MAPA
    # ========================================================================

    def mostrar_mapa_apos_geocodificacao(self):

        if len(self.geocoded_points) < 1:
            return

        try:

            if len(self.geocoded_points) >= 2:

                p1 = self.geocoded_points[0]
                p2 = self.geocoded_points[1]

                self.map = mostrar_mapa_enlace(
                    p1["lat"],
                    p1["lon"],
                    p2["lat"],
                    p2["lon"],
                )

            else:

                self.map = mostrar_mapa_enlace(
                    self.geocoded_points[0]["lat"],
                    self.geocoded_points[0]["lon"],
                    self.geocoded_points[0]["lat"],
                    self.geocoded_points[0]["lon"],
                )

            self.log_detail(
                "🗺️ Mapa atualizado."
            )

            if self.map_callback:

                try:
                    self.map_callback(self.map)
                except Exception as exc:
                    self.log_detail(
                        f"⚠️ Erro no map_callback: {exc}"
                    )

        except Exception as exc:

            self.log_detail(
                f"⚠️ Erro ao gerar mapa: {exc}"
            )

    # ========================================================================
    # RESUMO EVALUATE
    # ========================================================================

    def summarize_evaluate(self, result):

        if not isinstance(result, dict):
            return "Avaliação concluída."

        lines = []

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

        if fspl is not None:
            lines.append(
                f"FSPL={fspl}"
            )

        if distance is not None:
            lines.append(
                f"distância={distance}"
            )

        if lines:
            return " | ".join(lines)

        return "Avaliação concluída."

    def find_recursive(self, value, keys):

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
    # USAGE / CUSTO
    # ========================================================================

    def update_usage(self, response):

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

        # --------------------------------------------------------------
        # Cached input
        # --------------------------------------------------------------

        input_details = getattr(
            usage,
            "input_tokens_details",
            None,
        )

        if input_details is not None:

            cached_tokens = getattr(
                input_details,
                "cached_tokens",
                0,
            ) or 0

            self.cached_input_tokens += int(
                cached_tokens
            )

        # --------------------------------------------------------------
        # Custo estimado
        # --------------------------------------------------------------

        self.estimated_input_cost_usd = (
            self.input_tokens
            / 1_000_000.0
            * self.INPUT_PRICE_PER_MILLION
        )

        self.estimated_output_cost_usd = (
            self.output_tokens
            / 1_000_000.0
            * self.OUTPUT_PRICE_PER_MILLION
        )

        self.estimated_total_cost_usd = (
            self.estimated_input_cost_usd
            + self.estimated_output_cost_usd
        )

    # ========================================================================
    # TECHNICAL RESULT
    # ========================================================================

    def publish_technical_result(self, result):

        self.last_evaluate_result = result

        if self.result_callback:

            try:
                self.result_callback(result)
            except Exception as exc:

                self.log_detail(
                    f"⚠️ Erro no result_callback: {exc}"
                )

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

        self.log(
            f"🔧 MCP TOOL: {tool_name}"
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

            result = await self.mcp_session.call_tool(
                tool_name,
                arguments,
            )

        except Exception as exc:

            self.log(
                f"❌ Erro ao executar {tool_name}: {exc}",
                "error",
            )

            if tool_name == "evaluate_link":
                self.evaluate_error = str(exc)

            raise

        parsed = self.parse_mcp_result(result)

        safe_result = self.make_log_safe(
            parsed
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

        # --------------------------------------------------------------
        # Detecta erros reais, inclusive erros aninhados
        # --------------------------------------------------------------

        if self.is_mcp_error(
            result,
            parsed,
        ):

            error_message = (
                parsed
                if isinstance(parsed, str)
                else json.dumps(
                    safe_result,
                    ensure_ascii=False,
                    default=str,
                )
            )

            self.log(
                f"❌ MCP informou erro em {tool_name}.",
                "error",
            )

            if tool_name == "evaluate_link":
                self.evaluate_error = error_message

            return parsed

        # --------------------------------------------------------------
        # Geocode
        # --------------------------------------------------------------

        if tool_name == "geocode_place":

            query = arguments.get(
                "query"
            )

            self.register_geocoded_point(
                parsed,
                query=query,
            )

        # --------------------------------------------------------------
        # Evaluate
        # --------------------------------------------------------------

        if tool_name == "evaluate_link":

            self.evaluate_executed = True
            self.evaluate_error = None

            self.publish_technical_result(
                parsed
            )

            summary = self.summarize_evaluate(
                parsed
            )

            self.log(
                f"📡 Enlace avaliado: {summary}"
            )

            # ----------------------------------------------------------
            # Visualizações são sempre controladas pela aplicação.
            # ----------------------------------------------------------

            await self.gerar_visualizacoes()

        return parsed

    # ========================================================================
    # GERAR VISUALIZAÇÕES
    # ========================================================================

    async def gerar_visualizacoes(self):

        if not self.evaluate_executed:
            return

        if self.evaluate_error is not None:

            self.log_detail(
                "⚠️ Visualizações não serão geradas: "
                "evaluate_link apresentou erro."
            )

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

        # ------------------------------------------------------------------
        # Ordem determinística.
        # ------------------------------------------------------------------

        etapas = [

            (
                "DTM",
                "link_area",
                {
                    "ds_string": "DTM"
                },
            ),

            (
                "DSM",
                "link_area",
                {
                    "ds_string": "DSM"
                },
            ),

            (
                "COVER",
                "link_area",
                {
                    "ds_string": "COVER"
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

                result = await self.execute_mcp_tool(
                    tool_name,
                    arguments,
                )

            except Exception as exc:

                self.log_detail(
                    f"❌ Exceção em {titulo}: {exc}"
                )

                continue

            if not isinstance(result, dict):

                self.log_detail(
                    f"⚠️ Resultado inválido para {titulo}."
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
                    f"⚠️ Falha na visualização: {titulo}"
                )

                continue

            kind = result.get(
                "kind"
            )

            if kind != "image":

                self.log_detail(
                    f"ℹ️ {titulo}: "
                    "resultado não visualizável."
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

                image_bytes = base64.b64decode(
                    data,
                    validate=True,
                )

                if not image_bytes:

                    self.log_detail(
                        f"⚠️ {titulo}: "
                        "imagem decodificada vazia."
                    )

                    continue

                # ------------------------------------------------------
                # IMPORTANTE:
                #
                # Não usamos IPython.display.Image aqui.
                #
                # widgets.Image é necessário para que a imagem seja
                # armazenada e renderizada corretamente pelo notebook UI.
                # ------------------------------------------------------

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
                    f"❌ Erro ao decodificar "
                    f"{titulo}: {exc}"
                )

        # ------------------------------------------------------------------
        # Atualiza interface
        # ------------------------------------------------------------------

        if self.visualization_callback:

            try:

                self.visualization_callback(
                    self.visualizations
                )

            except Exception as exc:

                self.log_detail(
                    f"❌ Erro ao atualizar visualizações: {exc}"
                )

        self.log(
            f"📊 {len(self.visualizations)} "
            "visualizações geradas."
        )

    # ========================================================================
    # REGISTER
    # ========================================================================

    async def register_session(self):

        if self.registered:
            return

        self.log(
            f"📝 Registrando sessão: {self.user_id}"
        )

        result = await self.execute_mcp_tool(
            "register",
            {
                "user_id": self.user_id,
            },
        )

        self.registered = True

        self.log(
            "✅ Sessão PlanApp registrada."
        )

        return result

    # ========================================================================
    # EVALUATE LINK
    # ========================================================================

    async def ensure_evaluate_link(
        self,
        parameters=None,
    ):

        if self.evaluate_executed:
            return self.last_evaluate_result

        if self.evaluate_error is not None:
            return None

        if len(self.geocoded_points) < 2:

            self.log_detail(
                "⚠️ Ainda não existem dois pontos "
                "geocodificados para avaliar o enlace."
            )

            return None

        tx = self.geocoded_points[0]
        rx = self.geocoded_points[1]

        # ------------------------------------------------------------------
        # Parâmetros
        # ------------------------------------------------------------------

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

        on_rooftop = self.requested_on_rooftop

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

        self.log(
            "📡 Executando avaliação do enlace..."
        )

        self.log_detail(
            json.dumps(
                arguments,
                indent=2,
                ensure_ascii=False,
            )
        )

        return await self.execute_mcp_tool(
            "evaluate_link",
            arguments,
        )

    # ========================================================================
    # CONTEXTO TÉCNICO
    # ========================================================================

    def append_technical_context(self):

        if not self.last_evaluate_result:
            return

        technical_context = {
            "status": "OK",
            "technical_result": self.last_evaluate_result,
        }

        self.messages.append(
            {
                "role": "user",
                "content": (
                    "O resultado técnico oficial do PlanApp "
                    "para o enlace é:\n"
                    + json.dumps(
                        technical_context,
                        ensure_ascii=False,
                        default=str,
                    )
                    + "\n\n"
                    "Use estes dados como fonte de verdade "
                    "para sua resposta final. "
                    "Não invente valores técnicos."
                ),
            }
        )

    # ========================================================================
    # SYSTEM PROMPT
    # ========================================================================

    def system_prompt(self):

        return """
Você é o PlanApp AI, assistente técnico especializado
em planejamento e avaliação de enlaces de rádio.

REGRAS FUNDAMENTAIS:

1. O PlanApp é a fonte de verdade para resultados técnicos.

2. Nunca invente coordenadas.

3. Nunca invente distância, FSPL, altura, frequência,
   perda, visada ou qualquer outro resultado técnico.

4. Para encontrar coordenadas de locais fornecidos pelo usuário,
   use a ferramenta geocode_place.

5. O sistema da aplicação controla evaluate_link.
   Você NÃO deve chamar evaluate_link diretamente.

6. O sistema da aplicação também controla todas as visualizações.
   Você NÃO deve chamar ferramentas de visualização diretamente.

7. Quando houver dois pontos geocodificados, a aplicação executará
   automaticamente a avaliação do enlace.

8. Depois que evaluate_link for executado com sucesso,
   a aplicação gerará automaticamente as visualizações disponíveis.

9. Use os resultados retornados pelo PlanApp para responder.

10. Se uma ferramenta retornar erro, informe o problema.
    Não invente um resultado alternativo.

11. Frequência:
    - 450 MHz significa 450 MHz.
    - 450 GHz significa 450000 MHz.
    - 450 kHz significa 0.45 MHz.
    - 450 Hz significa 0.00045 MHz.

12. Preserve na resposta a unidade originalmente informada pelo usuário
    quando mencionar a frequência.

13. Se nenhuma frequência for informada, o padrão da aplicação é 900 MHz.

14. Se nenhuma altura for informada, o padrão da aplicação é:
    TX = 7 m
    RX = 7 m

15. Se o usuário informar uma altura única, ela pode ser aplicada
    a TX e RX.

16. Se o usuário especificar alturas TX e RX separadamente,
    preserve os valores.

17. Se o usuário especificar rooftop/telhado/teto,
    preserve essa intenção.

18. Não diga que uma visualização foi gerada se a aplicação
    não tiver confirmado sua geração.

19. Não produza JSON para o usuário final a menos que isso seja
    explicitamente solicitado.

20. Responda de forma objetiva e técnica.

Seu trabalho principal é:
- interpretar a solicitação;
- identificar os locais;
- utilizar geocodificação quando necessário;
- fornecer contexto para a aplicação;
- interpretar o resultado técnico oficial do PlanApp.
"""

    # ========================================================================
    # OPENAI RESPONSES API
    # ========================================================================

    async def openai_chat(self):

        if self.openai_client is None:

            raise RuntimeError(
                "Cliente OpenAI não inicializado."
            )

        tools = self.build_openai_tools()

        response = await self.openai_client.responses.create(

            model=OPENAI_MODEL,

            input=self.messages,

            tools=tools,

            tool_choice="auto",

            reasoning={
                "effort": OPENAI_REASONING_EFFORT,
            },
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
    # OUTPUT TEXT
    # ========================================================================

    def response_text(self, response):

        text = getattr(
            response,
            "output_text",
            None,
        )

        if text:
            return text

        # Fallback
        output = getattr(
            response,
            "output",
            None,
        )

        if not output:
            return ""

        texts = []

        for item in output:

            item_type = getattr(
                item,
                "type",
                None,
            )

            if item_type != "message":
                continue

            content = getattr(
                item,
                "content",
                None,
            )

            if not content:
                continue

            for part in content:

                part_type = getattr(
                    part,
                    "type",
                    None,
                )

                if part_type == "output_text":

                    text_value = getattr(
                        part,
                        "text",
                        None,
                    )

                    if text_value:
                        texts.append(
                            text_value
                        )

        return "\n".join(
            texts
        )

    # ========================================================================
    # AGENT TURN
    # ========================================================================

    async def agent_turn(
        self,
        user_text,
    ):

        for iteration in range(
            MAX_AGENT_ITERATIONS
        ):

            self.current_stage = (
                f"OpenAI — iteração "
                f"{iteration + 1}"
            )

            response = await self.openai_chat()

            output = getattr(
                response,
                "output",
                [],
            )

            function_calls = []

            for item in output:

                item_type = getattr(
                    item,
                    "type",
                    None,
                )

                if item_type == "function_call":

                    function_calls.append(
                        item
                    )

            # --------------------------------------------------------------
            # Nenhuma chamada de ferramenta:
            # resposta final do modelo.
            # --------------------------------------------------------------

            if not function_calls:

                text = self.response_text(
                    response
                )

                if text:

                    self.messages.append(
                        {
                            "role": "assistant",
                            "content": text,
                        }
                    )

                return text

            # --------------------------------------------------------------
            # Processa chamadas de ferramentas
            # --------------------------------------------------------------

            for call in function_calls:

                tool_name = getattr(
                    call,
                    "name",
                    None,
                )

                call_id = getattr(
                    call,
                    "call_id",
                    None,
                )

                arguments_text = getattr(
                    call,
                    "arguments",
                    "{}",
                )

                try:

                    arguments = json.loads(
                        arguments_text
                    )

                except Exception:

                    arguments = {}

                self.log(
                    f"🤖 OpenAI solicitou: "
                    f"{tool_name}"
                )

                # ----------------------------------------------------------
                # Segurança adicional:
                # o modelo não pode executar ferramentas controladas
                # pela aplicação.
                # ----------------------------------------------------------

                if tool_name in APPLICATION_CONTROLLED_TOOLS:

                    tool_result = {
                        "status": "ERROR",
                        "error": (
                            "Esta ferramenta é controlada "
                            "pela aplicação e não pode ser "
                            "executada diretamente pelo modelo."
                        ),
                    }

                else:

                    try:

                        tool_result = (
                            await self.execute_mcp_tool(
                                tool_name,
                                arguments,
                            )
                        )

                    except Exception as exc:

                        tool_result = {
                            "status": "ERROR",
                            "error": str(exc),
                        }

                # ----------------------------------------------------------
                # Responses API:
                # devolve resultado da função ao modelo.
                # ----------------------------------------------------------

                self.messages.append(
                    {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps(
                            tool_result,
                            ensure_ascii=False,
                            default=str,
                        ),
                    }
                )

            # --------------------------------------------------------------
            # Depois de dois pontos, a aplicação avalia automaticamente.
            # --------------------------------------------------------------

            if (
                len(self.geocoded_points) >= 2
                and not self.evaluate_executed
                and self.evaluate_error is None
            ):

                await self.ensure_evaluate_link()

                if self.evaluate_executed:

                    self.append_technical_context()

        return ""

    # ========================================================================
    # ASK
    # ========================================================================

    async def ask(
        self,
        user_text,
    ):

        self.reset_state()

        if self.visualization_callback:

            try:
                self.visualization_callback([])
            except Exception:
                pass

        self.extract_link_parameters(
            user_text
        )

        self.current_stage = "Inicialização"

        self.log(
            "🚀 Iniciando PlanApp AI..."
        )

        try:

            await self.connect()

            await self.register_session()

            self.messages = [

                {
                    "role": "system",
                    "content": self.system_prompt(),
                },

                {
                    "role": "user",
                    "content": user_text,
                },
            ]

            final_text = await self.agent_turn(
                user_text
            )

            # --------------------------------------------------------------
            # Garantia:
            # se o modelo terminou antes da avaliação, a aplicação
            # ainda executa evaluate_link automaticamente.
            # --------------------------------------------------------------

            if (
                len(self.geocoded_points) >= 2
                and not self.evaluate_executed
                and self.evaluate_error is None
            ):

                await self.ensure_evaluate_link()

            # --------------------------------------------------------------
            # Atualiza mapa
            # --------------------------------------------------------------

            if len(self.geocoded_points) >= 2:

                self.mostrar_mapa_apos_geocodificacao()

            # --------------------------------------------------------------
            # Contexto técnico final
            # --------------------------------------------------------------

            if self.evaluate_executed:

                self.append_technical_context()

                # ----------------------------------------------------------
                # Se ainda não houver texto final adequado, fazemos uma
                # chamada final do modelo usando o resultado técnico.
                # ----------------------------------------------------------

                if not final_text:

                    final_response = (
                        await self.openai_chat()
                    )

                    final_text = (
                        self.response_text(
                            final_response
                        )
                    )

                    if final_text:

                        self.messages.append(
                            {
                                "role": "assistant",
                                "content": final_text,
                            }
                        )

            # --------------------------------------------------------------
            # Resultado final
            # --------------------------------------------------------------

            if self.evaluate_error:

                self.log(
                    "❌ Avaliação do enlace terminou com erro.",
                    "error",
                )

            elif self.evaluate_executed:

                self.log(
                    "✅ Avaliação do enlace concluída."
                )

            else:

                self.log(
                    "ℹ️ Nenhuma avaliação de enlace foi executada."
                )

            self.log(
                "💰 Custo estimado da execução: "
                f"US$ {self.estimated_total_cost_usd:.6f}"
            )

            return final_text

        except Exception as exc:

            self.log(
                f"❌ Erro no PlanApp AI: {exc}",
                "error",
            )

            raise

    # ========================================================================
    # CLOSE
    # ========================================================================

    async def close(self):

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
        progress_callback=progress_callback,
        map_callback=map_callback,
        log_callback=log_callback,
        result_callback=result_callback,
        visualization_callback=visualization_callback,
    )

    try:

        return await agent.ask(
            user_text
        )

    finally:

        await agent.close()