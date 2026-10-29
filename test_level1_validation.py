"""Smoke tests for Level 1 structural validation; no SDK/services are called."""
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from nodes_compiler import NodesCompiler, NodesValidationError
from scenario_builder import ScenarioBuilder
import tomllib


class NodesCsvValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "nodes.csv"

    def tearDown(self):
        self.temp.cleanup()

    def write(self, headers, rows):
        with self.path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)

    def test_valid_canonical_csv(self):
        headers = list(NodesCompiler.COLUMNS)
        values = ["A1", "router", "leaf", "-25.4", "-49.2", "", "", "10", "TRUE", "FALSE", "1"]
        self.write(headers, [values])
        self.assertEqual(len(NodesCompiler.read_csv(self.path)), 1)

    def test_duplicate_header_is_rejected(self):
        self.write(["site_id", "site_id", "device_profile", "kind", "lat", "lon", "mount_height_m", "connected", "can_route"],
                   [["A", "A", "router", "leaf", "-25", "-49", "10", "true", "false"]])
        with self.assertRaisesRegex(NodesValidationError, "duplicadas"):
            NodesCompiler.read_csv(self.path)

    def test_unknown_header_is_rejected(self):
        self.write(["site_id", "device_profile", "kind", "lat", "lon", "mount_height_m", "connected", "can_route", "other"],
                   [["A", "router", "leaf", "-25", "-49", "10", "true", "false", "x"]])
        with self.assertRaisesRegex(NodesValidationError, "fora do esquema"):
            NodesCompiler.read_csv(self.path)

    def test_non_finite_coordinate_is_rejected(self):
        self.write(["site_id", "device_profile", "kind", "lat", "lon", "mount_height_m", "connected", "can_route"],
                   [["A", "router", "leaf", "nan", "-49", "10", "true", "false"]])
        with self.assertRaisesRegex(NodesValidationError, "não é finito"):
            NodesCompiler.read_csv(self.path)

    def test_wrong_field_count_is_rejected(self):
        self.path.write_text("site_id,device_profile,kind,lat,lon,mount_height_m,connected,can_route\nA,router,leaf,-25,-49,10,true,false,EXTRA\n", encoding="utf-8")
        with self.assertRaisesRegex(NodesValidationError, "campos"):
            NodesCompiler.read_csv(self.path)


class ScenarioTomlValidationTests(unittest.TestCase):
    def test_real_project_scenario_round_trips_through_builder(self):
        source = ROOT.parent / "vibeplanner_level1_sources" / "scenario_copel_lte450_provisorio.toml"
        if not source.is_file():
            self.skipTest("fixture do cenário não está disponível")
        spec = tomllib.loads(source.read_text(encoding="utf-8"))
        builder = ScenarioBuilder()
        builder.replace(spec)
        result = builder.validate()
        self.assertTrue(result.complete, result.as_dict())
        builder.confirm()
        generated = builder.generate_toml()
        parsed = tomllib.loads(generated)
        self.assertEqual(parsed["instances"]["source"], spec["instances"]["source"])
        self.assertEqual(set(parsed), {key for key, value in spec.items() if key == "scenario" or bool(value)})

    def test_notebook_json_and_code_cells_are_valid(self):
        import ast
        notebook = ROOT / "cisei_scenario_builder_nodes_toml_only_v7_level1_validation.ipynb"
        data = json.loads(notebook.read_text(encoding="utf-8"))
        for i, cell in enumerate(data["cells"]):
            if cell.get("cell_type") == "code":
                ast.parse("".join(cell.get("source", [])), filename=f"notebook-cell-{i}")


