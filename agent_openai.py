# ============================================================
# PLANAPP AI — OPENAI
#
# ETAPA 1 — REFATORAÇÃO
#
# Jupyter
#    |
#    v
# OpenAI Responses API / GPT-5.6 Luna
#    |
#    v
# geocode_place
#    |
#    v
# aplicação -> evaluate_link
#    |
#    +--> mapa interativo
#    +--> visualizações
#    |
#    +--> relatório técnico / PDF
#    |
#    v
# análise técnica final
#
# NÃO implementa multi-hop.
# ============================================================

import asyncio
import base64
import json
import os

from openai import AsyncOpenAI

import ipywidgets as widgets

from agent_common import (
    PlanAppAgentCommon,
    MCP_URL,
    USER_ID,
    DEFAULT_FREQ_MHZ,
    DEFAULT_TX_HA,
    DEFAULT_RX_HA,
    DEFAULT_ON_ROOFTOP,
    APPLICATION_CONTROLLED_TOOLS,
)

from report_generator import ReportGenerator


OPENAI_MODEL = os.getenv(
    "OPENAI_MODEL",
    "gpt-5.6-luna",
)

OPENAI_REASONING_EFFORT = os.getenv(
    "OPENAI_REASONING_EFFORT",
    "medium",
)

OPENAI_API_KEY = os.getenv(
    "OPENAI_API_KEY"
)

MAX_AGENT_ITERATIONS = 8


INPUT_PRICE_PER_MILLION = 0.20
CACHED_INPUT_PRICE_PER_MILLION = 0.02
OUTPUT_PRICE_PER_MILLION = 1.20


