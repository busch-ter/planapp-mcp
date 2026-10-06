# ============================================================
# PLANAPP / VIBEPLANNER
#
# SCENARIO SESSION
#
# Camada de sessão entre:
#
#     agente / interface conversacional
#              |
#              v
#       ScenarioSession
#              |
#              +--> ScenarioBuilder
#              |
#              +--> PlanningProject
#
# Responsabilidades:
#
#   - manter o estado de construção do cenário;
#   - receber atualizações incrementais;
#   - validar o cenário;
#   - informar campos faltantes;
#   - exigir confirmação explícita;
#   - persistir scenario.toml no PlanningProject.
#
# NÃO é responsabilidade desta classe:
#
#   - interpretar linguagem natural;
#   - inferir parâmetros técnicos;
#   - executar Planning Service;
#   - chamar MCP;
#   - executar evaluate_link;
#   - executar workflow de planejamento;
#   - gerar features.json;
#   - gerar result.json.
#
# Princípio:
#
#   LLM/interface -> declaração estruturada
#                   -> ScenarioSession
#                   -> ScenarioBuilder
#                   -> PlanningProject
#
# ============================================================

from __future__ import annotations

from pathlib import Path
from typing import Any

from cisei_planning_sdk.project import PlanningProject

from scenario_builder import ScenarioBuilder, ValidationResult


