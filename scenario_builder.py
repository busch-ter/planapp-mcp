from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import math
import re


@dataclass
class ValidationResult:
    """Resultado estruturado da validação de um cenário."""

    valid: bool
    missing: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        """Avisos não bloqueiam a conclusão; ausências e erros bloqueiam."""
        return self.valid and not self.missing and not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "complete": self.complete,
            "missing": list(self.missing),
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


class ScenarioBuilder:
    """Constrói, valida e serializa um cenário sem executar o planejamento."""

    REQUIRED_FIELDS = (
        "scenario.working_crs",
        "instances.source",
        "instances.format",
        "instances.profile_column",
    )

    REQUIRED_SECTION_MAP = {
        "antennas": (),
        "interfaces": (
            "tech",
            "freq_mhz",
            "tx_power_dbm",
            "antenna_id",
        ),
        "devices": ("interfaces",),
        "metrics": (),
    }

    def __init__(self) -> None:
        self.spec: dict[str, Any] = {
            "scenario": {},
            "antennas": {},
            "interfaces": {},
            "devices": {},
            "metrics": {},
            "instances": {},
        }
        self.confirmed = False

    def update(self, data: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise TypeError("Scenario data must be a dictionary.")

        self._merge_dict(self.spec, data)
        self.confirmed = False
        return self.to_dict()

    def replace(self, data: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise TypeError("Scenario data must be a dictionary.")

        self.spec = {
            "scenario": {},
            "antennas": {},
            "interfaces": {},
            "devices": {},
            "metrics": {},
            "instances": {},
        }
        self._merge_dict(self.spec, data)
        self.confirmed = False
        return self.to_dict()

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self.spec)

    def missing_fields(self) -> list[str]:
        return self.validate().missing

    def validate(self) -> ValidationResult:
        missing: list[str] = []
        errors: list[str] = []
        warnings: list[str] = []

        # ---------------------------------------------------------
        # 1. Estrutura geral e campos obrigatórios
        # ---------------------------------------------------------
        scenario = self.spec.get("scenario", {})
        if not isinstance(scenario, dict):
            errors.append("scenario must be a dictionary.")
            scenario = {}

        self._check_required_value(
            scenario,
            "working_crs",
            "scenario.working_crs",
            missing,
            errors,
            expected_type=str,
        )

        instances = self.spec.get("instances", {})
        if not isinstance(instances, dict):
            errors.append("instances must be a dictionary.")
            instances = {}

        self._check_required_value(
            instances,
            "source",
            "instances.source",
            missing,
            errors,
            expected_type=str,
        )

        if "format" not in instances or instances["format"] is None:
            missing.append("instances.format")
        elif instances["format"] != "csv":
            errors.append("instances.format must currently be 'csv'.")

        self._check_required_value(
            instances,
            "profile_column",
            "instances.profile_column",
            missing,
            errors,
            expected_type=str,
        )

        # ---------------------------------------------------------
        # 2. Estrutura das coleções
        # ---------------------------------------------------------
        sites = self.spec.get("sites", [])
        if sites is None:
            sites = []
        elif not isinstance(sites, list):
            errors.append("sites must be a list.")
            sites = []

        has_csv_instances = bool(instances)
        has_embedded_sites = bool(sites)

        required_sections = ["antennas", "metrics"]
        if has_csv_instances or not has_embedded_sites:
            required_sections.extend(["interfaces", "devices"])

        for section in required_sections:
            value = self.spec.get(section, {})
            if not isinstance(value, dict):
                errors.append(
                    f"{section} must be a dictionary of named objects."
                )
            elif not value:
                missing.append(f"{section}.<at_least_one>")

        # Verifica se as coleções de perfis e seus elementos têm
        # a estrutura esperada.
        for section, required_fields in self.REQUIRED_SECTION_MAP.items():
            objects = self.spec.get(section, {})

            if not isinstance(objects, dict):
                errors.append(
                    f"{section} must be a dictionary of named objects."
                )
                continue

            for object_name, obj in objects.items():
                path = f"{section}.{object_name}"

                if not isinstance(object_name, str) or not object_name.strip():
                    errors.append(
                        f"{section} contains an invalid object name."
                    )

                if not isinstance(obj, dict):
                    errors.append(f"{path} must be a dictionary.")
                    continue

                for field_name in required_fields:
                    value = obj.get(field_name)

                    if value is None:
                        missing.append(f"{path}.{field_name}")
                    elif isinstance(value, str) and not value.strip():
                        missing.append(f"{path}.{field_name}")

        # ---------------------------------------------------------
        # 3. Referências dos perfis de dispositivos
        # ---------------------------------------------------------
        devices = self.spec.get("devices", {})
        if isinstance(devices, dict):
            for name, device in devices.items():
                if not isinstance(device, dict):
                    continue

                refs = device.get("interfaces")

                if refs is None:
                    continue

                if not isinstance(refs, list):
                    errors.append(
                        f"devices.{name}.interfaces must be a list."
                    )
                    continue

                if not refs:
                    errors.append(
                        f"devices.{name}.interfaces must be a non-empty list."
                    )
                    continue

                for index, ref in enumerate(refs):
                    if not isinstance(ref, str) or not ref.strip():
                        errors.append(
                            f"devices.{name}.interfaces[{index}] "
                            "must be a non-empty string."
                        )

        # ---------------------------------------------------------
        # 4. Configuração da rede
        # ---------------------------------------------------------
        net = self.spec.get("net", {})

        if net is not None and not isinstance(net, dict):
            errors.append("net must be a dictionary.")

        elif isinstance(net, dict):
            for key in ("connectivity", "candidate_edges"):
                entries = net.get(key)

                if entries is not None and not isinstance(entries, list):
                    errors.append(f"net.{key} must be a list.")
                    continue

                if not isinstance(entries, list):
                    continue

                for index, entry in enumerate(entries):
                    path = f"net.{key}[{index}]"

                    if not isinstance(entry, dict):
                        errors.append(f"{path} must be a dictionary.")
                        continue

                    if key == "connectivity":
                        if entry.get("kind") == "rf":
                            self._check_required_value(
                                entry,
                                "tech",
                                f"{path}.tech",
                                missing,
                                errors,
                                expected_type=str,
                            )
                    else:
                        for field_name in ("src", "dst"):
                            self._check_required_value(
                                entry,
                                field_name,
                                f"{path}.{field_name}",
                                missing,
                                errors,
                                expected_type=str,
                            )

        # ---------------------------------------------------------
        # 5. Sites incorporados no TOML, quando utilizados
        # ---------------------------------------------------------
        antennas = self.spec.get("antennas", {})
        metrics = self.spec.get("metrics", {})

        if isinstance(sites, list):
            for index, site in enumerate(sites):
                path = f"sites[{index}]"

                if not isinstance(site, dict):
                    errors.append(f"{path} must be a dictionary.")
                    continue

                self._check_required_value(
                    site,
                    "site_id",
                    f"{path}.site_id",
                    missing,
                    errors,
                    expected_type=str,
                )

                has_latlon = (
                    site.get("lat") is not None
                    and site.get("lon") is not None
                )
                has_xy = (
                    site.get("x") is not None
                    and site.get("y") is not None
                )

                if not (has_latlon or has_xy):
                    missing.append(f"{path}.(lat/lon or x/y)")

                site_devices = site.get("devices", [])

                if site_devices is None:
                    site_devices = []

                if not isinstance(site_devices, list):
                    errors.append(
                        f"{path}.devices must be a list when provided."
                    )
                    continue

                for device_index, device in enumerate(site_devices):
                    device_path = f"{path}.devices[{device_index}]"

                    if not isinstance(device, dict):
                        errors.append(
                            f"{device_path} must be a dictionary."
                        )
                        continue

                    for field_name in ("device_id", "site_id"):
                        self._check_required_value(
                            device,
                            field_name,
                            f"{device_path}.{field_name}",
                            missing,
                            errors,
                            expected_type=str,
                        )

                    concrete_interfaces = device.get("interfaces", [])

                    if concrete_interfaces is None:
                        concrete_interfaces = []

                    if not isinstance(concrete_interfaces, list):
                        errors.append(
                            f"{device_path}.interfaces must be a list "
                            "when provided."
                        )
                        continue

                    for interface_index, interface in enumerate(
                        concrete_interfaces
                    ):
                        interface_path = (
                            f"{device_path}.interfaces[{interface_index}]"
                        )

                        if not isinstance(interface, dict):
                            errors.append(
                                f"{interface_path} must be a dictionary."
                            )
                            continue

                        for field_name in (
                            "interface_id",
                            "device_id",
                            "tech",
                            "freq_mhz",
                            "tx_power_dbm",
                            "antenna_id",
                        ):
                            self._check_required_value(
                                interface,
                                field_name,
                                f"{interface_path}.{field_name}",
                                missing,
                                errors,
                                expected_type=(
                                    str
                                    if field_name in (
                                        "interface_id",
                                        "device_id",
                                        "tech",
                                        "antenna_id",
                                    )
                                    else None
                                ),
                            )

                        for field_name in ("freq_mhz", "tx_power_dbm"):
                            self._check_number(
                                interface.get(field_name),
                                f"{interface_path}.{field_name}",
                                errors,
                            )

                        antenna_id = interface.get("antenna_id")
                        if antenna_id is not None:
                            if not isinstance(antennas, dict):
                                errors.append(
                                    f"{interface_path}.antenna_id cannot "
                                    "be checked because antennas is not "
                                    "a dictionary."
                                )
                            elif (
                                not isinstance(antenna_id, str)
                                or antenna_id not in antennas
                            ):
                                errors.append(
                                    f"{interface_path}.antenna_id "
                                    f"references unknown antenna "
                                    f"'{antenna_id}'."
                                )

                        tech = interface.get("tech")
                        if isinstance(tech, str) and tech.strip():
                            if (
                                not isinstance(metrics, dict)
                                or tech not in metrics
                            ):
                                errors.append(
                                    f"{interface_path}.tech '{tech}' "
                                    f"has no matching metrics.{tech} entry."
                                )

        # ---------------------------------------------------------
        # 6. Regras básicas para antenas
        # ---------------------------------------------------------
        if isinstance(antennas, dict):
            for name, antenna in antennas.items():
                if not isinstance(antenna, dict):
                    continue

                kind = antenna.get("kind")
                if kind not in (None, "omni", "sector"):
                    errors.append(
                        f"antennas.{name}.kind must be 'omni' or "
                        "'sector' when provided."
                    )

        # ---------------------------------------------------------
        # 7. Referências entre interfaces, antenas e dispositivos
        # ---------------------------------------------------------
        self._validate_references(errors)

        interfaces = self.spec.get("interfaces", {})
        metrics = self.spec.get("metrics", {})

        if isinstance(interfaces, dict):
            for name, interface in interfaces.items():
                if not isinstance(interface, dict):
                    continue

                tech = interface.get("tech")
                if isinstance(tech, str) and tech.strip():
                    if (
                        not isinstance(metrics, dict)
                        or tech not in metrics
                    ):
                        errors.append(
                            f"interfaces.{name}.tech '{tech}' has no "
                            f"matching metrics.{tech} entry."
                        )

        # ---------------------------------------------------------
        # 8. Campos numéricos
        # ---------------------------------------------------------
        self._validate_numeric_fields(errors)

        # Remove duplicações mantendo a ordem de ocorrência.
        missing = list(dict.fromkeys(missing))
        errors = list(dict.fromkeys(errors))
        warnings = list(dict.fromkeys(warnings))

        return ValidationResult(
            valid=not errors,
            missing=missing,
            errors=errors,
            warnings=warnings,
        )

    def is_complete(self) -> bool:
        return self.validate().complete

    def confirm(self) -> ValidationResult:
        result = self.validate()
        self.confirmed = result.complete
        return result

    def generate_toml(
        self,
        *,
        require_confirmation: bool = True,
    ) -> str:
        result = self.validate()

        if not result.complete:
            raise ValueError(self._format_validation_error(result))

        if require_confirmation and not self.confirmed:
            raise RuntimeError(
                "Scenario is complete but has not been confirmed. "
                "Call confirm() after presenting the collected values "
                "to the user."
            )

        return self._to_toml(self.spec)

    def save_toml(
        self,
        path: str | Path,
        *,
        require_confirmation: bool = True,
        encoding: str = "utf-8",
    ) -> str:
        content = self.generate_toml(
            require_confirmation=require_confirmation
        )

        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding=encoding)

        return content

    @staticmethod
    def _check_required_value(
        obj: dict[str, Any],
        key: str,
        path: str,
        missing: list[str],
        errors: list[str],
        *,
        expected_type: type | None = None,
    ) -> None:
        if key not in obj or obj[key] is None:
            missing.append(path)
            return

        value = obj[key]

        if isinstance(value, str) and not value.strip():
            missing.append(path)
            return

        if expected_type is not None and not isinstance(value, expected_type):
            errors.append(
                f"{path} must be of type {expected_type.__name__}."
            )

    @classmethod
    def _merge_dict(
        cls,
        destination: dict[str, Any],
        source: dict[str, Any],
    ) -> None:
        for key, value in source.items():
            if (
                isinstance(value, dict)
                and isinstance(destination.get(key), dict)
            ):
                cls._merge_dict(destination[key], value)
            else:
                destination[key] = deepcopy(value)

    @staticmethod
    def _get_path(data: dict[str, Any], path: str) -> Any:
        current: Any = data

        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]

        return current

    def _validate_references(self, errors: list[str]) -> None:
        antennas = self.spec.get("antennas", {})
        interfaces = self.spec.get("interfaces", {})
        devices = self.spec.get("devices", {})

        # Normalize only local validation variables. Do not alter self.spec.
        # The malformed original collections are reported as errors.
        if not isinstance(antennas, dict):
            errors.append("antennas must be a dictionary of named objects.")
            antennas = {}

        if not isinstance(interfaces, dict):
            errors.append("interfaces must be a dictionary of named objects.")
            interfaces = {}

        if not isinstance(devices, dict):
            errors.append("devices must be a dictionary of named objects.")
            devices = {}

        for name, interface in interfaces.items():
            if not isinstance(interface, dict):
                continue

            antenna_id = interface.get("antenna_id")

            if antenna_id is not None:
                if (
                    not isinstance(antenna_id, str)
                    or antenna_id not in antennas
                ):
                    errors.append(
                        f"interfaces.{name}.antenna_id references "
                        f"unknown antenna '{antenna_id}'."
                    )

        for name, device in devices.items():
            if not isinstance(device, dict):
                continue

            refs = device.get("interfaces")
            if refs is None:
                continue

            if not isinstance(refs, list):
                errors.append(
                    f"devices.{name}.interfaces must be a list."
                )
                continue

            for index, ref in enumerate(refs):
                if not isinstance(ref, str) or not ref.strip():
                    errors.append(
                        f"devices.{name}.interfaces[{index}] must be "
                        "a non-empty string."
                    )
                    continue

                if ref not in interfaces:
                    errors.append(
                        f"devices.{name}.interfaces references "
                        f"unknown interface '{ref}'."
                    )

    def _validate_numeric_fields(self, errors: list[str]) -> None:
        antennas = self.spec.get("antennas", {})
        interfaces = self.spec.get("interfaces", {})
        devices = self.spec.get("devices", {})

        if isinstance(antennas, dict):
            for name, antenna in antennas.items():
                if not isinstance(antenna, dict):
                    continue

                for field_name in (
                    "height_m",
                    "gain_dbi",
                    "azimuth_deg",
                    "downtilt_deg",
                    "beamwidth_deg",
                ):
                    if field_name in antenna:
                        self._check_number(
                            antenna[field_name],
                            f"antennas.{name}.{field_name}",
                            errors,
                        )

        if isinstance(interfaces, dict):
            for name, interface in interfaces.items():
                if not isinstance(interface, dict):
                    continue

                for field_name in ("freq_mhz", "tx_power_dbm"):
                    if field_name in interface:
                        self._check_number(
                            interface[field_name],
                            f"interfaces.{name}.{field_name}",
                            errors,
                        )

        if isinstance(devices, dict):
            for name, device in devices.items():
                if not isinstance(device, dict):
                    continue

                if "mount_height_m" in device:
                    self._check_number(
                        device["mount_height_m"],
                        f"devices.{name}.mount_height_m",
                        errors,
                    )

                if "rank" in device:
                    self._check_number(
                        device["rank"],
                        f"devices.{name}.rank",
                        errors,
                    )

    @staticmethod
    def _check_number(
        value: Any,
        field_path: str,
        errors: list[str],
    ) -> None:
        if value is None:
            return

        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append(f"{field_path} must be numeric.")
        elif not math.isfinite(value):
            errors.append(f"{field_path} must be finite.")

    @classmethod
    def _to_toml(cls, spec: dict[str, Any]) -> str:
        lines: list[str] = []

        scenario = spec.get("scenario", {})
        if not isinstance(scenario, dict):
            raise ValueError("scenario must be a dictionary for TOML generation.")

        lines.append("[scenario]")
        for key, value in scenario.items():
            lines.append(
                f"{cls._quote_inline_key(str(key))} = {cls._toml_value(value)}"
            )
        lines.append("")

        for section in ("antennas", "interfaces", "devices", "metrics"):
            cls._append_named_tables(
                lines,
                section,
                spec.get(section, {}),
            )

        instances = spec.get("instances", {})
        if instances:
            if not isinstance(instances, dict):
                raise ValueError(
                    "instances must be a dictionary for TOML generation."
                )

            lines.append("[instances]")
            for key, value in instances.items():
                lines.append(
                    f"{cls._quote_inline_key(str(key))} = {cls._toml_value(value)}"
                )
            lines.append("")

        net = spec.get("net", {})
        if net:
            if not isinstance(net, dict):
                raise ValueError("net must be a dictionary for TOML generation.")

            lines.append("[net]")
            for key, value in net.items():
                lines.append(
                    f"{cls._quote_inline_key(str(key))} = {cls._toml_value(value)}"
                )
            lines.append("")

        sites = spec.get("sites", [])
        if sites:
            if not isinstance(sites, list):
                raise ValueError("sites must be a list for TOML generation.")

            for index, site in enumerate(sites):
                if not isinstance(site, dict):
                    raise ValueError(
                        f"sites[{index}] must be a dictionary for TOML generation."
                    )

                lines.append("[[sites]]")
                for key, value in site.items():
                    lines.append(
                        f"{cls._quote_inline_key(str(key))} = "
                        f"{cls._toml_value(value)}"
                    )
                lines.append("")

        return "\n".join(lines).rstrip() + "\n"

    @classmethod
    def _append_named_tables(
        cls,
        lines: list[str],
        section_name: str,
        objects: Any,
    ) -> None:
        if not objects:
            return

        if not isinstance(objects, dict):
            raise ValueError(
                f"{section_name} must be a dictionary for TOML generation."
            )

        for object_name, values in objects.items():
            if not isinstance(object_name, str):
                raise ValueError(
                    f"{section_name} object names must be strings."
                )

            if not isinstance(values, dict):
                raise ValueError(
                    f"{section_name}.{object_name} must be a dictionary."
                )

            table_name = cls._quote_table_key(object_name)
            lines.append(f"[{section_name}.{table_name}]")

            for key, value in values.items():
                lines.append(
                    f"{cls._quote_inline_key(str(key))} = "
                    f"{cls._toml_value(value)}"
                )

            lines.append("")

    @staticmethod
    def _quote_table_key(value: str) -> str:
        if re.fullmatch(r"[A-Za-z0-9_-]+", value):
            return value

        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    @staticmethod
    def _quote_inline_key(value: str) -> str:
        if re.fullmatch(r"[A-Za-z0-9_-]+", value):
            return value

        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'

    @classmethod
    def _toml_value(cls, value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"

        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)

        if isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError("TOML does not support non-finite floats.")
            return repr(value)

        if isinstance(value, str):
            escaped = (
                value.replace("\\", "\\\\")
                .replace('"', '\\"')
                .replace("\n", "\\n")
                .replace("\r", "\\r")
                .replace("\t", "\\t")
            )
            return f'"{escaped}"'

        if isinstance(value, (list, tuple)):
            return "[" + ", ".join(
                cls._toml_value(item) for item in value
            ) + "]"

        if isinstance(value, dict):
            parts = [
                f"{cls._quote_inline_key(str(key))} = {cls._toml_value(item)}"
                for key, item in value.items()
            ]
            return "{ " + ", ".join(parts) + " }"

        raise TypeError(
            f"Unsupported TOML value type: {type(value).__name__}"
        )

    @staticmethod
    def _format_validation_error(result: ValidationResult) -> str:
        parts = ["Scenario cannot be generated."]

        if result.missing:
            parts.append(
                "Missing fields: " + ", ".join(result.missing) + "."
            )

        if result.errors:
            parts.append(
                "Validation errors: " + " ".join(result.errors)
            )

        if result.warnings:
            parts.append(
                "Warnings: " + " ".join(result.warnings)
            )

        return " ".join(parts)


__all__ = ["ScenarioBuilder", "ValidationResult"]