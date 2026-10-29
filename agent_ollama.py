# ============================================================
# PLANAPP AI — OLLAMA / QWEN
#
# ETAPA 1 / ETAPA 2
#
# Fluxo:
#   Jupyter
#      |
#      v
#   Ollama / Qwen
#      |
#      v
#   geocode_place
#      |
#      v
#   aplicação -> evaluate_link
#      |
#      +--> mapa interativo
#      +--> visualizações
#      +--> relatório técnico / PDF
#      |
#      v
#   Qwen analisa resultado técnico
#
# IMPORTANTE:
#   - enlace único preservado
#   - multi-hop suportado
#   - evaluate_link é controlado pela aplicação
#   - mapa e visualizações são controlados pela aplicação
#   - em multi-hop cada hop continua sendo um evaluate_link
#   - Qwen recebe contexto compacto para a análise final
# ============================================================

import asyncio
import base64
import json
import os
import re

import requests
import ipywidgets as widgets

from agent_common import (
    PlanAppAgentCommon,
    MCP_URL,
    USER_ID,
    DEFAULT_FREQ_MHZ,
    DEFAULT_TX_HA,
    DEFAULT_RX_HA,
    DEFAULT_ON_ROOFTOP,
    MAX_AGENT_ITERATIONS,
    LOG_DIR,
    APPLICATION_CONTROLLED_TOOLS,
)

from report_generator import ReportGenerator


# ============================================================
# CONFIGURAÇÃO OLLAMA
# ============================================================

OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://172.17.0.1:11434",
)

OLLAMA_MODEL = os.getenv(
    "OLLAMA_MODEL",
    "qwen3:8b",
)

OLLAMA_FINAL_TIMEOUT = int(
    os.getenv(
        "OLLAMA_FINAL_TIMEOUT",
        "300",
    )
)

OLLAMA_FINAL_NUM_PREDICT = int(
    os.getenv(
        "OLLAMA_FINAL_NUM_PREDICT",
        "2500",
    )
)


# ============================================================
# AGENTE
# ============================================================

