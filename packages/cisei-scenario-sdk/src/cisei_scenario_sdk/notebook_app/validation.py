import json
import re
import tomllib
import uuid
from pathlib import Path
from cisei_scenario_sdk.nodes_compiler import NodesCompiler
from cisei_scenario_sdk.scenario_validation import validate_with_planning_sdk


def validate_profiles(state, scenario_data=None):
    rows = state.compiler.read_csv(state.nodes_path)
    if scenario_data is None:
        scenario_data = state.conversation_session.builder.spec
    if not isinstance(scenario_data, dict):
        raise ValueError("Especificação inválida.")
    instances = scenario_data.get("instances", {})
    expected = {"source": "nodes.csv", "format": "csv", "profile_column": "device_profile"}
    if not isinstance(instances, dict) or any(instances.get(k) != v for k, v in expected.items()):
        raise ValueError("[instances] deve referenciar nodes.csv, csv e device_profile.")
    profiles = sorted({str(row.get("device_profile", "")).strip() for row in rows if str(row.get("device_profile", "")).strip()})
    devices = scenario_data.get("devices", {})
    if not isinstance(devices, dict):
        raise ValueError("[devices] inválido.")
    missing = [p for p in profiles if p not in devices]
    return {"rows": len(rows), "profiles_csv": profiles, "devices_defined": sorted(devices),
            "profiles_without_device_definition": missing,
            "warning": "Divergência preservada para revisão; nenhuma correção automática." if missing else None}


def validate_sdk_text(state, toml_text, *, base_url, workspace):
    temp = state.project_root / f".sdk_validation_{uuid.uuid4().hex}.toml"
    try:
        temp.write_text(toml_text, encoding="utf-8")
        result = validate_with_planning_sdk(
            project_path=state.project_root, scenario_path=temp,
            base_url=base_url, workspace=str(workspace), planner="cell", timeout=120.0)
        if not result["cleanup_ok"]:
            result["sdk_ok"] = False
            result.setdefault("validation_errors", []).append(
                "Falha na limpeza do cenário temporário: " + str(result.get("cleanup_error")))
        return result
    finally:
        temp.unlink(missing_ok=True)


def validate_existing(name, projects_root, *, base_url, workspace):
    from cisei_planning_sdk.project import PlanningProject
    from cisei_planning_sdk.client import PlanningClient
    import inspect
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name) or ".." in name:
        raise ValueError("Nome de projeto inválido.")
    project = (Path(projects_root) / name).resolve()
    if project.parent != Path(projects_root).resolve() or not project.is_dir():
        raise FileNotFoundError(project)
    nodes, toml = project / "nodes.csv", project / "scenario.toml"
    if not nodes.is_file() or not toml.is_file():
        raise FileNotFoundError("nodes.csv ou scenario.toml ausente")
    rows = NodesCompiler(project).read_csv(nodes)
    spec = tomllib.loads(toml.read_text(encoding="utf-8"))
    instances = spec.get("instances", {})
    expected = {"source": "nodes.csv", "format": "csv", "profile_column": "device_profile"}
    if not isinstance(instances, dict) or any(instances.get(k) != v for k, v in expected.items()):
        raise ValueError("[instances] incompatível com nodes.csv")
    profiles = sorted({str(r.get("device_profile", "")).strip() for r in rows})
    missing = [p for p in profiles if not p or p not in spec.get("devices", {})]
    if missing:
        raise ValueError("Perfis sem definição em [devices]: " + ", ".join(missing))
    client = PlanningClient(base_url=base_url, workspace=str(workspace), auto_register=True, timeout=120.0)
    signature = inspect.signature(PlanningProject).parameters
    if "path" in signature:
        client.project = PlanningProject(path=project)
    elif "root" in signature:
        client.project = PlanningProject(root=project)
    else:
        raise RuntimeError("Assinatura de PlanningProject não reconhecida")
    validation_id = f"validation_{name}_{uuid.uuid4().hex}"
    session = client.define_scenario(name=validation_id, scenario=toml, planner="cell")
    errors = list(session.validation_errors or [])
    return {"projeto": name, "nodes": len(rows), "perfis": profiles, "toml": str(toml),
            "sdk_ok": bool(session.ok) and not errors, "validation_errors": errors,
            "summary": session.summary, "validation_id": validation_id,
            "observacao": "ID de validação registrado no servidor; não removido automaticamente."}
