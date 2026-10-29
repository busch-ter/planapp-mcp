# ============================================================
# PLANAPP / VIBEPLANNER — SCENARIO SESSION
# ============================================================
from __future__ import annotations

import os
import shutil
import tempfile
import tomllib
from pathlib import Path
from typing import Any

from cisei_planning_sdk.project import PlanningProject
from cisei_scenario_sdk.nodes_compiler import CompilationReport, NodesCompiler
from cisei_scenario_sdk.scenario_builder import ScenarioBuilder, ValidationResult


class ScenarioSession:
    """Coordena a autoria do scenario.toml sobre nodes.csv já preparado.

    Não cria nem recompila nodes.csv. Não chama MCP/Planning Service
    e não executa planejamento.
    """

    def __init__(
        self,
        project: PlanningProject,
        *,
        builder: ScenarioBuilder | None = None,
        nodes_compiler: NodesCompiler | None = None,
        nodes_source: str | None = None,
        prepare_nodes: bool = False,
    ) -> None:
        if not isinstance(project, PlanningProject):
            raise TypeError("project must be an instance of PlanningProject")
        self.project = project
        if nodes_source is None:
            nodes_source = "nodes.csv"

        self._nodes_source = self._normalize_nodes_source(nodes_source)
        self.builder = builder or ScenarioBuilder()
        self.nodes_compiler = nodes_compiler or NodesCompiler(project.path)
        self._confirmed = False
        self._nodes_report: CompilationReport | None = None

        if prepare_nodes:
            # nodes.csv e um artefato derivado de data/.
            # As fontes em data/ permanecem intactas.
            self.nodes_compiler.compile_from_sources(
                output_path=self.nodes_path,
                overwrite=True,
            )

        if not self.nodes_path.is_file():
            raise FileNotFoundError(
                f"{self.nodes_source} ainda não existe em {self.nodes_path}. "
                "A compilacao a partir de data/ nao produziu o arquivo."
            )

        prepared_rows = NodesCompiler.read_csv(self.nodes_path)
        if self.nodes_compiler.last_report is not None:
            self._nodes_report = self.nodes_compiler.last_report
        else:
            self._nodes_report = CompilationReport(
                output_path=str(self.nodes_path),
                selected_sources=(f"{self.nodes_source} (preexistente e validado)",),
                rows_written=len(prepared_rows),
                strategy="validated_existing",
                assessments=tuple(self.nodes_compiler.analyze_sources()),
            )

        self._configure_nodes_input()

    @property
    def confirmed(self) -> bool:
        return self._confirmed

    @property
    def project_path(self) -> Path:
        return Path(self.project.path)

    @property
    def scenario_path(self) -> Path:
        return Path(self.project.scenario_path)

    @staticmethod
    def _normalize_nodes_source(source: str) -> str:
        """Aceita somente um caminho CSV relativo dentro do projeto."""
        if not isinstance(source, str) or not source.strip():
            raise ValueError("nodes_source precisa ser um caminho relativo não vazio.")

        candidate = Path(source.strip())
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("nodes_source deve permanecer dentro do projeto.")
        if candidate.suffix.lower() != ".csv":
            raise ValueError("nodes_source precisa apontar para um arquivo CSV.")

        return candidate.as_posix()

    @property
    def nodes_source(self) -> str:
        return self._nodes_source

    @property
    def nodes_path(self) -> Path:
        path = (self.project_path / self.nodes_source).resolve()
        root = self.project_path.resolve()
        if path == root or root not in path.parents:
            raise ValueError("O CSV precisa estar dentro do diretório do projeto.")
        return path

    @property
    def features_path(self) -> Path:
        return self.project.features_path

    @property
    def result_path(self) -> Path:
        return self.project.result_path

    @property
    def nodes_report(self) -> dict[str, Any] | None:
        return self._nodes_report.as_dict() if self._nodes_report else None

    def inspect_node_sources(self) -> list[dict[str, Any]]:
        """Inspeciona data/ sem gerar arquivos nem modificar entradas."""
        return [
            {
                "path": assessment.path,
                "recognized_columns": list(assessment.recognized_columns),
                "rows": assessment.rows,
                "usable": assessment.usable,
                "reason": assessment.reason,
            }
            for assessment in self.nodes_compiler.analyze_sources()
        ]

    def status(self) -> dict[str, Any]:
        validation = self.validate()
        return {
            "valid": validation.valid,
            "complete": validation.complete,
            "missing": list(validation.missing),
            "errors": list(validation.errors),
            "warnings": self.compatibility_warnings(),
            "confirmed": self.confirmed,
            "project": str(self.project_path),
            "scenario": str(self.scenario_path),
            "nodes_output": str(self.nodes_path),
            "nodes_ready": self.nodes_path.is_file(),
            "nodes_report": self.nodes_report,
        }

    def validate(self) -> ValidationResult:
        """Valida a especificação contra o CSV efetivamente configurado."""
        base = self.builder.validate()
        missing = list(base.missing)
        errors = list(base.errors)

        try:
            instances = self.builder.spec.get("instances", {})
            if not isinstance(instances, dict):
                errors.append("instances precisa ser uma tabela.")
            else:
                if instances.get("source") != self.nodes_source:
                    errors.append(
                        f"instances.source precisa ser {self.nodes_source!r}."
                    )
                if instances.get("format") != "csv":
                    errors.append("instances.format precisa ser 'csv'.")
                if instances.get("profile_column") != "device_profile":
                    errors.append(
                        "instances.profile_column precisa ser 'device_profile'."
                    )

            rows = self._read_nodes_rows()
            errors.extend(
                self._device_profile_compatibility_errors(
                    rows, self.builder.spec.get("devices", {})
                )
            )
            if not missing and not errors:
                self._validate_generated_toml(
                    self.builder.generate_toml(require_confirmation=False)
                )
        except Exception as exc:
            errors.append(
                f"Não foi possível ler/validar {self.nodes_source}: "
                f"{type(exc).__name__}: {exc}"
            )

        return ValidationResult(
            valid=not list(dict.fromkeys(errors)),
            missing=list(dict.fromkeys(missing)),
            errors=list(dict.fromkeys(errors)),
        )

    def compatibility_warnings(self) -> list[str]:
        """Avisos não bloqueantes; incompatibilidades de perfil são erros."""
        return []

    @staticmethod
    def _device_profile_compatibility_errors(
        rows: list[dict[str, str]],
        devices: Any,
    ) -> list[str]:
        """Bloqueia perfis do CSV sem definição correspondente em [devices]."""
        if not isinstance(devices, dict):
            return [
                "[compatibilidade SDK] [devices] precisa ser uma "
                "tabela de perfis para corresponder ao nodes.csv."
            ]

        missing_profiles: set[str] = set()
        rows_without_profile: list[int] = []

        for row_number, row in enumerate(rows, start=2):
            profile = str(row.get("device_profile") or "").strip()
            if not profile:
                rows_without_profile.append(row_number)
            elif profile not in devices:
                missing_profiles.add(profile)

        errors: list[str] = []
        if missing_profiles:
            errors.append(
                "[compatibilidade SDK] nodes.csv usa device_profile(s) "
                "sem definição correspondente em [devices]: "
                + ", ".join(sorted(missing_profiles))
                + ". Defina explicitamente os perfis técnicos ausentes; "
                "nenhum perfil será criado ou inferido automaticamente."
            )
        if rows_without_profile:
            errors.append(
                "[compatibilidade SDK] nodes.csv contém linhas sem "
                "device_profile: "
                + ", ".join(map(str, rows_without_profile))
                + "."
            )
        return errors

    def _read_nodes_rows(self) -> list[dict[str, str]]:
        if not self.nodes_path.is_file():
            raise FileNotFoundError(
                f"{self.nodes_source} não está disponível em {self.nodes_path}."
            )
        return NodesCompiler.read_csv(self.nodes_path)

    def _validate_generated_toml(self, content: str) -> dict[str, Any]:
        try:
            parsed = tomllib.loads(content)
        except (tomllib.TOMLDecodeError, ValueError) as exc:
            raise ValueError(f"scenario.toml inválido: {exc}") from exc

        instances = parsed.get("instances")
        if not isinstance(instances, dict):
            raise ValueError("scenario.toml precisa conter a tabela [instances].")

        if instances.get("source") != self.nodes_source:
            raise ValueError(
                f"scenario.toml deve usar instances.source = "
                f"{self.nodes_source!r}; recebido: {instances.get('source')!r}."
            )

        if instances.get("format") != "csv":
            raise ValueError("instances.format precisa ser 'csv'.")
        if instances.get("profile_column") != "device_profile":
            raise ValueError("instances.profile_column precisa ser 'device_profile'.")

        rows = self._read_nodes_rows()
        profile_errors = self._device_profile_compatibility_errors(
            rows, parsed.get("devices", {})
        )
        if profile_errors:
            raise ValueError(
                f"scenario.toml incompatível com {self.nodes_source}: "
                + " ".join(profile_errors)
            )

        # Validação local pelo SDK. O TOML e o CSV são copiados para um diretório
        # temporário, pois o loader resolve instances.source relativamente ao TOML.
        # Nenhum MCP/Planning Service é chamado e nenhum artefato do projeto é criado.
        try:
            from cisei_planning_sdk.local_io import load_scenario_bundle
        except Exception as exc:
            raise RuntimeError(
                "Não foi possível importar cisei_planning_sdk.local_io.load_scenario_bundle: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        with tempfile.TemporaryDirectory(prefix="scenario-local-validation-") as tmp:
            temp_root = Path(tmp)
            temp_toml = temp_root / "scenario.toml"
            temp_nodes = temp_root / self.nodes_source
            temp_nodes.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.nodes_path, temp_nodes)
            temp_toml.write_text(content, encoding="utf-8")
            try:
                bundle = load_scenario_bundle(temp_toml)
            except Exception as exc:
                raise ValueError(
                    "Validação local do SDK falhou: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
            if not isinstance(bundle, dict):
                raise ValueError(
                    "load_scenario_bundle não retornou um dicionário; "
                    f"tipo recebido: {type(bundle).__name__}."
                )
        return parsed

    @property
    def valid(self) -> bool:
        return self.validate().valid

    @property
    def complete(self) -> bool:
        return self.validate().complete

    @property
    def missing(self) -> list[str]:
        return list(self.validate().missing)

    @property
    def errors(self) -> list[str]:
        return list(self.validate().errors)

    def update(self, values: dict[str, Any]) -> ValidationResult:
        if not isinstance(values, dict):
            raise TypeError("values must be a dictionary")
        if not values:
            raise ValueError("values must not be empty")
        self._reject_conflicting_nodes_input(values)
        self.builder.update(values)
        self._configure_nodes_input()
        self._invalidate_confirmation()
        return self.validate()

    def replace(self, values: dict[str, Any]) -> ValidationResult:
        if not isinstance(values, dict):
            raise TypeError("values must be a dictionary")
        self._reject_conflicting_nodes_input(values)
        self.builder.replace(values)
        self._configure_nodes_input()
        self._invalidate_confirmation()
        return self.validate()

    def to_dict(self) -> dict[str, Any]:
        return self.builder.to_dict()

    def missing_fields(self) -> list[str]:
        return list(self.validate().missing)

    def confirm(self) -> ValidationResult:
        validation = self.validate()
        if not validation.valid:
            raise ValueError(
                "Cannot confirm an invalid scenario. Errors: "
                + str(validation.errors)
            )
        if not validation.complete:
            raise ValueError(
                "Cannot confirm an incomplete scenario. Missing: "
                + str(validation.missing)
            )
        self._assert_nodes_ready()
        self._assert_scenario_references_nodes_output()
        self.builder.confirm()
        self._confirmed = True
        return self.validate()

    def generate_toml(self) -> str:
        if not self.confirmed:
            raise RuntimeError(
                "Scenario must be explicitly confirmed before generating TOML."
            )
        self._assert_nodes_ready()
        self._assert_scenario_references_nodes_output()
        text = self.builder.generate_toml()
        self._validate_generated_toml(text)
        return text

    def save(self, *, overwrite: bool = False) -> Path:
        """Salva somente scenario.toml; nunca modifica nodes.csv."""
        if not self.confirmed:
            raise RuntimeError(
                "Scenario must be explicitly confirmed before saving the project."
            )
        text = self.generate_toml()
        self._write_text(self.scenario_path, text, overwrite=overwrite)
        return self.scenario_path

    save_scenario = save

    def finalize(self, *, overwrite_scenario: bool = False) -> Path:
        """Persiste somente scenario.toml após validação e confirmação explícita."""
        validation = self.validate()
        if not validation.valid:
            raise ValueError(
                "Cannot finalize an invalid scenario. Errors: "
                + str(validation.errors)
            )
        if not validation.complete:
            raise ValueError(
                "Cannot finalize an incomplete scenario. Missing: "
                + str(validation.missing)
            )
        if not self.confirmed:
            raise RuntimeError(
                "Scenario must be explicitly confirmed before finalization."
            )

        self._assert_nodes_ready()
        self._assert_scenario_references_nodes_output()
        toml_text = self.builder.generate_toml()
        self._validate_generated_toml(toml_text)
        self._write_text(
            self.scenario_path, toml_text, overwrite=overwrite_scenario
        )
        return self.scenario_path

    def _configure_nodes_input(self) -> None:
        """Liga instances ao CSV escolhido explicitamente para esta sessão."""
        instances = self.builder.spec.get("instances")
        if not isinstance(instances, dict):
            raise ValueError("instances precisa ser uma tabela.")

        expected = {
            "source": self.nodes_source,
            "format": "csv",
            "profile_column": "device_profile",
        }
        for key, value in expected.items():
            current = instances.get(key)
            if current is not None and current != value:
                raise ValueError(
                    f"instances.{key} precisa ser {value!r}; "
                    "a sessão não permite alterar a origem dos nós."
                )

        self.builder.update({"instances": expected})

    def _reject_conflicting_nodes_input(self, values: dict[str, Any]) -> None:
        incoming = values.get("instances")
        if incoming is None:
            return
        if not isinstance(incoming, dict):
            raise ValueError("instances precisa ser uma tabela.")

        expected = {
            "source": self.nodes_source,
            "format": "csv",
            "profile_column": "device_profile",
        }
        for key, value in expected.items():
            if key in incoming and incoming[key] is not None:
                if incoming[key] != value:
                    raise ValueError(
                        f"A especificação não pode alterar instances.{key}; "
                        f"o valor esperado é {value!r}."
                    )

    def _assert_nodes_ready(self) -> None:
        if not self.nodes_path.is_file():
            raise FileNotFoundError(
                f"{self.nodes_source} não está disponível em {self.nodes_path}. "
                "Prepare os nós antes de iniciar a conversa com o LLM."
            )
        NodesCompiler.read_csv(self.nodes_path)

    def _assert_scenario_references_nodes_output(self) -> None:
        instances = self.builder.spec.get("instances", {})
        source = instances.get("source") if isinstance(instances, dict) else None

        if source != self.nodes_source:
            raise ValueError(
                f"scenario.toml precisa referenciar o CSV configurado: "
                f"instances.source = {self.nodes_source!r}; recebido {source!r}."
            )

        resolved = (self.project_path / source).resolve()
        if resolved != self.nodes_path.resolve():
            raise ValueError(
                "instances.source não corresponde ao arquivo de nós configurado."
            )

    def _invalidate_confirmation(self) -> None:
        self._confirmed = False
        self._nodes_report = None

    @staticmethod
    def _write_text(
        destination: Path,
        content: str,
        *,
        overwrite: bool,
        encoding: str = "utf-8",
    ) -> None:
        destination = Path(destination)
        if destination.exists() and not overwrite:
            raise FileExistsError(
                f"O arquivo já existe: {destination}. Para substituí-lo, "
                "informe overwrite=True."
            )

        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".tmp")
        try:
            with temporary.open("w", encoding=encoding, newline="") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            if destination.exists() and not overwrite:
                raise FileExistsError(
                    f"O arquivo já existe: {destination}. Para substituí-lo, "
                    "informe overwrite=True."
                )
            temporary.replace(destination)
        finally:
            if temporary.exists():
                temporary.unlink()

    def __repr__(self) -> str:
        validation = self.validate()
        return (
            "ScenarioSession("
            f"project={self.project.name!r}, "
            f"valid={validation.valid}, "
            f"complete={validation.complete}, "
            f"confirmed={self.confirmed}"
            ")"
        )