class PlanAppAgent(PlanAppAgentCommon):

    AGENT_NAME = "PLANAPP AI — OLLAMA / QWEN"

    def __init__(
        self,
        progress_callback=None,
        map_callback=None,
        log_callback=None,
        result_callback=None,
        visualization_callback=None,
    ):

        super().__init__(
            progress_callback=progress_callback,
            map_callback=map_callback,
            log_callback=log_callback,
            result_callback=result_callback,
            visualization_callback=visualization_callback,
        )

        self.registered = False
        self.technical_context_added = False
        self.last_agent_text = ""
        self.technical_report = ""

        # ========================================================
        # SOLICITAÇÃO ORIGINAL
        # ========================================================

        self.user_request = ""

        # ========================================================
        # RELATÓRIO
        # ========================================================

        self.report_pdf_path = None

        # ========================================================
        # MAPA
        # ========================================================

        self.map = None
        self.map_image_bytes = None

        # ========================================================
        # VISUALIZAÇÕES
        # ========================================================

        self.visualizations = []
        self.visualization_images = []

        # ========================================================
        # LOGGER
        # ========================================================

        self._configure_logger()

        self.logger.info(
            "============================================================"
        )

        self.logger.info(
            "PLANAPP AI — OLLAMA / QWEN"
        )

        self.logger.info(
            f"MODEL={OLLAMA_MODEL}"
        )

        self.logger.info(
            f"OLLAMA_URL={OLLAMA_URL}"
        )

        self.logger.info(
            f"MCP_URL={MCP_URL}"
        )

        self.logger.info(
            f"USER_ID={USER_ID}"
        )

        self.logger.info(
            "============================================================"
        )

    # ============================================================
    # LOGGER
    # ============================================================

    def _configure_logger(self):

        # O PlanAppAgentCommon já configura o logger.
        # Mantemos este método para compatibilidade.
        pass

    # ============================================================
    # SYSTEM PROMPT
    # ============================================================

    def system_prompt(self):

        return """
Você é o PlanApp AI, assistente técnico especializado em planejamento e avaliação de enlaces de rádio.

O PlanApp é a fonte oficial dos resultados técnicos.

REGRAS:

1. Nunca invente valores, unidades ou resultados.
2. Nunca altere resultados retornados pelo PlanApp.
3. Não recalcule valores técnicos quando o PlanApp já os forneceu.
4. Use geocode_place para todas as localidades informadas pelo usuário.
5. Em uma rota com 3 ou mais localidades, geocodifique TODAS na ordem informada antes da avaliação.
6. Preserve rigorosamente a ordem dos pontos.
7. A -> B -> C representa Hop 1 A -> B e Hop 2 B -> C.
8. Não pare a geocodificação depois dos dois primeiros pontos em uma rota multi-hop.
9. NÃO execute evaluate_link diretamente. A aplicação controla a avaliação.
10. Em multi-hop, evaluate_link continua representando somente UM enlace.
11. Mapa e visualizações são controlados pela aplicação.
12. Preserve frequência, TX, RX e rooftop solicitados.
13. Padrões: 900 MHz, TX 7 m, RX 7 m, rooftop=false.
14. FSPL significa perda de percurso em espaço livre; não significa interferência.
15. Não invente potência TX, ganho, sensibilidade, margem ou limiares.
16. Não atribua significado físico próprio a core, fresnel, boundary, delta_diffra, VV, v_v ou d_norm.
17. Não converta radianos para graus.
18. status=OK significa sucesso de execução, não viabilidade.
19. Não declare enlace ou rota viável/inviável sem critério técnico explícito.
20. Em multi-hop, apresente os resultados de cada hop separadamente e compare os hops.
21. Pode comparar maior/menor e diferenças entre valores efetivamente retornados.
22. Destaque valores negativos, especialmente clearances negativas, sem inventar sua causa.
23. Identifique pontos de atenção sustentados pelos próprios dados.
24. Diferencie parâmetros solicitados, parâmetros efetivos, resultados, interpretação e limitações.
25. Sugestões não testadas devem ser apresentadas como sugestões.
26. Responda em português do Brasil.
27. Seja técnico, claro, objetivo e informativo.
"""

    # ============================================================
    # OLLAMA
    # ============================================================

    async def connect_ollama(self):

        try:

            response = await asyncio.to_thread(
                requests.get,
                f"{OLLAMA_URL}/api/tags",
                timeout=10,
            )

            response.raise_for_status()

            self.log_detail(
                "Ollama conectado."
            )

        except Exception as exc:

            raise RuntimeError(
                f"Não foi possível conectar ao Ollama: {exc}"
            )

    # ============================================================
    # FERRAMENTAS OLLAMA
    # ============================================================

    def build_ollama_tools(self):

        tools = []

        for tool in self.mcp_tools:

            name = getattr(
                tool,
                "name",
                None,
            )

            if not name:
                continue

            if name in APPLICATION_CONTROLLED_TOOLS:
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

            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": (
                            getattr(
                                tool,
                                "description",
                                "",
                            )
                            or ""
                        ),
                        "parameters": schema,
                    },
                }
            )

        return tools

    # ============================================================
    # CHAT OLLAMA
    # ============================================================

    async def ollama_chat(
        self,
        *,
        use_tools=True,
        options=None,
    ):

        payload = {
            "model": OLLAMA_MODEL,
            "messages": self.messages,
            "stream": False,
            "think": False,
        }

        if use_tools:
            payload["tools"] = self.build_ollama_tools()

        if options:
            payload["options"] = options

        self.log_detail(
            f"Enviando requisição ao Ollama: {OLLAMA_MODEL}"
        )

        if not use_tools:

            self.log_detail(
                "Análise final: chamada ao Ollama sem ferramentas MCP."
            )

        try:

            timeout = (
                OLLAMA_FINAL_TIMEOUT
                if not use_tools
                else 600
            )

            if not use_tools:

                self.log_detail(
                    "========== MESSAGES ENVIADAS AO OLLAMA ==========\n"
                    + json.dumps(
                        self.messages,
                        ensure_ascii=False,
                        default=str,
                    )
                    + "\n========== FIM MESSAGES ENVIADAS AO OLLAMA =========="
                )

            response = await asyncio.to_thread(
                requests.post,
                f"{OLLAMA_URL}/api/chat",
                json=payload,
                timeout=timeout,
            )

            response.raise_for_status()

            data = response.json()

            if not isinstance(
                data,
                dict,
            ):

                raise RuntimeError(
                    "Ollama retornou uma resposta em formato inesperado."
                )

            if not use_tools:

                final_text = self.response_text(
                    data
                )

                self.log_detail(
                    "Resposta final do Qwen recebida: "
                    f"{len(final_text)} caracteres."
                )

                if not final_text:

                    self.log_detail(
                        "⚠️ O Qwen respondeu sem texto na análise final."
                    )

            return data

        except requests.Timeout as exc:

            self.log_detail(
                "⚠️ Timeout na análise final do Qwen: "
                f"{exc}"
            )

            raise RuntimeError(
                "O Ollama não concluiu a análise final dentro do "
                f"tempo limite de {OLLAMA_FINAL_TIMEOUT}s."
            )

        except requests.RequestException as exc:

            raise RuntimeError(
                f"Erro na comunicação com Ollama: {exc}"
            )

        except Exception as exc:

            raise RuntimeError(
                f"Erro ao processar resposta do Ollama: {exc}"
            )

    # ============================================================
    # EXTRAÇÃO DA RESPOSTA OLLAMA
    # ============================================================

    def response_message(
        self,
        response,
    ):

        if not isinstance(
            response,
            dict,
        ):
            return {}

        message = response.get(
            "message",
            {},
        )

        if not isinstance(
            message,
            dict,
        ):
            return {}

        return message

    def response_text(
        self,
        response,
    ):

        message = self.response_message(
            response
        )

        content = message.get(
            "content",
            "",
        )

        if content is None:
            return ""

        return str(
            content
        ).strip()

    def response_tool_calls(
        self,
        response,
    ):

        message = self.response_message(
            response
        )

        tool_calls = message.get(
            "tool_calls",
            [],
        )

        if not isinstance(
            tool_calls,
            list,
        ):
            return []

        return tool_calls

    # ============================================================
    # CONTEXTO TÉCNICO
    # ============================================================

    def append_technical_context(
        self,
        result,
    ):

        context = (
            self.build_technical_context(
                result
            )
        )

        self.messages.append(
            {
                "role": "user",
                "content": json.dumps(
                    context,
                    ensure_ascii=False,
                    default=str,
                ),
            }
        )

        self.technical_context_added = True

        self.log_detail(
            "Contexto técnico do PlanApp enviado ao Qwen."
        )

    # ============================================================
    # MAPA
    # ============================================================

    async def mostrar_mapa_apos_geocodificacao(
        self,
    ):

        if len(
            self.geocoded_points
        ) < 2:

            return

        try:

            from map_utils import (
                mostrar_mapa_enlace,
                gerar_imagem_mapa_enlace,
            )

            p1 = (
                self.geocoded_points[0]
            )

            p2 = (
                self.geocoded_points[1]
            )

            tx_lat = p1["lat"]
            tx_lon = p1["lon"]

            rx_lat = p2["lat"]
            rx_lon = p2["lon"]

            self.map = (
                mostrar_mapa_enlace(
                    tx_lat,
                    tx_lon,
                    rx_lat,
                    rx_lon,
                )
            )

            if self.map_callback:

                self.map_callback(
                    self.map
                )

            self.map_image_bytes = (
                gerar_imagem_mapa_enlace(
                    tx_lat,
                    tx_lon,
                    rx_lat,
                    rx_lon,
                )
            )

            self.log_detail(
                "Mapa interativo preparado."
            )

            self.log_detail(
                "Imagem estática do mapa OSM "
                "preparada para o relatório."
            )

        except Exception as exc:

            self.log_detail(
                f"⚠️ Erro no mapa: {exc}"
            )

    # ============================================================
    # VISUALIZAÇÕES
    # ============================================================

    async def gerar_visualizacoes(
        self,
    ):

        if not self.multi_hop_requested:

            if not self.evaluate_executed:
                return

            if self.evaluate_error:
                return

            hop_info = {
                "key": "single",
                "index": None,
                "name": None,
            }

        else:

            if self.multi_hop_error:
                return

            hop_info = (
                self._get_current_hop_info()
            )

            if hop_info is None:

                self.log_detail(
                    "⚠️ Não foi possível identificar "
                    "o hop atual para gerar "
                    "as visualizações."
                )

                return

        hop_key = hop_info["key"]

        if hop_key in (
            self.visualizations_generated_hops
        ):

            self.log_detail(
                "Visualizações já preparadas "
                f"para {hop_key}; "
                "nova geração ignorada."
            )

            return

        if self.multi_hop_requested:

            hop_index = (
                hop_info.get("index")
            )

            hop_name = (
                hop_info.get("name")
            )

            if hop_name:

                if hop_index is not None:

                    hop_title = (
                        f"Hop {hop_index} — "
                        f"{hop_name}"
                    )

                else:

                    hop_title = (
                        str(hop_name)
                    )

            else:

                if hop_index is not None:

                    hop_title = (
                        f"Hop {hop_index}"
                    )

                else:

                    hop_title = "Hop"

        else:

            hop_title = None

        tools = [
            (
                "link_area",
                {"ds_string": "DTM"},
                "DTM",
            ),
            (
                "link_area",
                {"ds_string": "DSM"},
                "DSM",
            ),
            (
                "link_area",
                {"ds_string": "COVER"},
                "COVER",
            ),
            (
                "link_profile",
                {},
                "Perfil",
            ),
            (
                "lulc_fresnel",
                {},
                "LULC / Fresnel",
            ),
            (
                "bldg_prepare",
                {},
                "Buildings prepare",
            ),
            (
                "bldg_fresnel",
                {},
                "Buildings / Fresnel",
            ),
            (
                "bldg_profile",
                {},
                "Buildings profile",
            ),
        ]

        generated_count = 0

        for (
            tool_name,
            arguments,
            image_type,
        ) in tools:

            try:

                raw = (
                    await self.execute_mcp_tool_raw(
                        tool_name,
                        arguments,
                    )
                )

                parsed = (
                    self.parse_mcp_result(
                        raw
                    )
                )

                if not isinstance(
                    parsed,
                    dict,
                ):

                    self.log_detail(
                        f"⚠️ {image_type}: "
                        "resultado não é um objeto."
                    )

                    continue

                if parsed.get(
                    "kind"
                ) != "image":

                    self.log_detail(
                        f"⚠️ {image_type}: "
                        "resultado não contém imagem."
                    )

                    continue

                data = parsed.get(
                    "data"
                )

                if not data:

                    self.log_detail(
                        f"⚠️ {image_type}: "
                        "imagem sem dados."
                    )

                    continue

                image_bytes = (
                    base64.b64decode(
                        data
                    )
                )

                image = widgets.Image(
                    value=image_bytes,
                    format="png",
                    layout=widgets.Layout(
                        width="100%",
                        height="auto",
                    ),
                )

                if hop_title:

                    title = (
                        f"{hop_title} — "
                        f"{image_type}"
                    )

                else:

                    title = image_type

                self.visualizations.append(
                    image
                )

                self.visualization_images.append(
                    {
                        "title": title,
                        "data": image_bytes,
                        "mime_type": "image/png",
                    }
                )

                generated_count += 1

                if self.visualization_callback:

                    self.visualization_callback(
                        image,
                        title,
                    )

                self.log_detail(
                    f"Visualização preparada: "
                    f"{title}"
                )

            except Exception as exc:

                self.log_detail(
                    f"⚠️ Visualização "
                    f"{image_type}: {exc}"
                )

        self.visualizations_generated_hops.add(
            hop_key
        )

        self.log_detail(
            "Visualizações do "
            f"{hop_title or 'enlace único'} "
            f"preparadas: {generated_count}"
        )

        self.log_detail(
            "Total acumulado de visualizações: "
            f"{len(self.visualization_images)}"
        )

    # ============================================================
    # RELATÓRIO
    # ============================================================

    def build_report(
        self,
        technical_result,
        analysis_text=None,
    ):

        requested_parameters = {
            "frequency": getattr(
                self,
                "requested_frequency",
                None,
            ),
            "frequency_unit": getattr(
                self,
                "requested_frequency_unit",
                None,
            ),
            "frequency_text": getattr(
                self,
                "requested_frequency_text",
                None,
            ),
            "tx_ha": getattr(
                self,
                "requested_tx_ha",
                None,
            ),
            "rx_ha": getattr(
                self,
                "requested_rx_ha",
                None,
            ),
        }

        link_parameters = getattr(
            self,
            "link_parameters",
            {},
        )

        if not isinstance(
            link_parameters,
            dict,
        ):

            link_parameters = {}

        effective_parameters = {
            "freq_mhz": link_parameters.get(
                "freq_mhz",
                DEFAULT_FREQ_MHZ,
            ),
            "tx_ha": link_parameters.get(
                "tx_ha",
                DEFAULT_TX_HA,
            ),
            "rx_ha": link_parameters.get(
                "rx_ha",
                DEFAULT_RX_HA,
            ),
            "on_rooftop": link_parameters.get(
                "on_rooftop",
                DEFAULT_ON_ROOFTOP,
            ),
        }

        if (
            self.map_image_bytes is None
            and len(
                self.geocoded_points
            ) >= 2
        ):

            try:

                if (
                    self.multi_hop_requested
                    and getattr(
                        self,
                        "hops",
                        None,
                    )
                ):

                    from map_utils import (
                        gerar_imagem_mapa_multihop,
                    )

                    self.map_image_bytes = (
                        gerar_imagem_mapa_multihop(
                            self.hops
                        )
                    )

                else:

                    from map_utils import (
                        gerar_imagem_mapa_enlace,
                    )

                    p1 = (
                        self.geocoded_points[0]
                    )

                    p2 = (
                        self.geocoded_points[1]
                    )

                    self.map_image_bytes = (
                        gerar_imagem_mapa_enlace(
                            p1["lat"],
                            p1["lon"],
                            p2["lat"],
                            p2["lon"],
                        )
                    )

            except Exception as exc:

                self.log_detail(
                    "⚠️ Não foi possível "
                    "gerar imagem do mapa "
                    "para o relatório: "
                    f"{exc}"
                )

        if analysis_text is None:
            analysis_text = (
                self.technical_report
                or None
            )

        generator = ReportGenerator(
            requested_params=requested_parameters,
            effective_params=effective_parameters,
            technical_result=technical_result,
            geocoded_points=self.geocoded_points,
            map_image=self.map_image_bytes,
            visualization_images=self.visualization_images,
            user_request=self.user_request,
            analysis_text=analysis_text,
        )

        report = generator.generate_report(
            include_raw_result=False
        )

        self.technical_report = report

        pdf_path = generator.generate_pdf(
            report_text=report,
            include_raw_result=False,
        )

        self.report_pdf_path = pdf_path

        self.log_detail(
            "Relatório PDF gerado: "
            f"{pdf_path}"
        )

        self.log_detail(
            "Mapa no relatório: "
            + (
                "SIM"
                if self.map_image_bytes
                else "NÃO"
            )
        )

        self.log_detail(
            "Visualizações no relatório: "
            f"{len(self.visualization_images)}"
        )

        return report

    # ============================================================
    # AGENT TURN
    # ============================================================

    async def agent_turn(self):

        for iteration in range(
            MAX_AGENT_ITERATIONS
        ):

            self.log_detail(
                f"Iteração do agente: "
                f"{iteration + 1}/"
                f"{MAX_AGENT_ITERATIONS}"
            )

            response = (
                await self.ollama_chat()
            )

            message = (
                self.response_message(
                    response
                )
            )

            text = (
                self.response_text(
                    response
                )
            )

            tool_calls = (
                self.response_tool_calls(
                    response
                )
            )

            if text:
                self.last_agent_text = text

            if message:
                self.messages.append(
                    message
                )

            # ----------------------------------------------------
            # SEM TOOL CALLS
            # ----------------------------------------------------

            if not tool_calls:

                result = (
                    await self.ensure_application_evaluation()
                )

                if result is not None:

                    self.append_technical_context(
                        result
                    )

                    if (
                        self.multi_hop_requested
                        and getattr(
                            self,
                            "multi_hop_executed",
                            False,
                        )
                    ):

                        self.log_detail(
                            "🟢 Multi-hop concluído após a geocodificação."
                        )

                        self.log_detail(
                            "Encerrando agent_turn()."
                        )

                        return text

                    continue

                if (
                    self.multi_hop_requested
                    and len(
                        self.geocoded_points
                    ) < 3
                    and not self.geocoding_followup_sent
                ):

                    self.geocoding_followup_sent = True

                    self.messages.append(
                        {
                            "role": "user",
                            "content": (
                                "A solicitação atual descreve uma rota multi-hop. "
                                "Ainda existem menos de três pontos geocodificados. "
                                "Continue identificando e geocodificando, na ordem "
                                "solicitada pelo usuário, todas as localidades restantes. "
                                "Não execute avaliação técnica."
                            ),
                        }
                    )

                    continue

                return text

            # ----------------------------------------------------
            # EXECUÇÃO DAS TOOLS
            # ----------------------------------------------------

            tool_messages = []

            for call in tool_calls:

                function = call.get(
                    "function",
                    {},
                )

                if not isinstance(
                    function,
                    dict,
                ):
                    continue

                name = function.get(
                    "name"
                )

                if not name:
                    continue

                arguments = function.get(
                    "arguments",
                    {},
                )

                if isinstance(
                    arguments,
                    str,
                ):

                    try:

                        arguments = json.loads(
                            arguments or "{}"
                        )

                    except Exception as exc:

                        self.log_detail(
                            f"⚠️ Argumentos inválidos para {name}: {exc}"
                        )

                        arguments = {}

                if not isinstance(
                    arguments,
                    dict,
                ):

                    arguments = {}

                if name in APPLICATION_CONTROLLED_TOOLS:

                    self.log_detail(
                        f"⚠️ Ferramenta {name} é controlada pela aplicação."
                    )

                    continue

                self.log_detail(
                    f"Executando ferramenta MCP: {name}"
                )

                try:

                    result = (
                        await self.execute_mcp_tool(
                            name,
                            arguments,
                        )
                    )

                    tool_messages.append(
                        {
                            "role": "tool",
                            "content": json.dumps(
                                result,
                                ensure_ascii=False,
                                default=str,
                            ),
                        }
                    )

                except Exception as exc:

                    self.log_detail(
                        f"⚠️ Erro na ferramenta {name}: {exc}"
                    )

                    tool_messages.append(
                        {
                            "role": "tool",
                            "content": json.dumps(
                                {
                                    "error": str(exc)
                                },
                                ensure_ascii=False,
                            ),
                        }
                    )

            if tool_messages:

                self.messages.extend(
                    tool_messages
                )

                # Não avaliar aqui: o Qwen precisa ter a oportunidade
                # de geocodificar todos os pontos da rota.
                continue

            result = (
                await self.ensure_application_evaluation()
            )

            if result is not None:

                self.append_technical_context(
                    result
                )

                if (
                    self.multi_hop_requested
                    and getattr(
                        self,
                        "multi_hop_executed",
                        False,
                    )
                ):

                    self.log_detail(
                        "🟢 Multi-hop concluído após a execução das ferramentas."
                    )

                    self.log_detail(
                        "Encerrando agent_turn()."
                    )

                    return text

                continue

            if (
                self.multi_hop_requested
                and len(
                    self.geocoded_points
                ) < 3
                and not self.geocoding_followup_sent
            ):

                self.geocoding_followup_sent = True

                self.messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Continue a geocodificação da rota multi-hop solicitada. "
                            "Use geocode_place para os pontos restantes na ordem original. "
                            "Não execute avaliação técnica."
                        ),
                    }
                )

                continue

            return text

        return (
            "Não foi possível concluir o processamento dentro do "
            "limite de iterações."
        )

    # ============================================================
    # COMPACTAÇÃO GENÉRICA
    # ============================================================

    def _compact_analysis_context(
        self,
        technical_result,
    ):
        """
        Remove somente conteúdo pesado que não é necessário ao Qwen.

        O resultado técnico continua sendo o resultado real do PlanApp.
        Esta função permanece disponível para compatibilidade.

        A análise final utiliza build_final_analysis_context(),
        que é ainda mais específica e compacta.
        """

        def compact(
            value,
            key="",
            depth=0,
        ):

            key_lower = str(
                key
            ).lower()

            if key_lower in {
                "data",
                "image",
                "image_data",
                "image_bytes",
                "base64",
                "png",
                "jpeg",
                "jpg",
            }:

                return (
                    "[conteúdo visual omitido da análise textual]"
                )

            if isinstance(
                value,
                dict,
            ):

                result = {}

                for k, v in value.items():

                    result[k] = compact(
                        v,
                        k,
                        depth + 1,
                    )

                return result

            if isinstance(
                value,
                list,
            ):

                if len(value) > 200:

                    return {
                        "_total_itens": len(value),
                        "_amostra_inicial": [
                            compact(
                                v,
                                key,
                                depth + 1,
                            )
                            for v in value[:20]
                        ],
                        "_amostra_final": [
                            compact(
                                v,
                                key,
                                depth + 1,
                            )
                            for v in value[-5:]
                        ],
                        "_observacao": (
                            "lista extensa compactada "
                            "para análise textual"
                        ),
                    }

                return [
                    compact(
                        v,
                        key,
                        depth + 1,
                    )
                    for v in value
                ]

            if (
                isinstance(
                    value,
                    str,
                )
                and len(value) > 20000
            ):

                return (
                    value[:20000]
                    + "\n"
                    "[texto extenso truncado para análise final]"
                )

            return value

        return compact(
            technical_result
        )

    # ============================================================
    # CONTEXTO FINAL COMPACTO
    # ============================================================

    def build_final_analysis_context(
        self,
        technical_result,
    ):
        """
        Constrói um contexto pequeno e determinístico para a análise
        final do Qwen.

        IMPORTANTE:

        build_technical_context() continua sendo a fonte original
        dos dados.

        Aqui não recalculamos nada.

        Apenas extraímos os campos relevantes para a interpretação
        textual e removemos conteúdo pesado, como imagens, base64,
        geometrias extensas e estruturas redundantes.

        O objetivo principal é facilitar para o Qwen a reprodução
        exata dos valores numéricos retornados pelo PlanApp.
        """

        source = self.build_technical_context(
            technical_result
        )

        scalar_fields = {
            "dist_m",
            "fspl",
            "delta_diffra",
            "max_obstruction_angle_rad",
            "tx_rx_elevation_angle_rad",
            "tx_near_terminal_clearance_m",
            "rx_near_terminal_clearance_m",
        }

        grouped_fields = {
            "terrain": {
                "core",
                "fresnel",
                "boundary",
            },
            "vegetation": {
                "core",
                "fresnel",
                "boundary",
            },
            "buildings": {
                "core",
                "fresnel",
                "boundary",
            },
        }

        ignored_keys = {
            "data",
            "image",
            "image_data",
            "image_bytes",
            "base64",
            "png",
            "jpeg",
            "jpg",
        }

        def clean_value(
            value,
            key=None,
        ):

            key_lower = (
                str(key).lower()
                if key is not None
                else ""
            )

            if key_lower in ignored_keys:

                return (
                    "[conteúdo visual omitido]"
                )

            if isinstance(
                value,
                dict,
            ):

                cleaned = {}

                for k, v in value.items():

                    if str(k).lower() in ignored_keys:
                        continue

                    cleaned[k] = clean_value(
                        v,
                        k,
                    )

                return cleaned

            if isinstance(
                value,
                list,
            ):

                # Para listas pequenas preservamos tudo.
                if len(value) <= 30:

                    return [
                        clean_value(
                            item,
                            key,
                        )
                        for item in value
                    ]

                # Listas enormes não são úteis para a análise textual.
                return {
                    "_total_itens": len(value),
                    "_observacao": (
                        "lista extensa omitida "
                        "da análise textual"
                    ),
                }

            if (
                isinstance(
                    value,
                    str,
                )
                and len(value) > 5000
            ):

                return (
                    value[:5000]
                    + "\n[texto extenso omitido]"
                )

            return value

        # --------------------------------------------------------
        # BUSCA RECURSIVA
        # --------------------------------------------------------

        def find_all_key_values(
            value,
            target_key,
            results=None,
        ):

            if results is None:
                results = []

            if isinstance(
                value,
                dict,
            ):

                for k, v in value.items():

                    if str(k).lower() == str(
                        target_key
                    ).lower():

                        results.append(v)

                    find_all_key_values(
                        v,
                        target_key,
                        results,
                    )

            elif isinstance(
                value,
                list,
            ):

                for item in value:

                    find_all_key_values(
                        item,
                        target_key,
                        results,
                    )

            return results

        def find_first_key_value(
            value,
            target_key,
            default=None,
        ):

            values = find_all_key_values(
                value,
                target_key,
            )

            if values:
                return values[0]

            return default

        # --------------------------------------------------------
        # EXTRAI HOPS
        #
        # Estratégia:
        #
        # 1. procurar estruturas explícitas de hops;
        # 2. se não forem encontradas, procurar dicionários que
        #    contenham dist_m/fspl/delta_diffra;
        # 3. preservar os valores encontrados sem recalcular.
        # --------------------------------------------------------

        hop_candidates = []

        def collect_hop_candidates(
            value,
        ):

            if isinstance(
                value,
                dict,
            ):

                keys_lower = {
                    str(k).lower()
                    for k in value.keys()
                }

                has_main_metric = (
                    "dist_m" in keys_lower
                    or "fspl" in keys_lower
                    or "delta_diffra" in keys_lower
                )

                if has_main_metric:

                    hop_candidates.append(
                        value
                    )

                for child in value.values():

                    collect_hop_candidates(
                        child
                    )

            elif isinstance(
                value,
                list,
            ):

                for child in value:

                    collect_hop_candidates(
                        child
                    )

        collect_hop_candidates(
            source
        )

        # --------------------------------------------------------
        # TENTA ENCONTRAR LISTA EXPLÍCITA DE HOPS
        # --------------------------------------------------------

        explicit_hops = None

        possible_hop_keys = [
            "hops",
            "hop_results",
            "hop_results",
            "multi_hop_results",
            "results_by_hop",
            "resultados_hops",
            "resultados_por_hop",
            "resultado_multi_hop_para_analise",
            "resultado_tecnico_para_analise",
        ]

        for key in possible_hop_keys:

            values = find_all_key_values(
                source,
                key,
            )

            for value in values:

                if isinstance(
                    value,
                    list,
                ) and value:

                    explicit_hops = value
                    break

                if isinstance(
                    value,
                    dict,
                ):

                    # Pode ser um dicionário indexado por hop.
                    possible_items = list(
                        value.values()
                    )

                    if possible_items and all(
                        isinstance(
                            item,
                            dict,
                        )
                        for item in possible_items
                    ):

                        explicit_hops = (
                            possible_items
                        )

                        break

            if explicit_hops is not None:
                break

        if explicit_hops:

            normalized_candidates = []

            for item in explicit_hops:

                if isinstance(
                    item,
                    dict,
                ):

                    normalized_candidates.append(
                        item
                    )

            if normalized_candidates:

                hop_candidates = (
                    normalized_candidates
                )

        # --------------------------------------------------------
        # REMOVE DUPLICATAS
        # --------------------------------------------------------

        unique_hops = []

        seen_signatures = set()

        for hop in hop_candidates:

            if not isinstance(
                hop,
                dict,
            ):
                continue

            signature = (
                str(hop.get("dist_m", "")),
                str(hop.get("fspl", "")),
                str(hop.get("delta_diffra", "")),
            )

            # Um dicionário sem nenhuma das três métricas não é
            # suficiente para identificar um resultado de hop.
            if signature == ("", "", ""):
                continue

            if signature in seen_signatures:
                continue

            seen_signatures.add(
                signature
            )

            unique_hops.append(
                hop
            )

        # --------------------------------------------------------
        # EXTRAI PONTOS
        # --------------------------------------------------------

        points = []

        raw_points = getattr(
            self,
            "geocoded_points",
            [],
        )

        if isinstance(
            raw_points,
            list,
        ):

            for point in raw_points:

                if not isinstance(
                    point,
                    dict,
                ):
                    continue

                compact_point = {}

                for key in (
                    "name",
                    "display_name",
                    "place",
                    "locality",
                    "lat",
                    "lon",
                    "latitude",
                    "longitude",
                ):

                    if key in point:

                        compact_point[key] = (
                            point[key]
                        )

                if compact_point:

                    points.append(
                        compact_point
                    )

        # --------------------------------------------------------
        # PARÂMETROS
        # --------------------------------------------------------

        requested_parameters = {
            "frequency": getattr(
                self,
                "requested_frequency",
                None,
            ),
            "frequency_unit": getattr(
                self,
                "requested_frequency_unit",
                None,
            ),
            "frequency_text": getattr(
                self,
                "requested_frequency_text",
                None,
            ),
            "tx_ha": getattr(
                self,
                "requested_tx_ha",
                None,
            ),
            "rx_ha": getattr(
                self,
                "requested_rx_ha",
                None,
            ),
            "on_rooftop": getattr(
                self,
                "requested_on_rooftop",
                None,
            ),
        }

        link_parameters = getattr(
            self,
            "link_parameters",
            {},
        )

        if not isinstance(
            link_parameters,
            dict,
        ):

            link_parameters = {}

        effective_parameters = {
            "freq_mhz": link_parameters.get(
                "freq_mhz",
                DEFAULT_FREQ_MHZ,
            ),
            "tx_ha": link_parameters.get(
                "tx_ha",
                DEFAULT_TX_HA,
            ),
            "rx_ha": link_parameters.get(
                "rx_ha",
                DEFAULT_RX_HA,
            ),
            "on_rooftop": link_parameters.get(
                "on_rooftop",
                DEFAULT_ON_ROOFTOP,
            ),
        }

        # --------------------------------------------------------
        # EXTRAI CAMPOS DE CADA HOP
        # --------------------------------------------------------

        compact_hops = []

        for index, hop in enumerate(
            unique_hops,
            start=1,
        ):

            compact_hop = {
                "hop": index,
            }

            # ----------------------------------------------------
            # IDENTIFICAÇÃO
            # ----------------------------------------------------

            for key in (
                "id",
                "name",
                "label",
                "title",
                "tx",
                "rx",
                "source",
                "destination",
                "from",
                "to",
            ):

                if key in hop:

                    compact_hop[key] = (
                        clean_value(
                            hop[key],
                            key,
                        )
                    )

            # ----------------------------------------------------
            # CAMPOS ESCALARES
            # ----------------------------------------------------

            for field in scalar_fields:

                if field in hop:

                    compact_hop[field] = (
                        hop[field]
                    )

            # ----------------------------------------------------
            # GRUPOS:
            #
            # terrain
            # vegetation
            # buildings
            #
            # Procuramos primeiro a estrutura agrupada.
            # ----------------------------------------------------

            for group_name, fields in (
                grouped_fields.items()
            ):

                group_value = None

                # Estrutura:
                #
                # "terrain": {
                #     "core": ...,
                #     ...
                # }
                #
                for possible_key in (
                    group_name,
                    group_name.lower(),
                ):

                    if possible_key in hop:

                        candidate = hop[
                            possible_key
                        ]

                        if isinstance(
                            candidate,
                            dict,
                        ):

                            group_value = {}

                            for field in fields:

                                if field in candidate:

                                    group_value[
                                        field
                                    ] = candidate[
                                        field
                                    ]

                            break

                # ------------------------------------------------
                # Estrutura alternativa:
                #
                # terrain_core
                # terrain_fresnel
                # terrain_boundary
                # ------------------------------------------------

                if group_value is None:
                    group_value = {}

                for field in fields:

                    flat_key = (
                        f"{group_name}_{field}"
                    )

                    if flat_key in hop:

                        group_value[field] = (
                            hop[flat_key]
                        )

                if group_value:

                    compact_hop[
                        group_name
                    ] = group_value

            # ----------------------------------------------------
            # TERRAIN PEAKS
            # ----------------------------------------------------

            for key in (
                "terrain_peaks_vv",
                "terrain_peaks",
                "peaks",
            ):

                if key in hop:

                    compact_hop[key] = (
                        clean_value(
                            hop[key],
                            key,
                        )
                    )

            # ----------------------------------------------------
            # OUTROS CAMPOS PEQUENOS
            #
            # Preserva alguns indicadores técnicos úteis quando
            # estiverem presentes diretamente no hop.
            # ----------------------------------------------------

            additional_fields = {
                "status",
                "success",
                "ok",
                "error",
                "message",
                "vegetation",
                "cover",
                "lulc",
                "building_count",
                "buildings_count",
                "obstructions",
                "obstacle_count",
            }

            for key in additional_fields:

                if key in hop:

                    compact_hop[key] = (
                        clean_value(
                            hop[key],
                            key,
                        )
                    )

            compact_hops.append(
                compact_hop
            )

        # --------------------------------------------------------
        # FALLBACK:
        #
        # Se a estrutura do build_technical_context() não tiver
        # agrupado os campos, preservamos o contexto compacto
        # correspondente.
        #
        # Isso não substitui os hops quando encontrados.
        # --------------------------------------------------------

        if not compact_hops:

            fallback = self._compact_analysis_context(
                source
            )

            compact_hops = [
                {
                    "hop": 1,
                    "resultado": fallback,
                }
            ]

        # --------------------------------------------------------
        # RESULTADO FINAL COMPACTO
        # --------------------------------------------------------

        compact_context = {
            "fonte": "PlanApp",
            "observacao": (
                "Todos os valores abaixo foram extraídos dos "
                "resultados técnicos fornecidos pela aplicação. "
                "Nenhum valor foi recalculado."
            ),
            "parametros_solicitados": (
                clean_value(
                    requested_parameters
                )
            ),
            "parametros_efetivos": (
                clean_value(
                    effective_parameters
                )
            ),
            "multi_hop": bool(
                getattr(
                    self,
                    "multi_hop_requested",
                    False,
                )
            ),
            "pontos_geocodificados": points,
            "hops": compact_hops,
        }

        return compact_context

    # ============================================================
    # RESPOSTA FINAL
    # ============================================================

    async def generate_final_response(
        self,
        original_text,
        technical_result,
        technical_report=None,
    ):
        """
        Gera somente a interpretação final dos resultados já calculados.

        A chamada é deliberadamente independente do histórico do agente.

        O Qwen recebe:

            1. system prompt;
            2. solicitação original;
            3. contexto técnico COMPACTO;
            4. instruções de análise.

        Não são enviadas ferramentas MCP.

        A principal diferença em relação à versão anterior é que
        não enviamos o JSON técnico completo para o Qwen.
        """

        # --------------------------------------------------------
        # CONTEXTO FINAL COMPACTO
        # --------------------------------------------------------

        context = (
            self.build_final_analysis_context(
                technical_result
            )
        )

        context_json = json.dumps(
            context,
            ensure_ascii=False,
            default=str,
            indent=2,
        )

        self.log_detail(
            "========== CONTEXTO FINAL COMPACTO ENVIADO AO QWEN ==========\n"
            + context_json
            + "\n========== FIM CONTEXTO FINAL COMPACTO ENVIADO AO QWEN =========="
        )

        self.log_detail(
            "Contexto final compacto preparado para a análise: "
            f"{len(context_json)} caracteres."
        )

        # --------------------------------------------------------
        # INSTRUÇÃO FINAL
        # --------------------------------------------------------

        final_instruction = """
Produza agora a análise técnica final do PlanApp em português
do Brasil.

IMPORTANTE:

Os números presentes em "RESULTADOS TÉCNICOS DO PLANAPP" são
resultados reais produzidos pela aplicação.

Você deve COPIAR os valores exatamente como foram fornecidos.

NÃO invente números.

NÃO altere números.

NÃO arredonde números.

NÃO faça cálculos para substituir valores fornecidos.

NÃO transforme unidades.

NÃO crie valores intermediários.

Se um valor estiver presente no contexto, utilize exatamente
esse valor na resposta.

Em uma análise multi-hop, trate cada hop separadamente.

A resposta deve ser uma análise técnica, e não simplesmente
uma reprodução do JSON.

Use exatamente esta estrutura:

## 1. RESUMO EXECUTIVO

Apresente uma síntese objetiva dos resultados.

Se não existir critério técnico explícito suficiente para
classificar a viabilidade, informe:

INDETERMINADO

e explique a limitação.

## 2. IDENTIFICAÇÃO DA ROTA

Apresente os pontos na ordem em que foram geocodificados.

Em multi-hop, deixe explícita a sequência:

Hop 1: A -> B
Hop 2: B -> C
Hop 3: C -> D

ou a sequência correspondente aos dados reais.

Não invente nomes.

Utilize somente localidades e coordenadas fornecidas pelo
PlanApp.

## 3. PARÂMETROS UTILIZADOS

Diferencie:

- parâmetros solicitados;
- parâmetros efetivamente utilizados.

Apresente, quando disponíveis:

- frequência;
- TX;
- RX;
- rooftop.

Não altere os valores.

## 4. ANÁLISE POR HOP

Para cada hop, apresente separadamente:

- distância;
- FSPL;
- delta_diffra;
- resultados de terreno;
- resultados de vegetação;
- resultados de edificações;
- resultados geométricos;
- demais indicadores efetivamente fornecidos.

Não misture os valores entre hops.

NÃO atribua significado físico não documentado a:

- core;
- fresnel;
- boundary;
- delta_diffra;
- VV;
- v_v;
- d_norm.

## 5. COMPARAÇÃO ENTRE OS HOPS

Quando houver mais de um hop:

- compare distâncias;
- compare FSPL;
- compare delta_diffra;
- compare os demais valores efetivamente fornecidos.

Pode dizer que um valor é maior ou menor que outro quando
essa comparação estiver diretamente sustentada pelos valores.

Não invente causas.

## 6. TERRENO

Apresente os resultados de terreno efetivamente retornados.

Preserve exatamente os números.

Não atribua semântica adicional aos campos.

## 7. FRESNEL

Apresente os valores de Fresnel efetivamente retornados.

Não invente percentuais.

Não invente margem.

Não invente limiar.

Não invente classificação de obstrução.

## 8. VEGETAÇÃO / COBERTURA

Apresente os resultados efetivamente retornados pelo PlanApp.

Não invente classificação adicional.

## 9. EDIFICAÇÕES

Apresente os resultados efetivamente retornados pelo PlanApp.

Preserve exatamente os números.

Não invente interpretação física para campos não documentados.

## 10. GEOMETRIA E OBSTÁCULOS

Apresente, quando disponíveis:

- max_obstruction_angle_rad;
- tx_rx_elevation_angle_rad;
- tx_near_terminal_clearance_m;
- rx_near_terminal_clearance_m;
- terrain_peaks_vv;
- demais resultados geométricos.

NÃO converta radianos para graus.

Não invente a causa de um valor negativo.

## 11. PRINCIPAIS PONTOS DE ATENÇÃO

Identifique os valores que merecem atenção técnica.

Essa seção deve ser baseada exclusivamente nos dados fornecidos.

Não invente fatores externos.

## 12. DIAGNÓSTICO TÉCNICO

Faça uma síntese integrada.

Considere conjuntamente:

- propagação;
- distância;
- terreno;
- vegetação;
- edificações;
- geometria;
- demais indicadores disponíveis.

Não trate um único indicador isoladamente como suficiente.

## 13. CONCLUSÃO DE VIABILIDADE

Somente utilize:

- VIÁVEL
- NÃO VIÁVEL
- VIÁVEL COM RESSALVAS

quando existir critério técnico explícito suficiente nos dados.

Caso contrário, utilize:

INDETERMINADO

e explique por que os dados disponíveis não permitem uma
classificação definitiva.

Não invente limiares.

Não invente margem.

Não invente potência.

Não invente ganho.

Não invente sensibilidade.

## 14. ALTERNATIVAS

Se apropriado, apresente sugestões como:

- alteração de altura;
- alteração de frequência;
- alteração de posicionamento;
- alteração de parâmetros.

Essas alternativas devem ser claramente identificadas como
SUGESTÕES.

Não diga que uma sugestão resolve o problema.

Não diga que uma sugestão foi testada se ela não foi testada.

## 15. LIMITAÇÕES

Informe as limitações da análise.

Inclua qualquer critério de engenharia necessário para uma
conclusão definitiva que não esteja presente nos resultados.

REGRAS ABSOLUTAS:

- Nunca invente valores.
- Nunca altere valores.
- Nunca arredonde valores fornecidos.
- Nunca altere unidades.
- Nunca faça cálculos adicionais.
- Nunca converta radianos para graus.
- Nunca invente potência.
- Nunca invente ganho.
- Nunca invente sensibilidade.
- Nunca invente margem.
- Nunca invente limiares.
- Nunca invente critérios de viabilidade.
- Nunca atribua significado próprio a core.
- Nunca atribua significado próprio a fresnel.
- Nunca atribua significado próprio a boundary.
- Nunca atribua significado próprio a delta_diffra.
- Nunca atribua significado próprio a VV.
- Nunca atribua significado próprio a v_v.
- Nunca atribua significado próprio a d_norm.
- Não confunda status OK com viabilidade.
- Não apresente sugestões como resultados.
- Não diga que uma alternativa resolve o problema sem teste.
- Não misture valores de hops diferentes.
- Responda em português do Brasil.
- Seja técnico, claro e objetivo.
"""

        # --------------------------------------------------------
        # MENSAGENS FINAIS
        # --------------------------------------------------------

        final_messages = [
            {
                "role": "system",
                "content": self.system_prompt(),
            },
            {
                "role": "user",
                "content": (
                    "SOLICITAÇÃO ORIGINAL DO USUÁRIO:\n"
                    + str(original_text)
                ),
            },
            {
                "role": "user",
                "content": (
                    "RESULTADOS TÉCNICOS DO PLANAPP:\n"
                    + context_json
                ),
            },
            {
                "role": "user",
                "content": final_instruction,
            },
        ]

        # --------------------------------------------------------
        # CHAMADA FINAL
        # --------------------------------------------------------

        old_messages = self.messages

        try:

            self.messages = final_messages

            response = await self.ollama_chat(
                use_tools=False,
                options={
                    "temperature": 0.2,
                    "num_predict": OLLAMA_FINAL_NUM_PREDICT,
                },
            )

            answer = self.response_text(
                response
            )

            if answer:

                self.last_agent_text = answer

                self.log_detail(
                    "🧠 Análise final do Qwen concluída."
                )

            else:

                self.log_detail(
                    "⚠️ Análise final do Qwen retornou texto vazio."
                )

            return answer

        finally:

            self.messages = old_messages

    # ============================================================
    # ASK
    # ============================================================

    async def ask(
        self,
        text,
    ):

        # --------------------------------------------------------
        # RESET
        # --------------------------------------------------------

        self.reset_common_state()

        self.registered = False
        self.technical_context_added = False
        self.last_agent_text = ""
        self.technical_report = ""
        self.report_pdf_path = None
        self.user_request = text

        # --------------------------------------------------------
        # MULTI-HOP
        # --------------------------------------------------------

        self.multi_hop_requested = (
            self.detect_multi_hop_request(
                text
            )
        )

        self.geocoding_followup_sent = False

        self.log_detail(
            "🔗 Solicitação multi-hop detectada."
            if self.multi_hop_requested
            else "🔗 Solicitação de enlace único."
        )

        # --------------------------------------------------------
        # MAPA
        # --------------------------------------------------------

        self.map = None
        self.map_image_bytes = None

        # --------------------------------------------------------
        # VISUALIZAÇÕES
        # --------------------------------------------------------

        self.visualizations = []
        self.visualization_images = []

        self.visualizations_generated_hops = set()

        # --------------------------------------------------------
        # PARÂMETROS
        # --------------------------------------------------------

        self.extract_link_parameters(
            text
        )

        # --------------------------------------------------------
        # CONEXÕES
        # --------------------------------------------------------

        await self.connect_ollama()

        await self.connect()

        await self.register()

        # --------------------------------------------------------
        # MENSAGENS INICIAIS
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
        # EXECUTA AGENTE
        # --------------------------------------------------------

        await self.agent_turn()

        # --------------------------------------------------------
        # GARANTIA DA AVALIAÇÃO
        # --------------------------------------------------------

        result = (
            await self.ensure_application_evaluation()
        )

        if result is not None:

            if not self.technical_context_added:

                self.append_technical_context(
                    result
                )

            final_result = (
                getattr(
                    self,
                    "global_result",
                    result,
                )
                if self.multi_hop_requested
                else self.last_evaluate_result
            )

        else:

            final_result = None

        # --------------------------------------------------------
        # MAPA MULTI-HOP
        # --------------------------------------------------------

        if self.multi_hop_requested:

            if (
                getattr(
                    self,
                    "multi_hop_executed",
                    False,
                )
                and getattr(
                    self,
                    "hops",
                    None,
                )
            ):

                try:

                    from map_utils import (
                        mostrar_mapa_multihop,
                        gerar_imagem_mapa_multihop,
                    )

                    self.map = (
                        mostrar_mapa_multihop(
                            self.hops
                        )
                    )

                    if self.map_callback:

                        self.map_callback(
                            self.map
                        )

                    self.map_image_bytes = (
                        gerar_imagem_mapa_multihop(
                            self.hops
                        )
                    )

                    self.log_detail(
                        "Mapa multi-hop preparado "
                        f"com {len(self.hops)} hops."
                    )

                except Exception as exc:

                    self.log_detail(
                        f"⚠️ Erro no mapa multi-hop: {exc}"
                    )

        # --------------------------------------------------------
        # MAPA ENLACE ÚNICO
        # --------------------------------------------------------

        elif len(
            self.geocoded_points
        ) >= 2:

            await self.mostrar_mapa_apos_geocodificacao()

        # --------------------------------------------------------
        # ANÁLISE FINAL
        # --------------------------------------------------------

        if final_result is not None:

            answer = (
                await self.generate_final_response(
                    text,
                    final_result,
                    technical_report=None,
                )
            )

            # ----------------------------------------------------
            # PDF
            # ----------------------------------------------------

            self.technical_report = answer

            self.build_report(
                final_result,
                analysis_text=answer,
            )

        else:

            answer = self.last_agent_text

        return answer

    # ============================================================
    # DETECÇÃO MULTI-HOP
    # ============================================================

    def detect_multi_hop_request(
        self,
        text,
    ):
        """
        Detecta se a solicitação aparenta descrever uma rota
        com três ou mais pontos.

        A identificação das localidades continua sendo
        responsabilidade do LLM através de geocode_place.
        """

        if not text:
            return False

        normalized = (
            str(text)
            .strip()
            .lower()
        )

        explicit_patterns = [
            r"\bmulti[\s-]?hop\b",
            r"\bmulti[\s-]?enlace\b",
            r"\bmulti[\s-]?link\b",
            r"\bpor\s+.+\s+passando\s+por\b",
            r"\bpassando\s+por\b",
            r"\batrav[eé]s\s+de\b",
            r"\bvia\b",
            r"\brota\b",
            r"\btrajeto\b",
            r"\bsequ[eê]ncia\s+de\s+enlaces\b",
            r"\bv[aá]rios\s+enlaces\b",
            r"\bv[aá]rios\s+saltos\b",
            r"\bsaltos\b",
            r"\bhops?\b",
        ]

        for pattern in explicit_patterns:

            if re.search(
                pattern,
                normalized,
            ):

                return True

        arrow_count = len(
            re.findall(
                r"(?:->|→|⇒|⟶)",
                normalized,
            )
        )

        if arrow_count >= 2:
            return True

        multi_point_patterns = [
            r"\bentre\s+.+,\s*.+\s+e\s+.+",
            r"\bentre\s+.+,\s*.+,\s*.+",
            r"\bde\s+.+\s+até\s+.+\s+passando\s+por\s+.+",
            r"\banalise\s+.+,\s*.+\s+e\s+.+",
            r"\banalisar\s+.+,\s*.+\s+e\s+.+",
            r"\bavalie\s+.+,\s*.+\s+e\s+.+",
            r"\bavaliar\s+.+,\s*.+\s+e\s+.+",
            r"\bfa[cç]a\s+(?:uma\s+)?an[aá]lise\b.+,\s*.+\s+e\s+.+",
            r"\ban[aá]lise\s+(?:dos\s+enlaces\s+)?entre\s+.+,\s*.+\s+e\s+.+",
            r"\banalis[ea]\s+.+\bentre\s+.+,\s*.+\s+e\s+.+",
            r"\bavalie\s+.+\bentre\s+.+,\s*.+\s+e\s+.+",
        ]

        for pattern in multi_point_patterns:

            if re.search(
                pattern,
                normalized,
            ):

                return True

        comma_count = normalized.count(",")

        route_context = re.search(
            r"\b("
            r"analise|analisar|análise|"
            r"avalie|avaliar|enlace|enlaces|"
            r"link|links|rota|trajeto|"
            r"pontos?|localidades?"
            r")\b",
            normalized,
        )

        if (
            comma_count >= 2
            and re.search(
                r"\be\b",
                normalized,
            )
            and route_context
        ):

            return True

        return False

    # ============================================================
    # AVALIAÇÃO DA APLICAÇÃO
    # ============================================================

    async def ensure_application_evaluation(
        self,
    ):
        """
        Decide qual orquestrador deve ser utilizado.

        2 pontos:
            ensure_evaluate_link()

        3+ pontos:
            ensure_multi_hop_evaluation()

        evaluate_link continua sendo um enlace individual.
        """

        point_count = len(
            self.geocoded_points
        )

        # --------------------------------------------------------
        # PROTEÇÃO MULTI-HOP
        # --------------------------------------------------------

        if (
            point_count >= 3
            and not self.multi_hop_requested
        ):

            self.multi_hop_requested = True

            self.log_detail(
                "🔗 Três ou mais pontos geocodificados; "
                "solicitação promovida automaticamente "
                "para multi-hop."
            )

        # --------------------------------------------------------
        # MULTI-HOP
        # --------------------------------------------------------

        if self.multi_hop_requested:

            if point_count < 3:

                self.log_detail(
                    "⏳ Solicitação multi-hop detectada. "
                    f"Aguardando pontos adicionais "
                    f"(atualmente {point_count})."
                )

                return None

            if getattr(
                self,
                "multi_hop_executed",
                False,
            ):

                return self.global_result

            return await (
                self.ensure_multi_hop_evaluation(
                    route_points=self.geocoded_points,
                    parameters=self.link_parameters,
                )
            )

        # --------------------------------------------------------
        # ENLACE ÚNICO
        # --------------------------------------------------------

        if point_count >= 2:

            if self.evaluate_executed:

                return self.last_evaluate_result

            return await (
                self.ensure_evaluate_link()
            )

        return None

    # ============================================================
    # HOP ATUAL
    # ============================================================

    def _get_current_hop_info(
        self,
    ):
        """
        Retorna informações do hop atualmente em processamento.
        """

        if not self.multi_hop_requested:

            return {
                "key": "single",
                "index": None,
                "name": None,
            }

        current_hop = getattr(
            self,
            "current_hop",
            None,
        )

        if isinstance(
            current_hop,
            dict,
        ):

            index = current_hop.get(
                "index"
            )

            hop_id = current_hop.get(
                "id"
            )

            name = current_hop.get(
                "name"
            )

            if index is not None:

                key = (
                    f"hop_{index}"
                )

            elif hop_id:

                key = str(
                    hop_id
                )

            else:

                key = (
                    f"hop_{id(current_hop)}"
                )

            return {
                "key": key,
                "index": index,
                "name": name,
            }

        return None

    # ============================================================
    # CLOSE
    # ============================================================

    async def close(
        self,
    ):

        await super().close()