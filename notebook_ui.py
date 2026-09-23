import asyncio
import html
import importlib
import json
import re
import traceback
from pathlib import Path

import ipywidgets as widgets
from IPython.display import display, FileLink

import agent_openai
import agent_ollama
import agent_openrouter


# ============================================================
# RELOAD DOS AGENTES
# ============================================================

agent_openai = importlib.reload(
    agent_openai
)

agent_ollama = importlib.reload(
    agent_ollama
)

agent_openrouter = importlib.reload(
    agent_openrouter
)


# ============================================================
# PLANAPP AI
# ============================================================

def iniciar_planapp():

    # ========================================================
    # LOGOTIPO
    # ========================================================

    logo_path = Path(__file__).parent / "vibeplanner_logo.jpeg"

    logo = widgets.Image(
        value=logo_path.read_bytes(),
        format="jpeg",
        layout=widgets.Layout(
            width="180px",
            height="auto",
            margin="0 auto 8px auto",
        ),
    )
    
    # ========================================================
    # TÍTULO
    # ========================================================

    titulo = widgets.HTML(
        value="""
        <h2 style="margin:0 0 10px 0;">
            Planejamento de Enlaces
        </h2>
        """
    )

    # ========================================================
    # SELEÇÃO DO AGENTE
    # ========================================================

    agente_selector = widgets.Dropdown(
        options=[
            (
                "OpenAI (GPT-5.6 Luna)",
                "openai",
            ),
            (
                "Ollama (Qwen 3 8B)",
                "ollama",
            ),
            (
                "OpenRouter",
                "openrouter",
            ),
        ],
        value="openai",
        description="🤖 Agente:",
        layout=widgets.Layout(
            width="350px"
        ),
        style={
            "description_width": "80px"
        },
    )

    # ========================================================
    # ENTRADA
    # ========================================================

    entrada = widgets.Textarea(
        value="",
        placeholder=(
            "Exemplo: Analise um enlace entre "
            "a Praça da República e o Largo "
            "do Paissandu em São Paulo."
        ),
        layout=widgets.Layout(
            width="100%",
            height="90px",
        ),
    )

    # ========================================================
    # BOTÕES
    # ========================================================

    botao_analisar = widgets.Button(
        description="📡 Analisar enlace",
        button_style="primary",
        icon="search",
        layout=widgets.Layout(
            width="180px"
        ),
    )

    botao_relatorio = widgets.Button(
        description="📄 Gerar relatório técnico",
        button_style="success",
        icon="file-text",
        disabled=True,
        layout=widgets.Layout(
            width="220px"
        ),
    )

    botao_nova = widgets.Button(
        description="🔄 Nova análise",
        icon="refresh",
        layout=widgets.Layout(
            width="150px"
        ),
    )

    botoes = widgets.HBox(
        [
            botao_analisar,
            botao_relatorio,
            botao_nova,
        ],
        layout=widgets.Layout(
            margin="8px 0 12px 0"
        ),
    )

    # ========================================================
    # STATUS
    # ========================================================

    status = widgets.HTML(
        value=(
            "<b>Status:</b> "
            "Aguardando solicitação."
        )
    )

    historico_status = widgets.Output(
        layout=widgets.Layout(
            border="1px solid #ddd",
            padding="8px",
            max_height="180px",
            overflow="auto",
            width="100%",
        )
    )

    # ========================================================
    # RESULTADO TÉCNICO
    # ========================================================

    resultado_tecnico_output = widgets.Output(
        layout=widgets.Layout(
            border="1px solid #ddd",
            padding="10px",
            max_height="500px",
            overflow="auto",
            width="100%",
        )
    )

    # ========================================================
    # RELATÓRIO
    # ========================================================

    relatorio_output = widgets.Output(
        layout=widgets.Layout(
            border="1px solid #ddd",
            padding="10px",
            max_height="900px",
            overflow="auto",
            width="100%",
        )
    )

    relatorio_download = widgets.Output(
        layout=widgets.Layout(
            padding="8px 10px",
            width="100%",
        )
    )

    # ========================================================
    # VISUALIZAÇÕES
    # ========================================================

    visualizacoes_output = widgets.VBox(
        [],
        layout=widgets.Layout(
            width="100%"
        ),
    )

    # ========================================================
    # MAPA
    # ========================================================

    mapa_output = widgets.VBox(
        [],
        layout=widgets.Layout(
            width="100%"
        ),
    )

    # ========================================================
    # RESPOSTA FINAL
    #
    # IMPORTANTE:
    # Voltamos a usar HTML aqui.
    #
    # O problema anterior aconteceu porque Output + Markdown
    # estava deixando a renderização da resposta dependente
    # do contexto de display do notebook.
    # ========================================================

    resposta = widgets.HTML(
        value="",
        layout=widgets.Layout(
            width="100%",
            border="1px solid #ddd",
            padding="12px",
            margin="10px 0 0 0",
        ),
    )

    # ========================================================
    # ESTADO
    # ========================================================

    estado = {
        "status_count": 0,
        "visualizacao_count": 0,
        "mapa_count": 0,
        "resultado_count": 0,
        "analise_concluida": False,
        "relatorio_gerado": False,
        "ultimo_resultado": None,
    }

    # ========================================================
    # LIMPAR MARKDOWN GERADO PELO MODELO
    # ========================================================

    def limpar_markdown_resposta(
        texto
    ):

        texto = str(
            texto
        )

        substituicoes = [
            (
                r"\###",
                "###",
            ),
            (
                r"\##",
                "##",
            ),
            (
                r"\#",
                "#",
            ),
            (
                r"\*\*",
                "**",
            ),
            (
                r"\*",
                "*",
            ),
            (
                r"\-",
                "-",
            ),
            (
                r"\`",
                "`",
            ),
        ]

        for origem, destino in substituicoes:

            texto = texto.replace(
                origem,
                destino,
            )

        return texto.strip()

    # ========================================================
    # RENDERIZAR RESPOSTA FINAL
    # ========================================================

    def renderizar_resposta(
        texto
    ):

        if texto is None:

            texto = ""

        texto = str(
            texto
        ).strip()

        # ----------------------------------------------------
        # FALLBACK
        #
        # Caso a chamada ask() tenha retornado vazio, tenta
        # recuperar o último texto produzido pelo agente.
        # ----------------------------------------------------

        if not texto:

            texto_agente = getattr(
                agent,
                "last_agent_text",
                "",
            )

            if texto_agente:

                texto = str(
                    texto_agente
                ).strip()

        if not texto:

            texto = (
                "⚠️ O agente não retornou "
                "texto de análise."
            )

        texto = limpar_markdown_resposta(
            texto
        )

        # ----------------------------------------------------
        # ESCAPE HTML
        # ----------------------------------------------------

        texto = html.escape(
            texto
        )

        # ----------------------------------------------------
        # TÍTULOS
        # ----------------------------------------------------

        texto = re.sub(
            r"^### (.+)$",
            r"<h4 style='margin:14px 0 6px 0;'>\1</h4>",
            texto,
            flags=re.MULTILINE,
        )

        texto = re.sub(
            r"^## (.+)$",
            r"<h3 style='margin:16px 0 7px 0;'>\1</h3>",
            texto,
            flags=re.MULTILINE,
        )

        texto = re.sub(
            r"^# (.+)$",
            r"<h2 style='margin:18px 0 8px 0;'>\1</h2>",
            texto,
            flags=re.MULTILINE,
        )

        # ----------------------------------------------------
        # NEGRITO
        # ----------------------------------------------------

        texto = re.sub(
            r"\*\*(.+?)\*\*",
            r"<b>\1</b>",
            texto,
        )

        # ----------------------------------------------------
        # CÓDIGO INLINE
        # ----------------------------------------------------

        texto = re.sub(
            r"`([^`]+)`",
            r"<code>\1</code>",
            texto,
        )

        # ----------------------------------------------------
        # PROCESSAMENTO DAS LINHAS
        # ----------------------------------------------------

        linhas = texto.split(
            "\n"
        )

        resultado_html = []

        lista_aberta = False

        for linha in linhas:

            linha = linha.strip()

            if linha.startswith(
                "- "
            ):

                if not lista_aberta:

                    resultado_html.append(
                        "<ul style='margin-top:6px;'>"
                    )

                    lista_aberta = True

                resultado_html.append(
                    "<li>"
                    + linha[2:]
                    + "</li>"
                )

            else:

                if lista_aberta:

                    resultado_html.append(
                        "</ul>"
                    )

                    lista_aberta = False

                if linha:

                    resultado_html.append(
                        "<p style='margin:7px 0;'>"
                        + linha
                        + "</p>"
                    )

        if lista_aberta:

            resultado_html.append(
                "</ul>"
            )

        corpo = "\n".join(
            resultado_html
        )

        resposta.value = (
            "<div style='"
            "font-family:Arial,sans-serif;"
            "font-size:14px;"
            "line-height:1.6;"
            "color:#222;"
            "'>"
            "<div style='"
            "font-size:16px;"
            "font-weight:bold;"
            "margin-bottom:12px;"
            "'>"
            "💬 Resposta do PlanApp AI"
            "</div>"
            + corpo
            + "</div>"
        )

    # ========================================================
    # CRIAÇÃO DO AGENTE
    # ========================================================

    def criar_agente(
        tipo_agente
    ):

        if tipo_agente == "openai":

            return agent_openai.PlanAppAgent(
                progress_callback=atualizar_status,
                map_callback=atualizar_mapa,
                result_callback=atualizar_resultado_tecnico,
                visualization_callback=atualizar_visualizacoes,
            )

        if tipo_agente == "ollama":

            return agent_ollama.PlanAppAgent(
                progress_callback=atualizar_status,
                map_callback=atualizar_mapa,
                result_callback=atualizar_resultado_tecnico,
                visualization_callback=atualizar_visualizacoes,
            )

        if tipo_agente == "openrouter":

            return agent_openrouter.PlanAppAgent(
                progress_callback=atualizar_status,
                map_callback=atualizar_mapa,
                result_callback=atualizar_resultado_tecnico,
                visualization_callback=atualizar_visualizacoes,
            )

        raise ValueError(
            f"Agente desconhecido: "
            f"{tipo_agente}"
        )

    # ========================================================
    # CALLBACK — STATUS
    # ========================================================

    def atualizar_status(
        mensagem
    ):

        if mensagem is None:
            return

        texto = str(
            mensagem
        ).strip()

        if not texto:
            return

        # Evita poluir o painel com detalhes internos
        # que já aparecem nos logs do agente.

        mensagens_ignoradas = {
            "=" * 10,
            "=" * 20,
            "=" * 30,
            "=" * 40,
            "=" * 50,
            "=" * 60,
        }

        if texto in mensagens_ignoradas:
            return

        if texto.startswith(
            "MCP TOOL:"
        ):
            return

        if texto.startswith(
            "MCP RESULT:"
        ):
            return

        if texto.startswith(
            "Argumentos:"
        ):
            return

        if texto.startswith(
            "Resultado MCP:"
        ):
            return

        if texto.startswith(
            "Tool:"
        ):
            return

        if texto.startswith(
            "OpenAI response"
        ):
            return

        if texto.startswith(
            "Tokens"
        ):
            return

        estado[
            "status_count"
        ] += 1

        status.value = (
            "<b>Status:</b> "
            + html.escape(
                texto
            )
        )

        try:

            with historico_status:

                print(
                    f"[STATUS #{estado['status_count']}] "
                    f"{texto}"
                )

        except Exception as exc:

            print(
                "[ERRO CALLBACK STATUS] "
                f"{repr(exc)}"
            )

    # ========================================================
    # CALLBACK — RESULTADO TÉCNICO
    # ========================================================

    def atualizar_resultado_tecnico(
        resultado
    ):

        estado[
            "resultado_count"
        ] += 1

        estado[
            "ultimo_resultado"
        ] = resultado

        estado[
            "analise_concluida"
        ] = (
            resultado is not None
        )

        botao_relatorio.disabled = (
            resultado is None
        )

        try:

            resultado_tecnico_output.clear_output(
                wait=True
            )

            with resultado_tecnico_output:

                print(
                    "=================================================="
                )

                print(
                    "📊 RESULTADO TÉCNICO REAL DO PLANAPP"
                )

                print(
                    "=================================================="
                )

                if resultado is None:

                    print(
                        "Nenhum resultado técnico "
                        "foi retornado."
                    )

                    return

                try:

                    print(
                        json.dumps(
                            resultado,
                            ensure_ascii=False,
                            indent=2,
                            default=str,
                        )
                    )

                except Exception:

                    print(
                        str(resultado)
                    )

        except Exception as exc:

            print(
                "[ERRO CALLBACK RESULTADO]"
            )

            print(
                repr(exc)
            )

            traceback.print_exc()

    # ========================================================
    # CALLBACK — MAPA
    # ========================================================

    def atualizar_mapa(
        mapa
    ):

        estado[
            "mapa_count"
        ] += 1

        try:

            mapa_output.children = ()

            if mapa is None:
                return

            if isinstance(
                mapa,
                widgets.Widget,
            ):

                mapa_output.children = (
                    mapa,
                )

                return

            output = widgets.Output(
                layout=widgets.Layout(
                    width="100%"
                )
            )

            with output:

                display(
                    mapa
                )

            mapa_output.children = (
                output,
            )

        except Exception as exc:

            erro = widgets.Output(
                layout=widgets.Layout(
                    width="100%"
                )
            )

            with erro:

                print(
                    "❌ Erro ao exibir mapa:"
                )

                print(
                    repr(exc)
                )

                traceback.print_exc()

            mapa_output.children = (
                erro,
            )

    # ========================================================
    # CONVERSÃO DE VISUALIZAÇÃO
    # ========================================================

    def converter_visualizacao(
        item
    ):

        if isinstance(
            item,
            widgets.Widget,
        ):

            return item

        if isinstance(
            item,
            dict,
        ):

            kind = item.get(
                "kind"
            )

            if kind == "image":

                encoding = item.get(
                    "encoding"
                )

                data = item.get(
                    "data"
                )

                if (
                    encoding == "base64"
                    and data
                ):

                    import base64

                    image_bytes = (
                        base64.b64decode(
                            data
                        )
                    )

                    return widgets.Image(
                        value=image_bytes,
                        format="png",
                        layout=widgets.Layout(
                            width="100%",
                            height="auto",
                        ),
                    )

            texto = json.dumps(
                item,
                ensure_ascii=False,
                indent=2,
                default=str,
            )

            return widgets.HTML(
                value=(
                    "<pre style='"
                    "white-space:pre-wrap;"
                    "margin:10px 0;"
                    "'>"
                    + html.escape(
                        texto
                    )
                    + "</pre>"
                )
            )

        if isinstance(
            item,
            bytes,
        ):

            return widgets.Image(
                value=item,
                format="png",
                layout=widgets.Layout(
                    width="100%",
                    height="auto",
                ),
            )

        return widgets.HTML(
            value=(
                "<pre style='"
                "white-space:pre-wrap;"
                "'>"
                + html.escape(
                    str(item)
                )
                + "</pre>"
            )
        )

    # ========================================================
    # CALLBACK — VISUALIZAÇÕES
    # ========================================================

    def atualizar_visualizacoes(
        imagem,
        titulo=None,
    ):

        estado[
            "visualizacao_count"
        ] += 1

        try:

            if imagem is None:
                return

            # ------------------------------------------------
            # NOVO CONTRATO:
            #
            # agent_openai.py:
            #
            # visualization_callback(
            #     image,
            #     title,
            # )
            #
            # Portanto recebemos UMA imagem por chamada.
            # ------------------------------------------------

            children = list(
                visualizacoes_output.children
            )

            if titulo:

                children.append(
                    widgets.HTML(
                        value=(
                            "<h4 style='"
                            "margin:12px 0 6px 0;'>"
                            + html.escape(
                                str(titulo)
                            )
                            + "</h4>"
                        )
                    )
                )

            widget = (
                converter_visualizacao(
                    imagem
                )
            )

            if widget is not None:

                children.append(
                    widget
                )

            visualizacoes_output.children = (
                tuple(children)
            )

            atualizar_status(
                "🖼️ Visualização exibida: "
                f"{titulo or 'imagem'}"
            )

        except Exception as exc:

            erro = widgets.Output()

            with erro:

                print(
                    "❌ ERRO NO CALLBACK "
                    "DE VISUALIZAÇÕES"
                )

                print(
                    repr(exc)
                )

                traceback.print_exc()

            children = list(
                visualizacoes_output.children
            )

            children.append(
                erro
            )

            visualizacoes_output.children = (
                tuple(children)
            )

    # ========================================================
    # GERAÇÃO DO RELATÓRIO
    # ========================================================

    def gerar_relatorio():

        estado[
            "relatorio_gerado"
        ] = False

        relatorio_output.clear_output(
            wait=True
        )

        relatorio_download.clear_output(
            wait=True
        )

        if (
            estado[
                "ultimo_resultado"
            ] is None
        ):

            with relatorio_output:

                print(
                    "⚠️ Nenhum resultado técnico disponível."
                )

                print(
                    "Execute primeiro uma análise de enlace."
                )

            return

        try:

            atualizar_status(
                "📄 Gerando relatório técnico..."
            )

            # ------------------------------------------------
            # GERAÇÃO PELO AGENTE
            # ------------------------------------------------

            if hasattr(
                agent,
                "build_report",
            ):

                relatorio = (
                    agent.build_report(
                        estado[
                            "ultimo_resultado"
                        ]
                    )
                )

            elif hasattr(
                agent,
                "technical_report",
            ):

                relatorio = (
                    agent.technical_report
                )

            else:

                with relatorio_output:

                    print(
                        "⚠️ Este agente ainda "
                        "não disponibiliza "
                        "a geração de relatório técnico."
                    )

                atualizar_status(
                    "⚠️ Relatório ainda não "
                    "implementado para este agente."
                )

                return

            if not relatorio:

                with relatorio_output:

                    print(
                        "⚠️ O relatório técnico "
                        "não foi gerado."
                    )

                atualizar_status(
                    "⚠️ O relatório técnico "
                    "não foi gerado."
                )

                return

            estado[
                "relatorio_gerado"
            ] = True

            # ------------------------------------------------
            # TEXTO
            # ------------------------------------------------

            with relatorio_output:

                print(
                    "=================================================="
                )

                print(
                    "📄 RELATÓRIO TÉCNICO DO PLANAPP AI"
                )

                print(
                    "=================================================="
                )

                print()

                print(
                    str(relatorio)
                )

                # ------------------------------------------------
                # MAPA
                # ------------------------------------------------

                mapa = getattr(
                    agent,
                    "map",
                    None,
                )

                if mapa is not None:

                    print()
                    print(
                        "=================================================="
                    )

                    print(
                        "🗺️ MAPA DO ENLACE"
                    )

                    print(
                        "=================================================="
                    )

                    try:

                        display(
                            mapa
                        )

                    except Exception as exc:

                        print(
                            "⚠️ Não foi possível "
                            "exibir o mapa:"
                        )

                        print(
                            repr(exc)
                        )

                # ------------------------------------------------
                # VISUALIZAÇÕES
                # ------------------------------------------------

                visualizacoes = getattr(
                    agent,
                    "visualizations",
                    [],
                )

                imagens = getattr(
                    agent,
                    "visualization_images",
                    [],
                )

                if visualizacoes:

                    print()
                    print(
                        "=================================================="
                    )

                    print(
                        "📈 VISUALIZAÇÕES TÉCNICAS"
                    )

                    print(
                        "=================================================="
                    )

                    for index, image in enumerate(
                        visualizacoes
                    ):

                        title = None

                        if (
                            index
                            < len(imagens)
                            and isinstance(
                                imagens[index],
                                dict,
                            )
                        ):

                            title = (
                                imagens[index].get(
                                    "title"
                                )
                            )

                        if title:

                            display(
                                widgets.HTML(
                                    value=(
                                        "<h4 style='"
                                        "margin:12px 0 6px 0;'>"
                                        + html.escape(
                                            str(title)
                                        )
                                        + "</h4>"
                                    )
                                )
                            )

                        try:

                            display(
                                image
                            )

                        except Exception as exc:

                            print(
                                "⚠️ Erro exibindo "
                                f"visualização #{index + 1}: "
                                f"{exc}"
                            )

            # ------------------------------------------------
            # PDF
            # ------------------------------------------------

            pdf_path = getattr(
                agent,
                "report_pdf_path",
                None,
            )

            if pdf_path:

                pdf_path = Path(
                    pdf_path
                )

            if (
                pdf_path
                and pdf_path.exists()
            ):

                tamanho = (
                    pdf_path.stat().st_size
                )

                with relatorio_download:

                    display(
                        widgets.HTML(
                            value=(
                                "<div style='"
                                "padding:10px;"
                                "margin-top:5px;"
                                "border:1px solid #ddd;"
                                "border-radius:6px;"
                                "'>"
                                "<b>📄 Relatório PDF pronto</b>"
                                "<br>"
                                f"<span>{html.escape(pdf_path.name)}</span>"
                                "<br><br>"
                                f"<span>Tamanho: {tamanho:,} bytes</span>"
                                "</div>"
                            )
                        )
                    )

                    display(
                        FileLink(
                            str(pdf_path),
                            result_html_prefix="📥 ",
                            result_html_suffix=(
                                " — Baixar relatório PDF"
                            ),
                        )
                    )

                atualizar_status(
                    "🟢 Relatório técnico gerado "
                    "e PDF disponível para download."
                )

            else:

                with relatorio_download:

                    print(
                        "⚠️ O relatório textual foi "
                        "gerado, mas o arquivo PDF "
                        "não foi localizado."
                    )

                atualizar_status(
                    "⚠️ Relatório gerado, "
                    "mas PDF não localizado."
                )

        except Exception as exc:

            with relatorio_output:

                print(
                    "❌ Erro ao gerar relatório técnico."
                )

                print()

                print(
                    repr(exc)
                )

                traceback.print_exc()

            atualizar_status(
                f"❌ Erro ao gerar relatório: {exc}"
            )

    # ========================================================
    # AGENTE INICIAL
    # ========================================================

    agent = criar_agente(
        agente_selector.value
    )

    agent._planapp_agent_type = (
        agente_selector.value
    )

    # ========================================================
    # EXECUÇÃO DA ANÁLISE
    # ========================================================

    async def executar_analise_async():

        texto = (
            entrada.value.strip()
        )

        if not texto:

            atualizar_status(
                "⚠️ Digite uma solicitação."
            )

            return

        botao_analisar.disabled = True

        botao_relatorio.disabled = True

        agente_selecionado = (
            agente_selector.value
        )

        nonlocal agent

        if agente_selecionado == "openai":

            agente_atual = (
                "OpenAI (GPT-5.6 Luna)"
            )

        elif agente_selecionado == "ollama":

            agente_atual = (
                "Ollama (Qwen 3 8B)"
            )

        elif agente_selecionado == "openrouter":

            agente_atual = (
                "OpenRouter"
            )

        else:

            agente_atual = (
                agente_selecionado
            )

        # ----------------------------------------------------
        # LIMPAR INTERFACE
        # ----------------------------------------------------

        resposta.value = ""

        mapa_output.children = ()

        visualizacoes_output.children = ()

        resultado_tecnico_output.clear_output(
            wait=True
        )

        relatorio_output.clear_output(
            wait=True
        )

        relatorio_download.clear_output(
            wait=True
        )

        historico_status.clear_output(
            wait=True
        )

        estado[
            "ultimo_resultado"
        ] = None

        estado[
            "analise_concluida"
        ] = False

        estado[
            "relatorio_gerado"
        ] = False

        try:

            atualizar_status(
                f"🤖 Agente selecionado: "
                f"{agente_atual}"
            )

            atualizar_status(
                "🟡 Iniciando análise..."
            )

            tipo_atual = getattr(
                agent,
                "_planapp_agent_type",
                None,
            )

            if (
                tipo_atual
                != agente_selecionado
            ):

                try:

                    await agent.close()

                except Exception as exc:

                    print(
                        "Erro fechando agente anterior:",
                        repr(exc),
                    )

                agent = criar_agente(
                    agente_selecionado
                )

                agent._planapp_agent_type = (
                    agente_selecionado
                )

            # ------------------------------------------------
            # CHAMADA DO AGENTE
            # ------------------------------------------------

            resultado = await agent.ask(
                texto
            )

            # ------------------------------------------------
            # RESULTADO FINAL
            #
            # IMPORTANTE:
            # Não usamos Output/Markdown aqui.
            # Renderizamos diretamente no widgets.HTML.
            # ------------------------------------------------

            renderizar_resposta(
                resultado
            )

            atualizar_status(
                "🟢 Análise concluída."
            )

            # ------------------------------------------------
            # HABILITAR RELATÓRIO
            #
            # O callback normalmente já habilita o botão.
            # Aqui fazemos uma verificação adicional.
            # ------------------------------------------------

            if (
                estado[
                    "ultimo_resultado"
                ] is not None
            ):

                botao_relatorio.disabled = False

        except Exception as exc:

            atualizar_status(
                f"❌ Erro na execução: {exc}"
            )

            resposta.value = (
                "<div style='"
                "font-family:Arial,sans-serif;"
                "border:1px solid #d00;"
                "padding:12px;"
                "margin-top:10px;"
                "border-radius:6px;"
                "color:#900;"
                "'>"
                "<b>❌ Erro na execução</b>"
                "<pre style='"
                "white-space:pre-wrap;"
                "margin-top:10px;"
                "'>"
                + html.escape(
                    repr(exc)
                )
                + "</pre>"
                "</div>"
            )

            traceback.print_exc()

        finally:

            botao_analisar.disabled = False

    # ========================================================
    # BOTÃO ANALISAR
    # ========================================================

    def ao_clicar_analisar(
        _
    ):

        try:

            asyncio.ensure_future(
                executar_analise_async()
            )

        except Exception as exc:

            atualizar_status(
                f"❌ Não foi possível iniciar: "
                f"{exc}"
            )

            traceback.print_exc()

    botao_analisar.on_click(
        ao_clicar_analisar
    )

    # ========================================================
    # BOTÃO RELATÓRIO
    # ========================================================

    def ao_clicar_relatorio(
        _
    ):

        botao_relatorio.disabled = True

        try:

            gerar_relatorio()

        finally:

            botao_relatorio.disabled = (
                estado[
                    "ultimo_resultado"
                ] is None
            )

    botao_relatorio.on_click(
        ao_clicar_relatorio
    )

    # ========================================================
    # NOVA ANÁLISE
    # ========================================================

    def nova_analise(
        _
    ):

        nonlocal agent

        entrada.value = ""

        resposta.value = ""

        status.value = (
            "<b>Status:</b> "
            "Aguardando solicitação."
        )

        historico_status.clear_output(
            wait=True
        )

        resultado_tecnico_output.clear_output(
            wait=True
        )

        relatorio_output.clear_output(
            wait=True
        )

        relatorio_download.clear_output(
            wait=True
        )

        mapa_output.children = ()

        visualizacoes_output.children = ()

        estado[
            "ultimo_resultado"
        ] = None

        estado[
            "analise_concluida"
        ] = False

        estado[
            "relatorio_gerado"
        ] = False

        botao_relatorio.disabled = True

        try:

            asyncio.ensure_future(
                agent.close()
            )

        except Exception as exc:

            print(
                "Erro fechando agente anterior:",
                repr(exc),
            )

        try:

            agent = criar_agente(
                agente_selector.value
            )

            agent._planapp_agent_type = (
                agente_selector.value
            )

        except Exception as exc:

            atualizar_status(
                f"❌ Erro criando agente: "
                f"{exc}"
            )

            traceback.print_exc()

            return

        if (
            agente_selector.value
            == "openai"
        ):

            agente_atual = (
                "OpenAI (GPT-5.6 Luna)"
            )

        elif (
            agente_selector.value
            == "ollama"
        ):

            agente_atual = (
                "Ollama (Qwen 3 8B)"
            )

        elif (
            agente_selector.value
            == "openrouter"
        ):

            agente_atual = (
                "OpenRouter"
            )

        else:

            agente_atual = (
                agente_selector.value
            )

        atualizar_status(
            f"🔄 Nova análise pronta — "
            f"{agente_atual}."
        )

    botao_nova.on_click(
        nova_analise
    )

    # ========================================================
    # PAINEL STATUS
    # ========================================================

    painel_status = widgets.VBox(
        [
            #widgets.HTML(
            #    value="<h4>📋 Status</h4>"
            #),
            status,
            historico_status,
        ],
        layout=widgets.Layout(
            width="100%"
        ),
    )

    # ========================================================
    # PAINEL RESULTADO TÉCNICO
    # ========================================================

    painel_resultado = widgets.VBox(
        [
            widgets.HTML(
                value="<h4>📊 Resultado técnico</h4>"
            ),
            resultado_tecnico_output,
        ],
        layout=widgets.Layout(
            width="100%"
        ),
    )

    # ========================================================
    # PAINEL RELATÓRIO
    # ========================================================

    painel_relatorio = widgets.VBox(
        [
            widgets.HTML(
                value="<h4>📄 Relatório técnico</h4>"
            ),
            relatorio_download,
            relatorio_output,
        ],
        layout=widgets.Layout(
            width="100%"
        ),
    )

    # ========================================================
    # PAINEL MAPA
    # ========================================================

    painel_mapa = widgets.VBox(
        [
            widgets.HTML(
                value="<h4>🗺️ Mapa do enlace</h4>"
            ),
            mapa_output,
        ],
        layout=widgets.Layout(
            width="100%"
        ),
    )

    # ========================================================
    # PAINEL VISUALIZAÇÕES
    # ========================================================

    painel_visualizacoes = widgets.VBox(
        [
            widgets.HTML(
                value="<h4>📈 Visualizações técnicas</h4>"
            ),
            visualizacoes_output,
        ],
        layout=widgets.Layout(
            width="100%"
        ),
    )

    # ========================================================
    # PAINEL RESPOSTA
    # ========================================================

    painel_resposta = widgets.VBox(
        [
            widgets.HTML(
                value="<h4>💬 Análise do PlanApp AI</h4>"
            ),
            resposta,
        ],
        layout=widgets.Layout(
            width="100%"
        ),
    )

    # ========================================================
    # EXEMPLOS
    # ========================================================

    exemplos = widgets.HTML(
        value="""
        <div style="
            margin-top:15px;
            padding:10px;
            border:1px solid #ddd;
            border-radius:6px;
        ">
        <b>Exemplos:</b>
        <ul>
            <li>
                Analise um enlace entre a Praça da República
                e o Largo do Paissandu em São Paulo.
            </li>
            <li>
                Analise um enlace entre Curitiba e São José dos Pinhais
                usando 450 MHz.
            </li>
            <li>
                Analise o enlace com duas antenas de 10 metros
                em 2.4 GHz, sobre o telhado.
            </li>
        </ul>
        </div>
        """
    )

    # ========================================================
    # INTERFACE
    # ========================================================

    interface = widgets.VBox(
        [
            logo,

            titulo,

            widgets.HBox(
                [
                    agente_selector
                ],
                layout=widgets.Layout(
                    margin="0 0 8px 0"
                ),
            ),

            entrada,

            botoes,

            painel_status,

            painel_resultado,

            painel_relatorio,

            painel_mapa,

            painel_visualizacoes,

            painel_resposta,

            exemplos,
        ],
        layout=widgets.Layout(
            width="100%"
        ),
    )

    # ========================================================
    # DISPLAY
    # ========================================================

    display(
        interface
    )

    return (
        interface,
        agent,
    )