import re
from pathlib import Path
from cisei_scenario_sdk.nodes_compiler import NodesCompiler
from .state import BuilderState


def create_state(name: str, workspace: Path, code_root: Path) -> BuilderState:
    name = str(name).strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name) or ".." in name:
        raise ValueError("Nome de projeto inválido.")
    workspace = Path(workspace)
    project_root = workspace / "projects" / name
    data_root = project_root / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    return BuilderState(workspace, Path(code_root), name, project_root, data_root,
                        project_root / "nodes.csv", project_root / "scenario.toml",
                        NodesCompiler(project_root))


def prepare_nodes(state: BuilderState) -> bool:
    state.nodes_ready = False
    state.preparation_report = None
    if not state.nodes_path.is_file() and not state.compiler.inspect_sources():
        print("Ainda não há fontes suficientes. Carregue arquivos em:", state.data_root)
        return False
    try:
        state.nodes_path = state.compiler.prepare_output(overwrite_existing=False)
        if state.compiler.last_report is None:
            raise RuntimeError("Compilador não produziu relatório.")
        state.preparation_report = state.compiler.last_report.as_dict()
        state.nodes_ready = state.nodes_path.is_file()
        print("=== PREPARAÇÃO DE nodes.csv ===")
        import json
        print(json.dumps(state.preparation_report, indent=2, ensure_ascii=False))
        print("Arquivo:", state.nodes_path)
        return state.nodes_ready
    except Exception as exc:
        print(f"nodes.csv não preparado: {type(exc).__name__}: {exc}")
        for path in state.compiler.inspect_sources():
            print(" -", path)
        return False


def save_uploads(state, entries, *, overwrite=False):
    # Preflight de todos os arquivos antes de escrever qualquer um.
    pending = []
    for item in entries:
        raw_name = str(item.get("name") or "").strip()
        filename = Path(raw_name).name
        if not filename or filename in {".", ".."} or filename != raw_name or "\\" in raw_name:
            raise ValueError(f"Nome inválido: {raw_name!r}")
        content = item.get("content", b"")
        if hasattr(content, "tobytes"):
            content = content.tobytes()
        elif not isinstance(content, bytes):
            content = bytes(content)
        target = state.data_root / filename
        if target.exists():
            if target.read_bytes() == content:
                print("Arquivo idêntico preservado:", filename)
                continue
            if not overwrite:
                raise FileExistsError(f"Arquivo diferente já existe em data/: {filename}")
        pending.append((target, content))
    for target, content in pending:
        target.write_bytes(content)
        print(f"Fonte salva: {target.name} ({len(content)} bytes)")


def uploaded_entries(value):
    if isinstance(value, dict):
        return [dict(metadata, name=metadata.get("name", filename)) for filename, metadata in value.items()]
    if isinstance(value, (tuple, list)):
        return [dict(item) for item in value]
    return []
