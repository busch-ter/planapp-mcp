# ============================================================================
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
#   APLICAÇÃO
#      |
#      +--> evaluate_link
#      +--> mapa
#      +--> visualizações
#      +--> relatório técnico
#
# IMPORTANTE:
#
#   O LLM NÃO executa evaluate_link.
#   O LLM NÃO escolhe visualizações.
#   A aplicação controla evaluate_link, mapa e visualizações.
#
# ============================================================================

import asyncio
import base64
import json
import os
import re

import ipywidgets as widgets

from openai import AsyncOpenAI

from agent_common import (
    PlanAppAgentCommon,
    APPLICATION_CONTROLLED_TOOLS,
)

from report_generator import ReportGenerator


# ============================================================================
# CONFIGURAÇÃO
# ============================================================================

MCP_URL = os.getenv(
    "MCP_URL",
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
    "",
)

USER_ID = os.getenv(
    "USER_ID",
    "jupyter-user",
)

DEFAULT_FREQ_MHZ = float(
    os.getenv(
        "DEFAULT_FREQ_MHZ",
        "900",
    )
)

DEFAULT_TX_HA = float(
    os.getenv(
        "DEFAULT_TX_HA",
        "7",
    )
)

DEFAULT_RX_HA = float(
    os.getenv(
        "DEFAULT_RX_HA",
        "7",
    )
)

DEFAULT_ON_ROOFTOP = False

MAX_AGENT_ITERATIONS = 8


# ============================================================================
# FERRAMENTAS DISPONÍVEIS AO LLM
#
# O LLM pode usar geocode_place.
#
# Ferramentas controladas pela aplicação ficam fora daqui.
# ============================================================================

MODEL_ALLOWED_TOOLS = {
    "geocode_place",
}


# ============================================================================
# AGENTE
# ============================================================================