class ScenarioReferenceRegressionTests(unittest.TestCase):
    def make_spec(self, antenna_id="client_omni", include_antenna=True):
        antennas = {}
        if include_antenna:
            antennas["client_omni"] = {"kind": "omni"}

        return {
            "scenario": {"working_crs": "EPSG:31982"},
            "instances": {
                "source": "nodes.csv",
                "format": "csv",
                "profile_column": "device_profile",
            },
            "antennas": antennas,
            "interfaces": {
                "lte_client": {
                    "tech": "lte",
                    "freq_mhz": 450,
                    "tx_power_dbm": 20,
                    **({"antenna_id": antenna_id} if antenna_id is not None else {}),
                }
            },
            "devices": {
                "lte_leaf": {
                    "interfaces": ["lte_client"],
                }
            },
            "metrics": {"lte": {"spec": "lte_tower_node"}},
        }

    def test_interface_missing_antenna_id_is_reported(self):
        builder = ScenarioBuilder()
        builder.replace(self.make_spec(antenna_id=None))
        result = builder.validate()

        self.assertTrue(
            any("antenna_id" in item for item in result.missing),
            result.as_dict(),
        )

    def test_interface_unknown_antenna_reference_is_an_error(self):
        builder = ScenarioBuilder()
        builder.replace(
            self.make_spec(antenna_id="antenna_does_not_exist")
        )
        result = builder.validate()

        self.assertTrue(
            any(
                "antenna" in item.lower()
                and (
                    "unknown" in item.lower()
                    or "desconhecida" in item.lower()
                    or "inexistente" in item.lower()
                )
                for item in result.errors
            ),
            result.as_dict(),
        )

    def test_missing_interface_tech_is_reported(self):
        spec = self.make_spec()
        del spec["interfaces"]["lte_client"]["tech"]
        builder = ScenarioBuilder()
        builder.replace(spec)
        result = builder.validate()
        self.assertTrue(
            any("tech" in item for item in result.missing),
            result.as_dict(),
        )
    def test_missing_interface_frequency_is_reported(self):
        spec = self.make_spec()
        del spec["interfaces"]["lte_client"]["freq_mhz"]
        builder = ScenarioBuilder()
        builder.replace(spec)
        result = builder.validate()
        self.assertTrue(
            any("freq_mhz" in item for item in result.missing),
            result.as_dict(),
        )
    def test_missing_interface_tx_power_is_reported(self):
        spec = self.make_spec()
        del spec["interfaces"]["lte_client"]["tx_power_dbm"]
        builder = ScenarioBuilder()
        builder.replace(spec)
        result = builder.validate()
        self.assertTrue(
            any("tx_power_dbm" in item for item in result.missing),
            result.as_dict(),
        )
    def test_device_unknown_interface_reference_is_an_error(self):
        spec = self.make_spec()
        spec["devices"]["lte_leaf"]["interfaces"] = ["interface_inexistente"]
        builder = ScenarioBuilder()
        builder.replace(spec)
        result = builder.validate()
        self.assertTrue(
            any(
                "interface" in item.lower()
                and (
                    "unknown" in item.lower()
                    or "desconhecida" in item.lower()
                    or "inexistente" in item.lower()
                    or "not found" in item.lower()
                )
                for item in result.errors
            ),
            result.as_dict(),
        )


    def test_non_numeric_interface_frequency_is_rejected(self):
        spec = self.make_spec()
        spec["interfaces"]["lte_client"]["freq_mhz"] = "quatrocentos e cinquenta"
        builder = ScenarioBuilder()
        builder.replace(spec)
        result = builder.validate()
        self.assertFalse(result.complete, result.as_dict())
        self.assertTrue(
            result.errors or result.missing,
            result.as_dict(),
        )

    def test_invalid_interface_tx_power_is_rejected(self):
        spec = self.make_spec()
        spec["interfaces"]["lte_client"]["tx_power_dbm"] = "potência desconhecida"
        builder = ScenarioBuilder()
        builder.replace(spec)
        result = builder.validate()
        self.assertFalse(result.complete, result.as_dict())
        self.assertTrue(
            result.errors or result.missing,
            result.as_dict(),
        )

    def test_device_interfaces_must_be_a_list(self):
        spec = self.make_spec()
        spec["devices"]["lte_leaf"]["interfaces"] = "lte_client"
        builder = ScenarioBuilder()
        builder.replace(spec)
        result = builder.validate()
        self.assertFalse(result.complete, result.as_dict())
        self.assertTrue(
            result.errors or result.missing,
            result.as_dict(),
        )


class ScenarioConfirmationRegressionTests(
    ScenarioReferenceRegressionTests
):
    def test_invalid_scenario_cannot_be_confirmed(self):
        builder = ScenarioBuilder()
        spec = self.make_spec()
        del spec["interfaces"]["lte_client"]["antenna_id"]
        builder.replace(spec)

        result = builder.validate()
        self.assertFalse(result.complete, result.as_dict())

        builder.confirm()
        self.assertFalse(
            builder.confirmed,
            "Cenário incompleto não pode ficar confirmado.",
        )

    def test_invalid_scenario_cannot_generate_toml(self):
        builder = ScenarioBuilder()
        spec = self.make_spec()
        del spec["interfaces"]["lte_client"]["antenna_id"]
        builder.replace(spec)

        with self.assertRaises(Exception):
            builder.generate_toml()

    def test_valid_scenario_requires_explicit_confirmation(self):
        builder = ScenarioBuilder()
        builder.replace(self.make_spec())

        result = builder.validate()
        self.assertTrue(result.complete, result.as_dict())
        self.assertFalse(builder.confirmed)

        builder.confirm()
        self.assertTrue(builder.confirmed)

        generated = builder.generate_toml()
        self.assertIsInstance(generated, str)
        self.assertTrue(generated.strip())


if __name__ == "__main__":
    unittest.main(verbosity=2)
