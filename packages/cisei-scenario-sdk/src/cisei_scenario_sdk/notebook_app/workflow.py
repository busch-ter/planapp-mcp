import json
import os
import tomllib
import uuid
from .agent import chat, conversation_state
from .validation import validate_profiles, validate_sdk_text
from .offline_validation import validate_project


def confirm(state):
    status = conversation_state(state)
    if not (status.get("valid") and status.get("complete")):
        raise RuntimeError("Cenário inválido ou incompleto.")
    diagnostic = validate_profiles(state)
    if diagnostic["profiles_without_device_definition"]:
        print("AVISO: perfis divergentes:", diagnostic["profiles_without_device_definition"])
    return chat(state, "Confirmo o cenário.")


def generate(state, *, overwrite=False, base_url, workspace):
    status = conversation_state(state)
    for key in ("valid", "complete", "confirmed"):
        if status.get(key) is not True:
            raise RuntimeError(f"Geração bloqueada: {key} não está verdadeiro.")
    if state.scenario_path.exists() and not overwrite:
        raise FileExistsError(f"{state.scenario_path} já existe; habilite substituição explicitamente.")
    text = state.agent.scenario.generate_toml()
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("ScenarioBuilder não retornou TOML.")
    parsed = tomllib.loads(text)
    diagnostic = validate_profiles(state, parsed)
    if diagnostic["profiles_without_device_definition"]:
        raise ValueError("Perfis sem definição: " + ", ".join(diagnostic["profiles_without_device_definition"]))
    state.compiler.read_csv(state.nodes_path)
    report = validate_project(state.project_root, toml_text=text)
    print("=== VALIDAÇÃO LOCAL ===")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if not report["level1_ok"]:
        raise ValueError("Validação local reprovada: " + "; ".join(report["errors"]))
    sdk = validate_sdk_text(state, text, base_url=base_url, workspace=workspace)
    print("=== VALIDAÇÃO DO SDK ===")
    print(json.dumps(sdk, indent=2, ensure_ascii=False, default=str))
    if not sdk["sdk_ok"]:
        raise ValueError("Validação do SDK reprovada: " + "; ".join(map(str, sdk.get("validation_errors", []))))
    # Arquivo temporário exclusivo, sem tocar no original até a validação terminar.
    tmp = state.scenario_path.with_name(f".scenario.{uuid.uuid4().hex}.tmp")
    try:
        with tmp.open("x", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if not overwrite and state.scenario_path.exists():
            raise FileExistsError(state.scenario_path)
        tmp.replace(state.scenario_path)
    finally:
        tmp.unlink(missing_ok=True)
    print("scenario.toml salvo:", state.scenario_path)
    return text
