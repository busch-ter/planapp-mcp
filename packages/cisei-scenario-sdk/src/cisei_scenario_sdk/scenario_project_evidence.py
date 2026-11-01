from __future__ import annotations

"""Leitura conservadora de evidências técnicas do projeto ScenarioBuilder.

Este módulo é somente leitura: não altera data/, nodes.csv ou scenario.toml,
não infere aliases e não escolhe silenciosamente entre valores conflitantes.
"""

import csv
import json
import re
import tomllib
from pathlib import Path
from typing import Any

MAX_FILES = 250
MAX_ROWS_PER_TABLE = 500
MAX_VALUES_PER_FIELD = 500
MAX_TEXT_LINES_PER_FILE = 80
MAX_TEXT_LINE_CHARS = 500

# Chaves literais conhecidas pelo contrato técnico. Não são aliases semânticos.
TECHNICAL_KEYS = {
    "working_crs", "tech", "freq_mhz", "tx_power_dbm", "rx_power_dbm",
    "antenna_id", "model_id", "gain_dbi", "height_m", "mount_height_m",
    "azimuth_deg", "downtilt_deg", "beamwidth_deg", "kind", "rank",
    "profile_column", "source", "format", "connectivity", "candidate_edges",
    "site_id", "device_profile", "lat", "lon", "x", "y", "connected",
    "can_route", "interface_id", "device_id", "metrics", "crs",
    # Chaves literais encontradas nos JSONs da coluna atributos do KMZ.
    "Religador", "Lat_g", "Lon_g",
}
SUPPORTED_TABLE_SUFFIXES = {".csv", ".tsv"}
SUPPORTED_STRUCTURED_SUFFIXES = {".json", ".toml"}
TEXT_SUFFIXES = {".txt", ".md", ".rst", ".log", ".yaml", ".yml", ".ini", ".conf"}


class ProjectEvidenceError(RuntimeError):
    """Falha ao preparar evidências do projeto."""


def _clean_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value.strip() if isinstance(value, str) else value
    if isinstance(value, list):
        return [_clean_value(v) for v in value[:100]]
    if isinstance(value, dict):
        return {str(k): _clean_value(v) for k, v in list(value.items())[:100]}
    return str(value)


def _add_evidence(target: dict[str, list[dict[str, Any]]], key: str,
                  value: Any, source: str, location: str) -> None:
    if key not in TECHNICAL_KEYS or value is None or value == "":
        return
    bucket = target.setdefault(key, [])
    item = {"value": _clean_value(value), "source": source, "location": location}
    if item not in bucket and len(bucket) < MAX_VALUES_PER_FIELD:
        bucket.append(item)


def _walk_structured(obj: Any, *, source: str, location: str,
                     evidence: dict[str, list[dict[str, Any]]], depth: int = 0) -> None:
    if depth > 12:
        return
    if isinstance(obj, dict):
        for key, value in obj.items():
            key_text = str(key)
            child_location = f"{location}.{key_text}" if location else key_text
            if key_text in TECHNICAL_KEYS and not isinstance(value, (dict, list)):
                _add_evidence(evidence, key_text, value, source, child_location)
            _walk_structured(value, source=source, location=child_location,
                             evidence=evidence, depth=depth + 1)
    elif isinstance(obj, list):
        for index, value in enumerate(obj[:MAX_ROWS_PER_TABLE]):
            _walk_structured(value, source=source, location=f"{location}[{index}]",
                             evidence=evidence, depth=depth + 1)


def _read_delimited(path: Path, relative: str,
                    evidence: dict[str, list[dict[str, Any]]],
                    file_summary: dict[str, Any]) -> None:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            sample = handle.read(65536)
        if not sample.strip():
            file_summary[relative] = {"type": "delimited_text", "rows_examined": 0, "status": "empty"}
            return
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel_tab if path.suffix.lower() == ".tsv" else csv.excel
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, dialect=dialect)
            headers = [str(h).strip() for h in (reader.fieldnames or []) if h]
            count = 0
            truncated = False
            for row in reader:
                if count >= MAX_ROWS_PER_TABLE:
                    truncated = True  # uma linha adicional realmente existe
                    break
                count += 1
                for key in headers:
                    if key in TECHNICAL_KEYS:
                        _add_evidence(
                            evidence, key, row.get(key),
                            relative, f"row:{count + 1}.{key}"
                        )

                # A coluna atributos contém JSON serializado em algumas
                # tabelas exportadas do KMZ. Interpretamos apenas as chaves
                # literais conhecidas, mantendo a origem e a linha.
                raw_attributes = row.get("atributos")
                if raw_attributes and raw_attributes.strip():
                    try:
                        attributes = json.loads(raw_attributes)
                    except (json.JSONDecodeError, TypeError):
                        attributes = None

                    if isinstance(attributes, dict):
                        _walk_structured(
                            attributes,
                            source=relative,
                            location=f"row:{count + 1}.atributos",
                            evidence=evidence,
                        )

        file_summary[relative] = {
            "type": "delimited_text", "headers": headers,
            "rows_examined": count,
            "truncated": truncated,
            "status": "ok",
            "recognized_technical_columns": [h for h in headers if h in TECHNICAL_KEYS],
        }
    except (OSError, UnicodeError, csv.Error) as exc:
        file_summary[relative] = {"type": "delimited_text", "status": "read_error", "error": str(exc)[:300]}


