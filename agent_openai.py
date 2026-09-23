# ============================================================
# PLANAPP AI — OPENAI
#
# ETAPA 2 — MULTI-HOP
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
# aplicação
#    |
#    +--> enlace único:
#    |       evaluate_link
#    |
#    +--> multi-hop:
#            ensure_multi_hop_evaluation
#                 |
#                 +--> evaluate_link A -> B
#                 +--> evaluate_link B -> C
#                 +--> evaluate_link C -> D
#    |
#    +--> mapa interativo
#    +--> visualizações por hop
#    +--> relatório técnico / PDF
#    |
#    v
# análise técnica final
#
# IMPORTANTE:
#
# evaluate_link continua sendo uma operação de UM único enlace.
#
# O multi-hop é orquestrado pela aplicação através de
# ensure_multi_hop_evaluation(), implementada em agent_common.py.
#
# As visualizações são geradas uma única vez para cada hop.
# O mapa, por sua vez, representa toda a rota multi-hop.
# ============================================================

import asyncio
import base64
import json
import os
import re

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

        # ================================================================
        # SOLICITAÇÃO ORIGINAL DO USUÁRIO
        # ================================================================

        self.user_request = ""

        self.report_pdf_path = None

        # ================================================================
        # ETAPA 2 — CONTROLE DO TIPO DE ANÁLISE
        # ================================================================

        self.multi_hop_requested = False

        # ================================================================
        # CONTROLE DO ESTADO DE GEOCODIFICAÇÃO
        #
        # IMPORTANTE:
        #
        # A aplicação não deve executar evaluate_link apenas porque
        # apareceram dois pontos.
        #
        # Primeiro deixamos o GPT continuar o processo de geocodificação.
        #
        # Quando existirem 3 ou mais pontos, a aplicação promove
        # automaticamente a solicitação para multi-hop.
        # ================================================================

        self.geocoding_followup_sent = False

        # ================================================================
        # MAPA
        # ================================================================

        self.map = None

        self.map_image_bytes = None

        # ================================================================
        # VISUALIZAÇÕES
        # ================================================================

        self.visualizations = []

        self.visualization_images = []

        self.visualizations_generated_hops = set()

        # ================================================================
        # USAGE / CUSTOS
        # ================================================================

        self.input_tokens = 0

        self.cached_input_tokens = 0

        self.output_tokens = 0

        self.input_cost = 0.0

        self.cached_input_cost = 0.0

        self.output_cost = 0.0

        self.total_cost = 0.0

    # ========================================================================
    # ETAPA 2 — DETECÇÃO DE SOLICITAÇÃO MULTI-HOP
    # ========================================================================

    def detect_multi_hop_request(
        self,
        text,
    ):
        """
        Detecta se a solicitação do usuário aparenta descrever
        uma rota com três ou mais pontos.

        Esta função NÃO identifica as localidades.

        A identificação das localidades continua sendo responsabilidade
        do LLM através de geocode_place.

        O objetivo aqui é somente impedir que o fluxo da ETAPA 1
        execute A -> B antes de o agente terminar de obter os demais
        pontos da rota.
        """

        if not text:
            return False

        normalized = (
            str(text)
            .strip()
            .lower()
        )

        # ------------------------------------------------------------
        # Indicadores explícitos de multi-hop
        # ------------------------------------------------------------

        explicit_patterns = [
            r"\bmulti[\s-]?hop\b",
            r"\bmulti[\s-]?enlace\b",
            r"\bmulti[\s-]?link\b",
            r"\bpor\s+.+\s+passando\s+por\b",
            r"\bpassando\s+por\b",
            r"\batrav[eé]s\s+de\b",
            r"\bvia\b",
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

        # ------------------------------------------------------------
        # Notação explícita:
        #
        # A -> B -> C
        # A → B → C
        # ------------------------------------------------------------

        arrow_count = len(
            re.findall(
                r"(?:->|→|⇒|⟶)",
                normalized,
            )
        )

        if arrow_count >= 2:
            return True

        # ------------------------------------------------------------
        # Listas com três ou mais localidades
        # ------------------------------------------------------------

        multi_point_patterns = [

            r"\bentre\s+.+,\s*.+\s+e\s+.+",

            r"\bentre\s+.+,\s*.+,\s*.+",

            r"\bde\s+.+\s+até\s+.+\s+passando\s+por\s+.+",

            r"\banalise\s+.+,\s*.+\s+e\s+.+",

            r"\banalisar\s+.+,\s*.+\s+e\s+.+",

            r"\bavalie\s+.+,\s*.+\s+e\s+.+",

            r"\bavaliar\s+.+,\s*.+\s+e\s+.+",

            # Exemplos adicionais:
            #
            # "faça uma análise entre A, B e C"
            # "faca uma analise entre A, B e C"
            # "faça uma análise de A, B e C"
            # "analise os enlaces entre A, B e C"
            #

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

        # ------------------------------------------------------------
        # Indicador adicional:
        #
        # uma solicitação contendo duas vírgulas ou mais junto com
        # uma conjunção "e" normalmente representa uma sequência
        # de três elementos.
        #
        # Não usamos isso isoladamente: exigimos também um verbo/
        # contexto de análise ou de rota.
        # ------------------------------------------------------------

        comma_count = normalized.count(",")

        route_context = re.search(
            r"\b("
            r"analise|analisar|análise|analise|"
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

    # ========================================================================
    # ETAPA 2 — DECISÃO DO TIPO DE AVALIAÇÃO
    # ========================================================================

    async def ensure_application_evaluation(
        self,
    ):
        """
        Decide qual orquestrador deve ser utilizado.

        2 pontos:
            ensure_evaluate_link()

        3+ pontos:
            ensure_multi_hop_evaluation()

        A função nunca transforma evaluate_link em super-tool.

        IMPORTANTE:
        Se 3 ou mais pontos já foram geocodificados, a aplicação
        promove automaticamente a solicitação para multi-hop.

        Isso funciona como uma proteção adicional caso a detecção
        textual inicial não tenha identificado corretamente a intenção.
        """

        point_count = len(
            self.geocoded_points
        )

        # ------------------------------------------------------------
        # PROTEÇÃO MULTI-HOP
        #
        # Se a aplicação já possui 3 ou mais pontos, não existe
        # justificativa para executar somente o primeiro enlace.
        #
        # A rota é formada pelos pontos consecutivos:
        #
        # A -> B
        # B -> C
        # C -> D
        #
        # etc.
        # ------------------------------------------------------------

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

        # ------------------------------------------------------------
        # MULTI-HOP
        # ------------------------------------------------------------

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

        # ------------------------------------------------------------
        # ETAPA 1 — ENLACE ÚNICO
        # ------------------------------------------------------------

        if point_count >= 2:

            if self.evaluate_executed:

                return self.last_evaluate_result

            return await (
                self.ensure_evaluate_link()
            )

        return None

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

5. Quando o usuário fornecer duas localidades, utilize geocode_place para obter as coordenadas das duas localidades.

6. Quando o usuário fornecer uma rota com três ou mais localidades, utilize geocode_place para obter as coordenadas de TODAS as localidades da rota, na ordem informada pelo usuário.

7. Em uma rota multi-hop, preserve rigorosamente a ordem dos pontos fornecida pelo usuário.

8. Exemplos de rota multi-hop:

       A -> B -> C

   deve representar:

       Hop 1: A -> B
       Hop 2: B -> C

9. Outro exemplo:

       A -> B -> C -> D

   deve representar:

       Hop 1: A -> B
       Hop 2: B -> C
       Hop 3: C -> D

10. Não pare a geocodificação depois dos dois primeiros pontos quando o usuário tiver solicitado uma rota com três ou mais pontos.

11. Antes de qualquer avaliação técnica, certifique-se de que todas as localidades necessárias para a solicitação tenham sido geocodificadas.

12. NÃO execute evaluate_link diretamente.

13. evaluate_link é controlado pela aplicação.

14. Em uma análise multi-hop, evaluate_link continua representando apenas UM enlace.

15. A aplicação é responsável por executar os enlaces consecutivos da rota.

16. Não peça ao usuário para executar ferramentas.

17. Preserve frequência, TX, RX e rooftop solicitados.

18. Frequências podem ser informadas em GHz, MHz, kHz ou Hz.

19. Padrões:
       900 MHz
       TX 7 m
       RX 7 m
       rooftop=false

20. FSPL significa perda de percurso em espaço livre.

21. FSPL não significa interferência.

22. Não conclua viabilidade do enlace sem um critério técnico explícito.

23. Não invente potência TX.

24. Não invente ganho de antena.

25. Não invente sensibilidade do receptor.

26. Não invente margem de enlace.

27. Não atribua significado físico a campos cuja definição não esteja explicitamente documentada pelo PlanApp.

28. Não atribua significado próprio a core, fresnel, boundary, delta_diffra, VV, v_v ou d_norm.

29. Não converta radianos para graus.

30. status OK significa somente que a execução foi realizada com sucesso.

31. O resultado fornecido pela aplicação é a fonte de verdade.

32. O relatório técnico fornecido pela aplicação é apenas uma apresentação estruturada dos dados reais do PlanApp.

33. Não altere, recalcule ou contradiga os valores presentes no relatório técnico.

34. Diferencie claramente parâmetros solicitados pelo usuário de parâmetros efetivamente enviados ao PlanApp.

35. Se um campo técnico não tiver definição explícita, apresente o valor somente como resultado retornado pelo PlanApp, sem atribuir significado adicional.

36. A resposta técnica NÃO deve ser apenas uma reprodução do JSON.

37. Organize os resultados em seções claras.

38. Faça uma síntese objetiva dos resultados efetivamente retornados.

39. Pode comparar numericamente valores que já foram retornados pelo PlanApp.

40. Pode destacar diferenças entre parâmetros solicitados e parâmetros efetivamente utilizados.

41. Pode destacar distância, FSPL, delta_diffra, resultados de terreno, vegetação, edificações e resultados geométricos quando esses valores estiverem presentes.

42. Ao apresentar conjuntos como terreno, vegetação ou edificações, deixe claro que são resultados retornados pelo PlanApp.

43. Não atribua interpretação física adicional aos nomes dos campos quando sua definição não estiver documentada.

44. Informe quais etapas foram efetivamente executadas quando essa informação estiver disponível.

45. Diferencie claramente:
       - dados fornecidos pelo usuário;
       - parâmetros efetivamente utilizados;
       - resultados retornados pelo PlanApp;
       - limitações da interpretação.

46. Não declare o enlace como viável ou inviável sem um critério técnico explícito.

47. Não invente uma margem, limiar, classificação ou conclusão de engenharia que não esteja presente nos dados.

48. Em análises multi-hop, apresente os resultados de cada hop separadamente quando esses resultados estiverem disponíveis.

49. Em análises multi-hop, deixe explícita a sequência dos enlaces:
       Hop 1
       Hop 2
       Hop 3
       etc.

50. Não combine resultados de hops diferentes em um único valor técnico que não tenha sido fornecido pelo PlanApp.

51. Não calcule uma conclusão global de viabilidade da rota sem um critério técnico explícito fornecido pelo PlanApp ou pelo usuário.

52. Mapa e visualizações são controlados pela aplicação.

53. A aplicação é responsável pela execução técnica dos enlaces.

54. A resposta final deve ser em português do Brasil.

55. Seja técnico, claro, objetivo e informativo.

56. Prefira uma análise estruturada a uma simples listagem de campos.
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
                    tx_lat,tx_lon,
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
    # AUXILIAR — IDENTIFICAÇÃO DO HOP ATUAL
    # ========================================================================

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

    # ========================================================================
    # VISUALIZAÇÕES
    # ========================================================================

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

            # ================================================================
            # SEM TOOL CALLS
            # ================================================================

            if not tool_calls:

                result = (
                    await self.ensure_application_evaluation()
                )

                if result is not None:

                    self.append_technical_context(
                        result
                    )

                    # A avaliação técnica já foi executada pela aplicação.
                    # Não retornar ao GPT com geocode_place disponível:
                    # isso fazia o modelo repetir a geocodificação dos
                    # pontos já conhecidos e atrasava o mapa, o relatório
                    # e a análise final.
                    self.log_detail(
                        "🟢 Avaliação técnica concluída. "
                        "Encerrando agent_turn()."
                    )
                    return text

                # ------------------------------------------------------------
                # Se uma solicitação foi identificada como multi-hop mas
                # ainda temos menos de 3 pontos, não devemos simplesmente
                # encerrar o turno.
                #
                # Pedimos explicitamente ao GPT para continuar a
                # geocodificação da rota.
                # ------------------------------------------------------------

                if (
                    self.multi_hop_requested
                    and len(
                        self.geocoded_points
                    ) < 3
                ):

                    if not self.geocoding_followup_sent:

                        self.geocoding_followup_sent = True

                        followup = {
                            "role": "user",
                            "content": (
                                "A solicitação atual descreve "
                                "uma rota multi-hop. "
                                "Ainda existem menos de três "
                                "pontos geocodificados. "
                                "Continue identificando e "
                                "geocodificando, na ordem "
                                "solicitada pelo usuário, todas "
                                "as localidades restantes da rota "
                                "antes de concluir a resposta. "
                                "Não execute avaliação técnica."
                            ),
                        }

                        self.messages.append(
                            followup
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

            # ================================================================
            # EXECUÇÃO DAS FERRAMENTAS SOLICITADAS PELO GPT
            # ================================================================

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

            # ================================================================
            # DEVOLVER RESULTADO DAS TOOLS AO GPT
            #
            # CORREÇÃO PRINCIPAL DA ETAPA 2:
            #
            # NÃO chamar ensure_application_evaluation() imediatamente
            # depois de retornar os resultados das ferramentas.
            #
            # Antes:
            #
            #   geocode A
            #   geocode B
            #   evaluate A -> B
            #   geocode C
            #
            # Agora:
            #
            #   geocode A
            #   geocode B
            #   GPT continua
            #   geocode C
            #   3 pontos
            #   multi-hop
            #   evaluate A -> B
            #   evaluate B -> C
            #
            # ================================================================

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

                # ------------------------------------------------------------
                # NÃO executar avaliação aqui.
                #
                # Esta é a correção crítica.
                #
                # O próximo response da OpenAI terá a oportunidade
                # de solicitar outras geocodificações.
                # ------------------------------------------------------------

                continue

            # ================================================================
            # PROTEÇÃO PARA O CASO DE NÃO HAVER SAÍDA DE TOOL
            # ================================================================

            result = (
                await self.ensure_application_evaluation()
            )

            if result is not None:

                self.append_technical_context(
                    result
                )

                self.log_detail(
                    "🟢 Avaliação técnica concluída. "
                    "Encerrando agent_turn()."
                )
                return text

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
                            "Continue a geocodificação da "
                            "rota multi-hop solicitada. "
                            "Ainda não foram obtidas todas "
                            "as localidades necessárias. "
                            "Use geocode_place para obter "
                            "os pontos restantes na ordem "
                            "da solicitação original. "
                            "Não execute avaliação técnica."
                        ),
                    }
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
- destaque pontual com `**negrito**.

Para um enlace único, mantenha a estrutura tradicional:

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

Para uma rota multi-hop:

## 1. IDENTIFICAÇÃO DA ROTA
- apresente os pontos na ordem recebida;
- apresente a sequência dos hops.

## 2. PARÂMETROS
- parâmetros solicitados;
- parâmetros efetivamente utilizados.

## 3. RESULTADOS POR HOP

Para cada hop, apresente separadamente:
- TX;
- RX;
- distância;
- FSPL;
- delta_diffra;
- resultados geoespaciais disponíveis;
- resultados geométricos disponíveis;
- status.

Não misture os resultados técnicos de hops diferentes.

## 4. EXECUÇÃO DA ROTA
- quantidade total de hops;
- quantidade de hops concluídos;
- status global retornado pela aplicação.

## 5. OBSERVAÇÕES E LIMITAÇÕES
- destaque eventuais hops com erro;
- não declare viabilidade global da rota sem critério técnico explícito;
- não crie uma métrica global que não tenha sido retornada pelo PlanApp.

IMPORTANTE:

- Não invente valores.
- Não altere valores.
- Não altere unidades.
- Não faça cálculos técnicos adicionais.
- Não transforme radianos em graus.
- Não invente potência, ganho, sensibilidade, margem ou limiares.
- Não atribua significado próprio a core, fresnel, boundary, delta_diffra, VV, v_v ou d_norm.
- Não declare um enlace ou rota como viável ou inviável sem um critério técnico explícito.
- Não diga que um enlace está "bom", "ruim", "aprovado" ou "reprovado" sem um critério documentado.
- Quando um valor não tiver definição explícita, apresente-o simplesmente como resultado retornado pelo PlanApp.
- Faça uma síntese técnica clara dos dados disponíveis.""",
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

        self.user_request = text

        # ================================================================
        # ETAPA 2
        # ================================================================

        self.multi_hop_requested = (
            self.detect_multi_hop_request(
                text
            )
        )

        self.geocoding_followup_sent = False

        if self.multi_hop_requested:

            self.log_detail(
                "🔗 Solicitação multi-hop detectada."
            )

        else:

            self.log_detail(
                "🔗 Solicitação de enlace único."
            )

        # ================================================================
        # RESET LOCAL
        # ================================================================

        self.map = None

        self.map_image_bytes = None

        self.visualizations = []

        self.visualization_images = []

        self.visualizations_generated_hops = set()

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

        # ================================================================
        # APLICAÇÃO — AVALIAÇÃO FINAL
        # ================================================================

        result = (
            await self.ensure_application_evaluation()
        )

        if result is not None:

            if not self.technical_context_added:

                self.append_technical_context(
                    result
                )

            if self.multi_hop_requested:

                final_result = (
                    getattr(
                        self,
                        "global_result",
                        result,
                    )
                )

            else:

                final_result = (
                    self.last_evaluate_result
                )

        else:

            final_result = None

        # ================================================================
        # MAPA
        # ================================================================

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

                    self.log_detail(
                        "Imagem estática do mapa "
                        "multi-hop preparada para "
                        "o relatório."
                    )

                except Exception as exc:

                    self.log_detail(
                        f"⚠️ Erro no mapa multi-hop: "
                        f"{exc}"
                    )

        else:

            if len(
                self.geocoded_points
            ) >= 2:

                await (
                    self.mostrar_mapa_apos_geocodificacao()
                )

        # ================================================================
        # VISUALIZAÇÕES
        #
        # Não chamar gerar_visualizacoes() novamente.
        # ================================================================

        # ================================================================
        # RESPOSTA FINAL
        # ================================================================

        if final_result is not None:

            answer = (
                await self.generate_final_response(
                    text,
                    final_result,
                    technical_report=None,
                )
            )

            self.technical_report = answer

            self.build_report(
                final_result,
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