#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:?Informe a versão do SDK}"
INDEX_URL="${CISEI_PACKAGE_INDEX:-http://cisei-packages/simple/}"
DEST="/home/jovyan/work/cisei_workspace/notebooks"

python -m pip install \
  --no-deps --no-cache-dir --upgrade \
  --index-url "$INDEX_URL" \
  --trusted-host cisei-packages \
  "cisei-scenario-sdk==$VERSION"

python -m cisei_scenario_sdk.install_notebooks \
  --destination "$DEST" --update

python - <<'CHECK'
import hashlib
from pathlib import Path
from importlib.resources import files

name = "CISEI_Scenario_Builder.ipynb"
source = files("cisei_scenario_sdk").joinpath("resources/notebooks", name)
target = Path("/home/jovyan/work/cisei_workspace/notebooks") / name

expected = hashlib.sha256(source.read_bytes()).hexdigest()
actual = hashlib.sha256(target.read_bytes()).hexdigest()

if actual != expected:
    raise SystemExit("ERRO: notebook instalado difere do wheel")

print("Notebook instalado:", target)
print("SHA-256:", actual)
CHECK