def _read_text_lines(path: Path, relative: str,
                     evidence: dict[str, list[dict[str, Any]]],
                     file_summary: dict[str, Any]) -> None:
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
        matches = []
        key_pattern = re.compile(r"(?<![A-Za-z0-9_])(" + "|".join(map(re.escape, sorted(TECHNICAL_KEYS, key=len, reverse=True))) + r")(?![A-Za-z0-9_])\s*[:=]\s*(.+)")
        total_matches = 0
        for number, line in enumerate(lines, start=1):
            match = key_pattern.search(line)
            if not match:
                continue
            key, value = match.group(1), match.group(2).strip()
            value = value.split(" #", 1)[0].strip().rstrip(",")
            if value:
                total_matches += 1
                _add_evidence(evidence, key, value[:MAX_TEXT_LINE_CHARS], relative, f"line:{number}")
                if len(matches) < MAX_TEXT_LINES_PER_FILE:
                    matches.append({"line": number, "text": line[:MAX_TEXT_LINE_CHARS]})
        file_summary[relative] = {"type": "text", "lines": len(lines), "matched_lines": matches,
                                  "truncated_matches": total_matches > MAX_TEXT_LINES_PER_FILE,
                                  "status": "ok"}
    except OSError as exc:
        file_summary[relative] = {"type": "text", "status": "read_error", "error": str(exc)[:300]}


class ScenarioProjectEvidence:
    """Produz um resumo auditável das evidências explícitas do projeto."""

    def __init__(self, project_path: str | Path):
        self.project_path = Path(project_path).resolve()

    def collect(self) -> dict[str, Any]:
        if not self.project_path.is_dir():
            raise ProjectEvidenceError(f"Diretório do projeto não encontrado: {self.project_path}")
        evidence: dict[str, list[dict[str, Any]]] = {}
        files: dict[str, Any] = {}
        paths: list[Path] = []
        nodes_csv = self.project_path / "nodes.csv"
        if nodes_csv.is_file():
            paths.append(nodes_csv)
        data_dir = self.project_path / "data"
        if data_dir.is_dir():
            paths.extend(p for p in data_dir.rglob("*") if p.is_file() and p != nodes_csv)
        # Arquivos auxiliares da raiz são inventariados, mas não entram
        # automaticamente na extração de evidências nem substituem nodes.csv.
        root_auxiliary = sorted(
            (p for p in self.project_path.iterdir()
             if p.is_file() and not p.is_symlink() and p != nodes_csv),
            key=lambda p: p.name.casefold(),
        )
        paths = sorted(set(paths), key=lambda p: p.as_posix().casefold())
        candidates = [nodes_csv] if nodes_csv in paths else []
        candidates += [p for p in paths if p != nodes_csv]
        candidates += root_auxiliary
        total_discovered = len(candidates)
        paths = candidates[:MAX_FILES]

        for path in paths:
            try:
                relative = path.relative_to(self.project_path).as_posix()
            except ValueError:
                continue
            if path.is_symlink():
                files[relative] = {"type": "symlink", "status": "inventoried_only"}
                continue
            if path in root_auxiliary:
                files[relative] = {
                    "type": "auxiliary_root_file", "status": "inventoried_only",
                    "reason": "Arquivo da raiz não é fonte canônica de instâncias",
                }
                continue
            suffix = path.suffix.lower()
            if suffix in SUPPORTED_TABLE_SUFFIXES:
                _read_delimited(path, relative, evidence, files)
            elif suffix in SUPPORTED_STRUCTURED_SUFFIXES:
                try:
                    raw = path.read_bytes()
                    obj = json.loads(raw.decode("utf-8-sig")) if suffix == ".json" else tomllib.loads(raw.decode("utf-8-sig"))
                    _walk_structured(obj, source=relative, location="", evidence=evidence)
                    files[relative] = {"type": suffix[1:], "status": "parsed"}
                except (OSError, UnicodeError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
                    files[relative] = {"type": suffix[1:], "status": "parse_error", "error": str(exc)[:300]}
            elif suffix in TEXT_SUFFIXES:
                _read_text_lines(path, relative, evidence, files)
            else:
                files[relative] = {"type": "unsupported", "status": "inventoried_only"}

        # Valores diferentes em uma coluna não são, por si só, conflitos:
        # por exemplo, cada site possui seu próprio site_id, lat e lon.
        # A detecção de conflitos exige comparar o mesmo parâmetro para a
        # mesma entidade, algo que este coletor ainda não faz.
        conflicts = {}

        return {
            "project_path": str(self.project_path),
            "policy": {
                "read_only": True,
                "values_are_not_defaults": True,
                "no_semantic_alias_inference": True,
                "conflicts_are_not_resolved_automatically": True,
                "files_examined": len(files),
                "file_limit": MAX_FILES,
                "files_discovered": total_discovered,
                "inventory_truncated": total_discovered > MAX_FILES,
                "canonical_instances_source": "nodes.csv" if nodes_csv.is_file() else None,
                "conflict_detection": "not_implemented",
            },
            "technical_evidence": evidence,
            "conflicts": conflicts,
            "conflict_status": {"status": "not_checked_by_collector"},
            "files": files,
            "limitations": [
                "Somente chaves técnicas literais reconhecidas são extraídas; aliases não são inferidos.",
                "PDF, DOCX, XLSX, KML, KMZ, GeoJSON e outros formatos não suportados são apenas inventariados.",
                "Tabelas são limitadas a 500 linhas por arquivo e o inventário a 250 arquivos.",
                "Evidência documental não significa autorização automática para preencher o cenário.",
                "Arquivos auxiliares da raiz são apenas inventariados; nodes.csv continua canônico.",
                "Arquivos .txt são lidos como texto livre, não como tabelas delimitadas.",
                "Conflitos entre valores de uma mesma entidade não são detectados nesta versão.",
            ],
        }


__all__ = ["ScenarioProjectEvidence", "ProjectEvidenceError"]
