import asyncio
import json
import os
import re
from contextlib import AsyncExitStack

import requests

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from map_utils import mostrar_mapa_enlace


# ============================================================
# CONFIGURAÇÃO
# ============================================================

MCP_URL = os.getenv(
    "PLANAPP_MCP_URL",
    "http://172.17.0.1:8010/mcp"
)

OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://172.17.0.1:11434"
)

OLLAMA_MODEL = os.getenv(
    "OLLAMA_MODEL",
    "qwen3:8b"
)

USER_ID = "jupyter-user"


# ============================================================
# PARÂMETROS PADRÃO DO ENLACE
# ============================================================

DEFAULT_FREQ_MHZ = 900
DEFAULT_TX_HA = 7
DEFAULT_RX_HA = 7
DEFAULT_ON_ROOFTOP = False


# ============================================================
# AGENTE
# ============================================================

class PlanAppAgent:

    def __init__(
        self,
        progress_callback=None,
        map_callback=None
    ):

        self.progress_callback = (
            progress_callback
        )

        self.map_callback = (
            map_callback
        )

        self.exit_stack = (
            AsyncExitStack()
        )

        self.mcp_session = None
        self.mcp_tools = []

        self.messages = []

        self.geocoded_points = []

        self.evaluate_executed = False

        self.last_evaluate_result = None

        self.tool_count = 0

        self.current_stage = 0

        self.map = None

        self.connected = False

        # Parâmetros técnicos da solicitação atual
        self.link_parameters = {
            "freq_mhz": DEFAULT_FREQ_MHZ,
            "tx_ha": DEFAULT_TX_HA,
            "rx_ha": DEFAULT_RX_HA,
            "on_rooftop": DEFAULT_ON_ROOFTOP,
        }


    # ========================================================
    # LOG
    # ========================================================

    def log(self, message):

        if self.progress_callback:

            try:

                self.progress_callback(
                    message
                )

            except Exception:
                pass


    # ========================================================
    # SYSTEM PROMPT
    # ========================================================

    def system_prompt(self):
    
        return """
Você é o assistente de planejamento de enlaces de rádio do PlanApp.

Sua função é interpretar solicitações de planejamento de enlaces,
utilizando as ferramentas disponibilizadas pelo PlanApp.

REGRAS IMPORTANTES:

1. PlanApp é a fonte de verdade dos dados técnicos.

2. Nunca invente valores técnicos.

3. Nunca altere valores retornados pelo PlanApp.

4. Nunca recalcule parâmetros técnicos que já tenham sido calculados
   pelo PlanApp.

5. Quando o usuário fornecer dois locais, utilize geocode_place para
   localizar os pontos.

6. Depois que os dois pontos forem geocodificados, a avaliação técnica
   será executada automaticamente pelo sistema.

7. NÃO diga que a avaliação está sendo executada se você ainda não
   recebeu os resultados técnicos do PlanApp.

8. NÃO produza uma resposta intermediária pedindo para o usuário
   aguardar a avaliação.

9. NÃO invente resultados de uma avaliação que ainda não foi fornecida.

10. Não solicite novamente evaluate_link.

11. Não tente executar evaluate_link diretamente.

12. Quando o resultado técnico do PlanApp estiver disponível, utilize
    exclusivamente esse resultado para interpretar o enlace.

13. Preserve exatamente os valores e as unidades retornados pelo
    PlanApp.

14. FSPL significa:
    Free-Space Path Loss
    (Perda de Propagação no Espaço Livre).

15. Não trate clearance como altura de antena.

16. Não diga que um clearance é "adequado", "insuficiente",
    "seguro", "bom", "ruim" ou equivalente sem que exista um
    critério técnico explícito fornecido pelo PlanApp.

17. Não conclua que um enlace é viável ou inviável apenas a partir
    de distância, FSPL, difração ou clearance.

18. Para afirmar viabilidade de um enlace de rádio, são necessários,
    conforme o caso, parâmetros como potência de transmissão,
    ganhos das antenas, frequência, perdas adicionais, sensibilidade
    do receptor e margem de enlace.

19. NÃO atribua significado físico a um campo cujo significado não
    esteja explicitamente informado pelo PlanApp.

20. Quando houver dúvida sobre o significado de um campo, mantenha
    exatamente o nome original do campo e apresente seu valor sem
    criar uma interpretação.

21. Os campos "core", "fresnel" e "boundary", quando presentes nos
    resultados do PlanApp, devem ser tratados como valores retornados
    pelo PlanApp. NÃO os interprete como "área central", "zona de
    Fresnel", "limite da zona de Fresnel", "limite de obstáculos",
    "trecho bloqueado", "extensão de obstáculos" ou qualquer outro
    significado físico que não esteja explicitamente definido pelo
    PlanApp.

22. Um clearance negativo não significa automaticamente que uma
    antena esteja abaixo do solo ou que o enlace seja inviável.

23. O valor de max_obstruction_angle, isoladamente, não comprova que
    exista bloqueio, interferência ou obstáculo crítico no enlace.

24. elevation_angle igual a zero não significa automaticamente que
    TX e RX estejam na mesma altitude, que estejam no mesmo nível ou
    que o enlace seja horizontal.

25. FSPL, isoladamente, não implica que seja necessário aumentar a
    potência de transmissão.

26. Não invente potência, ganho de antena, sensibilidade, perdas ou
    margem de enlace quando esses dados não forem fornecidos.

27. Não transforme valores numéricos retornados pelo PlanApp em
    conclusões qualitativas sem um critério explícito.

28. Diferencie claramente:
    a) parâmetros fornecidos pelo usuário;
    b) resultados calculados e retornados pelo PlanApp;
    c) interpretação técnica desses resultados.

29. Quando a interpretação física de um campo não estiver definida,
    prefira dizer:
    "O PlanApp retornou o campo <nome> com valor <valor>, porém o
    significado físico específico desse campo não está definido nos
    dados disponibilizados."
    Não tente preencher essa lacuna por inferência.

30. Não use conhecimento genérico de engenharia de rádio para atribuir
    automaticamente significado a campos internos ou específicos do
    PlanApp.

31. Não apresente uma hipótese como se fosse um fato.

32. Não use expressões como "isso significa que" quando a relação
    entre o campo e a conclusão não estiver explicitamente estabelecida
    pelos dados do PlanApp.

33. Quando houver dados suficientes para uma interpretação técnica,
    explique-os de forma objetiva e deixe claro quais conclusões são
    efetivamente suportadas pelos resultados.

34. Quando os dados forem insuficientes para uma conclusão, diga
    explicitamente que os dados disponíveis não permitem essa conclusão.

35. Não omita resultados relevantes do PlanApp apenas porque seu
    significado físico não está claro. Nesse caso, apresente o campo
    e seu valor, mas não invente sua interpretação.

36. Responda em português.

37. Seja técnico, objetivo e claro.

38. Não mencione detalhes internos da implementação do agente, MCP ou
    Ollama ao usuário, a menos que ele pergunte explicitamente.

39. PRESERVE O NOME ORIGINAL DOS CAMPOS RETORNADOS PELO PLANAPP.

40. NÃO renomeie um campo técnico para uma descrição física.
    Por exemplo:
    - "core" deve permanecer "core";
    - "fresnel" deve permanecer "fresnel";
    - "boundary" deve permanecer "boundary";
    - "delta_diffra" deve permanecer "delta_diffra";
    - "VV" deve permanecer "VV";
    - "d_norm" deve permanecer "d_norm".

41. NÃO transforme "core", "fresnel" ou "boundary" em "raio da zona
    de Fresnel", "limite da zona de Fresnel", "zona de Fresnel",
    "área central", "trecho de obstrução" ou qualquer outra
    descrição física.

42. NÃO faça cálculos ou comparações entre campos do PlanApp para
    inferir significado físico, a menos que a relação matemática
    esteja explicitamente definida pelo próprio PlanApp.

43. NÃO compare a distância total do enlace com os valores
    "core", "fresnel" ou "boundary" para tirar conclusões sobre
    propagação, obstrução ou zona de Fresnel.

44. NÃO interprete "d_norm" apenas pelo nome. O campo deve ser
    apresentado exatamente como retornado pelo PlanApp, sem afirmar
    que representa posição normalizada, percentual, distância ou
    localização dentro de uma zona, salvo se isso estiver
    explicitamente definido.

45. NÃO interprete "VV" apenas pelo nome. Apresente o valor de VV
    exatamente como retornado pelo PlanApp e não atribua a ele
    automaticamente o significado de "altura do obstáculo",
    "pico de terreno" ou equivalente, salvo se o PlanApp definir
    explicitamente esse significado.

46. NÃO transforme "delta_diffra" em "zona de difração", "raio de
    difração", "perda de difração" ou qualquer outra grandeza física.
    Preserve o nome original e o valor retornado.

47. NÃO conclua que um determinado ponto, pico ou obstáculo está
    "dentro da zona de Fresnel", "fora da zona de Fresnel",
    "interferindo na zona de Fresnel" ou equivalente sem que essa
    relação esteja explicitamente informada pelo PlanApp.

48. NÃO conclua que um terreno, vegetação ou edifício impacta a
    qualidade do sinal somente pela existência de um valor numérico.
    Essa conclusão somente pode ser feita se o PlanApp fornecer
    explicitamente essa interpretação.

49. NÃO use conhecimento genérico de engenharia para preencher o
    significado de campos específicos do PlanApp.

50. Quando o significado de um campo não estiver definido, apresente-o
    desta forma:
    
    "O PlanApp retornou <campo> = <valor>. O significado físico
    específico desse campo não está definido nos dados
    disponibilizados."

51. É permitido organizar os resultados por categoria, mas não é
    permitido alterar a semântica dos campos ao criar os títulos
    ou descrições.

52. A resposta deve distinguir rigorosamente entre:
    - o que o usuário informou;
    - o que o PlanApp retornou;
    - o que pode ser concluído diretamente dos dados;
    - o que NÃO pode ser concluído dos dados.

53. Se uma conclusão exigir uma definição que não foi fornecida pelo
    PlanApp, NÃO faça a conclusão. Informe que a definição é
    necessária.

54. Uma comparação matemática simples entre dois números NÃO autoriza
    uma interpretação física. Por exemplo, o fato de A ser maior ou
    menor que B não significa que exista obstrução, interferência,
    cobertura ou qualquer outro fenômeno físico relacionado a A e B.

55. Não crie títulos como "Zona de Fresnel", "Terreno", "Obstáculos"
    ou "Zona de difração" para campos cujo significado específico
    não esteja definido pelo PlanApp. Quando necessário, use
    "Resultados retornados pelo PlanApp".

56. Quando os dados não forem suficientes para uma interpretação,
    é preferível apresentar menos conclusões e preservar os dados
    originais do que fornecer uma explicação física especulativa.
"""

    # ========================================================
    # EXTRAÇÃO DOS PARÂMETROS DA SOLICITAÇÃO
    # ========================================================

    def extract_link_parameters(self, text):

        parameters = {
            "freq_mhz": DEFAULT_FREQ_MHZ,
            "tx_ha": DEFAULT_TX_HA,
            "rx_ha": DEFAULT_RX_HA,
            "on_rooftop": DEFAULT_ON_ROOFTOP,
        }

        if not text:
            return parameters

        text_lower = text.lower()

        # ----------------------------------------------------
        # FREQUÊNCIA
        #
        # Exemplos:
        # 450 MHz
        # 450mhz
        # frequência de 450 MHz
        # frequência 450 MHz
        # ----------------------------------------------------

        freq_patterns = [
            r"(?:frequ[eê]ncia|freq(?:u[eê]ncia)?)"
            r".{0,30}?"
            r"(\d+(?:[.,]\d+)?)\s*"
            r"(?:mhz|megahertz)",

            r"(\d+(?:[.,]\d+)?)\s*"
            r"(?:mhz|megahertz)",
        ]

        for pattern in freq_patterns:

            match = re.search(
                pattern,
                text_lower,
                re.IGNORECASE
            )

            if match:

                value = match.group(1).replace(
                    ",",
                    "."
                )

                try:

                    parameters["freq_mhz"] = float(
                        value
                    )

                    break

                except ValueError:
                    pass

        # ----------------------------------------------------
        # ANTENAS
        #
        # Exemplos:
        # antenas de 40 metros em tx e rx
        # antenas 40 m em TX e RX
        # TX 40 m e RX 40 m
        # ----------------------------------------------------

        antenna_pattern = (
            r"antenas?\s+"
            r"(?:de\s+)?"
            r"(\d+(?:[.,]\d+)?)\s*"
            r"(?:m|metros?)"
            r".{0,60}?"
            r"(?:em|no|nas)?\s*"
            r"tx\s+e\s+rx"
        )

        match = re.search(
            antenna_pattern,
            text_lower,
            re.IGNORECASE
        )

        if match:

            value = match.group(1).replace(
                ",",
                "."
            )

            try:

                height = float(value)

                parameters["tx_ha"] = height
                parameters["rx_ha"] = height

            except ValueError:
                pass

        else:

            # ------------------------------------------------
            # TX / RX separados
            #
            # Exemplo:
            # TX 40 metros e RX 30 metros
            # ------------------------------------------------

            tx_match = re.search(
                r"\btx\b"
                r".{0,20}?"
                r"(\d+(?:[.,]\d+)?)\s*"
                r"(?:m|metros?)",
                text_lower,
                re.IGNORECASE
            )

            rx_match = re.search(
                r"\brx\b"
                r".{0,20}?"
                r"(\d+(?:[.,]\d+)?)\s*"
                r"(?:m|metros?)",
                text_lower,
                re.IGNORECASE
            )

            if tx_match:

                try:

                    parameters["tx_ha"] = float(
                        tx_match.group(1).replace(
                            ",",
                            "."
                        )
                    )

                except ValueError:
                    pass

            if rx_match:

                try:

                    parameters["rx_ha"] = float(
                        rx_match.group(1).replace(
                            ",",
                            "."
                        )
                    )

                except ValueError:
                    pass

        return parameters


    # ========================================================
    # CONEXÃO MCP
    # ========================================================

    async def connect(self):

        if self.connected:
            return

        self.log(
            "🔌 Conectando ao PlanApp MCP..."
        )

        transport = (
            await self.exit_stack.enter_async_context(
                streamable_http_client(
                    MCP_URL
                )
            )
        )

        read_stream, write_stream = transport

        self.mcp_session = (
            await self.exit_stack.enter_async_context(
                ClientSession(
                    read_stream,
                    write_stream
                )
            )
        )

        await self.mcp_session.initialize()

        tools_result = (
            await self.mcp_session.list_tools()
        )

        self.mcp_tools = (
            tools_result.tools
        )

        self.connected = True

        self.log(
            f"🟢 MCP conectado — "
            f"{len(self.mcp_tools)} ferramentas disponíveis."
        )


    # ========================================================
    # FERRAMENTAS PARA O OLLAMA
    # ========================================================

    def build_ollama_tools(self):

        tools = []

        for tool in self.mcp_tools:

            # register é executado diretamente pelo agente
            if tool.name == "register":
                continue

            # evaluate_link é executado automaticamente pelo agente
            if tool.name == "evaluate_link":
                continue

            input_schema = getattr(
                tool,
                "input_schema",
                None
            )

            if input_schema is None:

                input_schema = getattr(
                    tool,
                    "inputSchema",
                    None
                )

            if input_schema is None:

                input_schema = {
                    "type": "object",
                    "properties": {},
                }

            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": (
                            tool.description
                            or ""
                        ),
                        "parameters": input_schema,
                    },
                }
            )

        return tools


    # ========================================================
    # CHAMADA AO OLLAMA
    # ========================================================

    async def ollama_chat(self):

        payload = {
            "model": OLLAMA_MODEL,
            "messages": self.messages,
            "tools": self.build_ollama_tools(),
            "stream": False,
        }

        response = await asyncio.to_thread(
            requests.post,
            f"{OLLAMA_URL}/api/chat",
            json=payload,
            timeout=300,
        )

        response.raise_for_status()

        return response.json()


    # ========================================================
    # PARSE RESULTADO MCP
    # ========================================================

    def parse_mcp_result(self, result):

        # ----------------------------------------------------
        # MCP moderno
        # ----------------------------------------------------

        if hasattr(
            result,
            "structuredContent"
        ):

            structured = (
                result.structuredContent
            )

            if structured:
                return structured

        # Alguns clientes utilizam structured_content

        if hasattr(
            result,
            "structured_content"
        ):

            structured = (
                result.structured_content
            )

            if structured:
                return structured

        # ----------------------------------------------------
        # Conteúdo textual
        # ----------------------------------------------------

        content = getattr(
            result,
            "content",
            None
        )

        if content:

            texts = []

            for item in content:

                text = getattr(
                    item,
                    "text",
                    None
                )

                if text is not None:

                    texts.append(
                        text
                    )

            if texts:

                text = "\n".join(
                    texts
                )

                try:

                    return json.loads(
                        text
                    )

                except Exception:

                    return {
                        "text": text
                    }

        # ----------------------------------------------------
        # Fallback
        # ----------------------------------------------------

        return result


    # ========================================================
    # RESUMO GEOCODIFICAÇÃO
    # ========================================================

    def summarize_geocode(self, result):

        if not isinstance(
            result,
            dict
        ):
            return None

        # ----------------------------------------------------
        # O geocode_place retorna:
        #
        # {
        #   "status": "OK",
        #   "query": "...",
        #   "results": [
        #       {
        #           "name": "...",
        #           "lat": ...,
        #           "lon": ...
        #       }
        #   ]
        # }
        # ----------------------------------------------------

        point = result

        results = result.get(
            "results"
        )

        if (
            isinstance(results, list)
            and results
            and isinstance(results[0], dict)
        ):

            point = results[0]

        name = (
            point.get("name")
            or point.get("place")
            or result.get("query")
        )

        lat = (
            point.get("lat")
            if point.get("lat") is not None
            else point.get("latitude")
        )

        lon = (
            point.get("lon")
            if point.get("lon") is not None
            else point.get("longitude")
        )

        if lat is not None and lon is not None:

            if name:

                return (
                    f"📍 {name}: "
                    f"{float(lat):.6f}, "
                    f"{float(lon):.6f}"
                )

            return (
                f"📍 Ponto localizado: "
                f"{float(lat):.6f}, "
                f"{float(lon):.6f}"
            )

        return None


    # ========================================================
    # RESUMO EVALUATE
    # ========================================================

    def summarize_evaluate(self, result):

        if not isinstance(
            result,
            dict
        ):
            return None

        fspl = result.get(
            "fspl"
        )

        if fspl is None:

            fspl = result.get(
                "FSPL"
            )

        if fspl is None:

            technical = result.get(
                "technical"
            )

            if isinstance(
                technical,
                dict
            ):

                fspl = technical.get(
                    "fspl"
                )

        return fspl


    # ========================================================
    # REGISTRA PONTO GEOCODIFICADO
    # ========================================================

    def register_geocoded_point(
        self,
        result,
        arguments
    ):

        if not isinstance(
            result,
            dict
        ):
            return

        # ----------------------------------------------------
        # Extrai o primeiro resultado do geocode
        # ----------------------------------------------------

        point_data = result

        results = result.get(
            "results"
        )

        if (
            isinstance(results, list)
            and results
            and isinstance(results[0], dict)
        ):

            point_data = results[0]

        # ----------------------------------------------------
        # Coordenadas
        # ----------------------------------------------------

        lat = (
            point_data.get("lat")
            if point_data.get("lat") is not None
            else point_data.get("latitude")
        )

        lon = (
            point_data.get("lon")
            if point_data.get("lon") is not None
            else point_data.get("longitude")
        )

        if lat is None or lon is None:
            return

        # ----------------------------------------------------
        # Nome
        # ----------------------------------------------------

        name = (
            point_data.get("name")
            or point_data.get("place")
            or result.get("query")
            or arguments.get("query")
            or f"Ponto {len(self.geocoded_points) + 1}"
        )

        point = {
            "name": name,
            "lat": float(lat),
            "lon": float(lon),
        }

        self.geocoded_points.append(
            point
        )

        self.log(
            f"📍 Ponto registrado: "
            f"{name} "
            f"({point['lat']:.6f}, "
            f"{point['lon']:.6f})"
        )


    # ========================================================
    # MAPA
    # ========================================================

    async def mostrar_mapa_apos_geocodificacao(
        self
    ):

        if len(
            self.geocoded_points
        ) < 2:

            return

        self.log(
            "🗺️ Preparando enlace no mapa..."
        )

        try:

            # IMPORTANTE:
            # map_utils.mostrar_mapa_enlace()
            # recebe o agente inteiro.

            self.map = (
                mostrar_mapa_enlace(
                    self
                )
            )

            # ------------------------------------------------
            # ATUALIZA A INTERFACE
            # ------------------------------------------------

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


    # ========================================================
    # EXECUTA FERRAMENTA MCP
    # ========================================================

    async def execute_mcp_tool(
        self,
        tool_name,
        arguments
    ):

        # ----------------------------------------------------
        # Evita evaluate_link duplicado
        # ----------------------------------------------------

        if (
            tool_name == "evaluate_link"
            and self.evaluate_executed
        ):

            self.log(
                "⚠️ evaluate_link já foi executado. "
                "Ignorando chamada duplicada."
            )

            return (
                self.last_evaluate_result
            )

        self.tool_count += 1

        # ----------------------------------------------------
        # STATUS DA TOOL
        # ----------------------------------------------------

        self.log(
            f"🔧 MCP: {tool_name}"
        )

        # ----------------------------------------------------
        # ARGUMENTOS
        # ----------------------------------------------------

        self.log(
            "   Argumentos: "
            + json.dumps(
                arguments or {},
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )

        # ----------------------------------------------------
        # CHAMADA MCP
        # ----------------------------------------------------

        result = (
            await self.mcp_session.call_tool(
                tool_name,
                arguments or {}
            )
        )

        parsed = (
            self.parse_mcp_result(
                result
            )
        )

        # ----------------------------------------------------
        # RESULTADO
        # ----------------------------------------------------

        try:

            self.log(
                "   Resultado: "
                + json.dumps(
                    parsed,
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                )
            )

        except Exception:
            pass

        # ----------------------------------------------------
        # GEOCODE
        # ----------------------------------------------------

        if tool_name == "geocode_place":

            summary = (
                self.summarize_geocode(
                    parsed
                )
            )

            if summary:

                self.log(
                    summary
                )

            self.register_geocoded_point(
                parsed,
                arguments or {}
            )

            # ------------------------------------------------
            # SEGUNDO PONTO
            #
            # O mapa é preparado assim que os dois pontos
            # existem.
            # ------------------------------------------------

            if len(
                self.geocoded_points
            ) >= 2:

                await (
                    self.mostrar_mapa_apos_geocodificacao()
                )

        # ----------------------------------------------------
        # EVALUATE
        # ----------------------------------------------------

        elif tool_name == "evaluate_link":

            self.evaluate_executed = True

            self.last_evaluate_result = (
                parsed
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
                        f"{float(fspl):.2f} dB"
                    )

                except Exception:

                    self.log(
                        f"📥 FSPL: {fspl}"
                    )

        return parsed


    # ========================================================
    # REGISTER
    # ========================================================

    async def register(self):

        self.log(
            "👤 Registrando usuário no PlanApp..."
        )

        result = (
            await self.execute_mcp_tool(
                "register",
                {
                    "user_id": USER_ID
                }
            )
        )

        self.log(
            "🟢 Usuário registrado."
        )

        return result


    # ========================================================
    # EVALUATE AUTOMÁTICO
    # ========================================================

    async def ensure_evaluate_link(
        self
    ):

        if self.evaluate_executed:

            return (
                self.last_evaluate_result
            )

        if len(
            self.geocoded_points
        ) < 2:

            return None

        self.log(
            "📡 Executando avaliação técnica do enlace..."
        )

        tx = (
            self.geocoded_points[0]
        )

        rx = (
            self.geocoded_points[1]
        )

        parameters = (
            self.link_parameters
            or {}
        )

        arguments = {
            "tx_lat": tx["lat"],
            "tx_lon": tx["lon"],
            "rx_lat": rx["lat"],
            "rx_lon": rx["lon"],
            "tx_ha": parameters.get(
                "tx_ha",
                DEFAULT_TX_HA
            ),
            "rx_ha": parameters.get(
                "rx_ha",
                DEFAULT_RX_HA
            ),
            "freq_mhz": parameters.get(
                "freq_mhz",
                DEFAULT_FREQ_MHZ
            ),
            "on_rooftop": parameters.get(
                "on_rooftop",
                DEFAULT_ON_ROOFTOP
            ),
        }

        self.log(
            "📤 Parâmetros enviados ao PlanApp: "
            + json.dumps(
                arguments,
                ensure_ascii=False,
                indent=2,
            )
        )

        result = (
            await self.execute_mcp_tool(
                "evaluate_link",
                arguments
            )
        )

        return result


    # ========================================================
    # CONTEXTO TÉCNICO PARA O QWEN
    # ========================================================

    def append_technical_context(self):

        if self.last_evaluate_result is None:
            return

        resultado_json = json.dumps(
            self.last_evaluate_result,
            ensure_ascii=False,
            indent=2,
            default=str,
        )

        parameters_json = json.dumps(
            self.link_parameters,
            ensure_ascii=False,
            indent=2,
            default=str,
        )

        self.messages.append(
            {
                "role": "user",
                "content": (
                    "A avaliação técnica do enlace já foi "
                    "executada pelo PlanApp.\n\n"

                    "PARÂMETROS DA SOLICITAÇÃO ENVIADOS "
                    "AO PLANAPP:\n"
                    f"{parameters_json}\n\n"

                    "RESULTADO TÉCNICO REAL DO PLANAPP:\n"
                    f"{resultado_json}\n\n"

                    "Agora produza a análise técnica final "
                    "para o usuário.\n\n"

                    "IMPORTANTE:\n"
                    "- Utilize exclusivamente os dados "
                    "retornados pelo PlanApp.\n"
                    "- Não invente valores.\n"
                    "- Não recalcule valores já fornecidos.\n"
                    "- Não solicite novamente evaluate_link.\n"
                    "- Não diga que a avaliação ainda está "
                    "sendo executada.\n"
                    "- Não produza uma resposta de espera.\n"
                    "- Explique claramente os resultados "
                    "disponíveis e suas limitações.\n"
                    "- Se os dados disponíveis não forem "
                    "suficientes para concluir a viabilidade "
                    "do enlace, diga isso explicitamente."
                ),
            }
        )


    # ========================================================
    # TURNO DO AGENTE
    # ========================================================

    async def agent_turn(self):

        for _ in range(12):

            response = (
                await self.ollama_chat()
            )

            message = response.get(
                "message",
                {}
            )

            tool_calls = message.get(
                "tool_calls",
                []
            )

            content = message.get(
                "content",
                ""
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

            # =================================================
            # QWEN NÃO PEDIU TOOL
            # =================================================

            if not tool_calls:

                # -------------------------------------------------
                # Se temos dois pontos, a avaliação TEM que acontecer
                # antes de aceitar qualquer resposta final do Qwen.
                # -------------------------------------------------

                if (
                    len(
                        self.geocoded_points
                    ) >= 2
                    and not self.evaluate_executed
                ):

                    await (
                        self.ensure_evaluate_link()
                    )

                    self.append_technical_context()

                    # O Qwen recebe agora o resultado real e produz
                    # a análise final.
                    continue

                # -------------------------------------------------
                # Se a avaliação já aconteceu, agora sim podemos
                # aceitar a resposta final.
                # -------------------------------------------------

                if self.evaluate_executed:

                    self.current_stage = 3

                    self.log(
                        "🔵 Etapa 3 — "
                        "Interpretando resultados"
                    )

                    return content

                # -------------------------------------------------
                # Ainda não temos dois pontos.
                # -------------------------------------------------

                return content

            # =================================================
            # EXECUTA TOOL CALLS
            # =================================================

            for tool_call in tool_calls:

                function = tool_call.get(
                    "function",
                    {}
                )

                tool_name = function.get(
                    "name"
                )

                arguments = function.get(
                    "arguments",
                    {}
                )

                if isinstance(
                    arguments,
                    str
                ):

                    try:

                        arguments = json.loads(
                            arguments
                        )

                    except Exception:

                        arguments = {}

                result = (
                    await self.execute_mcp_tool(
                        tool_name,
                        arguments
                    )
                )

                # ------------------------------------------------
                # Retorna o resultado da ferramenta ao Qwen.
                # ------------------------------------------------

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

            # =================================================
            # APÓS AS TOOLS
            # =================================================

            if (
                len(
                    self.geocoded_points
                ) >= 2
                and not self.evaluate_executed
            ):

                # ------------------------------------------------
                # O Python executa obrigatoriamente o evaluate.
                # ------------------------------------------------

                await (
                    self.ensure_evaluate_link()
                )

                # ------------------------------------------------
                # Só depois entregamos o resultado real ao Qwen.
                # ------------------------------------------------

                self.append_technical_context()

                # ------------------------------------------------
                # Volta ao Ollama para produzir a análise final.
                # ------------------------------------------------

                continue

        return (
            "O agente atingiu o limite de iterações "
            "sem concluir a análise."
        )


    # ========================================================
    # ASK
    # ========================================================

    async def ask(
        self,
        text
    ):

        # ====================================================
        # RESET DO ESTADO DA ANÁLISE
        # ====================================================

        self.geocoded_points = []

        self.evaluate_executed = False

        self.last_evaluate_result = None

        self.tool_count = 0

        self.current_stage = 0

        self.map = None

        # ----------------------------------------------------
        # Extrai parâmetros técnicos da solicitação
        # ----------------------------------------------------

        self.link_parameters = (
            self.extract_link_parameters(
                text
            )
        )

        self.log(
            "⚙️ Parâmetros detectados: "
            + json.dumps(
                self.link_parameters,
                ensure_ascii=False,
            )
        )

        # ====================================================
        # CONEXÃO
        # ====================================================

        await self.connect()

        # ====================================================
        # REGISTER
        # ====================================================

        await self.register()

        # ====================================================
        # MENSAGENS
        # ====================================================

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

        # ====================================================
        # ETAPA 1
        # ====================================================

        self.current_stage = 1

        self.log(
            "🟡 Etapa 1 — "
            "Processando solicitação"
        )

        # ====================================================
        # AGENTE
        # ====================================================

        result = (
            await self.agent_turn()
        )

        # ====================================================
        # GARANTIA FINAL DA AVALIAÇÃO
        # ====================================================

        if (
            len(
                self.geocoded_points
            ) >= 2
            and not self.evaluate_executed
        ):

            await (
                self.ensure_evaluate_link()
            )

        # ====================================================
        # GARANTIA FINAL DO MAPA
        # ====================================================

        if (
            self.map is None
            and len(
                self.geocoded_points
            ) >= 2
        ):

            await (
                self.mostrar_mapa_apos_geocodificacao()
            )

        # ====================================================
        # STATUS FINAL
        # ====================================================

        self.log(
            "🗺️ Objeto do mapa disponível."
            if self.map is not None
            else "⚠️ Mapa não disponível."
        )

        self.log(
            "🟢 Análise concluída."
        )

        return result


    # ========================================================
    # CLOSE
    # ========================================================

    async def close(self):

        try:

            await self.exit_stack.aclose()

        except Exception:
            pass

        self.connected = False

        self.mcp_session = None

        self.mcp_tools = []