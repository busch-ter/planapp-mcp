"""
VibePlanner AI — Scenario Builder
POC-01

Responsabilidade
----------------
Construir um cenário de planejamento a partir de informações
explicitamente fornecidas pelo usuário.

Regras arquiteturais
--------------------
1. Não inferir valores técnicos ausentes.
2. Não chamar Planning Service.
3. Não chamar MCP.
4. Não executar planejamento.
5. Manter uma especificação estruturada intermediária.
6. Validar completude antes de gerar o TOML.
7. Exigir confirmação explícita do usuário antes da geração final.
8. Gerar scenario.toml de forma determinística.

Fluxo:

    usuário
       |
       v
    agente / interface
       |
       v
    ScenarioBuilder
       |
       +--> validação
       |
       +--> confirmação
       |
       v
    scenario.toml
       |
       v
    futuramente:
    MCP -> Planning Service

O TOML é um artefato de autoria/persistência.
A especificação estruturada em dict poderá futuramente ser
enviada diretamente ao Planning Service.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import math
import re


# ============================================================
# RESULTADO DA VALIDAÇÃO
# ============================================================


@dataclass
class ValidationResult:
    """Resultado produzido por ScenarioBuilder.validate()."""

    valid: bool
    missing: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        """
        True somente quando não existem campos faltantes
        nem erros de validação.
        """
        return self.valid and not self.missing and not self.errors

    def as_dict(self) -> dict[str, Any]:
        """Retorna o resultado em formato serializável."""
        return {
            "valid": self.valid,
            "complete": self.complete,
            "missing": list(self.missing),
            "errors": list(self.errors),
        }


# ============================================================
# SCENARIO BUILDER
# ============================================================


class ScenarioBuilder:
    """
    Builder determinístico para o POC-01 do Scenario Builder.

    O builder começa vazio.

    Nenhum dos seguintes valores é assumido automaticamente:

    - CRS
    - tecnologia
    - frequência
    - potência
    - altura
    - modelo de antena
    - azimute
    - downtilt
    - beamwidth
    - capacidade de relay
    - capacidade de roteamento
    - rank
    - profiles
    - métrica
    - arquivo CSV
    - coluna de profile

    Esses valores precisam ser fornecidos explicitamente pelo
    usuário/aplicação.

    Estrutura esperada:

        scenario
        antennas
        interfaces
        devices
        metrics
        instances (required): source, format, profile_column
        net (optional; connectivity/candidate_edges)
        sites (optional embedded concrete representation; does not replace
              the required instances fields)
    """

    # ========================================================
    # SEÇÕES PRINCIPAIS
    # ========================================================

    TOP_LEVEL_SECTIONS = (
        "scenario",
        "antennas",
        "interfaces",
        "devices",
        "metrics",
        "instances",
        "net",
        "sites",
    )

    # Campos obrigatórios do contrato POC-01.
    # O Builder valida estes campos, mas nunca cria defaults.
    REQUIRED_FIELDS = (
        "scenario.working_crs",
        "instances.source",
        "instances.format",
        "instances.profile_column",
    )

    # ========================================================
    # CAMPOS OBRIGATÓRIOS POR OBJETO
    #
    # ATENÇÃO:
    #
    # Não colocar aqui campos que sejam condicionais.
    #
    # Exemplos:
    #   - beamwidth_deg depende de kind=sector
    #   - rank pode não existir em determinados devices
    #
    # Essas regras são tratadas separadamente.
    # ========================================================

    REQUIRED_SECTION_MAP = {
        # Antenna profile fields are optional according to the canonical
        # contract. In particular model_id, azimuth_deg and downtilt_deg
        # are not universally required. The SDK recognizes additional
        # metadata and currently still recognizes the deprecated height_m.
        "antennas": (),
        "interfaces": (
            "tech",
            "freq_mhz",
            "tx_power_dbm",
            "antenna_id",
        ),
        "devices": (
            "interfaces",
        ),
        # Metric profiles may use a built-in spec, inline specification,
        # or a local TOML source; do not require a literal `spec` key.
        "metrics": (),
    }

    # ========================================================
    # CONSTRUTOR
    # ========================================================

    def __init__(self) -> None:
        """
        Inicializa um cenário vazio.

        Não existem defaults técnicos aqui de propósito.
        """

        self.spec: dict[str, Any] = {
            "scenario": {},
            "antennas": {},
            "interfaces": {},
            "devices": {},
            "metrics": {},
            "instances": {},
        }

        # A confirmação só pode acontecer depois que o cenário
        # estiver completo e válido.
        self.confirmed: bool = False

    # ========================================================
    # API PÚBLICA
    # ========================================================

    def update(
        self,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Atualiza parcialmente a especificação.

        Dicionários aninhados são mesclados recursivamente.

        Exemplo:

            builder.update({
                "scenario": {
                    "working_crs": "EPSG:31982"
                }
            })

        Nenhum valor ausente é criado automaticamente.
        """

        if not isinstance(data, dict):
            raise TypeError(
                "Scenario data must be a dictionary."
            )

        self._merge_dict(
            self.spec,
            data,
        )

        # Qualquer alteração invalida uma confirmação anterior.
        self.confirmed = False

        return self.to_dict()

    # --------------------------------------------------------

    def replace(
        self,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Substitui completamente a especificação atual.

        Útil quando a aplicação já possui uma especificação
        completa e deseja carregá-la de uma vez.
        """

        if not isinstance(data, dict):
            raise TypeError(
                "Scenario data must be a dictionary."
            )

        self.spec = {
            "scenario": {},
            "antennas": {},
            "interfaces": {},
            "devices": {},
            "metrics": {},
            "instances": {},
        }

        self._merge_dict(
            self.spec,
            data,
        )

        self.confirmed = False

        return self.to_dict()

    # --------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """
        Retorna uma cópia independente da especificação atual.
        """

        return deepcopy(self.spec)

    # --------------------------------------------------------

    def missing_fields(self) -> list[str]:
        """
        Retorna os campos ainda necessários.
        """

        return self.validate().missing

    # --------------------------------------------------------

    def validate(self) -> ValidationResult:
        """
        Valida a especificação atual.

        A validação é deliberadamente conservadora.

        Ela verifica:

        - campos obrigatórios;
        - existência das coleções;
        - estrutura dos objetos;
        - regras condicionais;
        - referências entre objetos;
        - tipos básicos;
        - números finitos.

        Ela NÃO tenta interpretar semanticamente os parâmetros.
        """

        missing: list[str] = []
        errors: list[str] = []

        # ====================================================
        # CONTRATO OBRIGATÓRIO: CENÁRIO E INSTÂNCIAS
        # ====================================================

        scenario = self.spec.get("scenario", {})
        if not isinstance(scenario, dict):
            errors.append("scenario must be a dictionary.")
            scenario = {}

        working_crs = scenario.get("working_crs")
        if working_crs is None or (
            isinstance(working_crs, str) and not working_crs.strip()
        ):
            missing.append("scenario.working_crs")
        elif not isinstance(working_crs, str):
            errors.append("scenario.working_crs must be a non-empty string.")

        instances = self.spec.get("instances", {})
        if not isinstance(instances, dict):
            errors.append("instances must be a dictionary.")
            instances = {}

        sites = self.spec.get("sites", [])
        if sites is not None and not isinstance(sites, list):
            errors.append("sites must be a list.")
            sites = []

        # Os campos abaixo são obrigatórios mesmo quando sites
        # embutidos também são fornecidos.
        source_value = instances.get("source")
        if source_value is None or (
            isinstance(source_value, str) and not source_value.strip()
        ):
            missing.append("instances.source")
        elif not isinstance(source_value, str):
            errors.append("instances.source must be a non-empty string.")

        if "format" not in instances or instances.get("format") is None:
            missing.append("instances.format")
        elif instances["format"] != "csv":
            errors.append("instances.format must currently be 'csv'.")

        profile_column = instances.get("profile_column")
        if profile_column is None or (
            isinstance(profile_column, str) and not profile_column.strip()
        ):
            missing.append("instances.profile_column")
        elif not isinstance(profile_column, str):
            errors.append(
                "instances.profile_column must be a non-empty string."
            )

        has_csv_instances = bool(instances)
        has_embedded_sites = isinstance(sites, list) and bool(sites)

        # ====================================================
        # COLEÇÕES DE PERFIS
        # ====================================================

        # A representação CSV exige perfis reutilizáveis de antenas,
        # interfaces e dispositivos. Sites embutidos podem conter dispositivos
        # e interfaces concretos, dispensando os templates de interfaces e
        # dispositivos. Em todos os modos, os quatro campos obrigatórios do
        # contrato acima continuam sendo exigidos.
        required_profile_sections = ["antennas", "metrics"]
        if has_csv_instances or not has_embedded_sites:
            required_profile_sections.extend(["interfaces", "devices"])
        for section in required_profile_sections:
            value = self.spec.get(section)
            if not isinstance(value, dict) or not value:
                missing.append(f"{section}.<at_least_one>")

        # ====================================================
        # OBJETOS INTERNOS
        # ====================================================

        for (
            section,
            required_fields,
        ) in self.REQUIRED_SECTION_MAP.items():

            objects = self.spec.get(
                section,
                {},
            )

            if not isinstance(
                objects,
                dict,
            ):

                errors.append(
                    f"{section} must be a dictionary "
                    "of named objects."
                )

                continue

            for (
                object_name,
                obj,
            ) in objects.items():

                if not isinstance(
                    obj,
                    dict,
                ):

                    errors.append(
                        f"{section}.{object_name} "
                        "must be a dictionary."
                    )

                    continue

                for field_name in required_fields:

                    if (
                        field_name not in obj
                        or obj[field_name] is None
                    ):

                        missing.append(
                            f"{section}."
                            f"{object_name}."
                            f"{field_name}"
                        )

        # `devices.<id>.interfaces` must be a non-empty list according
        # to the canonical contract.
        devices_for_shape = self.spec.get("devices", {})
        if isinstance(devices_for_shape, dict):
            for device_name, device in devices_for_shape.items():
                if not isinstance(device, dict):
                    continue
                interface_ids = device.get("interfaces")
                if isinstance(interface_ids, list) and not interface_ids:
                    errors.append(f"devices.{device_name}.interfaces must be a non-empty list.")

        # ====================================================
        # NET RULES / EMBEDDED SITES
        # ====================================================
        net = self.spec.get("net", {})
        if net is not None and not isinstance(net, dict):
            errors.append("net must be a dictionary.")
        elif isinstance(net, dict):
            for key in ("connectivity", "candidate_edges"):
                entries = net.get(key)
                if entries is not None and not isinstance(entries, list):
                    errors.append(f"net.{key} must be a list.")
                    continue
                if isinstance(entries, list):
                    for index, entry in enumerate(entries):
                        if not isinstance(entry, dict):
                            errors.append(f"net.{key}[{index}] must be a dictionary.")
                            continue
                        if key == "connectivity":
                            if entry.get("kind") == "rf" and not entry.get("tech"):
                                missing.append(f"net.connectivity[{index}].tech")
                        else:
                            for required_edge_field in ("src", "dst"):
                                if entry.get(required_edge_field) is None:
                                    missing.append(f"net.candidate_edges[{index}].{required_edge_field}")

        embedded_sites = self.spec.get("sites", [])
        if isinstance(embedded_sites, list):
            for index, site in enumerate(embedded_sites):
                if not isinstance(site, dict):
                    errors.append(f"sites[{index}] must be a dictionary.")
                    continue
                if not site.get("site_id"):
                    missing.append(f"sites[{index}].site_id")
                has_latlon = site.get("lat") is not None and site.get("lon") is not None
                has_xy = site.get("x") is not None and site.get("y") is not None
                if not (has_latlon or has_xy):
                    missing.append(f"sites[{index}].(lat/lon or x/y)")
                site_devices = site.get("devices", [])
                if site_devices is not None and not isinstance(site_devices, list):
                    errors.append(f"sites[{index}].devices must be a list when provided.")
                    continue
                for device_index, concrete_device in enumerate(site_devices or []):
                    device_path = f"sites[{index}].devices[{device_index}]"
                    if not isinstance(concrete_device, dict):
                        errors.append(f"{device_path} must be a dictionary.")
                        continue
                    for field_name in ("device_id", "site_id"):
                        if concrete_device.get(field_name) is None:
                            missing.append(f"{device_path}.{field_name}")
                    concrete_interfaces = concrete_device.get("interfaces", [])
                    if not isinstance(concrete_interfaces, list):
                        errors.append(f"{device_path}.interfaces must be a list when provided.")
                        continue
                    for interface_index, concrete_interface in enumerate(concrete_interfaces):
                        interface_path = f"{device_path}.interfaces[{interface_index}]"
                        if not isinstance(concrete_interface, dict):
                            errors.append(f"{interface_path} must be a dictionary.")
                            continue
                        for field_name in ("interface_id", "device_id", "tech", "freq_mhz", "tx_power_dbm", "antenna_id"):
                            if concrete_interface.get(field_name) is None:
                                missing.append(f"{interface_path}.{field_name}")
                        for field_name in ("freq_mhz", "tx_power_dbm"):
                            self._check_number(concrete_interface.get(field_name), f"{interface_path}.{field_name}", errors)
                        antenna_id = concrete_interface.get("antenna_id")
                        if antenna_id is not None and antenna_id not in self.spec.get("antennas", {}):
                            errors.append(f"{interface_path}.antenna_id references unknown antenna '{antenna_id}'.")
                        # A correspondência entre tech e metrics é
                        # validada centralmente após a construção das seções.
                        # Não rejeitar interfaces durante a montagem incremental.

        # ====================================================
        # REGRAS CONDICIONAIS DE ANTENAS
        # ====================================================

        antennas = self.spec.get(
            "antennas",
            {},
        )

        if isinstance(
            antennas,
            dict,
        ):

            for (
                name,
                antenna,
            ) in antennas.items():

                if not isinstance(
                    antenna,
                    dict,
                ):

                    continue

                kind = antenna.get(
                    "kind"
                )

                # ------------------------------------------------
                # Sector
                # ------------------------------------------------
                #
                # Para uma antena sector, beamwidth_deg faz
                # parte da configuração explícita.
                #
                # ------------------------------------------------

                # The canonical schema recognizes beamwidth_deg but does
                # not make it universally required. Fixed-sector orientation
                # constraints belong to planner/domain validation.
                if kind not in (None, "omni", "sector"):
                    errors.append(
                        f"antennas.{name}.kind must be 'omni' or 'sector' when provided."
                    )

                # ------------------------------------------------
                # Omni
                # ------------------------------------------------
                #
                # Para uma antena omni, beamwidth_deg NÃO é
                # obrigatório.
                #
                # ------------------------------------------------

                elif kind == "omni":

                    pass

        # ====================================================
        # CRS
        # ====================================================
        # scenario.working_crs já é validado como obrigatório na seção
        # CONTRATO OBRIGATÓRIO: CENÁRIO E INSTÂNCIAS.

        # ====================================================
        # REFERÊNCIAS
        # ====================================================

        self._validate_references(
            errors
        )

        # Cada tecnologia usada por uma interface deve possuir uma
        # entrada de métricas correspondente, conforme o contrato.
        interfaces_for_metrics = self.spec.get("interfaces", {})
        metrics_for_tech = self.spec.get("metrics", {})
        if (
            isinstance(interfaces_for_metrics, dict)
            and isinstance(metrics_for_tech, dict)
            and bool(metrics_for_tech)
        ):
            for interface_name, interface in interfaces_for_metrics.items():
                if not isinstance(interface, dict):
                    continue
                tech = interface.get("tech")
                if tech and tech not in metrics_for_tech:
                    errors.append(
                        f"interfaces.{interface_name}.tech '{tech}' has no matching metrics.{tech} entry."
                    )

        # ====================================================
        # VALORES NUMÉRICOS
        # ====================================================

        self._validate_numeric_fields(
            errors
        )

        # ====================================================
        # REMOVER DUPLICAÇÕES
        # ====================================================

        missing = list(
            dict.fromkeys(missing)
        )

        errors = list(
            dict.fromkeys(errors)
        )

        return ValidationResult(
            valid=not errors,
            missing=missing,
            errors=errors,
        )

    # --------------------------------------------------------

    def is_complete(self) -> bool:
        """
        Retorna True quando o cenário está completo e válido.
        """

        return self.validate().complete

    # --------------------------------------------------------

    def confirm(self) -> ValidationResult:
        """
        Confirma explicitamente o cenário.

        A confirmação somente é aceita quando o cenário
        estiver completo e válido.
        """

        result = self.validate()

        if not result.complete:

            self.confirmed = False

            return result

        self.confirmed = True

        return result

    # --------------------------------------------------------

    def generate_toml(
        self,
        *,
        require_confirmation: bool = True,
    ) -> str:
        """
        Gera o TOML determinístico.

        Por padrão exige:

        1. cenário completo;
        2. cenário válido;
        3. confirmação explícita.

        Isso evita que o agente gere um scenario.toml
        parcialmente preenchido.
        """

        result = self.validate()

        if not result.complete:

            raise ValueError(
                self._format_validation_error(
                    result
                )
            )

        if (
            require_confirmation
            and not self.confirmed
        ):

            raise RuntimeError(
                "Scenario is complete but has not "
                "been confirmed. Call confirm() after "
                "presenting the collected values to "
                "the user."
            )

        return self._to_toml(
            self.spec
        )

    # --------------------------------------------------------

    def save_toml(
        self,
        path: str | Path,
        *,
        require_confirmation: bool = True,
        encoding: str = "utf-8",
    ) -> str:
        """
        Gera e salva o scenario.toml.

        Retorna o texto gerado.
        """

        text = self.generate_toml(
            require_confirmation=require_confirmation
        )

        destination = Path(path)

        destination.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        destination.write_text(
            text,
            encoding=encoding,
        )

        return text

    # ========================================================
    # MERGE / LOOKUP
    # ========================================================

    @classmethod
    def _merge_dict(
        cls,
        destination: dict[str, Any],
        source: dict[str, Any],
    ) -> None:
        """
        Faz merge recursivo de dicionários.
        """

        for (
            key,
            value,
        ) in source.items():

            if (
                isinstance(
                    value,
                    dict,
                )
                and isinstance(
                    destination.get(key),
                    dict,
                )
            ):

                cls._merge_dict(
                    destination[key],
                    value,
                )

            else:

                destination[key] = deepcopy(
                    value
                )

    # --------------------------------------------------------

    @staticmethod
    def _get_path(
        data: dict[str, Any],
        path: str,
    ) -> Any:
        """
        Obtém um valor usando caminho pontuado.

        Exemplo:

            _get_path(
                spec,
                "scenario.working_crs"
            )
        """

        current: Any = data

        for part in path.split("."):

            if (
                not isinstance(
                    current,
                    dict,
                )
                or part not in current
            ):

                return None

            current = current[part]

        return current

    # ========================================================
    # VALIDAÇÃO DE REFERÊNCIAS
    # ========================================================

    def _validate_references(
        self,
        errors: list[str],
    ) -> None:

        antennas = self.spec.get(
            "antennas",
            {},
        )

        interfaces = self.spec.get(
            "interfaces",
            {},
        )

        devices = self.spec.get(
            "devices",
            {},
        )

        # ====================================================
        # interface -> antenna
        # ====================================================

        if isinstance(
            interfaces,
            dict,
        ):

            for (
                name,
                interface,
            ) in interfaces.items():

                if not isinstance(
                    interface,
                    dict,
                ):

                    continue

                antenna_id = interface.get(
                    "antenna_id"
                )

                if (
                    antenna_id is not None
                    and antenna_id not in antennas
                ):

                    errors.append(
                        f"interfaces.{name}.antenna_id "
                        f"references unknown antenna "
                        f"'{antenna_id}'."
                    )

        # ====================================================
        # device -> interface
        # ====================================================

        if isinstance(
            devices,
            dict,
        ):

            for (
                name,
                device,
            ) in devices.items():

                if not isinstance(
                    device,
                    dict,
                ):

                    continue

                interface_ids = device.get(
                    "interfaces"
                )

                if interface_ids is None:
                    continue

                if not isinstance(
                    interface_ids,
                    list,
                ):

                    errors.append(
                        f"devices.{name}.interfaces "
                        "must be a list."
                    )

                    continue

                for interface_id in interface_ids:

                    if interface_id not in interfaces:

                        errors.append(
                            f"devices.{name}.interfaces "
                            f"references unknown interface "
                            f"'{interface_id}'."
                        )

    # ========================================================
    # VALIDAÇÃO NUMÉRICA
    # ========================================================

    def _validate_numeric_fields(
        self,
        errors: list[str],
    ) -> None:

        antennas = self.spec.get(
            "antennas",
            {},
        )

        interfaces = self.spec.get(
            "interfaces",
            {},
        )

        devices = self.spec.get(
            "devices",
            {},
        )

        # ====================================================
        # ANTENAS
        # ====================================================

        if isinstance(
            antennas,
            dict,
        ):

            for (
                name,
                antenna,
            ) in antennas.items():

                if not isinstance(
                    antenna,
                    dict,
                ):

                    continue

                self._check_number(
                    antenna.get(
                        "height_m"
                    ),
                    f"antennas.{name}.height_m",
                    errors,
                )
                self._check_number(
                    antenna.get("gain_dbi"),
                    f"antennas.{name}.gain_dbi",
                    errors,
                )

                self._check_number(
                    antenna.get(
                        "azimuth_deg"
                    ),
                    f"antennas.{name}.azimuth_deg",
                    errors,
                )

                self._check_number(
                    antenna.get(
                        "downtilt_deg"
                    ),
                    f"antennas.{name}.downtilt_deg",
                    errors,
                )

                # beamwidth pode não existir para omni.
                if "beamwidth_deg" in antenna:

                    self._check_number(
                        antenna.get(
                            "beamwidth_deg"
                        ),
                        f"antennas.{name}.beamwidth_deg",
                        errors,
                    )

        # ====================================================
        # INTERFACES
        # ====================================================

        if isinstance(
            interfaces,
            dict,
        ):

            for (
                name,
                interface,
            ) in interfaces.items():

                if not isinstance(
                    interface,
                    dict,
                ):

                    continue

                self._check_number(
                    interface.get(
                        "freq_mhz"
                    ),
                    f"interfaces.{name}.freq_mhz",
                    errors,
                )

                self._check_number(
                    interface.get(
                        "tx_power_dbm"
                    ),
                    f"interfaces.{name}.tx_power_dbm",
                    errors,
                )

        # ====================================================
        # DEVICES
        # ====================================================

        if isinstance(
            devices,
            dict,
        ):

            for (
                name,
                device,
            ) in devices.items():

                if not isinstance(
                    device,
                    dict,
                ):

                    continue

                self._check_number(
                    device.get("mount_height_m"),
                    f"devices.{name}.mount_height_m",
                    errors,
                )

                # rank é opcional.
                #
                # Se estiver presente, deve ser numérico.
                if "rank" in device:

                    self._check_number(
                        device.get(
                            "rank"
                        ),
                        f"devices.{name}.rank",
                        errors,
                    )

    # --------------------------------------------------------

    @staticmethod
    def _check_number(
        value: Any,
        field_path: str,
        errors: list[str],
    ) -> None:

        if value is None:
            return

        if (
            isinstance(value, bool)
            or not isinstance(
                value,
                (int, float),
            )
        ):

            errors.append(
                f"{field_path} must be numeric."
            )

            return

        if (
            isinstance(
                value,
                float,
            )
            and not math.isfinite(value)
        ):

            errors.append(
                f"{field_path} must be finite."
            )

    # ========================================================
    # TOML SERIALIZATION
    # ========================================================

    @classmethod
    def _to_toml(
        cls,
        spec: dict[str, Any],
    ) -> str:
        """
        Serializa a especificação em TOML.

        A ordem das seções é fixa para tornar o resultado
        determinístico e fácil de comparar com um cenário
        de referência.
        """

        lines: list[str] = []

        # ====================================================
        # [scenario]
        # ====================================================

        scenario = spec.get(
            "scenario",
            {},
        )

        lines.append(
            "[scenario]"
        )

        for (
            key,
            value,
        ) in scenario.items():

            lines.append(
                f"{key} = "
                f"{cls._toml_value(value)}"
            )

        lines.append("")

        # ====================================================
        # [antennas.*]
        # ====================================================

        cls._append_named_tables(
            lines,
            "antennas",
            spec.get(
                "antennas",
                {},
            ),
        )

        # ====================================================
        # [interfaces.*]
        # ====================================================

        cls._append_named_tables(
            lines,
            "interfaces",
            spec.get(
                "interfaces",
                {},
            ),
        )

        # ====================================================
        # [devices.*]
        # ====================================================

        cls._append_named_tables(
            lines,
            "devices",
            spec.get(
                "devices",
                {},
            ),
        )

        # ====================================================
        # [metrics.*]
        # ====================================================

        cls._append_named_tables(
            lines,
            "metrics",
            spec.get(
                "metrics",
                {},
            ),
        )

        # ====================================================
        # [instances]
        # ====================================================

        instances = spec.get(
            "instances",
            {},
        )

        if instances:

            lines.append(
                "[instances]"
            )

            for (
                key,
                value,
            ) in instances.items():

                lines.append(
                    f"{key} = "
                    f"{cls._toml_value(value)}"
                )

            lines.append("")

        # ====================================================
        # [net] — mantém connectivity e candidate_edges.
        # Arrays de inline tables são TOML válido e preservam a
        # mesma estrutura dict/list após o parse.
        # ====================================================
        net = spec.get("net", {})
        if net:
            if not isinstance(net, dict):
                raise ValueError("net must be a dictionary for TOML generation.")
            lines.append("[net]")
            for key, value in net.items():
                lines.append(f"{key} = {cls._toml_value(value)}")
            lines.append("")

        # ====================================================
        # [[sites]] — representação concreta opcional embutida.
        # Cada site é uma array-table TOML; campos aninhados, como
        # devices/interfaces, são preservados como inline tables.
        # ====================================================
        sites = spec.get("sites", [])
        if sites:
            if not isinstance(sites, list):
                raise ValueError("sites must be a list for TOML generation.")
            for index, site in enumerate(sites):
                if not isinstance(site, dict):
                    raise ValueError(f"sites[{index}] must be a dictionary for TOML generation.")
                lines.append("[[sites]]")
                for key, value in site.items():
                    lines.append(f"{key} = {cls._toml_value(value)}")
                lines.append("")

        return (
            "\n".join(lines)
            .rstrip()
            + "\n"
        )

    # --------------------------------------------------------

    @classmethod
    def _append_named_tables(
        cls,
        lines: list[str],
        section_name: str,
        objects: Any,
    ) -> None:
        """
        Gera tabelas TOML nomeadas.

        Exemplo:

            [antennas.lte_sector_0]

            ...

            [interfaces.lte_sector_0]

            ...
        """

        if not objects:
            return

        if not isinstance(
            objects,
            dict,
        ):

            raise ValueError(
                f"{section_name} must be "
                "a dictionary for TOML generation."
            )

        for (
            object_name,
            values,
        ) in objects.items():

            if not isinstance(
                values,
                dict,
            ):

                raise ValueError(
                    f"{section_name}.{object_name} "
                    "must be a dictionary."
                )

            table_name = cls._quote_table_key(
                object_name
            )

            lines.append(
                f"[{section_name}.{table_name}]"
            )

            for (
                key,
                value,
            ) in values.items():

                lines.append(
                    f"{key} = "
                    f"{cls._toml_value(value)}"
                )

            lines.append("")

    # --------------------------------------------------------

    @staticmethod
    def _quote_table_key(
        value: str,
    ) -> str:
        """
        Mantém identificadores simples sem aspas.

        Exemplo:

            lte_sector_0

        permanece:

            lte_sector_0
        """

        if re.fullmatch(
            r"[A-Za-z0-9_-]+",
            value,
        ):

            return value

        return (
            '"'
            + value
            .replace(
                "\\",
                "\\\\",
            )
            .replace(
                '"',
                '\\"',
            )
            + '"'
        )

    # --------------------------------------------------------

    @classmethod
    def _toml_value(
        cls,
        value: Any,
    ) -> str:
        """
        Converte um valor Python para TOML.
        """

        # ====================================================
        # BOOLEAN
        # ====================================================

        if isinstance(
            value,
            bool,
        ):

            return (
                "true"
                if value
                else "false"
            )

        # ====================================================
        # INTEGER
        # ====================================================

        if (
            isinstance(
                value,
                int,
            )
            and not isinstance(
                value,
                bool,
            )
        ):

            return str(value)

        # ====================================================
        # FLOAT
        # ====================================================

        if isinstance(
            value,
            float,
        ):

            if not math.isfinite(
                value
            ):

                raise ValueError(
                    "TOML does not support "
                    "non-finite floats."
                )

            return repr(value)

        # ====================================================
        # STRING
        # ====================================================

        if isinstance(
            value,
            str,
        ):

            escaped = (
                value
                .replace(
                    "\\",
                    "\\\\",
                )
                .replace(
                    '"',
                    '\\"',
                )
                .replace(
                    "\n",
                    "\\n",
                )
                .replace(
                    "\r",
                    "\\r",
                )
                .replace(
                    "\t",
                    "\\t",
                )
            )

            return f'"{escaped}"'

        # ====================================================
        # LIST
        # ====================================================

        if isinstance(
            value,
            list,
        ):

            return (
                "["
                + ", ".join(
                    cls._toml_value(item)
                    for item in value
                )
                + "]"
            )

        # ====================================================
        # TUPLE
        # ====================================================

        if isinstance(
            value,
            tuple,
        ):

            return (
                "["
                + ", ".join(
                    cls._toml_value(item)
                    for item in value
                )
                + "]"
            )

        # ====================================================
        # INLINE TABLE
        # ====================================================

        if isinstance(
            value,
            dict,
        ):

            parts: list[str] = []

            for (
                key,
                item,
            ) in value.items():

                parts.append(
                    f"{cls._quote_inline_key(str(key))}"
                    f" = "
                    f"{cls._toml_value(item)}"
                )

            return (
                "{ "
                + ", ".join(parts)
                + " }"
            )

        # ====================================================
        # TIPO NÃO SUPORTADO
        # ====================================================

        raise TypeError(
            "Unsupported TOML value type: "
            f"{type(value).__name__}"
        )

    # --------------------------------------------------------

    @staticmethod
    def _quote_inline_key(
        value: str,
    ) -> str:

        if re.fullmatch(
            r"[A-Za-z0-9_-]+",
            value,
        ):

            return value

        return (
            '"'
            + value
            .replace(
                "\\",
                "\\\\",
            )
            .replace(
                '"',
                '\\"',
            )
            + '"'
        )

    # ========================================================
    # ERRO DE VALIDAÇÃO
    # ========================================================

    @staticmethod
    def _format_validation_error(
        result: ValidationResult,
    ) -> str:

        parts = [
            "Scenario cannot be generated."
        ]

        if result.missing:

            parts.append(
                "Missing fields: "
                + ", ".join(
                    result.missing
                )
                + "."
            )

        if result.errors:

            parts.append(
                "Validation errors: "
                + " ".join(
                    result.errors
                )
            )

        return " ".join(parts)


__all__ = [
    "ScenarioBuilder",
    "ValidationResult",
]