class PlanAppAgentOpenRouter(PlanAppAgentCommon):

    AGENT_NAME = "PLANAPP AI — OPENROUTER"

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

        super().__init__(
            progress_callback=progress_callback,
            map_callback=map_callback,
            log_callback=log_callback,
            result_callback=result_callback,
            visualization_callback=visualization_callback,
        )

        # --------------------------------------------------------------------
        # ESTADO
        # --------------------------------------------------------------------

        self.registered = False

        self.technical_context_added = False

        self.last_agent_text = ""

        # Texto da análise técnica final produzida pelo OpenRouter.
        #
        # Esse texto pode ser utilizado pelo ReportGenerator como
        # conteúdo principal do relatório.
        self.technical_report = ""

        self.user_request = ""

        # ETAPA 2 — MULTI-HOP
        self.multi_hop_requested = False
        self.geocoding_followup_sent = False
        self.visualizations_generated_hops = set()

        self.report_pdf_path = None

        # --------------------------------------------------------------------
        # MAPA
        # --------------------------------------------------------------------

        self.map = None

        self.map_image_bytes = None

        # --------------------------------------------------------------------
        # VISUALIZAÇÕES
        # --------------------------------------------------------------------

        self.visualizations = []

        self.visualization_images = []

        # --------------------------------------------------------------------
        # OPENROUTER
        # --------------------------------------------------------------------

        self.client = None

        # --------------------------------------------------------------------
        # LOGGER
        # --------------------------------------------------------------------

        self._configure_logger()

        self.logger.info(
            "============================================================"
        )

        self.logger.info(
            "PLANAPP AI — OPENROUTER"
        )

        self.logger.info(
            f"Modelo: {OPENROUTER_MODEL}"
        )

        self.logger.info(
            f"OpenRouter URL: {OPENROUTER_URL}"
        )

        self.logger.info(
            f"MCP URL: {MCP_URL}"
        )

        self.logger.info(
            f"USER_ID: {USER_ID}"
        )

        self.logger.info(
            "============================================================"
        )

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
            if re.search(pattern, normalized):
                return True

        arrow_count = len(
            re.findall(r"(?:->|→|⇒|⟶)", normalized)
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
            if re.search(pattern, normalized):
                return True

        comma_count = normalized.count(",")

        route_context = re.search(
            r"\b("
            r"analise|analisar|análise|avalie|avaliar|enlace|enlaces|"
            r"link|links|rota|trajeto|pontos?|localidades?"
            r")\b",
            normalized,
        )

        if (
            comma_count >= 2
            and re.search(r"\be\b", normalized)
            and route_context
        ):
            return True

        # ------------------------------------------------------------
        # Rotas descritas como sequência de transições
        #
        # Exemplos:
        # "A e B, desse para C, desse para D e desse de volta para A"
        # "A para B, de B para C, de C para D"
        #
        # Nessas formulações o usuário pode não usar a estrutura
        # "A, B e C". A repetição de transições "para" / "desse para"
        # junto com contexto de enlaces caracteriza multi-hop.
        # ------------------------------------------------------------

        transition_count = len(
            re.findall(
                r"\b(?:desse|dessa|deste|desta|de)\s+para\b",
                normalized,
            )
        )

        para_count = len(
            re.findall(
                r"\bpara\b",
                normalized,
            )
        )

        if (
            transition_count >= 2
            and re.search(
                r"\b(enlace|enlaces|link|links|rota|trajeto)\b",
                normalized,
            )
        ):
            return True

        if (
            para_count >= 3
            and re.search(
                r"\b(enlace|enlaces|link|links|rota|trajeto|analise|análise|avaliar|avalie)\b",
                normalized,
            )
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
        Decide qual avaliação deve ser executada pela aplicação.

        2 pontos:
            ensure_evaluate_link()

        3+ pontos:
            ensure_multi_hop_evaluation()

        A função nunca transforma evaluate_link em super-tool.
        """

        point_count = len(
            self.geocoded_points
        )

        # --------------------------------------------------------
        # Proteção: três ou mais pontos significam multi-hop.
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
        # ETAPA 1 — SINGLE LINK
        # --------------------------------------------------------

        if point_count >= 2:

            if self.evaluate_executed:

                return self.last_evaluate_result

            return await (
                self.ensure_evaluate_link()
            )

        return None


    # ========================================================================
    # LOGGER
    # ========================================================================

    def _configure_logger(self):

        # O logger já é configurado pelo PlanAppAgentCommon.
        pass

    # ========================================================================
    # SYSTEM PROMPT
    # ========================================================================

    def system_prompt(self):

        return """
Você é o PlanApp AI, assistente técnico especializado em
planejamento e avaliação de enlaces de rádio.

O PlanApp é a fonte oficial dos resultados técnicos.

Seu papel é interpretar tecnicamente os dados retornados pelo
PlanApp sem inventar informações que não estejam presentes.

REGRAS FUNDAMENTAIS:

1. Nunca invente valores.

2. Nunca invente unidades.

3. Nunca altere resultados retornados pelo PlanApp.

4. Não recalcule valores técnicos quando o PlanApp já os forneceu.

5. Quando o usuário fornecer duas localidades, utilize
   geocode_place para obter suas coordenadas.

6. Depois de obtidos os dois pontos, a aplicação executará
   automaticamente evaluate_link.

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

16. Não conclua viabilidade do enlace sem um critério técnico
    explícito e sustentado pelos dados disponíveis.

17. Não invente potência TX.

18. Não invente ganho de antena.

19. Não invente sensibilidade do receptor.

20. Não invente margem de enlace.

21. Não atribua significado físico a campos cuja definição não
    esteja explicitamente documentada pelo PlanApp.

22. Não atribua significado próprio a:

       core
       fresnel
       boundary
       delta_diffra
       VV
       v_v
       d_norm

23. Não converta radianos para graus.

24. status=OK significa somente que a operação foi executada
    com sucesso.

25. O resultado fornecido pela aplicação é a fonte de verdade.

26. O relatório técnico fornecido pela aplicação, quando existir,
    é apenas uma apresentação estruturada dos dados reais do
    PlanApp.

27. Não altere, recalcule ou contradiga os valores presentes
    nos resultados do PlanApp.

28. Diferencie claramente:

       - parâmetros solicitados pelo usuário;
       - parâmetros efetivamente utilizados;
       - resultados retornados pelo PlanApp;
       - interpretação técnica;
       - limitações da análise.

29. Se um campo técnico não tiver definição explícita, apresente
    o valor somente como resultado retornado pelo PlanApp,
    sem atribuir significado adicional.

30. A resposta técnica NÃO deve ser apenas uma reprodução
    do JSON.

31. Organize os resultados em seções claras.

32. Faça uma síntese objetiva dos resultados efetivamente
    retornados.

33. Pode comparar numericamente valores que já foram retornados
    pelo PlanApp.

34. Pode destacar diferenças entre parâmetros solicitados e
    parâmetros efetivamente utilizados.

35. Pode destacar distância, FSPL, delta_diffra, resultados
    de terreno, vegetação, edificações e resultados geométricos
    quando esses valores estiverem presentes.

36. Ao apresentar conjuntos como terreno, vegetação ou
    edificações, deixe claro que são resultados retornados
    pelo PlanApp.

37. Não atribua interpretação física adicional aos nomes dos
    campos quando sua definição não estiver documentada.

38. Informe quais etapas foram efetivamente executadas quando
    essa informação estiver disponível.

39. Diferencie claramente dados fornecidos pelo usuário,
    parâmetros utilizados, resultados calculados e limitações.

40. Não declare o enlace como viável ou inviável sem um
    critério técnico explícito.

41. Não invente uma margem, limiar, classificação ou conclusão
    de engenharia que não esteja presente nos dados.

42. A resposta final deve ser em português do Brasil.

43. Seja técnico, claro, objetivo e informativo.

44. Prefira uma análise estruturada a uma simples listagem
    de campos.

45. A análise deve considerar conjuntamente os dados disponíveis
    de propagação, geometria, terreno, vegetação, edificações
    e demais resultados fornecidos pelo PlanApp.

46. Não trate um único indicador isoladamente como suficiente
    para determinar a qualidade do enlace.

47. Quando houver dados suficientes e um critério técnico
    documentado pelo PlanApp, apresente claramente a conclusão
    correspondente.

48. Quando não houver critério suficiente para uma conclusão de
    viabilidade, declare explicitamente essa limitação.

49. Sugestões de alteração de frequência, altura de antena,
    posicionamento ou outras alternativas devem ser apresentadas
    como sugestões, e não como soluções comprovadas.

50. Não diga que uma alternativa resolve o problema se ela não
    tiver sido efetivamente testada pelo PlanApp.

51. Diferencie claramente:

       - alternativa sugerida;
       - alternativa efetivamente testada pelo PlanApp.

52. A análise deve procurar relações entre os diferentes
    resultados retornados, mas sem inventar significado para
    campos cuja semântica não esteja documentada.
"""

    # ========================================================================
    # CRIA CLIENTE OPENROUTER
    # ========================================================================

    async def create_client(self):

        if not OPENROUTER_API_KEY:

            raise RuntimeError(
                "OPENROUTER_API_KEY não está configurada."
            )

        self.client = AsyncOpenAI(
            api_key=OPENROUTER_API_KEY,
            base_url=OPENROUTER_URL,
            default_headers={
                "HTTP-Referer": "https://planapp.pucpr.br",
                "X-Title": "PlanApp AI",
            },
        )

        self.log_detail(
            f"OpenRouter client criado — "
            f"modelo: {OPENROUTER_MODEL}"
        )

    # ========================================================================
    # CONSTRÓI TOOLS PARA OPENROUTER
    # ========================================================================

    def build_openrouter_tools(self):

        tools = []

        for tool in self.mcp_tools:

            name = getattr(
                tool,
                "name",
                None,
            )

            if not name:
                continue

            # ---------------------------------------------------------------
            # SOMENTE FERRAMENTAS PERMITIDAS AO LLM
            # ---------------------------------------------------------------

            if name not in MODEL_ALLOWED_TOOLS:
                continue

            # ---------------------------------------------------------------
            # SEGURANÇA EXTRA
            # ---------------------------------------------------------------

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

            description = getattr(
                tool,
                "description",
                "",
            )

            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": (
                            description or ""
                        ),
                        "parameters": schema,
                    },
                }
            )

        return tools

    # ========================================================================
    # CHAMADA OPENROUTER
    # ========================================================================

    async def openrouter_chat(
        self,
        messages=None,
        use_tools=True,
    ):

        if self.client is None:

            raise RuntimeError(
                "Cliente OpenRouter não foi criado."
            )

        if messages is None:

            messages = self.messages

        kwargs = {
            "model": OPENROUTER_MODEL,
            "messages": messages,
        }

        if use_tools:

            tools = (
                self.build_openrouter_tools()
            )

            if tools:

                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"

        self.log_detail(
            f"OpenRouter request — "
            f"model={OPENROUTER_MODEL}"
        )

        response = (
            await self.client.chat.completions.create(
                **kwargs
            )
        )

        return response

    # ========================================================================
    # OBTÉM MESSAGE
    # ========================================================================

    def response_message(
        self,
        response,
    ):

        if response is None:
            return None

        choices = getattr(
            response,
            "choices",
            None,
        )

        if not choices:
            return None

        return getattr(
            choices[0],
            "message",
            None,
        )

    # ========================================================================
    # OBTÉM TEXTO
    # ========================================================================

    def response_text(
        self,
        response,
    ):

        message = (
            self.response_message(
                response
            )
        )

        if message is None:
            return ""

        content = getattr(
            message,
            "content",
            None,
        )

        if content is None:
            return ""

        if isinstance(
            content,
            str,
        ):

            return content.strip()

        if isinstance(
            content,
            list,
        ):

            parts = []

            for item in content:

                if isinstance(
                    item,
                    dict,
                ):

                    value = item.get(
                        "text"
                    )

                    if value:
                        parts.append(
                            str(value)
                        )

                else:

                    value = getattr(
                        item,
                        "text",
                        None,
                    )

                    if value:
                        parts.append(
                            str(value)
                        )

            return "\n".join(
                parts
            ).strip()

        return str(
            content
        ).strip()

    # ========================================================================
    # OBTÉM TOOL CALLS
    # ========================================================================

    def response_tool_calls(
        self,
        response,
    ):

        message = (
            self.response_message(
                response
            )
        )

        if message is None:
            return []

        calls = getattr(
            message,
            "tool_calls",
            None,
        )

        if not calls:
            return []

        return calls

    # ========================================================================
    # LIMPA RESPOSTAS DE RACIOCÍNIO
    # ========================================================================

    def clean_final_response(
        self,
        text,
    ):

        if not text:
            return ""

        text = str(
            text
        )

        text = re.sub(
            r"<think>.*?</think>",
            "",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )

        text = re.sub(
            r"<reasoning>.*?</reasoning>",
            "",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )

        text = re.sub(
            r"<analysis>.*?</analysis>",
            "",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )

        return text.strip()

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

        self.log_detail(
            "Contexto técnico enviado ao OpenRouter."
        )

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

            # ---------------------------------------------------------------
            # MAPA INTERATIVO
            # ---------------------------------------------------------------

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

            # ---------------------------------------------------------------
            # IMAGEM ESTÁTICA
            # ---------------------------------------------------------------

            self.map_image_bytes = (
                gerar_imagem_mapa_enlace(
                    tx_lat,
                    tx_lon,
                    rx_lat,
                    rx_lon,
                )
            )

            self.log_detail(
                "Mapa preparado."
            )

        except Exception as exc:

            self.log_detail(
                f"⚠️ Erro ao preparar mapa: {exc}"
            )

    # ========================================================================
    # VISUALIZAÇÕES
    # ========================================================================

    async def gerar_visualizacoes(
        self,
    ):

        if not self.evaluate_executed:

            self.log_detail(
                "Visualizações não executadas: "
                "evaluate_link não foi executado."
            )

            return

        if self.evaluate_error:

            self.log_detail(
                "Visualizações não executadas: "
                "evaluate_link apresentou erro."
            )

            return

        visualizations = [

            (
                "link_area",
                {
                    "ds_string": "DTM"
                },
                "DTM",
            ),

            (
                "link_area",
                {
                    "ds_string": "DSM"
                },
                "DSM",
            ),

            (
                "link_area",
                {
                    "ds_string": "COVER"
                },
                "COVER",
            ),

            (
                "link_profile",
                {},
                "Perfil do enlace",
            ),

            (
                "lulc_fresnel",
                {},
                "LULC / Fresnel",
            ),

            (
                "bldg_prepare",
                {},
                "Buildings / Prepare",
            ),

            (
                "bldg_fresnel",
                {},
                "Buildings / Fresnel",
            ),

            (
                "bldg_profile",
                {},
                "Buildings / Profile",
            ),
        ]

        self.visualizations = []

        self.visualization_images = []

        for (
            tool_name,
            arguments,
            title,
        ) in visualizations:

            try:

                self.log_detail(
                    f"Executando visualização: "
                    f"{title}"
                )

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
                        f"⚠️ {title}: "
                        "resultado inválido."
                    )

                    continue

                if parsed.get(
                    "kind"
                ) != "image":

                    self.log_detail(
                        f"⚠️ {title}: "
                        "resultado não contém imagem."
                    )

                    continue

                data = parsed.get(
                    "data"
                )

                if not data:

                    self.log_detail(
                        f"⚠️ {title}: "
                        "dados da imagem ausentes."
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

                if self.visualization_callback:

                    self.visualization_callback(
                        image,
                        title,
                    )

                self.log_detail(
                    f"Visualização concluída: "
                    f"{title}"
                )

            except Exception as exc:

                self.log_detail(
                    f"⚠️ Erro na visualização "
                    f"{title}: {exc}"
                )

        self.log_detail(
            "Total de visualizações: "
            f"{len(self.visualization_images)}"
        )

    # ========================================================================
    # RELATÓRIO
    #
    # A análise final do OpenRouter pode ser passada para o
    # ReportGenerator como conteúdo principal do relatório.
    #
    # A geração automática do PDF continua fora do ask(),
    # preservando o fluxo atual da interface.
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
                    f"⚠️ Erro ao gerar imagem "
                    f"do mapa: {exc}"
                )

        # --------------------------------------------------------------------
        # GERADOR
        # --------------------------------------------------------------------

        generator = ReportGenerator(

            requested_params=(
                requested_parameters
            ),

            effective_params=(
                effective_parameters
            ),

            technical_result=(
                technical_result
            ),

            geocoded_points=(
                self.geocoded_points
            ),

            map_image=(
                self.map_image_bytes
            ),

            visualization_images=(
                self.visualization_images
            ),

            user_request=(
                self.user_request
            ),

            # ---------------------------------------------------------------
            # NOVO:
            # análise final do OpenRouter
            # ---------------------------------------------------------------

            analysis_text=(
                analysis_text
                if analysis_text
                else None
            ),
        )

        # --------------------------------------------------------------------
        # TEXTO DO RELATÓRIO
        # --------------------------------------------------------------------

        report = (
            generator.generate_report(
                include_raw_result=False
            )
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
    # ASSISTANT MESSAGE PARA CHAT COMPLETIONS
    # ========================================================================

    def _assistant_message_to_dict(
        self,
        message,
    ):

        try:

            data = message.model_dump(
                exclude_none=True
            )

            return data

        except Exception:

            data = {
                "role": "assistant",
                "content": getattr(
                    message,
                    "content",
                    None,
                ),
            }

            tool_calls = getattr(
                message,
                "tool_calls",
                None,
            )

            if tool_calls:

                converted = []

                for call in tool_calls:

                    function = getattr(
                        call,
                        "function",
                        None,
                    )

                    if function is None:
                        continue

                    converted.append(
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": function.name,
                                "arguments": function.arguments,
                            },
                        }
                    )

                if converted:

                    data["tool_calls"] = converted

            return data

    # ========================================================================
    # AGENT TURN
    # ========================================================================

    async def agent_turn(
        self,
    ):

        for iteration in range(MAX_AGENT_ITERATIONS):

            self.log_detail(
                f"OpenRouter — iteração {iteration + 1}/{MAX_AGENT_ITERATIONS}"
            )

            try:
                response = await self.openrouter_chat(
                    messages=self.messages,
                    use_tools=True,
                )
            except Exception as exc:
                self.log_detail(f"❌ Erro OpenRouter: {exc}")
                return ""

            message = self.response_message(response)
            if message is None:
                self.log_detail("⚠️ OpenRouter não retornou uma mensagem.")
                continue

            text = self.clean_final_response(
                self.response_text(response)
            )
            if text:
                self.last_agent_text = text

            tool_calls = self.response_tool_calls(response)
            self.messages.append(
                self._assistant_message_to_dict(message)
            )

            if not tool_calls:
                result = await self.ensure_application_evaluation()

                if result is not None:
                    if not self.technical_context_added:
                        self.append_technical_context(result)

                    # Em multi-hop, a aplicação já executou todos os hops.
                    # NÃO voltar ao OpenRouter: devolver o controle ao ask().
                    if (
                        self.multi_hop_requested
                        and getattr(self, "multi_hop_executed", False)
                    ):
                        self.log_detail(
                            "🟢 Multi-hop concluído após a geocodificação."
                        )
                        self.log_detail("Encerrando agent_turn().")
                        return text

                    continue

                if (
                    self.multi_hop_requested
                    and len(self.geocoded_points) < 3
                    and not self.geocoding_followup_sent
                ):
                    self.geocoding_followup_sent = True
                    self.messages.append({
                        "role": "user",
                        "content": (
                            "A solicitação atual descreve uma rota multi-hop. "
                            "Ainda existem menos de três pontos geocodificados. "
                            "Continue identificando e geocodificando, na ordem "
                            "solicitada pelo usuário, todas as localidades restantes. "
                            "Não execute avaliação técnica."
                        ),
                    })
                    continue

                return text

            # O único tool permitido ao modelo é geocode_place.
            for call in tool_calls:
                function = getattr(call, "function", None)
                if function is None:
                    continue

                tool_name = getattr(function, "name", "")
                arguments_text = getattr(function, "arguments", "{}")

                try:
                    arguments = json.loads(arguments_text)
                except Exception:
                    arguments = {}

                if not isinstance(arguments, dict):
                    arguments = {}

                if tool_name in APPLICATION_CONTROLLED_TOOLS:
                    self.log_detail(
                        f"⚠️ OpenRouter tentou executar {tool_name}, "
                        "mas esta ferramenta é controlada pela aplicação."
                    )
                    tool_result = {
                        "error": (
                            f"A ferramenta {tool_name} é controlada pela "
                            "aplicação e não deve ser executada pelo LLM."
                        )
                    }
                elif tool_name not in MODEL_ALLOWED_TOOLS:
                    self.log_detail(
                        f"⚠️ Ferramenta não permitida ao OpenRouter: {tool_name}"
                    )
                    tool_result = {
                        "error": f"A ferramenta {tool_name} não está disponível ao modelo."
                    }
                else:
                    self.log_detail(f"MCP TOOL: {tool_name}")
                    self.log_detail(
                        "Argumentos: "
                        + json.dumps(arguments, ensure_ascii=False)
                    )
                    try:
                        tool_result = await self.execute_mcp_tool(
                            tool_name, arguments
                        )
                    except Exception as exc:
                        self.log_detail(f"❌ Erro MCP: {exc}")
                        tool_result = {"error": str(exc)}

                self.messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(
                        tool_result,
                        ensure_ascii=False,
                        default=str,
                    ),
                })

            # Depois das tools, a aplicação decide se já há pontos suficientes
            # para executar a avaliação. Em multi-hop, ela aguarda todos os pontos.
            result = await self.ensure_application_evaluation()

            if result is not None:
                if not self.technical_context_added:
                    self.append_technical_context(result)

                if (
                    self.multi_hop_requested
                    and getattr(self, "multi_hop_executed", False)
                ):
                    self.log_detail(
                        "🟢 Multi-hop concluído após a execução das ferramentas."
                    )
                    self.log_detail("Encerrando agent_turn().")
                    return text

                continue

            if (
                self.multi_hop_requested
                and len(self.geocoded_points) < 3
                and not self.geocoding_followup_sent
            ):
                self.geocoding_followup_sent = True
                self.messages.append({
                    "role": "user",
                    "content": (
                        "Continue a geocodificação da rota multi-hop solicitada. "
                        "Use geocode_place para os pontos restantes na ordem original. "
                        "Não execute avaliação técnica."
                    ),
                })
                continue

            continue

        self.log_detail("⚠️ Limite máximo de iterações atingido.")
        return self.last_agent_text

    # ========================================================================
    # FALLBACK DETERMINÍSTICO
    # ========================================================================

    def _fallback_final_response(
        self,
    ):

        result = getattr(
            self,
            "last_evaluate_result",
            None,
        )

        if not result:

            return (
                "A avaliação técnica foi executada, "
                "mas o modelo não retornou uma "
                "resposta textual final."
            )

        try:

            context = (
                self.build_technical_context(
                    result
                )
            )

            lines = []

            lines.append(
                "## Análise técnica do enlace"
            )

            if self.geocoded_points:

                lines.append(
                    "\n### Pontos geográficos"
                )

                for index, point in enumerate(
                    self.geocoded_points,
                    start=1,
                ):

                    label = (
                        "TX"
                        if index == 1
                        else "RX"
                    )

                    name = point.get(
                        "name",
                        point.get(
                            "query",
                            "",
                        ),
                    )

                    lines.append(
                        f"- {label}: {name}"
                    )

                    if point.get(
                        "lat"
                    ) is not None:

                        lines.append(
                            f"  - latitude: "
                            f"{point['lat']}"
                        )

                    if point.get(
                        "lon"
                    ) is not None:

                        lines.append(
                            f"  - longitude: "
                            f"{point['lon']}"
                        )

            lines.append(
                "\n### Resultado retornado pelo PlanApp"
            )

            if isinstance(
                context,
                dict,
            ):

                for key, value in context.items():

                    if isinstance(
                        value,
                        (dict, list),
                    ):

                        value_text = json.dumps(
                            value,
                            ensure_ascii=False,
                            default=str,
                        )

                    else:

                        value_text = str(
                            value
                        )

                    lines.append(
                        f"- {key}: {value_text}"
                    )

            else:

                lines.append(
                    str(context)
                )

            lines.append(
                "\n### Limitação"
            )

            lines.append(
                "- A avaliação apresenta os dados "
                "retornados pelo PlanApp."
            )

            lines.append(
                "- Não foi aplicado um critério adicional "
                "de viabilidade que não estivesse "
                "documentado nos resultados."
            )

            return "\n".join(
                lines
            )

        except Exception as exc:

            self.log_detail(
                f"⚠️ Erro no fallback final: {exc}"
            )

            return (
                "A avaliação técnica foi executada, "
                "mas não foi possível gerar a "
                "resposta textual final."
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
                    "RESULTADO TÉCNICO DO PLANAPP:\n\n"
                    + json.dumps(
                        context,
                        ensure_ascii=False,
                        default=str,
                    )
                ),
            },
        ]

        if technical_report:

            final_messages.append(
                {
                    "role": "user",
                    "content": (
                        "RELATÓRIO TÉCNICO:\n\n"
                        + technical_report
                    ),
                }
            )

        final_messages.append(
            {
                "role": "user",
                "content": """
Produza agora a análise técnica final do enlace.

A resposta deve ser em português do Brasil.

A análise deve interpretar os dados do PlanApp e NÃO apenas
reproduzir o JSON.

Considere conjuntamente, quando disponíveis:

- geometria do enlace;
- distância;
- frequência;
- alturas das antenas;
- FSPL;
- resultados de terreno;
- resultados de vegetação/COVER;
- resultados de edificações;
- resultados de Fresnel;
- resultados geométricos;
- demais indicadores retornados pelo PlanApp.

Não atribua significado físico a campos cuja definição não esteja
documentada.

Use exatamente a estrutura abaixo, adaptando o conteúdo aos dados
realmente disponíveis.

## 1. RESUMO EXECUTIVO

Apresente uma síntese técnica objetiva do resultado.

Se houver dados suficientes e critério técnico explícito para uma
classificação, apresente a conclusão correspondente.

Se não houver critério suficiente, informe claramente que a
viabilidade não pode ser determinada a partir dos dados
disponíveis.

## 2. IDENTIFICAÇÃO DO ENLACE

Apresente:

- localidade TX;
- coordenadas TX;
- localidade RX;
- coordenadas RX;
- distância, quando retornada.

## 3. PARÂMETROS UTILIZADOS

Diferencie:

- parâmetros solicitados pelo usuário;
- parâmetros efetivamente utilizados pelo PlanApp.

Apresente:

- frequência;
- altura TX;
- altura RX;
- rooftop;
- demais parâmetros relevantes.

## 4. ANÁLISE DE PROPAGAÇÃO

Apresente os resultados de propagação retornados pelo PlanApp.

Inclua, quando disponíveis:

- FSPL;
- delta_diffra;
- outros indicadores de propagação.

Não invente significado para campos não documentados.

## 5. ANÁLISE DO TERRENO

Apresente os resultados de terreno retornados pelo PlanApp.

Pode comparar numericamente valores retornados.

Não atribua significado adicional a core, fresnel, boundary,
v_v, VV ou d_norm sem documentação explícita.

## 6. ANÁLISE DA FRESNEL

Apresente os resultados relacionados à Fresnel que estejam
disponíveis.

Não invente critérios de obstrução ou margens.

## 7. VEGETAÇÃO / COBERTURA

Apresente os resultados de COVER/LULC retornados pelo PlanApp.

Não invente classificação adicional.

## 8. EDIFICAÇÕES

Apresente os resultados relacionados a edificações.

Destaque os valores disponíveis sem atribuir significado físico
não documentado.

## 9. GEOMETRIA E OBSTÁCULOS

Apresente os resultados geométricos retornados pelo PlanApp.

Inclua, quando presentes:

- ângulos;
- clearance;
- obstáculos;
- outros valores geométricos.

Não converta radianos para graus.

## 10. PRINCIPAIS FATORES LIMITANTES

Identifique os resultados que merecem atenção técnica.

Não invente fatores que não estejam sustentados pelos dados.

## 11. DIAGNÓSTICO TÉCNICO

Faça uma síntese integrada.

Relacione, quando possível:

- propagação;
- terreno;
- vegetação;
- edificações;
- geometria.

Não trate um único indicador isoladamente como suficiente.

## 12. CONCLUSÃO DE VIABILIDADE

Utilize uma classificação SOMENTE quando houver critério técnico
explícito e suficiente nos dados:

- VIÁVEL
- NÃO VIÁVEL
- VIÁVEL COM RESSALVAS
- INDETERMINADO

Na ausência de critério suficiente, utilize:

INDETERMINADO

e explique objetivamente a limitação.

Não invente limiares de engenharia.

## 13. ALTERNATIVAS

Quando apropriado, sugira:

- alteração de altura;
- alteração de frequência;
- alteração de posicionamento;
- alteração de parâmetros.

Mas diferencie:

- alternativa sugerida;
- alternativa efetivamente testada pelo PlanApp.

Não diga que uma alternativa resolve o problema se ela não foi
efetivamente testada.

## 14. RECOMENDAÇÕES

Apresente recomendações técnicas baseadas exclusivamente nos
dados disponíveis.

Diferencie recomendações de resultados efetivamente testados.

## 15. LIMITAÇÕES

Liste as limitações da análise.

Inclua critérios ou informações necessários para uma conclusão
definitiva que não estejam presentes nos dados.

REGRAS ABSOLUTAS:

- Não invente valores.
- Não altere valores.
- Não altere unidades.
- Não faça cálculos técnicos adicionais.
- Não converta radianos para graus.
- Não invente potência.
- Não invente ganho.
- Não invente sensibilidade.
- Não invente margem.
- Não invente limiares.
- Não invente critérios de viabilidade.
- Não atribua significado próprio a core.
- Não atribua significado próprio a fresnel.
- Não atribua significado próprio a boundary.
- Não atribua significado próprio a delta_diffra.
- Não atribua significado próprio a VV.
- Não atribua significado próprio a v_v.
- Não atribua significado próprio a d_norm.
- Não confunda status OK com viabilidade.
- Não apresente uma sugestão como resultado testado.
- Não diga que uma alternativa resolve o problema sem teste.
- Seja técnico, objetivo e claro.
""",
            }
        )

        old_messages = self.messages

        try:

            self.messages = final_messages

            # ----------------------------------------------------------------
            # PRIMEIRA TENTATIVA
            # ----------------------------------------------------------------

            response = (
                await self.openrouter_chat(
                    messages=final_messages,
                    use_tools=False,
                )
            )

            answer = (
                self.clean_final_response(
                    self.response_text(
                        response
                    )
                )
            )

            if answer:

                self.last_agent_text = answer

                # ------------------------------------------------------------
                # NOVO:
                # guarda a análise final para que a UI possa utilizá-la
                # na geração do relatório.
                # ------------------------------------------------------------

                self.technical_report = answer

                return answer

            self.log_detail(
                "⚠️ OpenRouter retornou resposta "
                "final vazia."
            )

            # ----------------------------------------------------------------
            # SEGUNDA TENTATIVA
            # ----------------------------------------------------------------

            retry_messages = list(
                final_messages
            )

            retry_messages.append(
                {
                    "role": "user",
                    "content": (
                        "A resposta anterior veio vazia. "
                        "Retorne somente a análise técnica "
                        "final, em português do Brasil, "
                        "usando os dados do PlanApp já "
                        "fornecidos nesta conversa. "
                        "Não retorne JSON e não inclua "
                        "raciocínio interno."
                    ),
                }
            )

            response = (
                await self.openrouter_chat(
                    messages=retry_messages,
                    use_tools=False,
                )
            )

            answer = (
                self.clean_final_response(
                    self.response_text(
                        response
                    )
                )
            )

            if answer:

                self.last_agent_text = answer

                # ------------------------------------------------------------
                # NOVO:
                # também guarda a resposta da segunda tentativa.
                # ------------------------------------------------------------

                self.technical_report = answer

                return answer

            self.log_detail(
                "⚠️ Segunda tentativa também retornou "
                "resposta vazia."
            )

            return ""

        except Exception as exc:

            self.log_detail(
                f"⚠️ Erro na resposta final: {exc}"
            )

            return ""

        finally:

            self.messages = old_messages

    # ========================================================================
    # ASK
    # ========================================================================

    async def ask(
        self,
        text,
    ):

        self.reset_common_state()

        self.registered = False
        self.technical_context_added = False
        self.last_agent_text = ""
        self.technical_report = ""
        self.report_pdf_path = None
        self.user_request = text

        # ETAPA 2 — MULTI-HOP
        self.multi_hop_requested = self.detect_multi_hop_request(text)
        self.geocoding_followup_sent = False
        self.visualizations_generated_hops = set()

        self.log_detail(
            "🔗 Solicitação multi-hop detectada."
            if self.multi_hop_requested
            else "🔗 Solicitação de enlace único."
        )

        self.map = None
        self.map_image_bytes = None
        self.visualizations = []
        self.visualization_images = []

        try:
            self.extract_link_parameters(text)
        except Exception as exc:
            self.log_detail(f"⚠️ Erro ao extrair parâmetros: {exc}")

        try:
            await self.create_client()
        except Exception as exc:
            self.log_detail(f"❌ Erro ao criar cliente OpenRouter: {exc}")
            return "Não foi possível conectar ao OpenRouter. Verifique a OPENROUTER_API_KEY."

        try:
            await self.connect()
        except Exception as exc:
            self.log_detail(f"❌ Erro ao conectar ao MCP: {exc}")
            return "Não foi possível conectar ao serviço PlanApp."

        try:
            await self.register()
            self.registered = True
        except Exception as exc:
            self.log_detail(f"❌ Erro no registro do usuário: {exc}")
            return "Não foi possível registrar o usuário no serviço PlanApp."

        self.messages = [
            {"role": "system", "content": self.system_prompt()},
            {"role": "user", "content": text},
        ]

        try:
            await self.agent_turn()
        except Exception as exc:
            self.log_detail(f"❌ Erro no agent_turn: {exc}")

        # APLICAÇÃO — avaliação final
        try:
            result = await self.ensure_application_evaluation()
        except Exception as exc:
            self.log_detail(f"❌ Erro na avaliação da aplicação: {exc}")
            result = None

        if result is not None:
            if not self.technical_context_added:
                self.append_technical_context(result)

            final_result = (
                getattr(self, "global_result", result)
                if self.multi_hop_requested
                else self.last_evaluate_result
            )
        else:
            final_result = None

        # MAPA
        if self.multi_hop_requested:
            if (
                getattr(self, "multi_hop_executed", False)
                and getattr(self, "hops", None)
            ):
                try:
                    from map_utils import (
                        mostrar_mapa_multihop,
                        gerar_imagem_mapa_multihop,
                    )

                    self.map = mostrar_mapa_multihop(self.hops)
                    if self.map_callback:
                        self.map_callback(self.map)

                    self.log_detail(
                        "Mapa multi-hop preparado "
                        f"com {len(self.hops)} hops."
                    )
                    self.log_detail(
                        "Mapa interativo contém "
                        f"{len(self.geocoded_points)} pontos da rota."
                    )

                    self.map_image_bytes = gerar_imagem_mapa_multihop(
                        self.hops
                    )
                    self.log_detail(
                        "Imagem estática do mapa multi-hop preparada para o relatório."
                    )
                except Exception as exc:
                    self.log_detail(f"⚠️ Erro no mapa multi-hop: {exc}")
        elif len(self.geocoded_points) >= 2:
            await self.mostrar_mapa_apos_geocodificacao()

        # VISUALIZAÇÕES
        # Em multi-hop elas já são geradas pela orquestração da aplicação.
        if (
            not self.multi_hop_requested
            and self.evaluate_executed
            and not self.evaluate_error
        ):
            await self.gerar_visualizacoes()

        # RESPOSTA FINAL
        if final_result is not None:
            self.log_detail(
                "🧠 Iniciando análise técnica final do OpenRouter."
            )

            answer = await self.generate_final_response(
                text,
                final_result,
                technical_report=None,
            )

            if not answer:
                self.log_detail(
                    "⚠️ OpenRouter não retornou texto final. Usando fallback."
                )
                answer = self._fallback_final_response()

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

        try:

            if self.client is not None:

                await self.client.close()

        except Exception as exc:

            self.log_detail(
                f"⚠️ Erro ao fechar OpenRouter: "
                f"{exc}"
            )

        self.client = None

        await super().close()


# ============================================================================
# COMPATIBILIDADE COM notebook_ui.py
# ============================================================================

PlanAppAgent = PlanAppAgentOpenRouter