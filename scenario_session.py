# ============================================================
# PLANAPP / VIBEPLANNER — SCENARIO SESSION
# ============================================================
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from cisei_planning_sdk.project import PlanningProject
from nodes_compiler import CompilationReport, NodesCompiler
from scenario_builder import ScenarioBuilder, ValidationResult


class ScenarioSession:
    """Coordena a autoria do scenario.toml sobre nodes.csv já preparado.

    Pré-condição: prepare_project_nodes(project.path) deve ter sido executado
    antes da inicialização da sessão e, principalmente, antes da conversa com
    o LLM. Esta sessão nunca cria nem recompila nodes.csv.

    A sessão não chama MCP nem Planning Service e não executa planejamento.
    """

    def __init__(
        self,
        project: PlanningProject,
        *,
        builder: ScenarioBuilder | None = None,
        nodes_compiler: NodesCompiler | None = None,
    ) -> None:
        if not isinstance(project, PlanningProject):
            raise TypeError("project must be an instance of PlanningProject")
        self.project = project
        self.builder = builder or ScenarioBuilder()
        self.nodes_compiler = nodes_compiler or NodesCompiler(project.path)
        self._confirmed = False
        self._nodes_report: CompilationReport | None = None

        # Fail fast: a conversa com o LLM só deve começar depois que nodes.csv
        # estiver disponível e validado. Esta etapa apenas lê o arquivo.
        if not self.nodes_path.is_file():
            raise FileNotFoundError(
                f"nodes.csv ainda não existe em {self.nodes_path}. "
                "Execute prepare_project_nodes(project.path) antes de criar "
                "ScenarioSession ou iniciar a conversa com o LLM."
            )
        prepared_rows = NodesCompiler.read_csv(self.nodes_path)
        if self.nodes_compiler.last_report is not None:
            self._nodes_report = self.nodes_compiler.last_report
        else:
            # A sessão revalida o artefato, mas não refaz a descoberta nem
            # recompila. O relatório detalhado de preparação é retornado por
            # prepare_project_nodes() antes de iniciar o agente.
            self._nodes_report = CompilationReport(
                output_path=str(self.nodes_path),
                selected_sources=("nodes.csv (preexistente e validado)",),
                rows_written=len(prepared_rows),
                strategy="validated_existing",
                assessments=tuple(self.nodes_compiler.analyze_sources()),
            )

        # Esses três campos são ligação técnica determinística entre os
        # artefatos, não valores técnicos inferidos pelo LLM.
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

    @property
    def nodes_path(self) -> Path:
        return self.project_path / "nodes.csv"

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
            "confirmed": self.confirmed,
            "project": str(self.project_path),
            "scenario": str(self.scenario_path),
            "nodes_output": str(self.nodes_path),
            "nodes_ready": self.nodes_path.is_file(),
            "nodes_report": self.nodes_report,
        }

    def validate(self) -> ValidationResult:
        return self.builder.validate()

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
        return self.builder.generate_toml()

    def save(self, *, overwrite: bool = False) -> Path:
        """Salva somente scenario.toml, usando nodes.csv já preparado.

        Não compila, altera nem substitui nodes.csv.
        """
        if not self.confirmed:
            raise RuntimeError(
                "Scenario must be explicitly confirmed before saving the project."
            )
        text = self.generate_toml()
        self._write_text(self.scenario_path, text, overwrite=overwrite)
        return self.scenario_path

    save_scenario = save

    def finalize(self, *, overwrite_scenario: bool = False) -> Path:
        """Persiste apenas scenario.toml, usando nodes.csv já preparado.

        nodes.csv deve existir, estar válido e ter sido preparado antes da
        conversa com o LLM. Finalizar nunca compila ou altera esse arquivo.
        """
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
        self._write_text(
            self.scenario_path,
            toml_text,
            overwrite=overwrite_scenario,
        )
        return self.scenario_path

    def _configure_nodes_input(self) -> None:
        """Garante a ligação de instances ao CSV pré-gerado do projeto."""
        instances = self.builder.spec.get("instances")
        if not isinstance(instances, dict):
            raise ValueError("instances must be a dictionary.")
        expected = {
            "source": "nodes.csv",
            "format": "csv",
            "profile_column": "device_profile",
        }
        for key, expected_value in expected.items():
            current = instances.get(key)
            if current is not None and current != expected_value:
                if key == "source" and isinstance(current, str):
                    candidate = Path(current)
                    resolved = candidate.resolve() if candidate.is_absolute() else (self.project_path / candidate).resolve()
                    if resolved == self.nodes_path.resolve():
                        continue
                raise ValueError(
                    f"instances.{key} precisa ser {expected_value!r}, pois "
                    "nodes.csv é preparado antes da conversa com o LLM."
                )
        # Define só os campos de ligação do artefato; não preenche parâmetros
        # de RF, CRS ou outros valores técnicos do cenário.
        self.builder.update({"instances": expected})

    def _reject_conflicting_nodes_input(self, values: dict[str, Any]) -> None:
        incoming = values.get("instances")
        if incoming is None:
            return
        if not isinstance(incoming, dict):
            raise ValueError("instances must be a dictionary.")
        expected = {
            "source": "nodes.csv",
            "format": "csv",
            "profile_column": "device_profile",
        }
        for key, expected_value in expected.items():
            if key not in incoming or incoming[key] is None:
                continue
            current = incoming[key]
            if key == "source" and isinstance(current, str):
                candidate = Path(current)
                resolved = candidate.resolve() if candidate.is_absolute() else (self.project_path / candidate).resolve()
                if resolved == self.nodes_path.resolve():
                    continue
            if current != expected_value:
                raise ValueError(
                    f"A especificação não pode alterar instances.{key}; "
                    f"o valor esperado é {expected_value!r}."
                )

    def _assert_nodes_ready(self) -> None:
        if not self.nodes_path.is_file():
            raise FileNotFoundError(
                f"nodes.csv não está disponível em {self.nodes_path}. "
                "Prepare os nós antes de iniciar a conversa com o LLM."
            )
        NodesCompiler.read_csv(self.nodes_path)

    def _assert_scenario_references_nodes_output(self) -> None:
        instances = self.builder.spec.get("instances", {})
        source = instances.get("source") if isinstance(instances, dict) else None
        if not isinstance(source, str) or not source.strip():
            raise ValueError(
                "instances.source must explicitly reference the generated nodes.csv."
            )

        source_path = Path(source.strip())
        if source_path.is_absolute():
            resolved = source_path.resolve()
        else:
            resolved = (self.project_path / source_path).resolve()

        if resolved != self.nodes_path.resolve():
            raise ValueError(
                "scenario.toml deve referenciar o CSV canônico já preparado: "
                "instances.source = 'nodes.csv'. "
                f"O valor atual é {source!r}. Corrija a especificação, revise-a "
                "e confirme novamente antes de finalizar."
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