class ScenarioSession:
    """
    Sessão de construção de um cenário de planejamento.

    A sessão mantém duas entidades distintas:

        ScenarioBuilder
            Responsável pela estrutura, validação e geração
            determinística do cenário.

        PlanningProject
            Responsável pela persistência do projeto no workspace.

    Exemplo:

        project = PlanningProject(
            "/home/jovyan/work/cisei_workspace/projects/my_project"
        )

        session = ScenarioSession(project)

        session.update({
            "scenario": {
                "working_crs": "EPSG:31982"
            }
        })

        status = session.validate()

        if status.complete:
            session.confirm()
            session.save()
    """

    def __init__(
        self,
        project: PlanningProject,
        *,
        builder: ScenarioBuilder | None = None,
    ) -> None:
        if not isinstance(project, PlanningProject):
            raise TypeError(
                "project must be an instance of PlanningProject"
            )

        self.project = project
        self.builder = builder or ScenarioBuilder()

        # A confirmação pertence à sessão.
        #
        # O cenário pode ser alterado depois de uma confirmação.
        # Nesse caso, a confirmação precisa ser invalidada e uma
        # nova confirmação será necessária antes da geração.
        self._confirmed = False

    # ========================================================
    # PROPRIEDADES
    # ========================================================

    @property
    def confirmed(self) -> bool:
        """Indica se o estado atual do cenário foi confirmado."""
        return self._confirmed

    @property
    def project_path(self) -> Path:
        """Diretório físico do projeto."""
        return self.project.path

    @property
    def scenario_path(self) -> Path:
        """Caminho do scenario.toml."""
        return self.project.scenario_path

    @property
    def features_path(self) -> Path:
        """Caminho reservado para features.json."""
        return self.project.features_path

    @property
    def result_path(self) -> Path:
        """Caminho reservado para result.json."""
        return self.project.result_path

    # ========================================================
    # ESTADO / VALIDAÇÃO
    # ========================================================

    def validate(self) -> ValidationResult:
        """
        Valida o estado atual do ScenarioBuilder.

        Não altera o cenário.
        """
        return self.builder.validate()

    @property
    def valid(self) -> bool:
        """True quando o cenário atual não possui erros."""
        return self.validate().valid

    @property
    def complete(self) -> bool:
        """True quando todos os campos obrigatórios estão presentes."""
        return self.validate().complete

    @property
    def missing(self) -> list[str]:
        """Lista dos campos obrigatórios ainda ausentes."""
        return list(self.validate().missing)

    @property
    def errors(self) -> list[str]:
        """Lista dos erros de validação atuais."""
        return list(self.validate().errors)

    def status(self) -> dict[str, Any]:
        """
        Retorna o estado atual em formato serializável.

        Esse método é útil para uma futura integração com o agente,
        UI ou MCP.

        Exemplo:

            {
                "valid": True,
                "complete": False,
                "missing": [...],
                "errors": [],
                "confirmed": False,
                "project": "...",
                "scenario": "..."
            }
        """
        validation = self.validate()

        return {
            "valid": validation.valid,
            "complete": validation.complete,
            "missing": list(validation.missing),
            "errors": list(validation.errors),
            "confirmed": self.confirmed,
            "project": str(self.project.path),
            "scenario": str(self.project.scenario_path),
        }

    # ========================================================
    # ATUALIZAÇÃO
    # ========================================================

    def update(self, values: dict[str, Any]) -> ValidationResult:
        """
        Atualiza parcialmente o cenário.

        A atualização é delegada ao ScenarioBuilder.

        Qualquer alteração invalida uma confirmação anterior.

        Parameters
        ----------
        values:
            Estrutura parcial do cenário.

        Returns
        -------
        ValidationResult
            Estado do cenário após a atualização.

        Raises
        ------
        TypeError
            Se values não for um dicionário.
        """
        if not isinstance(values, dict):
            raise TypeError(
                "values must be a dictionary"
            )

        if not values:
            raise ValueError(
                "values must not be empty"
            )

        self.builder.update(values)

        # Qualquer mudança exige nova confirmação.
        self._confirmed = False

        return self.validate()

    def replace(self, values: dict[str, Any]) -> ValidationResult:
        """
        Substitui o conteúdo do ScenarioBuilder.

        Esta operação é útil quando o cenário completo vem de uma
        fonte estruturada, por exemplo:

            - arquivo TOML;
            - template;
            - teste;
            - cenário de referência.

        Também invalida confirmação anterior.
        """
        if not isinstance(values, dict):
            raise TypeError(
                "values must be a dictionary"
            )

        self.builder.replace(values)

        self._confirmed = False

        return self.validate()

    # ========================================================
    # CONSULTA DO CENÁRIO
    # ========================================================

    def to_dict(self) -> dict[str, Any]:
        """
        Retorna uma representação estruturada do cenário atual.

        A implementação real pertence ao ScenarioBuilder.
        """
        return self.builder.to_dict()

    def missing_fields(self) -> list[str]:
        """
        Retorna os campos obrigatórios que ainda faltam.
        """
        return list(self.validate().missing)

    # ========================================================
    # CONFIRMAÇÃO
    # ========================================================

    def confirm(self) -> ValidationResult:
        """
        Confirma explicitamente o cenário atual.

        A confirmação só é permitida quando o cenário está:

            valid == True
            complete == True

        Depois da confirmação, o cenário pode ser salvo.

        Qualquer chamada posterior a update() ou replace()
        invalida esta confirmação.
        """
        validation = self.validate()

        if not validation.valid:
            raise ValueError(
                "Cannot confirm an invalid scenario. "
                f"Errors: {validation.errors}"
            )

        if not validation.complete:
            raise ValueError(
                "Cannot confirm an incomplete scenario. "
                f"Missing: {validation.missing}"
            )

        self.builder.confirm()

        self._confirmed = True

        return self.validate()

    # ========================================================
    # GERAÇÃO
    # ========================================================

    def generate_toml(self) -> str:
        """
        Gera o TOML do cenário atual.

        A confirmação é obrigatória.

        Returns
        -------
        str
            Conteúdo TOML gerado pelo ScenarioBuilder.
        """
        if not self.confirmed:
            raise RuntimeError(
                "Scenario must be explicitly confirmed "
                "before generating TOML."
            )

        return self.builder.generate_toml()

    # ========================================================
    # PERSISTÊNCIA
    # ========================================================

    def save(self) -> Path:
        """
        Gera e salva o scenario.toml no PlanningProject.

        A confirmação é obrigatória.

        Returns
        -------
        Path
            Caminho do scenario.toml salvo.
        """
        if not self.confirmed:
            raise RuntimeError(
                "Scenario must be explicitly confirmed "
                "before saving the project."
            )

        self.builder.save_toml(self.project.scenario_path)

        return self.project.scenario_path

    # Alias explícito para deixar a intenção clara em chamadas
    # futuras do agente.
    save_scenario = save

    # ========================================================
    # FLUXO FINAL
    # ========================================================

    def finalize(self) -> Path:
        """
        Finaliza a sessão e persiste o scenario.toml.

        Requer:

            1. cenário válido;
            2. cenário completo;
            3. confirmação explícita.

        Não executa Planning Service nem MCP.
        """
        validation = self.validate()

        if not validation.valid:
            raise ValueError(
                "Cannot finalize an invalid scenario. "
                f"Errors: {validation.errors}"
            )

        if not validation.complete:
            raise ValueError(
                "Cannot finalize an incomplete scenario. "
                f"Missing: {validation.missing}"
            )

        if not self.confirmed:
            raise RuntimeError(
                "Scenario must be explicitly confirmed "
                "before finalization."
            )

        return self.save()

    # ========================================================
    # REPRESENTAÇÃO
    # ========================================================

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