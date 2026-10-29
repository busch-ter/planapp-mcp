
# ============================================================
# TESTE — SCENARIO AGENT
#
# POC-07a
#
# Valida:
#
#     ScenarioAgent
#          |
#          v
#     ScenarioConversation
#          |
#          v
#     ScenarioSession
#          |
#          v
#     ScenarioBuilder
#          |
#          v
#     PlanningProject
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
#
# DIAGNÓSTICO:
#     - Imprime os dados de antennas e interfaces do golden.
#     - Imprime errors e missing após cada atualização.
#     - Interrompe no primeiro estado inválido, preservando
#       o diagnóstico da seção que provocou a falha.
# ============================================================

from pathlib import Path
import shutil
import tomllib
import pprint

from cisei_planning_sdk.project import PlanningProject
from scenario_agent import ScenarioAgent


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
    / "scenario_agent_poc"
)


def reset_project():
    if PROJECT_PATH.exists():
        shutil.rmtree(PROJECT_PATH)


def load_toml(path: Path):
    return tomllib.loads(
        path.read_text(encoding="utf-8")
    )


def print_diagnostics(result, indent="    "):
    """Imprime os detalhes de validação retornados pelo agente."""

    print(f"{indent}valid:     {result.get('valid')}")
    print(f"{indent}complete:  {result.get('complete')}")
    print(f"{indent}confirmed: {result.get('confirmed')}")

    errors = result.get("errors", [])
    missing = result.get("missing", [])

    print(f"{indent}errors ({len(errors)}):")

    if errors:
        for item in errors:
            print(f"{indent}  - {item}")
    else:
        print(f"{indent}  (nenhum)")

    print(f"{indent}missing ({len(missing)}):")

    if missing:
        for item in missing:
            print(f"{indent}  - {item}")
    else:
        print(f"{indent}  (nenhum)")


