
from __future__ import annotations

import csv
import json
import os
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

from openai import OpenAI

from cisei_planning_sdk.project import PlanningProject
from scenario_agent import ScenarioAgent
from scenario_domain.provider import DomainContextProvider


DEFAULT_MODEL = "gpt-5.6-luna"
DEFAULT_DOMAIN_CONTEXT_SECTIONS = (
    "scenario_format",
    "assistant_workflow",
    "design_gaps_and_decisions",
)


class ScenarioAgentOpenAIError(RuntimeError):
    """Erro específico do adapter OpenAI do ScenarioAgent."""


class ScenarioAgentOpenAI:
    ALLOWED_ACTIONS = {
        "update_scenario",
        "ask_user",
        "confirm",
        "reject_confirmation",
        "finalize",
    }

    # Estas colunas descrevem instâncias da rede. Seus valores não devem
    # ser confundidos com definições completas de perfis técnicos.
    _INSTANCE_EVIDENCE_KEYS = {
        "site_id",
        "device_profile",
        "kind",
        "lat",
        "lon",
        "x",
        "y",
        "mount_height_m",
        "connected",
        "can_route",
        "rank",
        "religador",
        "lat_g",
        "lon_g",
    }

    def __init__(
        self,
        project: PlanningProject,
        *,
        model: str | None = None,
        client: OpenAI | None = None,
        domain_context_provider: DomainContextProvider | None = None,
        domain_context_sections: tuple[str, ...] | None = None,
    ):
        if not isinstance(project, PlanningProject):
            raise TypeError("project must be an instance of PlanningProject")

        if domain_context_sections is not None:
            if not isinstance(domain_context_sections, tuple):
                raise TypeError(
                    "domain_context_sections must be a tuple[str, ...] or None"
                )
            if any(
                not isinstance(section, str) or not section.strip()
                for section in domain_context_sections
            ):
                raise ValueError(
                    "domain_context_sections must contain non-empty strings"
                )

        self.project = project
        self.model = (
            model
            or os.getenv("SCENARIO_AGENT_OPENAI_MODEL")
            or DEFAULT_MODEL
        )
        self.client = client or OpenAI()
        self.scenario_agent = ScenarioAgent(project)
        self.domain_context_provider = domain_context_provider
        self.domain_context_sections = (
            domain_context_sections
            if domain_context_sections is not None
            else DEFAULT_DOMAIN_CONTEXT_SECTIONS
        )

        self.messages: list[dict[str, Any]] = []
        self._pending_exchange: list[dict[str, Any]] | None = None
        self.pending_question: dict[str, Any] | None = None

        # Registro conversacional dos requisitos explícitos.
        # Não substitui o snapshot canônico do ScenarioBuilder.
        self.explicit_requirements: dict[str, Any] = {}

        # Evidências de arquivos são somente leitura.
        # Não são requisitos do usuário nem valores canônicos do cenário.
        self._project_evidence = self._collect_project_evidence()

    @property
    def scenario_state(self) -> dict[str, Any]:
        return self.scenario_agent.conversation_state()

    @property
    def scenario(self) -> ScenarioAgent:
        return self.scenario_agent

    @property
    def project_path(self) -> Path:
        return Path(self.project.path)

    @property
    def scenario_path(self) -> Path:
        return self.project_path / "scenario.toml"

    @staticmethod
    def _normalize_confirmation_text(user_message: str) -> str:
        value = unicodedata.normalize("NFKD", user_message.casefold())
        value = "".join(
            char for char in value if not unicodedata.combining(char)
        )
        return re.sub(r"[^a-z0-9]+", " ", value).strip()

    @classmethod
    def _is_explicit_confirmation(cls, user_message: str) -> bool:
        if not isinstance(user_message, str):
            return False
    
        value = cls._normalize_confirmation_text(user_message.strip())
    
        if not value:
            return False
    
        # Uma negativa ou pedido de alteração nunca deve ser tratado
        # como confirmação positiva.
        if re.search(
            r"\b(?:nao|nunca|cancele|cancelar|"
            r"alterar|mudar|corrigir|revisar|"
            r"aguardar|esperar)\b",
            value,
        ):
            return False
    
        # Confirmações curtas e inequívocas.
        exact = {
            "confirmo",
            "eu confirmo",
            "confirmo o cenario",
            "eu confirmo o cenario",
            "confirmo este cenario",
            "eu confirmo este cenario",
            "confirmo o cenario atual",
            "eu confirmo o cenario atual",
            "pode confirmar",
            "pode confirmar o cenario",
            "pode prosseguir",
            "pode prosseguir com o cenario",
            "pode finalizar",
            "pode finalizar o cenario",
            "aprovo o cenario",
            "eu aprovo o cenario",
            "confirm",
            "i confirm",
            "i confirm the scenario",
            "i confirm this scenario",
            "confirm the scenario",
            "confirm this scenario",
            "approve this scenario",
            "i approve this scenario",
            "proceed with this scenario",
            "finalize the scenario",
        }
    
        if value in exact:
            return True
    
        # Confirmações explícitas acompanhadas de contexto adicional.
        # Exemplo:
        # "Revisei o resumo técnico apresentado e confirmo
        # explicitamente a configuração atual do cenário COPEL LTE."
        if re.search(
            r"\b(?:confirmo|aprovo)\s+"
            r"(?:explicitamente\s+)?"
            r"(?:a\s+configuracao(?:\s+atual)?|"
            r"o\s+cenario(?:\s+atual)?|"
            r"este\s+cenario)\b",
            value,
        ):
            return True
    
        # Mantém os padrões de confirmação da implementação original.
        patterns = (
            r"(?:sim )?(?:eu )?(?:confirmo|aprovo)"
            r"(?: o| este| esse)? cenario(?: atual)?"
            r"(?: e pode)?(?: gerar| gravar| finalizar)?",
    
            r"(?:sim )?(?:esta correto|tudo correto|de acordo)"
            r" e pode (?:gerar|gravar|finalizar)(?: o cenario)?",
    
            r"pode (?:gerar|gravar|finalizar) o cenario(?: confirmado)?",
    
            r"confirmo que pode (?:gerar|gravar|finalizar)"
            r"(?: o cenario)?",
        )
    
        return any(
            re.fullmatch(pattern, value)
            for pattern in patterns
        )
        
    @staticmethod
    def _merge_facts(
        destination: dict[str, Any],
        incoming: dict[str, Any],
    ) -> None:
        """Mescla fatos sem apagar informações previamente registradas."""
        for key, value in incoming.items():
            if isinstance(value, dict):
                existing = destination.get(key)
                if not isinstance(existing, dict):
                    existing = {}
                    destination[key] = existing
                ScenarioAgentOpenAI._merge_facts(existing, value)
            else:
                destination[key] = value

    def _user_history(self, current_message: str) -> list[str]:
        """
        Retorna as mensagens do usuário e a mensagem atual.

        Remove o contexto serializado da aplicação para que ele não seja
        confundido com uma declaração feita pelo usuário.
        """
        history: list[str] = []

        for message in self.messages:
            if message.get("role") != "user":
                continue

            content = message.get("content", "")
            if not isinstance(content, str):
                continue

            marker = "MENSAGEM ATUAL DO USUÁRIO\n"
            if marker in content:
                content = content.split(marker, 1)[1]

                separator = "\n\nCONTEXTO ATUAL DA APLICAÇÃO\n"
                if separator in content:
                    content = content.split(separator, 1)[0]

            content = content.strip()
            if content and (not history or history[-1] != content):
                history.append(content)

        current_message = current_message.strip()
        if current_message and (
            not history or history[-1] != current_message
        ):
            history.append(current_message)

        return history

    def _extract_explicit_requirements(
        self,
        current_message: str,
    ) -> dict[str, Any]:
        """
        Extrai requisitos técnicos explicitamente identificados.

        Os fatos permanecem separados do cenário canônico até que exista
        um mapeamento seguro para os campos e perfis do ScenarioBuilder.
        """
        texts = self._user_history(current_message)
        all_text = "\n".join(texts)
        normalized = self._normalize_confirmation_text(all_text)

        facts: dict[str, Any] = {}

        # Tecnologia e frequência.
        has_lte = bool(re.search(r"\blte\b", normalized))
        has_450_mhz = bool(
            re.search(r"\b450\s*(?:mhz|megahertz)\b", normalized)
        )

        if has_lte and has_450_mhz:
            facts["radio"] = {
                "technology": "LTE",
                "frequency_mhz": 450,
            }

        # Quantidade de setores: somente com declaração explícita.
        has_sector_count = bool(
            re.search(
                r"\b3\s*(?:setores|setor|sectors|sectors per tower)\b",
                normalized,
            )
        )

        if has_sector_count:
            facts.setdefault("antenna_layout", {})[
                "sectors_per_tower"
            ] = 3

        # Azimutes: reconhece sequências separadas por vírgulas, barras,
        # ponto e vírgula ou pela conjunção "e".
        azimuth_pattern = (
            r"0\s*°?\s*[,;/]\s*120\s*°?\s*[,;/]\s*240\s*°?"
            r"|0\s*°?\s*,?\s*120\s*°?\s*e\s*240\s*°?"
        )

        if re.search(azimuth_pattern, all_text, re.IGNORECASE):
            facts.setdefault("antenna_layout", {})[
                "azimuths_deg"
            ] = [0, 120, 240]

        # Largura de feixe: exige referência explícita ao feixe.
        has_beamwidth_reference = bool(
            re.search(
                r"(largura\s+(?:horizontal\s+)?(?:de\s+)?feixe|"
                r"beamwidth|feixe)",
                normalized,
            )
        )
        has_120_degrees = bool(
            re.search(r"\b120\s*(?:graus|degree|degrees)?\b", normalized)
        )

        if has_beamwidth_reference and has_120_degrees:
            facts.setdefault("antenna_layout", {})[
                "beamwidth_deg"
            ] = 120

        # Funções dos elementos da rede.
        if (
            re.search(r"\breligadores\b", normalized)
            and re.search(r"\btorres\b", normalized)
        ):
            facts["network_roles"] = {
                "client_endpoints": "religadores",
                "connectivity_infrastructure": "torres",
            }

        return facts

    def _refresh_explicit_requirements(self, current_message: str) -> None:
        """Acumula requisitos sem apagar fatos anteriormente registrados."""
        extracted = self._extract_explicit_requirements(current_message)
        self._merge_facts(self.explicit_requirements, extracted)

    def restore_explicit_requirements(
        self,
        requirements: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Restaura requisitos recuperados de uma conversa anterior.

        Não altera o cenário canônico, não confirma o cenário e não grava
        arquivos. O chamador deve fornecer apenas fatos já conhecidos.
        """
        if not isinstance(requirements, dict):
            raise TypeError("requirements must be a dictionary")

        self._merge_facts(self.explicit_requirements, requirements)

        return json.loads(
            json.dumps(self.explicit_requirements, ensure_ascii=False)
        )

    @staticmethod
    def _normalized_evidence_key(value: Any) -> str:
        """Normaliza apenas a grafia de uma chave, não seu significado."""
        return str(value).strip().casefold()

    def _nodes_csv_summary(self) -> dict[str, Any]:
        """
        Resume nodes.csv sem modificar o arquivo.

        As contagens descrevem as instâncias existentes; não constituem
        definições de perfis técnicos nem autorização para criá-los.
        """
        path = self.project_path / "nodes.csv"

        if not path.is_file():
            return {
                "available": False,
                "reason": "nodes.csv não encontrado no diretório do projeto.",
            }

        try:
            with path.open(
                "r",
                encoding="utf-8-sig",
                newline="",
            ) as stream:
                reader = csv.DictReader(stream)
                columns = list(reader.fieldnames or [])
                rows = list(reader)

            summary: dict[str, Any] = {
                "available": True,
                "file": path.name,
                "row_count": len(rows),
                "columns": columns,
                "read_only": True,
                "interpretation": (
                    "Contagens de instâncias não definem nem criam "
                    "perfis técnicos."
                ),
            }

            profile_column = next(
                (
                    column
                    for column in columns
                    if column.strip().casefold() == "device_profile"
                ),
                None,
            )
            if profile_column:
                counts = Counter(
                    str(row.get(profile_column, "")).strip()
                    for row in rows
                    if str(row.get(profile_column, "")).strip()
                )
                summary["device_profile_counts"] = dict(
                    sorted(counts.items())
                )

            kind_column = next(
                (
                    column
                    for column in columns
                    if column.strip().casefold() == "kind"
                ),
                None,
            )
            if kind_column:
                counts = Counter(
                    str(row.get(kind_column, "")).strip()
                    for row in rows
                    if str(row.get(kind_column, "")).strip()
                )
                summary["kind_counts"] = dict(sorted(counts.items()))

            return summary

        except (OSError, UnicodeError, csv.Error) as exc:
            return {
                "available": False,
                "file": path.name,
                "reason": (
                    f"Não foi possível ler nodes.csv em modo somente leitura: "
                    f"{type(exc).__name__}: {exc}"
                ),
            }

    def _compact_technical_evidence(
        self,
        raw: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Compacta evidências preservando a origem e limitando o contexto.

        O limite é aplicado ao total de entradas distintas de cada chave,
        não a cada arquivo. A cobertura e a amostragem são reportadas
        separadamente por _evidence_sampling_summary().
        """
        if not isinstance(raw, dict):
            return {}

        evidence = raw.get("technical_evidence", {})
        if not isinstance(evidence, dict):
            return {}

        compact: dict[str, Any] = {}

        for key, entries in evidence.items():
            if not isinstance(entries, list):
                entries = [entries]

            grouped: dict[str, dict[str, Any]] = {}

            for entry in entries:
                if isinstance(entry, dict):
                    value = entry.get("value")
                    source = entry.get("source")
                else:
                    value = entry
                    source = None

                if value is None or value == "":
                    continue

                source_name = (
                    Path(str(source)).name
                    if source
                    else "origem não identificada"
                )

                try:
                    value_signature = json.dumps(
                        value,
                        ensure_ascii=False,
                        sort_keys=True,
                        default=str,
                    )
                except (TypeError, ValueError):
                    value_signature = repr(value)

                signature = json.dumps(
                    [value_signature, source_name],
                    ensure_ascii=False,
                )

                if signature not in grouped:
                    grouped[signature] = {
                        "value": value,
                        "source": source_name,
                    }

            if grouped:
                compact[str(key)] = list(grouped.values())[:12]

        return compact

    def _evidence_sampling_summary(
        self,
        raw: dict[str, Any],
    ) -> dict[str, Any]:
        """Expõe quantas evidências foram encontradas, enviadas e omitidas."""
        evidence = raw.get("technical_evidence", {})
        if not isinstance(evidence, dict):
            return {}

        summary: dict[str, Any] = {}

        for key, entries in evidence.items():
            if not isinstance(entries, list):
                entries = [entries]

            grouped: dict[str, str] = {}

            for entry in entries:
                if isinstance(entry, dict):
                    value = entry.get("value")
                    source = entry.get("source")
                else:
                    value = entry
                    source = None

                if value is None or value == "":
                    continue

                source_name = (
                    Path(str(source)).name
                    if source
                    else "origem não identificada"
                )

                try:
                    value_signature = json.dumps(
                        value,
                        ensure_ascii=False,
                        sort_keys=True,
                        default=str,
                    )
                except (TypeError, ValueError):
                    value_signature = repr(value)

                signature = json.dumps(
                    [value_signature, source_name],
                    ensure_ascii=False,
                )
                grouped.setdefault(signature, source_name)

            if not grouped:
                continue

            all_entries = list(grouped.items())
            included = all_entries[:12]
            sources_found = list(dict.fromkeys(grouped.values()))
            sources_sent = list(
                dict.fromkeys(source for _, source in included)
            )

            summary[str(key)] = {
                "distinct_entries_found": len(all_entries),
                "entries_sent": len(included),
                "entries_omitted": max(0, len(all_entries) - len(included)),
                "sampled": len(all_entries) > len(included),
                "sources_found": sources_found,
                "sources_represented_in_sent_sample": sources_sent,
                "interpretation": (
                    "Amostra parcial; não representa necessariamente "
                    "todos os valores ou todas as fontes."
                    if len(all_entries) > len(included)
                    else "Todas as entradas distintas coletadas para esta chave."
                ),
            }

        return summary

    def _collect_project_evidence(self) -> dict[str, Any]:
        """
        Reúne evidências dos arquivos do projeto sem escrita.

        Este método não modifica o cenário canônico, não cria TOML,
        não altera CSVs e não chama MCP ou Planning Service.
        """
        try:
            from scenario_project_evidence import ScenarioProjectEvidence

            collector = ScenarioProjectEvidence(self.project_path)
            raw = collector.collect()

            if not isinstance(raw, dict):
                raise TypeError(
                    "ScenarioProjectEvidence.collect() deve retornar dict"
                )

            policy = raw.get("policy", {})
            if not isinstance(policy, dict):
                policy = {}

            conflicts = raw.get("conflicts", {})
            if not isinstance(conflicts, dict):
                conflicts = {"reported_conflicts": conflicts}

            files = raw.get("files", [])
            if not isinstance(files, (list, dict)):
                files = []

            limitations = raw.get("limitations", [])
            if not isinstance(limitations, list):
                limitations = [str(limitations)]

            file_items = (
                files.items() if isinstance(files, dict) else []
            )
            file_coverage = []
            truncated_files = []
            unsupported_files = []

            for filename, metadata in file_items:
                if not isinstance(metadata, dict):
                    metadata = {"status": "unknown"}

                item = {
                    "file": str(filename),
                    "type": metadata.get("type"),
                    "status": metadata.get("status"),
                }

                for field in (
                    "rows_examined",
                    "truncated",
                    "truncated_matches",
                ):
                    if field in metadata:
                        item[field] = metadata[field]

                file_coverage.append(item)

                if (
                    metadata.get("truncated") is True
                    or metadata.get("truncated_matches") is True
                ):
                    truncated_files.append(str(filename))

                if (
                    metadata.get("type") == "unsupported"
                    or metadata.get("status") == "inventoried_only"
                ):
                    unsupported_files.append(str(filename))

            conflict_status = (
                "reported_entries_present_detection_incomplete"
                if conflicts
                else "not_checked_by_collector"
            )

            return {
                "available": True,
                "project_path": str(self.project_path),
                "policy": {
                    **policy,
                    "read_only": True,
                    "values_are_not_defaults": True,
                    "no_semantic_alias_inference": True,
                    "conflicts_are_not_resolved_automatically": True,
                    "conflict_detection": "not_implemented",
                },
                "technical_evidence": self._compact_technical_evidence(raw),
                "evidence_sampling": self._evidence_sampling_summary(raw),
                "coverage": {
                    "files_in_inventory": len(files),
                    "files_with_truncation": truncated_files,
                    "unsupported_files": unsupported_files,
                    "file_statuses": file_coverage,
                },
                "conflict_status": {
                    "status": conflict_status,
                    "reported_entries": conflicts,
                    "explanation": (
                        "O coletor ainda não implementa detecção de conflitos. "
                        "Um resultado vazio não comprova ausência de conflitos."
                    ),
                },
                "conflicts": conflicts,
                "files": files,
                "limitations": limitations,
                "nodes_csv": self._nodes_csv_summary(),
                "interpretation_rules": [
                    "Evidências descrevem arquivos; não são requisitos do usuário.",
                    "Valores encontrados não são defaults.",
                    "Amostras compactadas não são listas completas quando sampled=true.",
                    "A cobertura indica somente os arquivos efetivamente examinados.",
                    "Arquivos não suportados foram inventariados, não interpretados.",
                    "A detecção de conflitos ainda não está implementada.",
                    "Não inferir equivalência entre nomes de colunas, perfis ou tecnologias.",
                    "Não resolver conflitos automaticamente.",
                    "Não criar perfis técnicos a partir apenas de contagens de instâncias.",
                    "Solicitar esclarecimentos quando faltar informação necessária.",
                ],
            }

        except Exception as exc:
            # A falha na coleta não deve impedir a conversa nem autorizar
            # o preenchimento de informações ausentes.
            return {
                "available": False,
                "project_path": str(self.project_path),
                "policy": {
                    "read_only": True,
                    "values_are_not_defaults": True,
                    "no_semantic_alias_inference": True,
                    "conflicts_are_not_resolved_automatically": True,
                },
                "technical_evidence": {},
                "conflicts": {},
                "conflict_status": {
                    "status": "not_checked_by_collector",
                    "reported_entries": {},
                    "explanation": (
                        "A coleta falhou; não é possível concluir que "
                        "não existam conflitos."
                    ),
                },
                "evidence_sampling": {},
                "coverage": {
                    "files_in_inventory": 0,
                    "files_with_truncation": [],
                    "unsupported_files": [],
                    "file_statuses": [],
                },
                "files": [],
                "limitations": [
                    (
                        "A coleta de evidências do projeto falhou: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                    "Nenhum valor técnico deve ser inferido por causa dessa falha.",
                ],
                "nodes_csv": self._nodes_csv_summary(),
            }

    def _system_prompt(self) -> str:
        return """
Você é o adaptador conversacional OpenAI do CISEI Scenario Agent.
Retorne exatamente um objeto JSON com uma única ação.

REGRAS DE AUTORIDADE
- O estado da aplicação é a autoridade sobre o cenário canônico.
- Valores explicitamente informados pelo usuário são a autoridade
  para os requisitos desejados.
- O registro de requisitos explícitos é evidência do que o usuário disse,
  mas não equivale a perfis técnicos já implementados no cenário.
- project_evidence descreve arquivos do projeto em modo somente leitura.
- Evidências dos arquivos não são requisitos do usuário, defaults,
  parâmetros canônicos nem autorização para preencher valores ausentes.
- Documentação, exemplos e conhecimento técnico geral não autorizam
  preencher valores ausentes.
- Não infira equivalência semântica entre nomes de colunas, identificadores,
  perfis ou tecnologias.
- Não resolva conflitos de evidências automaticamente.
- Contagens e categorias em nodes.csv descrevem instâncias, não definem
  os perfis técnicos correspondentes.
- Se uma evidência for insuficiente ou conflitante, pergunte ao usuário.
- Nunca invente valores, defaults, identificadores técnicos ou mapeamentos.
- Não escreva arquivos nem execute MCP ou Planning Service.

ACUMULAÇÃO
- Examine todas as mensagens anteriores do usuário, a mensagem atual,
  o snapshot, o registro de requisitos explícitos e as evidências do projeto.
- Não pergunte novamente por valores já informados.
- Não descarte requisitos anteriores quando uma mensagem acrescentar outros.
- Se houver uma atualização canônica inequívoca que ainda não foi persistida,
  retorne update_scenario.
- Não force requisitos incompletos para perfis inventados só para satisfazer
  a validação.
- Não confunda requisitos conhecidos com parâmetros técnicos completos.
- Uma resposta a uma pergunta pendente não equivale a confirmação do cenário,
  salvo se a mensagem confirmar explicitamente o cenário completo.

CONTRATO DO CENÁRIO
- scenario.working_crs é obrigatório.
- Interfaces exigem tech, freq_mhz, tx_power_dbm e antenna_id.
- Devices exigem uma lista interfaces não vazia.
- Perfis de antena e seus parâmetros devem respeitar o contrato do projeto.
- Para CSV externo, preserve instances.source, instances.format e
  instances.profile_column.
- Preserve net.connectivity e net.candidate_edges quando fornecidos.
- Não acrescente defaults do SDK.
- Não altere nodes.csv nem qualquer CSV de origem.
- Não gere TOML enquanto o cenário não estiver válido, completo e confirmado.

AÇÕES
update_scenario:
Use quando houver valores explícitos que possam ser representados com
segurança na estrutura canônica.
{"action":"update_scenario","updates":{...}}

ask_user:
Use quando for necessário esclarecer algo e não houver atualização canônica
pendente. Inclua question e fields.
{"action":"ask_user","question":"...","fields":["..."]}

confirm:
Somente após confirmação explícita e quando o estado estiver pronto.

reject_confirmation:
Quando o usuário rejeitar explicitamente a confirmação ou pedir mudanças.

finalize:
Somente quando o estado indicar cenário válido, completo, confirmado e
pronto para finalização.

Retorne JSON válido apenas, sem Markdown.
""".strip()

    def _domain_context(self) -> dict[str, Any]:
        if self.domain_context_provider is None:
            return {}

        try:
            context = self.domain_context_provider.get_context(
                sections=self.domain_context_sections
            )
            return context.to_dict()
        except Exception as exc:
            raise ScenarioAgentOpenAIError(
                f"Failed to load domain context: {exc}"
            ) from exc

    def _domain_context_prompt(self, context: dict[str, Any]) -> str:
        if not context:
            return (
                "DOMAIN CONTEXT: nenhum provider configurado. "
                "Não infira valores técnicos."
            )

        return (
            "DOMAIN CONTEXT — referência apenas; não é estado atual nem "
            "autorização para preencher valores. Exemplos não são defaults.\n\n"
            + json.dumps(context, ensure_ascii=False, indent=2)
        )

    def _application_context(self) -> dict[str, Any]:
        return {
            "scenario_state": self.scenario_agent.conversation_state(),
            "scenario_snapshot": self.scenario_agent.snapshot(),
            "explicit_requirements": self.explicit_requirements,
            "project_evidence": self._project_evidence,
            "pending_question": self.pending_question,
        }

    def _request_model(self, user_message: str) -> dict[str, Any]:
        if not isinstance(user_message, str):
            raise TypeError("user_message must be a string")

        user_message = user_message.strip()
        if not user_message:
            raise ValueError("user_message cannot be empty")

        app_context = self._application_context()
        domain_context = self._domain_context()

        current_user_message = {
            "role": "user",
            "content": (
                "MENSAGEM ATUAL DO USUÁRIO\n"
                f"{user_message}\n\n"
                "CONTEXTO ATUAL DA APLICAÇÃO\n"
                f"{json.dumps(app_context, ensure_ascii=False, indent=2)}"
            ),
        }

        inputs = [
            {"role": "system", "content": self._system_prompt()},
            {
                "role": "system",
                "content": self._domain_context_prompt(domain_context),
            },
            *self.messages,
            current_user_message,
        ]

        try:
            response = self.client.responses.create(
                model=self.model,
                reasoning={"effort": "medium"},
                input=inputs,
                text={"format": {"type": "json_object"}},
            )
        except Exception as exc:
            raise ScenarioAgentOpenAIError(
                f"OpenAI request failed: {exc}"
            ) from exc

        if getattr(response, "status", None) == "incomplete":
            raise ScenarioAgentOpenAIError(
                "OpenAI returned an incomplete response: "
                f"{getattr(response, 'incomplete_details', None)!r}"
            )

        output = getattr(response, "output_text", None)
        if not output or not output.strip():
            raise ScenarioAgentOpenAIError("OpenAI returned an empty response")

        output = output.strip()

        try:
            action = json.loads(output)
        except json.JSONDecodeError as exc:
            raise ScenarioAgentOpenAIError(
                f"OpenAI returned invalid JSON: {output[:2000]!r}"
            ) from exc

        if not isinstance(action, dict):
            raise ScenarioAgentOpenAIError(
                "Model response must be a JSON object"
            )

        # A troca fica pendente até que o chamador decida como registrá-la.
        self._pending_exchange = [
            current_user_message,
            {"role": "assistant", "content": output},
        ]

        return action

    def _validate_action(self, action: dict[str, Any]) -> None:
        if not isinstance(action, dict):
            raise ScenarioAgentOpenAIError(
                "Model action must be a JSON object"
            )

        if action.get("action") not in self.ALLOWED_ACTIONS:
            raise ScenarioAgentOpenAIError(
                f"Unsupported model action: {action.get('action')!r}"
            )

    def _apply_action(
        self,
        action: dict[str, Any],
        user_message: str,
    ) -> dict[str, Any]:
        self._validate_action(action)
        name = action["action"]

        if name == "update_scenario":
            updates = action.get("updates")

            if not isinstance(updates, dict) or not updates:
                raise ScenarioAgentOpenAIError(
                    "update_scenario requires a non-empty updates dictionary"
                )

            result = self.scenario_agent.process_update(updates)
            self.pending_question = None
            return result

        if name == "ask_user":
            question = action.get("question")
            fields = action.get("fields", [])

            if not isinstance(question, str) or not question.strip():
                raise ScenarioAgentOpenAIError(
                    "ask_user requires a non-empty question"
                )

            if fields is None:
                fields = []

            if not isinstance(fields, list) or any(
                not isinstance(field, str) for field in fields
            ):
                raise ScenarioAgentOpenAIError(
                    "ask_user fields must be a list of strings"
                )

            self.pending_question = {
                "question": question.strip(),
                "fields": fields,
            }

            return {
                "action": "ask_user",
                "question": question.strip(),
                "fields": fields,
                "explicit_requirements": self.explicit_requirements,
            }

        if name == "confirm":
            if not self._is_explicit_confirmation(user_message):
                raise ScenarioAgentOpenAIError(
                    "Confirmação recusada: a mensagem atual não contém "
                    "confirmação explícita."
                )

            self.pending_question = None
            return self.scenario_agent.process_confirmation(
                confirmed=True
            )

        if name == "reject_confirmation":
            self.pending_question = None
            return self.scenario_agent.process_confirmation(
                confirmed=False
            )

        if name == "finalize":
            state = self.scenario_agent.conversation_state()
            ready = (
                state.get("valid") is True
                and state.get("complete") is True
                and state.get("confirmed") is True
                and state.get("next_action") == "finalize"
            )

            if not ready:
                raise ScenarioAgentOpenAIError(
                    "Finalização recusada: cenário não está válido, "
                    f"completo e confirmado. Estado: {state!r}"
                )

            self.pending_question = None
            return self.scenario_agent.process_finalize()

        raise ScenarioAgentOpenAIError(f"Unhandled action: {name}")

    def chat(self, user_message: str) -> dict[str, Any]:
        if not isinstance(user_message, str):
            raise TypeError("user_message must be a string")

        message = user_message.strip()
        if not message:
            raise ValueError("user_message cannot be empty")

        # Acumula os requisitos explícitos antes de consultar o modelo.
        self._refresh_explicit_requirements(message)

        state = self.scenario_agent.conversation_state()

        # Confirmação direta: só ocorre quando o estado já exige confirmação
        # e a mensagem atual é uma confirmação explícita.
        if (
            state.get("next_action") == "confirm"
            and self._is_explicit_confirmation(message)
        ):
            return self._apply_action(
                {"action": "confirm"},
                message,
            )

        normalized = self._normalize_confirmation_text(message)

        finalize_phrases = {
            "finalizar",
            "finalize",
            "pode finalizar",
            "pode gerar",
            "pode gravar",
            "gerar scenario toml",
            "gerar o scenario toml",
            "gravar scenario toml",
            "finalizar o cenario",
            "gerar o cenario confirmado",
            "pode gerar o scenario toml",
        }

        if (
            state.get("next_action") == "finalize"
            and normalized in finalize_phrases
        ):
            return self._apply_action(
                {"action": "finalize"},
                message,
            )

        self._pending_exchange = None
        action = self._request_model(message)

        # Preserva o turno recebido, inclusive se a aplicação da ação falhar.
        # Isso mantém a mensagem disponível para as próximas interações.
        exchange = self._pending_exchange
        self._pending_exchange = None

        if exchange is not None:
            self.messages.extend(exchange)

        return self._apply_action(action, message)


def create_scenario_agent_openai(
    project_path: str | Path,
    *,
    model: str | None = None,
    domain_context_provider: DomainContextProvider | None = None,
    domain_context_sections: tuple[str, ...] | None = None,
) -> ScenarioAgentOpenAI:
    project = PlanningProject(project_path)

    return ScenarioAgentOpenAI(
        project,
        model=model,
        domain_context_provider=domain_context_provider,
        domain_context_sections=domain_context_sections,
    )


if __name__ == "__main__":
    from scenario_domain.providers import (
        CISEIPluginDomainContextProvider,
    )

    project_path = Path(os.getenv("SCENARIO_PROJECT_PATH", "."))
    plugin_path = (
        Path("/home/jovyan/work/planapp-mcp")
        / "cisei-planning-engineering"
    )

    provider = CISEIPluginDomainContextProvider(plugin_path)
    agent = create_scenario_agent_openai(
        project_path,
        domain_context_provider=provider,
    )

    print("ScenarioAgentOpenAI criado com sucesso.")
    print("Domain provider:", provider.provider_id)
    print("Domain version:", provider.provider_version)
    print("Domain sections:", agent.domain_context_sections)