class PlanAppAgent(PlanAppAgentCommon):

    AGENT_NAME = "PLANAPP AI — OPENAI"

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

        self.client = None

        self.registered = False

        self.technical_context_added = False

        self.last_agent_text = ""

        self.last_response_id = None

        self.technical_report = ""

        # SOLICITAÇÃO ORIGINAL DO USUÁRIO
        self.user_request = ""

        self.report_pdf_path = None

        # MAPA
        self.map = None
        self.map_image_bytes = None

        # VISUALIZAÇÕES
        self.visualizations = []
        self.visualization_images = []

        # USAGE / CUSTOS
        self.input_tokens = 0
        self.cached_input_tokens = 0
        self.output_tokens = 0

        self.input_cost = 0.0
        self.cached_input_cost = 0.0
        self.output_cost = 0.0
        self.total_cost = 0.0

    # ========================================================================
    # SYSTEM PROMPT
    # ========================================================================

    def system_prompt(self):
        return """
Você é o PlanApp AI, assistente técnico do PlanApp.

O PlanApp é a fonte oficial dos resultados técnicos.

REGRAS:

1. Nunca invente valores.
2. Nunca invente unidades.
3. Nunca altere resultados retornados pelo PlanApp.
4. Não recalcule valores técnicos quando o PlanApp já os forneceu.
5. Quando o usuário fornecer duas localidades, utilize geocode_place para obter suas coordenadas.
6. Depois de obtidos os dois pontos, a aplicação executará automaticamente evaluate_link.
7. NÃO execute evaluate_link diretamente.
8. evaluate_link é controlado pela aplicação.
9. Mapa e visualizações também são controlados pela aplicação.
10. Não peça ao usuário para executar ferramentas.
11. Preserve frequência, TX, RX e rooftop solicitados.
12. Frequências podem ser informadas em GHz, MHz, kHz ou Hz.
13. Padrões:
       900 MHz
       TX 7 m
       RX 7 m
       rooftop=false
14. FSPL significa perda de percurso em espaço livre.
15. FSPL não significa interferência.
16. Não conclua viabilidade do enlace sem um critério técnico explícito.
17. Não invente potência TX.
18. Não invente ganho de antena.
19. Não invente sensibilidade do receptor.
20. Não invente margem de enlace.
21. Não atribua significado físico a campos cuja definição não esteja explicitamente documentada pelo PlanApp.
22. Não atribua significado próprio a core, fresnel, boundary, delta_diffra, VV, v_v ou d_norm.
23. Não converta radianos para graus.
24. status OK significa somente que a execução foi realizada com sucesso.
25. O resultado fornecido pela aplicação é a fonte de verdade.
26. O relatório técnico fornecido pela aplicação é apenas uma apresentação estruturada dos dados reais do PlanApp.
27. Não altere, recalcule ou contradiga os valores presentes no relatório técnico.
28. Diferencie claramente parâmetros solicitados pelo usuário de parâmetros efetivamente enviados ao PlanApp.
29. Se um campo técnico não tiver definição explícita, apresente o valor somente como resultado retornado pelo PlanApp, sem atribuir significado adicional.

30. A resposta técnica NÃO deve ser apenas uma reprodução do JSON.
31. Organize os resultados em seções claras.
32. Faça uma síntese objetiva dos resultados efetivamente retornados.
33. Pode comparar numericamente valores que já foram retornados pelo PlanApp.
34. Pode destacar diferenças entre parâmetros solicitados e parâmetros efetivamente utilizados.
35. Pode destacar distância, FSPL, delta_diffra, resultados de terreno, vegetação, edificações e resultados geométricos quando esses valores estiverem presentes.
36. Ao apresentar conjuntos como terreno, vegetação ou edificações, deixe claro que são resultados retornados pelo PlanApp.
37. Não atribua interpretação física adicional aos nomes dos campos quando sua definição não estiver documentada.
38. Informe quais etapas foram efetivamente executadas quando essa informação estiver disponível.
39. Diferencie claramente:
       - dados fornecidos pelo usuário;
       - parâmetros efetivamente utilizados;
       - resultados retornados pelo PlanApp;
       - limitações da interpretação.
40. Não declare o enlace como viável ou inviável sem um critério técnico explícito.
41. Não invente uma margem, limiar, classificação ou conclusão de engenharia que não esteja presente nos dados.
42. A resposta final deve ser em português do Brasil.
43. Seja técnico, claro, objetivo e informativo.
44. Prefira uma análise estruturada a uma simples listagem de campos.
"""

    # ========================================================================
    # OPENAI
    # ========================================================================

    async def connect_openai(self):

        if not OPENAI_API_KEY:
            raise RuntimeError(
                "OPENAI_API_KEY não encontrada."
            )

        self.client = AsyncOpenAI(
            api_key=OPENAI_API_KEY
        )

    def build_openai_tools(self):

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
                }
            )

        return tools

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

        cached_tokens = 0

        details = getattr(
            usage,
            "input_tokens_details",
            None,
        )

        if details:

            cached_tokens = getattr(
                details,
                "cached_tokens",
                0,
            ) or 0

        self.input_tokens += (
            input_tokens
        )

        self.output_tokens += (
            output_tokens
        )

        self.cached_input_tokens += (
            cached_tokens
        )

        normal_input_tokens = max(
            input_tokens
            - cached_tokens,
            0,
        )

        self.input_cost += (
            normal_input_tokens
            / 1_000_000
            * INPUT_PRICE_PER_MILLION
        )

        self.cached_input_cost += (
            cached_tokens
            / 1_000_000
            * CACHED_INPUT_PRICE_PER_MILLION
        )

        self.output_cost += (
            output_tokens
            / 1_000_000
            * OUTPUT_PRICE_PER_MILLION
        )

        self.total_cost = (
            self.input_cost
            + self.cached_input_cost
            + self.output_cost
        )

        self.log_detail(
            "OpenAI usage: "
            f"input={input_tokens}, "
            f"cached={cached_tokens}, "
            f"output={output_tokens}, "
            f"cost=${self.total_cost:.6f}"
        )

    async def openai_chat(
        self,
        input_data,
        tools=None,
        previous_response_id=None,
    ):

        if self.client is None:
            await self.connect_openai()

        kwargs = {
            "model": OPENAI_MODEL,
            "input": input_data,
            "reasoning": {
                "effort": OPENAI_REASONING_EFFORT
            },
        }

        if tools:
            kwargs["tools"] = tools

        if previous_response_id:

            kwargs[
                "previous_response_id"
            ] = previous_response_id

        response = await self.client.responses.create(
            **kwargs
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

        parts = []

        output = getattr(
            response,
            "output",
            None,
        ) or []

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
            ) or []

            for block in content:

                block_text = getattr(
                    block,
                    "text",
                    None,
                )

                if block_text:
                    parts.append(
                        block_text
                    )

        return "\n".join(
            parts
        ).strip()

    def response_tool_calls(
        self,
        response,
    ):

        calls = []

        output = getattr(
            response,
            "output",
            None,
        ) or []

        for item in output:

            item_type = getattr(
                item,
                "type",
                None,
            )

            if item_type != "function_call":
                continue

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

            call_id = getattr(
                item,
                "call_id",
                None,
            )

            calls.append(
                {
                    "name": name,
                    "arguments": arguments,
                    "call_id": call_id,
                }
            )

        return calls

    # ========================================================================
    # CONTEXTO TÉCNICO
    # ========================================================================

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

    # ========================================================================
    # MAPA
    # ========================================================================

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
                "Imagem estática do mapa OSM "
                "preparada para o relatório."
            )

        except Exception as exc:

            self.log_detail(
                f"⚠️ Erro no mapa: {exc}"
            )

    # ========================================================================
    # VISUALIZAÇÕES
    # ========================================================================

    async def gerar_visualizacoes(
        self,
    ):

        if not self.evaluate_executed:
            return

        if self.evaluate_error:
            return

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

        self.visualizations = []

        self.visualization_images = []

        for (
            tool_name,
            arguments,
            title,
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
                        f"⚠️ {title}: resultado não é um objeto."
                    )
                    continue

                if parsed.get(
                    "kind"
                ) != "image":

                    self.log_detail(
                        f"⚠️ {title}: resultado não contém imagem."
                    )
                    continue

                data = parsed.get(
                    "data"
                )

                if not data:
                    self.log_detail(
                        f"⚠️ {title}: imagem sem dados."
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

                # IMPORTANTE:
                # O callback recebe UMA imagem e o título.
                # O notebook_ui.py adiciona essa imagem
                # incrementalmente ao VBox.
                if self.visualization_callback:

                    self.visualization_callback(
                        image,
                        title,
                    )

                self.log_detail(
                    f"Visualização preparada: {title}"
                )

            except Exception as exc:

                self.log_detail(
                    f"⚠️ Visualização "
                    f"{title}: {exc}"
                )

        self.log_detail(
            "Total de visualizações "
            f"preparadas: "
            f"{len(self.visualization_images)}"
        )

    # ========================================================================
    # RELATÓRIO
    # ========================================================================

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

        # --------------------------------------------------------------------
        # GARANTIR IMAGEM DO MAPA
        # --------------------------------------------------------------------

        if (
            self.map_image_bytes is None
            and len(
                self.geocoded_points
            ) >= 2
        ):

            try:

                from map_utils import (
                    gerar_imagem_mapa_enlace
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

        # --------------------------------------------------------------------
        # GERADOR
        # --------------------------------------------------------------------

        # Quando a análise final já foi produzida, ela passa a ser o
        # conteúdo oficial do relatório. Se não for fornecida, preservamos
        # o comportamento anterior e o ReportGenerator usa o relatório
        # estruturado de dados como fallback.
        if analysis_text is None:
            analysis_text = self.technical_report or None

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

        # --------------------------------------------------------------------
        # PDF
        # --------------------------------------------------------------------

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

    # ========================================================================
    # AGENT TURN
    # ========================================================================

    async def agent_turn(
        self,
    ):

        response = await self.openai_chat(
            self.messages,
            self.build_openai_tools(),
            previous_response_id=None,
        )

        for iteration in range(
            MAX_AGENT_ITERATIONS
        ):

            tool_calls = (
                self.response_tool_calls(
                    response
                )
            )

            text = self.response_text(
                response
            )

            if text:
                self.last_agent_text = text

            if not tool_calls:

                if (
                    len(
                        self.geocoded_points
                    ) >= 2
                    and not self.evaluate_executed
                ):

                    result = (
                        await self.ensure_evaluate_link()
                    )

                    if result is not None:

                        self.append_technical_context(
                            result
                        )

                        response = (
                            await self.openai_chat(
                                self.messages,
                                self.build_openai_tools(),
                                previous_response_id=None,
                            )
                        )

                        continue

                return text

            tool_outputs = []

            for call in tool_calls:

                name = call["name"]

                call_id = call[
                    "call_id"
                ]

                if not call_id:

                    self.log_detail(
                        f"⚠️ Tool call {name} "
                        "não possui call_id."
                    )

                    continue

                if name in APPLICATION_CONTROLLED_TOOLS:

                    self.log_detail(
                        f"⚠️ Ferramenta {name} "
                        "é controlada pela aplicação."
                    )

                    continue

                try:

                    arguments = json.loads(
                        call["arguments"]
                        or "{}"
                    )

                except Exception as exc:

                    self.log_detail(
                        f"⚠️ Argumentos inválidos "
                        f"para {name}: {exc}"
                    )

                    arguments = {}

                self.log_detail(
                    f"Executando ferramenta MCP: "
                    f"{name}"
                )

                result = (
                    await self.execute_mcp_tool(
                        name,
                        arguments,
                    )
                )

                tool_outputs.append(
                    {
                        "type":
                            "function_call_output",
                        "call_id":
                            call_id,
                        "output":
                            json.dumps(
                                result,
                                ensure_ascii=False,
                                default=str,
                            ),
                    }
                )

            if tool_outputs:

                response_id = getattr(
                    response,
                    "id",
                    None,
                )

                if not response_id:

                    raise RuntimeError(
                        "A resposta da OpenAI "
                        "contendo function_call "
                        "não possui response.id."
                    )

                response = (
                    await self.openai_chat(
                        tool_outputs,
                        self.build_openai_tools(),
                        previous_response_id=response_id,
                    )
                )

                if (
                    len(
                        self.geocoded_points
                    ) >= 2
                    and not self.evaluate_executed
                ):

                    result = (
                        await self.ensure_evaluate_link()
                    )

                    if result is not None:

                        self.append_technical_context(
                            result
                        )

                        response = (
                            await self.openai_chat(
                                self.messages,
                                self.build_openai_tools(),
                                previous_response_id=None,
                            )
                        )

                continue

            if (
                len(
                    self.geocoded_points
                ) >= 2
                and not self.evaluate_executed
            ):

                result = (
                    await self.ensure_evaluate_link()
                )

                if result is not None:

                    self.append_technical_context(
                        result
                    )

                    response = (
                        await self.openai_chat(
                            self.messages,
                            self.build_openai_tools(),
                            previous_response_id=None,
                        )
                    )

                    continue

            return text

        return (
            "Não foi possível concluir "
            "o processamento dentro do "
            "limite de iterações."
        )

    # ========================================================================
    # RESPOSTA FINAL
    # ========================================================================

    async def generate_final_response(
        self,
        original_text,
        technical_result,
        technical_report=None,
    ):

        context = (
            self.build_technical_context(
                technical_result
            )
        )

        if technical_report is None:
            technical_report = ""

        input_data = [
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
                "content": json.dumps(
                    context,
                    ensure_ascii=False,
                    default=str,
                ),
            },
        ]

        if technical_report:

            input_data.append(
                {
                    "role": "user",
                    "content": (
                        "RELATÓRIO TÉCNICO "
                        "GERADO PELA APLICAÇÃO:\n\n"
                        + technical_report
                    ),
                }
            )

        input_data.append(
            {
                "role": "user",
                "content": """
Produza a análise técnica final em português do Brasil.

Use exclusivamente os dados retornados pelo PlanApp e, quando disponível, o relatório técnico gerado pela aplicação.

A resposta deve ser organizada e informativa, e não apenas uma reprodução do JSON.

Use Markdown simples para a formatação:
- títulos de seção com `##`;
- subtítulos com `###`;
- listas com `-`;
- destaque pontual com `**negrito**`.

Quando houver dados suficientes, estruture a resposta com as seguintes seções:

## 1. IDENTIFICAÇÃO DO ENLACE
- localidades TX e RX;
- coordenadas;
- distância, se retornada.

## 2. PARÂMETROS
- frequência solicitada;
- altura TX solicitada;
- altura RX solicitada;
- rooftop solicitado;
- parâmetros efetivamente utilizados pelo PlanApp.

## 3. RESULTADOS PRINCIPAIS
- FSPL;
- delta_diffra;
- outros resultados principais efetivamente retornados.

## 4. RESULTADOS DOS DADOS GEOESPACIAIS
- terreno;
- vegetação/COVER;
- edificações;
- outros conjuntos retornados.

## 5. RESULTADOS GEOMÉTRICOS
- apresente os valores retornados pelo PlanApp;
- não atribua significado físico a campos cuja definição não esteja explicitamente documentada.

## 6. EXECUÇÃO
- indique objetivamente quais etapas foram executadas quando essa informação estiver disponível.

## 7. OBSERVAÇÕES E LIMITAÇÕES
- diferencie dados efetivamente calculados pelo PlanApp de interpretações que exigiriam critérios técnicos adicionais.

IMPORTANTE:

- Não invente valores.
- Não altere valores.
- Não altere unidades.
- Não faça cálculos técnicos adicionais.
- Não transforme radianos em graus.
- Não invente potência, ganho, sensibilidade, margem ou limiares.
- Não atribua significado próprio a core, fresnel, boundary, delta_diffra, VV, v_v ou d_norm.
- Não declare o enlace como viável ou inviável sem um critério técnico explícito.
- Não diga que um enlace está "bom", "ruim", "aprovado" ou "reprovado" sem um critério documentado.
- Quando um valor não tiver definição explícita, apresente-o simplesmente como resultado retornado pelo PlanApp.
- Faça uma síntese técnica clara dos dados disponíveis.
""",
            }
        )

        response = await self.openai_chat(
            input_data,
            tools=None,
            previous_response_id=None,
        )

        return self.response_text(
            response
        )

    # ========================================================================
    # ASK
    # ========================================================================

    async def ask(
        self,
        text,
    ):

        if not OPENAI_API_KEY:

            raise RuntimeError(
                "OPENAI_API_KEY não encontrada."
            )

        self.reset_common_state()

        self.registered = False

        self.technical_context_added = False

        self.last_agent_text = ""

        self.last_response_id = None

        self.technical_report = ""

        self.report_pdf_path = None

        # IMPORTANTE:
        # guardar exatamente a solicitação recebida
        # para utilização posterior no relatório.
        self.user_request = text

        self.map = None

        self.map_image_bytes = None

        self.visualizations = []

        self.visualization_images = []

        self.input_tokens = 0

        self.cached_input_tokens = 0

        self.output_tokens = 0

        self.input_cost = 0.0

        self.cached_input_cost = 0.0

        self.output_cost = 0.0

        self.total_cost = 0.0

        self.extract_link_parameters(
            text
        )

        await self.connect_openai()

        await self.connect()

        await self.register()

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

        await self.agent_turn()

        if (
            len(
                self.geocoded_points
            ) >= 2
            and not self.evaluate_executed
        ):

            result = (
                await self.ensure_evaluate_link()
            )

            if result is not None:

                self.append_technical_context(
                    result
                )

        if len(
            self.geocoded_points
        ) >= 2:

            await self.mostrar_mapa_apos_geocodificacao()

        if (
            self.evaluate_executed
            and not self.evaluate_error
        ):

            await self.gerar_visualizacoes()

        if self.evaluate_executed:

            answer = (
                await self.generate_final_response(
                    text,
                    self.last_evaluate_result,
                    technical_report=None,
                )
            )

            # O texto final produzido pelo OpenAI é o texto oficial do
            # relatório. O PDF é gerado somente depois da análise final,
            # preservando mapa e visualizações já preparados.
            self.technical_report = answer

            self.build_report(
                self.last_evaluate_result,
                analysis_text=answer,
            )

        else:

            answer = self.last_agent_text

        return answer

    # ========================================================================
    # CLOSE
    # ========================================================================

    async def close(
        self,
    ):

        await super().close()

        self.client = None