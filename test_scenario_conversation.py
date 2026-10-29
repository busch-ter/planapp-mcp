# ============================================================
# TESTE — SCENARIO CONVERSATION
#
# Valida a integração:
#
#     ScenarioConversation
#          |
#          +--> ScenarioSession
#          |       |
#          |       +--> ScenarioBuilder
#          |
#          +--> PlanningProject
#          |
#          v
#     scenario.toml
#
# Não utiliza:
#     - OpenAI
#     - Ollama
#     - OpenRouter
#     - MCP
#     - Planning Service
# ============================================================

from pathlib import Path
import shutil
import tomllib

from cisei_planning_sdk.project import PlanningProject
from nodes_compiler import prepare_project_nodes

from scenario_conversation import (
    ScenarioConversation,
    ScenarioConfirmationRequiredError,
    ScenarioNotReadyError,
)


# ============================================================
# CAMINHOS
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
    / "scenario_conversation_poc"
)


# ============================================================
# UTILITÁRIOS
# ============================================================

def reset_project():
    """
    Remove o projeto do teste anterior.
    """

    if PROJECT_PATH.exists():
        shutil.rmtree(PROJECT_PATH)


def load_toml(path: Path):
    """
    Carrega um arquivo TOML.
    """

    return tomllib.loads(
        path.read_text(encoding="utf-8")
    )


# ============================================================
# TESTE PRINCIPAL
# ============================================================

