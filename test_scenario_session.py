# ============================================================
# TESTE — SCENARIO SESSION
#
# Valida a integração:
#
#     ScenarioSession
#          |
#          +--> ScenarioBuilder
#          |
#          +--> PlanningProject
#
# O teste NÃO executa MCP nem Planning Service.
# ============================================================

from pathlib import Path
import shutil
import tomllib

from cisei_planning_sdk.project import PlanningProject

from scenario_session import ScenarioSession


# ============================================================
# CAMINHOS
# ============================================================

WORKSPACE = Path(
    "/home/jovyan/work/cisei_workspace"
)

GOLDEN = (
    WORKSPACE
    / "projects"
    / "example1_LTE_planning_basic"
    / "scenario.toml"
)

PROJECT_PATH = (
    WORKSPACE
    / "projects"
    / "scenario_session_poc"
)


# ============================================================
# UTILITÁRIOS
# ============================================================

def reset_project():
    """
    Remove o projeto do teste anterior para garantir
    execução limpa e determinística.
    """
    if PROJECT_PATH.exists():
        shutil.rmtree(PROJECT_PATH)


def load_toml(path: Path):
    return tomllib.loads(
        path.read_text(encoding="utf-8")
    )


# ============================================================
# TESTE PRINCIPAL
# ============================================================

def main():

    print("=" * 60)
    print("SCENARIO SESSION — TESTE")
    print("=" * 60)

    # --------------------------------------------------------
    # 1. Preparação
    # --------------------------------------------------------

    reset_project()

    golden_data = load_toml(GOLDEN)

    project = PlanningProject(PROJECT_PATH)

    session = ScenarioSession(project)

    print("\n[1] Sessão inicial")

    status = session.status()

    print("  valid:", status["valid"])
    print("  complete:", status["complete"])
    print("  confirmed:", status["confirmed"])
    print("  missing:", len(status["missing"]))

    assert status["valid"] is True
    assert status["complete"] is False
    assert status["confirmed"] is False
    assert len(status["missing"]) == 8

    print("  OK")

    # --------------------------------------------------------
    # 2. Atualização incremental
    # --------------------------------------------------------

    print("\n[2] Atualização incremental")

    for section_name, section_data in golden_data.items():

        print(f"  -> {section_name}")

        status = session.update({
            section_name: section_data
        })

        print(
            f"     valid={status.valid} "
            f"complete={status.complete} "
            f"missing={len(status.missing)}"
        )

        assert status.valid is True

    print("  OK")

    # --------------------------------------------------------
    # 3. Estado completo
    # --------------------------------------------------------

    print("\n[3] Estado completo")

    status = session.status()

    print("  valid:", status["valid"])
    print("  complete:", status["complete"])
    print("  missing:", status["missing"])
    print("  confirmed:", status["confirmed"])

    assert status["valid"] is True
    assert status["complete"] is True
    assert status["missing"] == []
    assert status["confirmed"] is False

    print("  OK")

    # --------------------------------------------------------
    # 4. Não permitir salvar sem confirmação
    # --------------------------------------------------------

    print("\n[4] Proteção contra save sem confirmação")

    try:
        session.save()

    except RuntimeError as exc:
        print("  OK — save bloqueado:")
        print(f"       {exc}")

    else:
        raise AssertionError(
            "session.save() deveria exigir confirmação"
        )

    # --------------------------------------------------------
    # 5. Não permitir generate_toml sem confirmação
    # --------------------------------------------------------

    print("\n[5] Proteção contra geração sem confirmação")

    try:
        session.generate_toml()

    except RuntimeError as exc:
        print("  OK — geração bloqueada:")
        print(f"       {exc}")

    else:
        raise AssertionError(
            "generate_toml() deveria exigir confirmação"
        )

    # --------------------------------------------------------
    # 6. Confirmação
    # --------------------------------------------------------

    print("\n[6] Confirmação")

    validation = session.confirm()

    print("  valid:", validation.valid)
    print("  complete:", validation.complete)
    print("  confirmed:", session.confirmed)

    assert validation.valid is True
    assert validation.complete is True
    assert session.confirmed is True

    print("  OK")

    # --------------------------------------------------------
    # 7. Geração após confirmação
    # --------------------------------------------------------

    print("\n[7] Geração após confirmação")

    toml_text = session.generate_toml()

    assert isinstance(toml_text, str)
    assert len(toml_text) > 0

    print(f"  caracteres gerados: {len(toml_text)}")
    print("  OK")

    # --------------------------------------------------------
    # 8. Save
    # --------------------------------------------------------

    print("\n[8] Persistência no PlanningProject")

    saved_path = session.save()

    print("  salvo em:")
    print(f"  {saved_path}")

    assert saved_path == project.scenario_path
    assert saved_path.exists()

    print("  OK")

    # --------------------------------------------------------
    # 9. Comparação com golden
    # --------------------------------------------------------

    print("\n[9] Comparação com golden reference")

    generated_data = load_toml(
        project.scenario_path
    )

    assert generated_data == golden_data

    print("  RESULTADO: IDENTICOS")
    print("  OK")

    # --------------------------------------------------------
    # 10. Alteração depois da confirmação
    # --------------------------------------------------------

    print("\n[10] Invalidação após alteração")

    assert session.confirmed is True

    session.update({
        "scenario": {
            "working_crs": "EPSG:31982"
        }
    })

    print(
        "  confirmado após update:",
        session.confirmed
    )

    assert session.confirmed is False

    print("  OK — confirmação invalidada")

    # --------------------------------------------------------
    # 11. Save novamente deve ser bloqueado
    # --------------------------------------------------------

    print("\n[11] Proteção após alteração")

    try:
        session.save()

    except RuntimeError as exc:
        print("  OK — save bloqueado novamente:")
        print(f"       {exc}")

    else:
        raise AssertionError(
            "save() deveria ser bloqueado após alteração "
            "sem nova confirmação"
        )

    # --------------------------------------------------------
    # 12. Finalização
    # --------------------------------------------------------

    print("\n" + "=" * 60)
    print("SCENARIO SESSION — TESTE PASSOU")
    print("=" * 60)
    print()
    print(f"Projeto: {project.path}")
    print(f"Scenario: {project.scenario_path}")
    print()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