def main():
    print("=" * 60)
    print("SCENARIO AGENT — POC-07a — TESTE")
    print("MODO DIAGNÓSTICO")
    print("=" * 60)

    reset_project()

    assert WORKSPACE.exists(), (
        f"Workspace não encontrado: {WORKSPACE}"
    )

    assert GOLDEN_PATH.exists(), (
        f"Golden reference não encontrado: {GOLDEN_PATH}"
    )

    golden_data = load_toml(GOLDEN_PATH)

    # --------------------------------------------------------
    # DIAGNÓSTICO DOS DADOS DE REFERÊNCIA
    # --------------------------------------------------------

    print("\n[DIAGNÓSTICO 0] Dados do golden reference")

    print("\n--- Seções disponíveis ---")
    print(list(golden_data.keys()))

    print("\n--- Antennas ---")
    pprint.pprint(
        golden_data.get("antennas", {}),
        sort_dicts=False,
    )

    print("\n--- Interfaces ---")
    pprint.pprint(
        golden_data.get("interfaces", {}),
        sort_dicts=False,
    )

    print("\n--- Verificação preliminar das referências ---")

    antennas = golden_data.get("antennas", {})
    interfaces = golden_data.get("interfaces", {})

    if not isinstance(antennas, dict):
        print("ERRO: antennas não é um dicionário.")
    if not isinstance(interfaces, dict):
        print("ERRO: interfaces não é um dicionário.")

    if isinstance(antennas, dict) and isinstance(interfaces, dict):
        for interface_name, interface in interfaces.items():
            if not isinstance(interface, dict):
                print(
                    f"ERRO: interfaces.{interface_name} "
                    "não é um dicionário."
                )
                continue

            antenna_id = interface.get("antenna_id")

            print(
                f"  interface={interface_name!r}; "
                f"antenna_id={antenna_id!r}; "
                f"antena_existe={antenna_id in antennas}"
                if antenna_id is not None
                else (
                    f"  interface={interface_name!r}; "
                    "antenna_id ausente"
                )
            )

    # --------------------------------------------------------
    # CRIAÇÃO DO AGENTE
    # --------------------------------------------------------

    project = PlanningProject(PROJECT_PATH)
    agent = ScenarioAgent(project)

    print("\n[1] Agente criado")
    print(f"  projeto:  {agent.project_path}")
    print(f"  scenario: {agent.scenario_path}")
    print(f"  repr:     {agent}")

    assert agent.valid is True
    assert agent.complete is False
    assert agent.confirmed is False

    print("  OK")

    # --------------------------------------------------------
    # ESTADO INICIAL
    # --------------------------------------------------------

    print("\n[2] Estado inicial")

    state = agent.conversation_state()

    print(f"  valid:     {state['valid']}")
    print(f"  complete:  {state['complete']}")
    print(f"  confirmed: {state['confirmed']}")
    print(f"  missing:   {len(state['missing'])}")
    print(f"  next:      {state['next_action']}")

    if state.get("errors"):
        print("  errors:", state["errors"])

    if state.get("missing"):
        print("  campos ausentes:", state["missing"])

    assert state["valid"] is True
    assert state["complete"] is False
    assert state["confirmed"] is False
    assert len(state["missing"]) == 8
    assert state["next_action"] == (
        "collect_missing_fields"
    )

    assert agent.needs_input() is True
    assert agent.needs_confirmation() is False
    assert agent.has_validation_errors() is False

    print("  OK")

    # --------------------------------------------------------
    # PRIMEIRA ATUALIZAÇÃO
    # --------------------------------------------------------

    print("\n[3] Primeira atualização — scenario")

    result = agent.process_update({
        "scenario": golden_data["scenario"]
    })

    print(f"  action:    {result.get('action')}")
    print_diagnostics(result, indent="  ")

    assert result["valid"] is True
    assert result["complete"] is False
    assert result["confirmed"] is False
    assert result["action"] == (
        "collect_missing_fields"
    )

    assert "request" in result
    assert result["request"]["type"] == (
        "missing_fields"
    )

    print("  OK")

    # --------------------------------------------------------
    # CONSTRUÇÃO INCREMENTAL
    # --------------------------------------------------------

    print("\n[4] Construção incremental")

    for section_name in (
        "antennas",
        "interfaces",
        "devices",
        "metrics",
        "instances",
    ):
        print("\n" + "-" * 60)
        print(f"ATUALIZAÇÃO: {section_name}")
        print("-" * 60)

        section_data = golden_data[section_name]

        if section_name == "interfaces":
            print("\nInterfaces enviadas ao agente:")
            pprint.pprint(
                section_data,
                sort_dicts=False,
            )

            print("\nAntennas atualmente presentes no golden:")
            pprint.pprint(
                golden_data.get("antennas", {}),
                sort_dicts=False,
            )

        result = agent.process_update({
            section_name: section_data
        })

        print(f"\n  action: {result.get('action')}")
        print_diagnostics(result, indent="  ")

        if result.get("valid") is not True:
            print("\n" + "!" * 60)
            print(
                f"FALHA IDENTIFICADA NA ATUALIZAÇÃO: "
                f"{section_name}"
            )
            print("!" * 60)

            print(
                "\nEstado atual retornado pelo agente:"
            )
            pprint.pprint(
                agent.conversation_state(),
                sort_dicts=False,
            )

            raise AssertionError(
                f"Agente inválido após atualizar "
                f"'{section_name}'. "
                f"errors={result.get('errors')}; "
                f"missing={result.get('missing')}"
            )

        print(f"\n  Atualização '{section_name}': OK")

    # --------------------------------------------------------
    # CENÁRIO PRONTO PARA CONFIRMAÇÃO
    # --------------------------------------------------------

    assert agent.valid is True
    assert agent.complete is True
    assert agent.confirmed is False

    print("\n[5] Cenário pronto para confirmação")

    state = agent.conversation_state()

    print(f"  action:    {state['next_action']}")
    print(f"  valid:     {state['valid']}")
    print(f"  complete:  {state['complete']}")
    print(f"  confirmed: {state['confirmed']}")
    print(f"  missing:   {state['missing']}")

    if state.get("errors"):
        print("  errors:", state["errors"])

    assert state["valid"] is True
    assert state["complete"] is True
    assert state["confirmed"] is False
    assert state["missing"] == []
    assert state["next_action"] == "confirm"

    assert agent.needs_input() is False
    assert agent.needs_confirmation() is True

    print("  OK")

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    print("\n[6] Resumo")

    summary = agent.build_summary()

    assert summary["valid"] is True
    assert summary["complete"] is True
    assert summary["confirmed"] is False
    assert summary["missing"] == []
    assert summary["scenario"] == golden_data

    print("  resumo contém o cenário completo")
    print("  OK")

    # --------------------------------------------------------
    # PROTEÇÃO CONTRA GERAÇÃO
    # --------------------------------------------------------

    print("\n[7] Geração antes da confirmação")

    try:
        agent.generate_toml()
    except Exception as exc:
        print("  OK — geração bloqueada:")
        print(f"       {exc}")
    else:
        raise AssertionError(
            "generate_toml() deveria exigir confirmação"
        )

    # --------------------------------------------------------
    # CONFIRMAÇÃO
    # --------------------------------------------------------

    print("\n[8] Confirmação explícita")

    result = agent.process_confirmation(True)

    print(f"  action:    {result['action']}")
    print(f"  valid:     {result['valid']}")
    print(f"  complete:  {result['complete']}")
    print(f"  confirmed: {result['confirmed']}")

    if result.get("errors"):
        print("  errors:", result["errors"])

    assert result["action"] == "finalize"
    assert result["valid"] is True
    assert result["complete"] is True
    assert result["confirmed"] is True
    assert agent.confirmed is True

    print("  OK")

    # --------------------------------------------------------
    # GERAÇÃO
    # --------------------------------------------------------

    print("\n[9] Geração do TOML")

    toml_text = agent.generate_toml()

    assert isinstance(toml_text, str)
    assert len(toml_text) > 0

    print(f"  caracteres gerados: {len(toml_text)}")
    print("  OK")

    # --------------------------------------------------------
    # FINALIZAÇÃO
    # --------------------------------------------------------

    print("\n[10] Finalização")

    result = agent.process_finalize()

    print(f"  action:    {result['action']}")
    print(f"  scenario:  {result['scenario_path']}")

    assert result["action"] == "completed"
    assert result["valid"] is True
    assert result["complete"] is True
    assert result["confirmed"] is True

    saved_path = Path(result["scenario_path"])

    assert saved_path.exists()
    assert saved_path == project.scenario_path

    print("  OK")

    # --------------------------------------------------------
    # GOLDEN
    # --------------------------------------------------------

    print("\n[11] Comparação com golden reference")

    generated_data = load_toml(
        project.scenario_path
    )

    assert generated_data == golden_data

    print("  RESULTADO: IDENTICOS")
    print("  OK")

    # --------------------------------------------------------
    # INVALIDAÇÃO
    # --------------------------------------------------------

    print("\n[12] Alteração após confirmação")

    assert agent.confirmed is True

    result = agent.process_update({
        "scenario": {
            "working_crs": "EPSG:31982"
        }
    })

    print(
        f"  confirmed após update: "
        f"{result['confirmed']}"
    )

    if result.get("errors"):
        print("  errors:", result["errors"])

    assert result["confirmed"] is False
    assert agent.confirmed is False

    print("  OK — confirmação invalidada")

    # --------------------------------------------------------
    # NOVA CONFIRMAÇÃO
    # --------------------------------------------------------

    print("\n[13] Nova confirmação")

    result = agent.process_confirmation(True)

    assert result["confirmed"] is True
    assert agent.confirmed is True

    print("  OK")

    # --------------------------------------------------------
    # FINAL
    # --------------------------------------------------------

    print()
    print("=" * 60)
    print("SCENARIO AGENT — POC-07a — TESTE PASSOU")
    print("=" * 60)
    print()
    print("Fluxo validado:")
    print("  ScenarioAgent")
    print("       ↓")
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
    print(f"Projeto:  {project.path}")
    print(f"Scenario: {project.scenario_path}")
    print()


if __name__ == "__main__":
    main()