def main():

    print("=" * 60)
    print("SCENARIO CONVERSATION — TESTE")
    print("=" * 60)

    # --------------------------------------------------------
    # 1. Preparação
    # --------------------------------------------------------

    reset_project()

    assert WORKSPACE.exists(), (
        f"Workspace não encontrado: {WORKSPACE}"
    )

    assert GOLDEN_PATH.exists(), (
        f"Golden reference não encontrado: {GOLDEN_PATH}"
    )

    golden_data = load_toml(GOLDEN_PATH)

    # Fonte canônica exclusiva do teste; não usa dados do projeto COPEL.
    source = Path(
        "/home/jovyan/work/cisei_workspace/projects/teste/nodes.csv"
    )
    if not source.is_file():
        raise FileNotFoundError(f"Fonte de teste ausente: {source}")

    test_data = PROJECT_PATH / "data"
    test_data.mkdir(parents=True, exist_ok=True)

    with source.open(encoding="utf-8-sig", newline="") as f:
        header = f.readline()
        first_row = f.readline()

    if not header.strip() or not first_row.strip():
        raise RuntimeError(f"Fonte de teste sem linha de dados: {source}")

    fixture = test_data / "nodes_fixture.csv"
    fixture.write_text(header + first_row, encoding="utf-8")

    nodes_path, report = prepare_project_nodes(PROJECT_PATH)
    print(f"  nodes.csv preparado: {nodes_path}")
    print(f"  estratégia: {report.strategy}")
    print(f"  linhas: {report.rows_written}")

    project = PlanningProject(PROJECT_PATH)

    conversation = ScenarioConversation(project)

    print("\n[1] Conversa criada")

    print("  projeto:")
    print(f"    {project.path}")

    print("  scenario:")
    print(f"    {project.scenario_path}")

    print("  repr:")
    print(f"    {conversation}")

    print("  OK")

    # --------------------------------------------------------
    # 2. Estado inicial
    # --------------------------------------------------------

    print("\n[2] Estado inicial")

    state = conversation.conversation_state()

    print(f"  valid:     {state['valid']}")
    print(f"  complete:  {state['complete']}")
    print(f"  confirmed: {state['confirmed']}")
    print(f"  missing:   {len(state['missing'])}")
    print(f"  next:      {state['next_action']}")

    assert state["valid"] is True
    assert state["complete"] is False
    assert state["confirmed"] is False
    assert len(state["missing"]) == 8
    assert state["next_action"] == (
        "collect_missing_fields"
    )

    print("  OK")

    # --------------------------------------------------------
    # 3. Proteção contra finalização prematura
    # --------------------------------------------------------

    print("\n[3] Proteção contra finalização prematura")

    try:
        conversation.finalize()

    except ScenarioNotReadyError as exc:
        print("  OK — finalização bloqueada:")
        print(f"       {exc}")

    else:
        raise AssertionError(
            "finalize() deveria bloquear cenário incompleto"
        )

    # --------------------------------------------------------
    # 4. Proteção contra confirmação prematura
    # --------------------------------------------------------

    print("\n[4] Proteção contra confirmação prematura")

    try:
        conversation.confirm()

    except Exception as exc:
        print("  confirmação bloqueada:")
        print(f"       {exc}")

    else:
        raise AssertionError(
            "confirm() não deveria confirmar cenário incompleto"
        )

    # --------------------------------------------------------
    # 5. Construção incremental
    # --------------------------------------------------------

    print("\n[5] Construção incremental")

    for section_name, section_data in golden_data.items():

        print(
            f"\n  -> Atualizando seção: "
            f"{section_name}"
        )

        result = conversation.update({
            section_name: section_data
        })

        print(
            f"     valid={result['valid']} "
            f"complete={result['complete']} "
            f"confirmed={result['confirmed']} "
            f"missing={len(result['missing'])}"
        )

        assert result["valid"] is True

    print("\n  Construção incremental: OK")

    # --------------------------------------------------------
    # 6. Estado completo
    # --------------------------------------------------------

    print("\n[6] Estado completo")

    state = conversation.conversation_state()

    print(f"  valid:     {state['valid']}")
    print(f"  complete:  {state['complete']}")
    print(f"  confirmed: {state['confirmed']}")
    print(f"  missing:   {state['missing']}")
    print(f"  next:      {state['next_action']}")

    assert state["valid"] is True
    assert state["complete"] is True
    assert state["confirmed"] is False
    assert state["missing"] == []
    assert state["next_action"] == "confirm"

    print("  OK")

    # --------------------------------------------------------
    # 7. Snapshot do cenário
    # --------------------------------------------------------

    print("\n[7] Snapshot do cenário")

    snapshot = conversation.to_dict()

    assert snapshot == golden_data

    print("  Snapshot estruturalmente idêntico ao golden.")
    print("  OK")

    # --------------------------------------------------------
    # 8. Geração sem confirmação
    # --------------------------------------------------------

    print("\n[8] Proteção contra geração sem confirmação")

    try:
        conversation.generate_toml()

    except ScenarioConfirmationRequiredError as exc:
        print("  OK — geração bloqueada:")
        print(f"       {exc}")

    else:
        raise AssertionError(
            "generate_toml() deveria exigir confirmação"
        )

    # --------------------------------------------------------
    # 9. Save sem confirmação
    # --------------------------------------------------------

    print("\n[9] Proteção contra save sem confirmação")

    try:
        conversation.save()

    except ScenarioConfirmationRequiredError as exc:
        print("  OK — save bloqueado:")
        print(f"       {exc}")

    else:
        raise AssertionError(
            "save() deveria exigir confirmação"
        )

    # --------------------------------------------------------
    # 10. Confirmação
    # --------------------------------------------------------

    print("\n[10] Confirmação explícita")

    result = conversation.confirm()

    print(f"  valid:     {result['valid']}")
    print(f"  complete:  {result['complete']}")
    print(f"  confirmed: {result['confirmed']}")

    assert result["valid"] is True
    assert result["complete"] is True
    assert result["confirmed"] is True

    assert conversation.confirmed is True

    print("  OK")

    # --------------------------------------------------------
    # 11. Geração do TOML
    # --------------------------------------------------------

    print("\n[11] Geração do TOML")

    toml_text = conversation.generate_toml()

    assert isinstance(toml_text, str)
    assert len(toml_text) > 0

    print(
        f"  caracteres gerados: "
        f"{len(toml_text)}"
    )

    print("  OK")

    # --------------------------------------------------------
    # 12. Persistência
    # --------------------------------------------------------

    print("\n[12] Persistência")

    saved_path = conversation.save()

    print("  salvo em:")
    print(f"    {saved_path}")

    assert saved_path.exists()
    assert saved_path == project.scenario_path

    print("  OK")

    # --------------------------------------------------------
    # 13. Comparação com golden
    # --------------------------------------------------------

    print("\n[13] Comparação com golden reference")

    generated_data = load_toml(
        project.scenario_path
    )

    assert generated_data == golden_data

    print("  RESULTADO: IDENTICOS")
    print("  OK")

    # --------------------------------------------------------
    # 14. Invalidação da confirmação
    # --------------------------------------------------------

    print("\n[14] Invalidação após alteração")

    assert conversation.confirmed is True

    result = conversation.update({
        "scenario": {
            "working_crs": "EPSG:31982"
        }
    })

    print(
        "  confirmed após update:",
        result["confirmed"]
    )

    assert result["confirmed"] is False
    assert conversation.confirmed is False

    print("  OK — confirmação invalidada")

    # --------------------------------------------------------
    # 15. Save após alteração
    # --------------------------------------------------------

    print("\n[15] Proteção após alteração")

    try:
        conversation.save()

    except ScenarioConfirmationRequiredError as exc:
        print("  OK — save bloqueado novamente:")
        print(f"       {exc}")

    else:
        raise AssertionError(
            "save() deveria ser bloqueado após alteração "
            "sem nova confirmação"
        )

    # --------------------------------------------------------
    # 16. Nova confirmação
    # --------------------------------------------------------

    print("\n[16] Nova confirmação")

    result = conversation.confirm()

    assert result["valid"] is True
    assert result["complete"] is True
    assert result["confirmed"] is True

    print("  Nova confirmação: OK")

    # --------------------------------------------------------
    # 17. Finalização
    # --------------------------------------------------------

    print("\n[17] Finalização")

    final_path = conversation.finalize()

    print("  finalizado em:")
    print(f"    {final_path}")

    assert final_path.exists()
    assert final_path == project.scenario_path

    print("  OK")

    # --------------------------------------------------------
    # 18. Estado final
    # --------------------------------------------------------

    print("\n[18] Estado final")

    final_state = conversation.conversation_state()

    print(f"  valid:     {final_state['valid']}")
    print(f"  complete:  {final_state['complete']}")
    print(f"  confirmed: {final_state['confirmed']}")
    print(f"  missing:   {final_state['missing']}")
    print(f"  next:      {final_state['next_action']}")

    assert final_state["valid"] is True
    assert final_state["complete"] is True
    assert final_state["confirmed"] is True
    assert final_state["missing"] == []

    # --------------------------------------------------------
    # 19. Resultado
    # --------------------------------------------------------

    print()
    print("=" * 60)
    print("SCENARIO CONVERSATION — TESTE PASSOU")
    print("=" * 60)
    print()
    print(f"Projeto:  {project.path}")
    print(f"Scenario: {project.scenario_path}")
    print()
    print("Fluxo validado:")
    print("  ScenarioConversation")
    print("       ↓")
    print("  ScenarioSession")
    print("       ↓")
    print("  ScenarioBuilder")
    print("       ↓")
    print("  PlanningProject")
    print("       ↓")
    print("  scenario.toml")
    print()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
