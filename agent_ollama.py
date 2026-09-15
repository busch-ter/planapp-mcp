import asyncio
import base64
import json
import logging
import os
import re
from contextlib import AsyncExitStack

import requests

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

import ipywidgets as widgets

from map_utils import mostrar_mapa_enlace


# ============================================================
# CONFIGURAÇÕES
# ============================================================

MCP_URL = os.getenv(
    "PLANAPP_MCP_URL",
    "http://172.17.0.1:8010/mcp",
)

OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://172.17.0.1:11434",
)

OLLAMA_MODEL = os.getenv(
    "OLLAMA_MODEL",
    "qwen3:8b",
)

USER_ID = "jupyter-user"


DEFAULT_FREQ_MHZ = 900
DEFAULT_TX_HA = 7
DEFAULT_RX_HA = 7
DEFAULT_ON_ROOFTOP = False

MAX_AGENT_ITERATIONS = 12

LOG_DIR = os.path.expanduser("~/work/planapp-mcp/logs")


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
        """
        Agente do PlanApp.

        Callbacks:

        progress_callback:
            Mensagens amigáveis de andamento/status.

        map_callback:
            Recebe o mapa gerado após a geocodificação.

        log_callback:
            Logs técnicos do MCP.

        result_callback:
            Recebe o resultado técnico real retornado pelo
            evaluate_link.

        visualization_callback:
            Recebe a lista de visualizações geradas
            automaticamente após evaluate_link.
        """

        self.progress_callback = progress_callback
        self.map_callback = map_callback
        self.log_callback = log_callback
        self.result_callback = result_callback
        self.visualization_callback = visualization_callback

        self.exit_stack = AsyncExitStack()

        self.mcp_session = None
        self.mcp_tools = []

        self.messages = []

        self.geocoded_points = []

        self.evaluate_executed = False
        self.last_evaluate_result = None
        self.evaluate_error = None

        self.tool_count = 0
        self.current_stage = 0

        self.map = None

        self.connected = False

        self.link_parameters = {
            "freq_mhz": DEFAULT_FREQ_MHZ,
            "tx_ha": DEFAULT_TX_HA,
            "rx_ha": DEFAULT_RX_HA,
            "on_rooftop": DEFAULT_ON_ROOFTOP,
        }

        # ----------------------------------------------------
        # Parâmetros exatamente como solicitados pelo usuário
        # ----------------------------------------------------

        self.requested_frequency = None
        self.requested_frequency_unit = None
        self.requested_frequency_text = None

        self.requested_tx_ha = None
        self.requested_rx_ha = None

        # ----------------------------------------------------
        # Visualizações
        # ----------------------------------------------------

        self.visualizations = []

        # ----------------------------------------------------
        # Log em arquivo — um arquivo por execução
        # ----------------------------------------------------
        self.file_logger = None
        self.file_log_handler = None
        self.log_file_path = None


    # ========================================================
    # LOG EM ARQUIVO
    # ========================================================

    def start_file_log(self):
        """Cria um arquivo de log independente para esta execução."""

        self.close_file_log()
        os.makedirs(LOG_DIR, exist_ok=True)

        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file_path = os.path.join(
            LOG_DIR,
            f"planapp_agent_ollama_{timestamp}.log",
        )

        logger_name = f"planapp_agent_ollama_{id(self)}"
        self.file_logger = logging.getLogger(logger_name)
        self.file_logger.setLevel(logging.DEBUG)
        self.file_logger.propagate = False

        self.file_log_handler = logging.FileHandler(
            self.log_file_path, encoding="utf-8"
        )
        self.file_log_handler.setLevel(logging.DEBUG)
        self.file_log_handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        self.file_logger.addHandler(self.file_log_handler)

        self.file_logger.info("=" * 80)
        self.file_logger.info("PLANAPP AI — OLLAMA / QWEN")
        self.file_logger.info("Log iniciado")
        self.file_logger.info(f"Modelo: {OLLAMA_MODEL}")
        self.file_logger.info(f"MCP_URL: {MCP_URL}")
        self.file_logger.info(f"USER_ID: {USER_ID}")
        self.file_logger.info("=" * 80)

    def close_file_log(self):
        """Fecha e remove o handler do log em arquivo."""
        if self.file_logger is not None and self.file_log_handler is not None:
            try:
                self.file_logger.removeHandler(self.file_log_handler)
            except Exception:
                pass
            try:
                self.file_log_handler.close()
            except Exception:
                pass
        self.file_log_handler = None
        self.file_logger = None


    # ========================================================
    # STATUS
    # ========================================================

    def log(self, message):
        """
        Envia somente mensagens de andamento/status.

        Argumentos e resultados brutos do MCP NÃO devem passar
        por este método.
        """

        if self.file_logger:
            try:
                self.file_logger.info(str(message))
            except Exception:
                pass

        if self.progress_callback:
            try:
                self.progress_callback(message)
            except Exception:
                pass


    # ========================================================
    # LOG TÉCNICO
    # ========================================================

    def log_detail(self, message):
        """
        Envia logs técnicos para o painel de log MCP.
        """

        if self.file_logger:
            try:
                self.file_logger.info(str(message))
            except Exception:
                pass

        if self.log_callback:
            try:
                self.log_callback(message)
            except Exception:
                pass


    # ========================================================
    # RESULTADO TÉCNICO
    # ========================================================

    def publish_technical_result(self, result):
        """
        Publica o resultado técnico real do evaluate_link.

        Esse resultado é separado da resposta textual produzida
        pelo modelo.
        """

        if self.result_callback:
            try:
                self.result_callback(result)
            except Exception:
                pass


    # ========================================================
    # SYSTEM PROMPT
    # ========================================================

    def system_prompt(self):

        return """
Você é o PlanApp AI, um assistente especializado em planejamento
e avaliação técnica de enlaces de rádio.

REGRAS FUNDAMENTAIS:

1. O PlanApp é a fonte de verdade para resultados técnicos.

2. Nunca invente valores técnicos.

3. Nunca recalcule valores fornecidos pelo PlanApp usando fórmulas
   próprias, salvo quando explicitamente solicitado e quando isso
   não substituir o resultado do PlanApp.

4. Quando o usuário informar dois locais, geocodifique ambos usando
   a ferramenta geocode_place.

5. Depois que os dois pontos forem geocodificados, a avaliação técnica
   do enlace deve ser executada automaticamente pela aplicação.

6. Nunca peça ao usuário para executar manualmente a avaliação.

7. Nunca diga que precisa esperar uma próxima etapa para executar
   a avaliação.

8. Não solicite ao usuário uma chamada direta de evaluate_link.

9. Não faça chamadas diretas de evaluate_link através do modelo.
   A aplicação executará evaluate_link automaticamente.

10. Preserve exatamente os valores fornecidos pelo PlanApp.

11. Preserve as unidades fornecidas pelo PlanApp.

12. FSPL significa Free-Space Path Loss.

13. Não faça julgamentos sobre qualidade de clearance sem que exista
    um critério explícito fornecido pelo PlanApp ou pelo usuário.

14. Não conclua que um enlace é viável ou inviável apenas com base
    em distância, FSPL, difração ou clearance.

15. Uma conclusão de viabilidade exige os parâmetros e critérios
    técnicos necessários.

16. Não atribua significado físico a campos que não estejam definidos
    explicitamente pelo PlanApp.

17. Os campos:
    core
    fresnel
    boundary
    delta_diffra
    VV
    d_norm

    devem permanecer com seus nomes originais.

18. Não interprete esses campos usando conhecimento genérico de
    engenharia quando o significado não tiver sido explicitamente
    definido pelo PlanApp.

19. Não compare distância com core, fresnel ou boundary.

20. Não interprete d_norm como posição normalizada, percentual ou
    qualquer outro significado sem definição explícita.

21. Não interprete VV como altura de obstáculo, pico de terreno ou
    qualquer outra grandeza física sem definição explícita.

22. Não interprete delta_diffra como zona de difração ou perda de
    difração sem definição explícita.

23. Não conclua que um ponto está dentro ou fora da zona de Fresnel
    apenas com base em campos não definidos.

24. Não afirme que terreno, vegetação ou edificações afetam o sinal
    apenas porque existem valores numéricos nesses campos.

25. Diferencie claramente:
    - valores fornecidos pelo usuário;
    - valores usados pelo PlanApp;
    - resultados fornecidos pelo PlanApp;
    - conclusões tecnicamente suportadas;
    - conclusões que não podem ser obtidas com os dados disponíveis.

REGRAS DE PARÂMETROS:

26. Parâmetros explicitamente fornecidos pelo usuário têm prioridade
    absoluta sobre os valores padrão.

27. Valores padrão só podem ser usados quando o usuário não informar
    aquele parâmetro.

28. Frequência padrão:
    900 MHz.

29. Altura padrão da antena TX:
    7 m.

30. Altura padrão da antena RX:
    7 m.

31. on_rooftop padrão:
    false.

32. Preserve a unidade original informada pelo usuário.

33. A conversão interna da frequência para MHz deve ser feita somente
    para o parâmetro freq_mhz enviado ao PlanApp.

34. Exemplo:
    "450 MHz" significa 450 MHz.

35. Exemplo:
    "450 Hz" pode ser convertido internamente para
    0.00045 MHz.

36. Exemplo:
    "450 kHz" pode ser convertido internamente para
    0.45 MHz.

37. Exemplo:
    "450 GHz" pode ser convertido internamente para
    450000 MHz.

38. Entretanto, a solicitação original deve continuar sendo apresentada
    como foi informada pelo usuário.

39. Nunca escreva uma unidade que não foi informada pelo usuário.

40. Não escreva:
    "450 MHz (Hz)"
    se o usuário informou apenas "450 Hz".

41. Quando o usuário disser algo como:
    "duas antenas de 10 metros"
    interprete como:
    TX = 10 m
    RX = 10 m.

42. Quando o usuário informar alturas diferentes, preserve
    individualmente TX e RX.

43. Se houver divergência entre o parâmetro solicitado pelo usuário
    e o parâmetro efetivamente utilizado pelo PlanApp, informe
    explicitamente a divergência.

COMPORTAMENTO DA RESPOSTA:

44. A resposta final deve ser clara e objetiva.

45. Não apresente JSON bruto como resposta final quando houver
    informação técnica que possa ser apresentada de forma legível.

46. Use os resultados reais fornecidos pelo PlanApp.

47. Não invente informações ausentes.

48. Não transforme campos técnicos desconhecidos em conceitos conhecidos
    apenas pelo nome.

49. Se um campo não possui definição suficiente, informe que seu
    significado não foi definido nos dados retornados.

50. Quando apropriado, apresente:
    - origem/destino;
    - coordenadas;
    - distância;
    - frequência;
    - alturas das antenas;
    - FSPL;
    - demais resultados técnicos relevantes.

51. Não esconda divergências entre os parâmetros solicitados e utilizados.

52. Não apresente conclusões que não possam ser sustentadas pelos
    resultados retornados pelo PlanApp.

53. A análise deve distinguir claramente dados e interpretação.

54. O mapa é preparado automaticamente depois que os dois pontos
    são geocodificados.

55. A avaliação técnica é executada automaticamente depois da
    geocodificação.

56. Não diga ao usuário para aguardar uma execução futura.

57. Não interrompa o fluxo depois da geocodificação.

58. Depois da avaliação técnica, interprete os resultados retornados.

59. Quando houver FSPL, apresente-o como:
    "FSPL (Free-Space Path Loss)".

60. Não invente unidade para campos que não tenham unidade explícita.

61. Não faça comparações de valores técnicos sem contexto.

62. Não faça afirmações sobre desempenho do enlace sem parâmetros
    suficientes.

63. Não considere apenas FSPL para determinar viabilidade.

64. Não considere apenas distância para determinar viabilidade.

65. Não considere apenas clearance para determinar viabilidade.

66. Não considere apenas difração para determinar viabilidade.

67. Não transforme uma análise parcial em uma conclusão definitiva.

68. Caso o usuário solicite apenas uma informação específica,
    responda diretamente com aquela informação.

69. Caso o usuário solicite uma análise completa, apresente os
    principais resultados disponíveis.

70. Sempre utilize os nomes originais dos campos retornados.

71. Não altere valores numéricos.

72. Não arredonde valores internamente.

73. Arredondamentos apresentados ao usuário devem ser apenas
    formatação visual.

74. Se o PlanApp fornecer valores com casas decimais, preserve a
    precisão disponível quando relevante.

75. Nunca substitua um resultado do PlanApp por uma estimativa própria.

76. Nunca diga que uma ferramenta foi executada se ela não foi realmente
    executada.

77. Nunca invente sucesso de uma ferramenta.

78. Nunca invente erro de uma ferramenta.

79. Se uma ferramenta retornar erro, informe o erro real retornado
    pela ferramenta. Não especule sobre possíveis causas.

80. Se uma ferramenta retornar sucesso, utilize o resultado real.

81. Se houver dados insuficientes para uma conclusão, diga explicitamente
    que os dados disponíveis não são suficientes.

82. O objetivo é produzir uma análise técnica fiel aos dados do PlanApp.

83. Não extrapole além dos resultados.

84. A resposta final deve priorizar precisão técnica sobre interpretações
    genéricas.

85. O resultado técnico retornado pelo PlanApp é diferente da resposta
    textual do assistente.

86. Nunca substitua o resultado técnico real do PlanApp por uma estimativa
    feita pelo modelo.

87. Se evaluate_link retornar erro, não invente distância, FSPL ou outros
    resultados técnicos.

88. Se evaluate_link retornar erro, apresente o erro real e deixe claro
    que a análise técnica não foi concluída.

89. Não diga que um valor foi calculado pelo PlanApp se ele não estiver
    presente no resultado real.

90. Não estime a distância entre as coordenadas quando evaluate_link
    não tiver fornecido uma distância.

91. A aplicação pode executar evaluate_link automaticamente mesmo que
    o modelo não faça uma chamada direta dessa ferramenta.

92. As ferramentas de visualização são controladas exclusivamente pela
    aplicação. O modelo não deve chamá-las diretamente.
"""


    # ========================================================
    # EXTRAÇÃO DOS PARÂMETROS
    # ========================================================

    def extract_link_parameters(self, text):

        parameters = {
            "freq_mhz": DEFAULT_FREQ_MHZ,
            "tx_ha": DEFAULT_TX_HA,
            "rx_ha": DEFAULT_RX_HA,
            "on_rooftop": DEFAULT_ON_ROOFTOP,
        }

        # Reset dos parâmetros solicitados

        self.requested_frequency = None
        self.requested_frequency_unit = None
        self.requested_frequency_text = None
        self.requested_tx_ha = None
        self.requested_rx_ha = None

        # ----------------------------------------------------
        # Frequência
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Duas antenas com mesma altura
        # ----------------------------------------------------

        same_height_patterns = [
            r"duas\s+antenas?\s+de\s+(\d+(?:[.,]\d+)?)\s*(?:m|metros?)",
            r"antenas?\s+de\s+(\d+(?:[.,]\d+)?)\s*(?:m|metros?)",
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
                same_height_match.group(1).replace(",", ".")
            )

            parameters["tx_ha"] = height
            parameters["rx_ha"] = height

            self.requested_tx_ha = height
            self.requested_rx_ha = height

        else:

            # ------------------------------------------------
            # TX / RX separados
            # ------------------------------------------------

            tx_match = re.search(
                r"(?:tx|transmissora?|transmissor)"
                r".{0,30}?"
                r"(\d+(?:[.,]\d+)?)\s*(?:m|metros?)",
                text,
                re.IGNORECASE,
            )

            rx_match = re.search(
                r"(?:rx|receptora?|receptor)"
                r".{0,30}?"
                r"(\d+(?:[.,]\d+)?)\s*(?:m|metros?)",
                text,
                re.IGNORECASE,
            )

            if tx_match:

                height = float(
                    tx_match.group(1).replace(",", ".")
                )

                parameters["tx_ha"] = height
                self.requested_tx_ha = height

            if rx_match:

                height = float(
                    rx_match.group(1).replace(",", ".")
                )

                parameters["rx_ha"] = height
                self.requested_rx_ha = height

        # ----------------------------------------------------
        # Rooftop
        # ----------------------------------------------------

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


    # ========================================================
    # CONEXÃO MCP
    # ========================================================

    async def connect(self):

        self.log(
            "🔌 Conectando ao PlanApp MCP..."
        )

        transport = await self.exit_stack.enter_async_context(
            streamable_http_client(MCP_URL)
        )

        read_stream, write_stream = transport

        self.mcp_session = await self.exit_stack.enter_async_context(
            ClientSession(
                read_stream,
                write_stream,
            )
        )

        await self.mcp_session.initialize()

        tools_result = await self.mcp_session.list_tools()

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


    # ========================================================
    # FERRAMENTAS PARA O OLLAMA
    # ========================================================

    def build_ollama_tools(self):

        tools = []

        for tool in self.mcp_tools:

            # ------------------------------------------------
            # Estas ferramentas são controladas exclusivamente
            # pela aplicação e NÃO pelo modelo.
            # ------------------------------------------------

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


    # ========================================================
    # OLLAMA
    # ========================================================

    async def ollama_chat(self):

        payload = {
            "model": OLLAMA_MODEL,
            "messages": self.messages,
            "tools": self.build_ollama_tools(),
            "stream": False,
            "think": False,
        }

        def do_request():

            response = requests.post(
                f"{OLLAMA_URL}/api/chat",
                json=payload,
                timeout=300,
            )

            response.raise_for_status()

            return response.json()

        return await asyncio.to_thread(
            do_request
        )


    # ========================================================
    # PARSE RESULTADO MCP
    # ========================================================

    def parse_mcp_result(self, result):

        # ----------------------------------------------------
        # Conteúdo estruturado
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Conteúdo textual
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Fallback
        # ----------------------------------------------------

        return result


    # ========================================================
    # DETECÇÃO RECURSIVA DE ERRO
    # ========================================================

    def contains_nested_error(self, value):
        """
        Procura erros em qualquer nível de uma estrutura
        retornada pelo MCP.
        """

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


    # ========================================================
    # DETECÇÃO DE ERRO MCP
    # ========================================================

    def is_mcp_error(self, result, parsed):

        # ----------------------------------------------------
        # Campo padrão isError do MCP
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Erro no payload, inclusive aninhado
        # ----------------------------------------------------

        return self.contains_nested_error(
            parsed
        )


    # ========================================================
    # RESULTADO SEGURO PARA LOG
    # ========================================================

    def make_log_safe(self, value):
        """
        Evita colocar grandes payloads Base64 de imagens no
        painel de log.
        """

        if isinstance(value, dict):

            safe = {}

            for key, child in value.items():

                if (
                    key == "data"
                    and isinstance(child, str)
                    and value.get("kind") == "image"
                ):

                    safe[key] = (
                        f"<base64 image: "
                        f"{len(child)} chars>"
                    )

                else:

                    safe[key] = self.make_log_safe(
                        child
                    )

            return safe

        if isinstance(value, list):

            return [
                self.make_log_safe(child)
                for child in value
            ]

        return value


    # ========================================================
    # RESUMO GEOCODE
    # ========================================================

    def summarize_geocode(self, parsed):

        if not isinstance(parsed, dict):
            return None

        results = parsed.get("results")

        if not results:
            return None

        first = results[0]

        if not isinstance(first, dict):
            return None

        name = first.get("name")

        lat = first.get("lat")
        lon = first.get("lon")

        if lat is None or lon is None:
            return None

        return {
            "name": name,
            "lat": float(lat),
            "lon": float(lon),
        }


    # ========================================================
    # RESUMO EVALUATE
    # ========================================================

    def summarize_evaluate(self, parsed):

        if not isinstance(parsed, dict):
            return None

        if "fspl" in parsed:
            return parsed["fspl"]

        technical = parsed.get(
            "technical"
        )

        if isinstance(technical, dict):

            if "fspl" in technical:
                return technical["fspl"]

        data = parsed.get(
            "data"
        )

        if isinstance(data, dict):

            if "fspl" in data:
                return data["fspl"]

        return None


    # ========================================================
    # REGISTRA PONTO GEOCODIFICADO
    # ========================================================

    def register_geocoded_point(self, parsed):

        point = self.summarize_geocode(
            parsed
        )

        if point is None:

            self.log(
                "⚠️ Não foi possível extrair coordenadas "
                "do resultado da geocodificação."
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


    # ========================================================
    # PREPARAÇÃO DO MAPA
    # ========================================================

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

            self.map = mostrar_mapa_enlace(
                p1["lat"],
                p1["lon"],
                p2["lat"],
                p2["lon"],
            )

            if self.map_callback:

                try:

                    self.map_callback(
                        self.map
                    )

                except Exception as exc:

                    self.log(
                        f"⚠️ Erro ao atualizar mapa: "
                        f"{exc}"
                    )

            self.log(
                "🟢 Mapa preparado."
            )

        except Exception as exc:

            self.log(
                f"❌ Erro ao preparar mapa: "
                f"{exc}"
            )

            self.log_detail(
                f"Erro detalhado ao preparar mapa: "
                f"{exc}"
            )


    # ========================================================
    # VISUALIZAÇÕES AUTOMÁTICAS
    # ========================================================

    async def gerar_visualizacoes(
        self
    ):

        # ----------------------------------------------------
        # Segurança
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Lista determinística.
        #
        # O modelo NÃO escolhe essas visualizações.
        # ----------------------------------------------------

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

                result = await self.execute_mcp_tool(
                    tool_name,
                    arguments,
                )

            except Exception as exc:

                self.log_detail(
                    f"❌ Exceção em {titulo}: "
                    f"{exc}"
                )

                continue

            # ------------------------------------------------
            # Resultado inválido
            # ------------------------------------------------

            if not isinstance(result, dict):

                self.log_detail(
                    f"⚠️ Resultado inválido para "
                    f"{titulo}."
                )

                continue

            # ------------------------------------------------
            # Erro
            # ------------------------------------------------

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
                    f"⚠️ Falha na visualização: "
                    f"{titulo}"
                )

                continue

            # ------------------------------------------------
            # Tipo do resultado
            # ------------------------------------------------

            kind = result.get(
                "kind"
            )

            # ------------------------------------------------
            # Etapas não visuais
            # ------------------------------------------------

            if kind != "image":

                self.log_detail(
                    f"ℹ️ {titulo}: "
                    f"resultado não visualizável."
                )

                continue

            # ------------------------------------------------
            # Base64
            # ------------------------------------------------

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
                        f"imagem decodificada vazia."
                    )

                    continue

                # ------------------------------------------------
                # Cria widget IPython
                # ------------------------------------------------

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

        # ----------------------------------------------------
        # Publica as visualizações para a UI
        # ----------------------------------------------------

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
            f"visualizações geradas."
        )


    # ========================================================
    # EXECUÇÃO DE FERRAMENTA MCP
    # ========================================================

    async def execute_mcp_tool(
        self,
        tool_name,
        arguments,
    ):

        if (
            tool_name == "evaluate_link"
            and self.evaluate_executed
        ):

            self.log(
                "⚠️ evaluate_link já foi executado."
            )

            return self.last_evaluate_result

        self.tool_count += 1

        # ----------------------------------------------------
        # LOG TÉCNICO
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # EXECUTA MCP
        # ----------------------------------------------------

        try:

            result = await self.mcp_session.call_tool(
                tool_name,
                arguments or {},
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
                self.evaluate_error = error_result
                self.last_evaluate_result = error_result

                self.publish_technical_result(
                    error_result
                )

            return error_result

        # ----------------------------------------------------
        # PARSE
        # ----------------------------------------------------

        parsed = self.parse_mcp_result(
            result
        )

        mcp_error = self.is_mcp_error(
            result,
            parsed,
        )

        # ----------------------------------------------------
        # RESULTADO VAI SOMENTE PARA O LOG
        #
        # Imagens Base64 são resumidas para não poluir
        # o painel.
        # ----------------------------------------------------

        self.log_detail(
            "Resultado:"
        )

        safe_parsed = self.make_log_safe(
            parsed
        )

        self.log_detail(
            json.dumps(
                safe_parsed,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )

        # ----------------------------------------------------
        # ERRO
        # ----------------------------------------------------

        if mcp_error:

            self.log_detail(
                "❌ MCP retornou erro."
            )

        # ----------------------------------------------------
        # GEOCODE
        # ----------------------------------------------------

        if tool_name == "geocode_place":

            if not mcp_error:

                self.register_geocoded_point(
                    parsed
                )

                if len(
                    self.geocoded_points
                ) == 2:

                    await self.mostrar_mapa_apos_geocodificacao()

            else:

                self.log(
                    "❌ Falha na geocodificação."
                )

        # ----------------------------------------------------
        # EVALUATE
        # ----------------------------------------------------

        elif tool_name == "evaluate_link":

            self.evaluate_executed = True

            self.last_evaluate_result = parsed

            if mcp_error:

                self.evaluate_error = parsed

                self.log(
                    "❌ A avaliação técnica retornou erro."
                )

                self.publish_technical_result(
                    parsed
                )

            else:

                self.evaluate_error = None

                # ------------------------------------------------
                # ESTE É O RESULTADO TÉCNICO REAL DO PLANAPP
                # ------------------------------------------------

                self.publish_technical_result(
                    parsed
                )

                # ------------------------------------------------
                # VISUALIZAÇÕES AUTOMÁTICAS
                #
                # Somente após evaluate_link OK.
                # ------------------------------------------------

                await self.gerar_visualizacoes()

                fspl = self.summarize_evaluate(
                    parsed
                )

                if fspl is not None:

                    try:

                        self.log(
                            f"📥 FSPL: "
                            f"{float(fspl):.2f} dB"
                        )

                    except Exception:

                        self.log(
                            f"📥 FSPL: {fspl}"
                        )

                else:

                    self.log(
                        "🟢 Avaliação técnica concluída."
                    )

        return parsed


    # ========================================================
    # REGISTER
    # ========================================================

    async def register(self):

        self.log(
            "👤 Registrando usuário no PlanApp..."
        )

        result = await self.execute_mcp_tool(
            "register",
            {
                "user_id": USER_ID,
            },
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


    # ========================================================
    # EVALUATE AUTOMÁTICO
    # ========================================================

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

            parameters = self.link_parameters

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
            "📡 Executando avaliação técnica do enlace..."
        )

        # ----------------------------------------------------
        # Parâmetros técnicos vão para o LOG MCP
        # ----------------------------------------------------

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

        return await self.execute_mcp_tool(
            "evaluate_link",
            arguments,
        )


    # ========================================================
    # CONTEXTO TÉCNICO PARA O QWEN
    # ========================================================

    def append_technical_context(
        self,
        technical_result,
    ):

        effective = {
            "freq_mhz": self.link_parameters.get(
                "freq_mhz"
            ),
            "tx_ha": self.link_parameters.get(
                "tx_ha"
            ),
            "rx_ha": self.link_parameters.get(
                "rx_ha"
            ),
            "on_rooftop": self.link_parameters.get(
                "on_rooftop"
            ),
        }

        requested = {
            "frequency": self.requested_frequency,
            "frequency_unit": self.requested_frequency_unit,
            "frequency_text": self.requested_frequency_text,
            "tx_ha": self.requested_tx_ha,
            "rx_ha": self.requested_rx_ha,
        }

        conversion_text = ""

        if (
            self.requested_frequency is not None
            and self.requested_frequency_unit is not None
        ):

            conversion_text = (
                f"A frequência foi solicitada pelo usuário como "
                f"{self.requested_frequency_text}. "
                f"Apenas internamente ela foi convertida para "
                f"{effective['freq_mhz']} MHz para o parâmetro "
                f"freq_mhz do PlanApp. "
                f"Na resposta ao usuário, preserve a unidade original "
                f"{self.requested_frequency_unit}."
            )

        context = {
            "parametros_solicitados_pelo_usuario": requested,
            "parametros_efetivos_enviados_ao_planapp": effective,
            "conversao_de_frequencia": conversion_text,
            "resultado_tecnico_real_do_planapp": technical_result,
            "regras_de_interpretacao": [
                "Use o resultado real do PlanApp.",
                "Não invente valores.",
                "Não recalcule FSPL.",
                "Não altere unidades.",
                "Não interprete core, fresnel, boundary, "
                "delta_diffra, VV ou d_norm sem definição explícita.",
                "Não conclua viabilidade sem critérios suficientes.",
                "Diferencie parâmetros solicitados dos parâmetros efetivos.",
                "Se o resultado contiver erro, informe o erro real.",
                "Não estime valores técnicos ausentes.",
            ],
        }

        self.messages.append(
            {
                "role": "user",
                "content": (
                    "CONTEXTO TÉCNICO OBTIDO AUTOMATICAMENTE "
                    "PELO PLANAPP.\n\n"
                    + json.dumps(
                        context,
                        ensure_ascii=False,
                        indent=2,
                        default=str,
                    )
                ),
            }
        )


    # ========================================================
    # TURNO DO AGENTE
    # ========================================================

    async def agent_turn(self):

        for iteration in range(
            MAX_AGENT_ITERATIONS
        ):

            self.log_detail(
                f"🤖 Iteração do agente: "
                f"{iteration + 1}/"
                f"{MAX_AGENT_ITERATIONS}"
            )

            response = await self.ollama_chat()

            message = response.get(
                "message",
                {},
            )

            content = message.get(
                "content",
                "",
            )

            tool_calls = message.get(
                "tool_calls",
                [],
            )

            assistant_message = {
                "role": "assistant",
                "content": content,
            }

            if tool_calls:

                assistant_message[
                    "tool_calls"
                ] = tool_calls

            self.messages.append(
                assistant_message
            )

            # ------------------------------------------------
            # Sem chamada de ferramenta
            # ------------------------------------------------

            if not tool_calls:

                # --------------------------------------------
                # Se já temos os dois pontos e a avaliação
                # ainda não ocorreu, a aplicação executa.
                # --------------------------------------------

                if (
                    len(self.geocoded_points) >= 2
                    and not self.evaluate_executed
                ):

                    technical_result = (
                        await self.ensure_evaluate_link(
                            self.link_parameters
                        )
                    )

                    self.append_technical_context(
                        technical_result
                    )

                    continue

                # --------------------------------------------
                # Se evaluate_link terminou com erro,
                # não tentar "consertar" ou inventar.
                # --------------------------------------------

                if self.evaluate_error is not None:

                    return content

                if self.evaluate_executed:

                    return content

                return content

            # ------------------------------------------------
            # Executa chamadas de ferramentas
            # ------------------------------------------------

            for tool_call in tool_calls:

                function = tool_call.get(
                    "function",
                    {},
                )

                tool_name = function.get(
                    "name"
                )

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
                            arguments
                        )

                    except Exception:

                        arguments = {}

                result = await self.execute_mcp_tool(
                    tool_name,
                    arguments,
                )

                self.messages.append(
                    {
                        "role": "tool",
                        "content": json.dumps(
                            result,
                            ensure_ascii=False,
                            default=str,
                        ),
                    }
                )

            # ------------------------------------------------
            # Após as ferramentas
            # ------------------------------------------------

            if (
                len(self.geocoded_points) >= 2
                and not self.evaluate_executed
            ):

                technical_result = (
                    await self.ensure_evaluate_link(
                        self.link_parameters
                    )
                )

                self.append_technical_context(
                    technical_result
                )

                continue

            # ------------------------------------------------
            # Após evaluate_link, uma nova chamada ao modelo
            # produz a resposta final baseada no resultado real.
            # ------------------------------------------------

            if self.evaluate_executed:

                continue

        return (
            "A análise foi executada, mas o modelo atingiu "
            "o limite de processamento da resposta."
        )


    # ========================================================
    # ASK
    # ========================================================

    async def ask(
        self,
        text,
    ):

        # ----------------------------------------------------
        # Log em arquivo desta execução
        # ----------------------------------------------------

        self.start_file_log()
        self.log_detail("Solicitação do usuário:")
        self.log_detail(str(text))

        # ----------------------------------------------------
        # Reset da execução
        # ----------------------------------------------------

        self.messages = []

        self.geocoded_points = []

        self.evaluate_executed = False
        self.last_evaluate_result = None
        self.evaluate_error = None

        self.tool_count = 0
        self.current_stage = 0

        self.map = None

        self.visualizations = []

        # Limpa visualizações da UI imediatamente.

        if self.visualization_callback:

            try:

                self.visualization_callback(
                    []
                )

            except Exception:
                pass

        # ----------------------------------------------------
        # Parâmetros
        # ----------------------------------------------------

        parameters = self.extract_link_parameters(
            text
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

        # ----------------------------------------------------
        # MCP
        # ----------------------------------------------------

        await self.connect()

        register_result = await self.register()

        # Se o registro falhar, não continuar.

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

        # ----------------------------------------------------
        # Mensagens iniciais
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Agente
        # ----------------------------------------------------

        resultado = await self.agent_turn()

        # ----------------------------------------------------
        # Garantia final da avaliação
        # ----------------------------------------------------

        if (
            len(self.geocoded_points) >= 2
            and not self.evaluate_executed
        ):

            technical_result = (
                await self.ensure_evaluate_link(
                    parameters
                )
            )

            self.append_technical_context(
                technical_result
            )

            resultado = await self.agent_turn()

        # ----------------------------------------------------
        # Garantia final do mapa
        # ----------------------------------------------------

        if (
            len(self.geocoded_points) >= 2
            and self.map is None
        ):

            await self.mostrar_mapa_apos_geocodificacao()

        if self.map is not None:

            self.log(
                "🗺️ Mapa disponível."
            )

        # ----------------------------------------------------
        # Resultado técnico
        # ----------------------------------------------------

        if self.evaluate_error is not None:

            self.current_stage = 3

            self.log(
                "🔴 Etapa 3 — Avaliação técnica não concluída"
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
                "🟢 Resultado técnico recebido do PlanApp."
            )

            self.log(
                "🟢 Análise concluída."
            )

        else:

            self.current_stage = 3

            self.log(
                "🔵 Etapa 3 — Interpretando resultados"
            )

            self.log(
                "🟡 Análise concluída sem avaliação técnica."
            )

        self.log_detail("=" * 80)
        self.log_detail("Análise finalizada.")
        if self.log_file_path:
            self.log_detail(f"Arquivo de log: {self.log_file_path}")
        self.log_detail("=" * 80)

        return resultado


    # ========================================================
    # CLOSE
    # ========================================================

    async def close(self):

        try:

            await self.exit_stack.aclose()

        finally:

            self.mcp_session = None
            self.mcp_tools = []
            self.connected = False
            self.close_file_log()