# ============================================================
# TESTE REAL — SCENARIO AGENT OPENAI
#
# POC-08
#
# Testa o ScenarioAgentOpenAI usando GPT-5.6 Luna REAL.
#
# IMPORTANTE:
#
# Este teste:
#
#   - usa OPENAI_API_KEY do ambiente;
#   - usa GPT-5.6 Luna;
#   - NÃO modifica agent_openai.py;
#   - NÃO usa MCP;
#   - NÃO usa Planning Service;
#   - NÃO executa ferramentas externas;
#   - trabalha somente com ScenarioAgent + ScenarioBuilder.
#
# Fluxo:
#
#     Usuário
#        ↓
#     GPT-5.6 Luna
#        ↓
#     ScenarioAgentOpenAI
#        ↓
#     ScenarioAgent
#        ↓
#     ScenarioConversation
#        ↓
#     ScenarioSession
#        ↓
#     ScenarioBuilder
#        ↓
#     PlanningProject
#        ↓
#     scenario.toml
#
# ============================================================

from __future__ import annotations

import json
import os
import shutil
import sys
import tomllib
from pathlib import Path

from cisei_planning_sdk.project import PlanningProject

from scenario_agent_openai import (
    ScenarioAgentOpenAI,
)


# ============================================================
# CONFIGURAÇÃO
# ============================================================

WORKSPACE = Path(
    "/home/jovyan/work/cisei_workspace"
)

GOLDEN_PATH = (
    WORKSPACE
    / "projects"
    / "example1_LTE_planning_basic"
    / "scenario.toml"
)

PROJECT_PATH = (
    WORKSPACE
    / "projects"
    / "scenario_agent_openai_real_poc"
)

MODEL = "gpt-5.6-luna"


# ============================================================
# UTILITÁRIOS
# ============================================================

def reset_project():
    """
    Remove o projeto anterior do POC-08.
    """

    if PROJECT_PATH.exists():
        shutil.rmtree(PROJECT_PATH)


def load_toml(path: Path):
    """
    Carrega um arquivo TOML.
    """

    return tomllib.loads(
        path.read_text(
            encoding="utf-8"
        )
    )


def print_json(
    label: str,
    value,
):
    """
    Imprime JSON de forma legível.
    """

    print(label)

    print(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
        )
    )


def check_environment():
    """
    Verifica pré-requisitos do teste.
    """

    print(
        "\n[1] Verificação do ambiente"
    )

    api_key = os.getenv(
        "OPENAI_API_KEY"
    )

    assert api_key, (
        "OPENAI_API_KEY não está definida."
    )

    assert WORKSPACE.exists(), (
        f"Workspace não encontrado: "
        f"{WORKSPACE}"
    )

    assert GOLDEN_PATH.exists(), (
        f"Golden reference não encontrado: "
        f"{GOLDEN_PATH}"
    )

    print(
        "  OPENAI_API_KEY: definida"
    )

    print(
        f"  openai model: {MODEL}"
    )

    print(
        f"  golden: {GOLDEN_PATH}"
    )

    print("  OK")


# ============================================================
# ENVIO DE MENSAGEM
# ============================================================

def send_message(
    agent: ScenarioAgentOpenAI,
    message: str,
    number: int,
):
    """
    Envia uma mensagem ao agente e imprime
    a resposta estruturada.
    """

    print()
    print(
        "=" * 60
    )

    print(
        f"[INTERAÇÃO {number}]"
    )

    print(
        f"USUÁRIO: {message}"
    )

    print(
        "-" * 60
    )

    result = agent.chat(
        message
    )

    print(
        f"AÇÃO DO AGENTE: "
        f"{result.get('action')}"
    )

    if "question" in result:

        print(
            "PERGUNTA:"
        )

        print(
            result["question"]
        )

    if "result" in result:

        print_json(
            "RESULTADO DA APLICAÇÃO:",
            result["result"],
        )

    state = result.get(
        "state",
        {},
    )

    scenario_state = state.get(
        "scenario_state",
        {},
    )

    print(
        "\nESTADO DA APLICAÇÃO:"
    )

    print(
        f"  valid: "
        f"{scenario_state.get('valid')}"
    )

    print(
        f"  complete: "
        f"{scenario_state.get('complete')}"
    )

    print(
        f"  confirmed: "
        f"{scenario_state.get('confirmed')}"
    )

    print(
        f"  missing: "
        f"{scenario_state.get('missing')}"
    )

    return result


# ============================================================
# TESTE PRINCIPAL
# ============================================================

def main():

    print()
    print("=" * 60)
    print(
        "SCENARIO AGENT OPENAI — "
        "POC-08 — TESTE REAL"
    )
    print("=" * 60)

    # --------------------------------------------------------
    # Ambiente
    # --------------------------------------------------------

    check_environment()

    # --------------------------------------------------------
    # Golden
    # --------------------------------------------------------

    golden_data = load_toml(
        GOLDEN_PATH
    )

    # --------------------------------------------------------
    # Projeto
    # --------------------------------------------------------

    reset_project()

    project = PlanningProject(
        PROJECT_PATH
    )

    print(
        "\n[2] Projeto criado"
    )

    print(
        f"  projeto: {project.path}"
    )

    print(
        f"  scenario: {project.scenario_path}"
    )

    print("  OK")

    # --------------------------------------------------------
    # Agente real
    # --------------------------------------------------------

    agent = ScenarioAgentOpenAI(
        project,
        model=MODEL,
    )

    print(
        "\n[3] ScenarioAgentOpenAI real"
    )

    print(
        f"  model: {agent.model}"
    )

    print(
        f"  client: {type(agent.client).__name__}"
    )

    assert agent.model == MODEL

    assert agent.scenario.valid is True

    assert agent.scenario.complete is False

    assert agent.scenario.confirmed is False

    print("  OK")

    # ========================================================
    # INTERAÇÃO 1
    #
    # Não fornecer parâmetros.
    #
    # O modelo deve pedir informações e NÃO inventar
    # parâmetros técnicos.
    # ========================================================

    result = send_message(
        agent,
        "Quero criar um cenário LTE.",
        1,
    )

    assert result["action"] in {
        "ask_user",
        "update_scenario",
    }

    # --------------------------------------------------------
    # Observação:
    #
    # Para o teste real não vamos exigir textualmente que
    # a primeira resposta seja ask_user, porque o modelo pode
    # organizar a coleta de maneira diferente.
    #
    # O requisito importante é que ele NÃO tenha completado
    # o cenário sem receber os parâmetros.
    # --------------------------------------------------------

    state = (
        agent.scenario
        .conversation_state()
    )

    assert state["complete"] is False, (
        "O modelo completou o cenário sem "
        "receber os parâmetros."
    )

    assert state["confirmed"] is False

    # ========================================================
    # INTERAÇÃO 2
    #
    # Scenario
    # ========================================================

    result = send_message(
        agent,
        "O CRS de trabalho é EPSG:31982.",
        2,
    )

    state = (
        agent.scenario
        .conversation_state()
    )

    assert state["confirmed"] is False

    # ========================================================
    # INTERAÇÃO 3
    #
    # Antenas
    #
    # Fornecemos explicitamente os valores do golden.
    # ========================================================

    antennas_text = json.dumps(
        golden_data["antennas"],
        ensure_ascii=False,
    )

    result = send_message(
        agent,
        (
            "Estas são exatamente as antenas "
            "que quero utilizar no cenário. "
            "Não altere nenhum valor:\n"
            f"{antennas_text}"
        ),
        3,
    )

    state = (
        agent.scenario
        .conversation_state()
    )

    assert state["confirmed"] is False

    # ========================================================
    # INTERAÇÃO 4
    #
    # Interfaces
    # ========================================================

    interfaces_text = json.dumps(
        golden_data["interfaces"],
        ensure_ascii=False,
    )

    result = send_message(
        agent,
        (
            "Estas são exatamente as interfaces "
            "que quero utilizar. "
            "Não altere nenhum valor:\n"
            f"{interfaces_text}"
        ),
        4,
    )

    state = (
        agent.scenario
        .conversation_state()
    )

    assert state["confirmed"] is False

    # ========================================================
    # INTERAÇÃO 5
    #
    # Dispositivos
    # ========================================================

    devices_text = json.dumps(
        golden_data["devices"],
        ensure_ascii=False,
    )

    result = send_message(
        agent,
        (
            "Estes são exatamente os dispositivos "
            "que quero utilizar. "
            "Não altere nenhum valor:\n"
            f"{devices_text}"
        ),
        5,
    )

    state = (
        agent.scenario
        .conversation_state()
    )

    assert state["confirmed"] is False

    # ========================================================
    # INTERAÇÃO 6
    #
    # Métricas
    # ========================================================

    metrics_text = json.dumps(
        golden_data["metrics"],
        ensure_ascii=False,
    )

    result = send_message(
        agent,
        (
            "Esta é exatamente a configuração "
            "de métricas que quero utilizar. "
            "Não altere nenhum valor:\n"
            f"{metrics_text}"
        ),
        6,
    )

    state = (
        agent.scenario
        .conversation_state()
    )

    assert state["confirmed"] is False

    # ========================================================
    # INTERAÇÃO 7
    #
    # Instâncias
    # ========================================================

    instances_text = json.dumps(
        golden_data["instances"],
        ensure_ascii=False,
    )

    result = send_message(
        agent,
        (
            "Estas são exatamente as instâncias "
            "que quero utilizar. "
            "Não altere nenhum valor:\n"
            f"{instances_text}"
        ),
        7,
    )

    state = (
        agent.scenario
        .conversation_state()
    )

    print()
    print(
        "=" * 60
    )

    print(
        "[4] Verificação do cenário após coleta"
    )

    print(
        f"  valid: "
        f"{state['valid']}"
    )

    print(
        f"  complete: "
        f"{state['complete']}"
    )

    print(
        f"  confirmed: "
        f"{state['confirmed']}"
    )

    print(
        f"  missing: "
        f"{state['missing']}"
    )

    assert state["valid"] is True

    assert state["complete"] is True, (
        "O cenário não ficou completo após "
        "o fornecimento dos parâmetros."
    )

    assert state["confirmed"] is False, (
        "O cenário foi confirmado sem "
        "confirmação explícita do usuário."
    )

    assert state["missing"] == []

    print("  OK")

    # ========================================================
    # INTERAÇÃO 8 — CONFIRMAÇÃO
    # ========================================================

    result = send_message(
        agent,
        "Confirmo o cenário. Está correto.",
        8,
    )

    print()
    print(
        "[5] Verificação da confirmação"
    )

    assert result["action"] == (
        "confirm"
    ), (
        "O agente não retornou "
        "'confirm' após confirmação explícita."
    )

    state = (
        agent.scenario
        .conversation_state()
    )

    assert state["valid"] is True

    assert state["complete"] is True

    assert state["confirmed"] is True

    assert state["missing"] == []

    print(
        "  confirmed: True"
    )

    print("  OK")

    # ========================================================
    # INTERAÇÃO 9 — FINALIZAÇÃO
    # ========================================================

    result = send_message(
        agent,
        "Finalize o cenário.",
        9,
    )

    print()
    print(
        "[6] Verificação da finalização"
    )

    assert result["action"] == (
        "finalize"
    ), (
        "O agente não retornou "
        "'finalize' após solicitação explícita."
    )

    assert result["result"]["valid"] is True

    assert result["result"]["complete"] is True

    assert result["result"]["confirmed"] is True

    scenario_path = Path(
        result["result"]["scenario_path"]
    )

    print(
        f"  scenario: {scenario_path}"
    )

    assert scenario_path.exists()

    print("  OK")

    # ========================================================
    # COMPARAÇÃO COM GOLDEN
    # ========================================================

    print()
    print(
        "[7] Comparação com golden reference"
    )

    generated = load_toml(
        scenario_path
    )

    if generated != golden_data:

        print()
        print(
            "ERRO: TOML gerado é diferente "
            "do golden reference."
        )

        print()
        print(
            "GERADO:"
        )

        print(
            json.dumps(
                generated,
                ensure_ascii=False,
                indent=2,
            )
        )

        print()
        print(
            "GOLDEN:"
        )

        print(
            json.dumps(
                golden_data,
                ensure_ascii=False,
                indent=2,
            )
        )

        raise AssertionError(
            "scenario.toml gerado "
            "é diferente do golden."
        )

    print(
        "  RESULTADO: IDENTICOS"
    )

    print("  OK")

    # ========================================================
    # ISOLAMENTO
    # ========================================================

    print()
    print(
        "[8] Verificação do isolamento"
    )

    assert not hasattr(
        agent,
        "mcp"
    )

    assert not hasattr(
        agent,
        "planning_service"
    )

    print(
        "  nenhuma dependência MCP/"
        "Planning Service"
    )

    print("  OK")

    # ========================================================
    # RESULTADO FINAL
    # ========================================================

    print()
    print("=" * 60)

    print(
        "SCENARIO AGENT OPENAI — "
        "POC-08 — TESTE REAL PASSOU"
    )

    print("=" * 60)

    print()

    print(
        "GPT-5.6 Luna conseguiu:"
    )

    print(
        "  ✓ iniciar a conversa"
    )

    print(
        "  ✓ coletar os parâmetros"
    )

    print(
        "  ✓ manter o cenário incompleto "
        "até receber os dados"
    )

    print(
        "  ✓ completar o cenário"
    )

    print(
        "  ✓ aguardar confirmação explícita"
    )

    print(
        "  ✓ confirmar o cenário"
    )

    print(
        "  ✓ finalizar o cenário"
    )

    print(
        "  ✓ gerar scenario.toml"
    )

    print(
        "  ✓ produzir TOML idêntico ao golden"
    )

    print()

    print(
        f"Projeto:  {project.path}"
    )

    print(
        f"Scenario: {project.scenario_path}"
    )

    print()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    try:
        main()

    except KeyboardInterrupt:

        print()
        print(
            "Teste interrompido pelo usuário."
        )

        sys.exit(130)

    except Exception as exc:

        print()
        print("=" * 60)

        print(
            "POC-08 FALHOU"
        )

        print("=" * 60)

        print()
        print(
            f"Erro: {exc}"
        )

        print()

        raise