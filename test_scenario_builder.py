from pathlib import Path

from scenario_builder import ScenarioBuilder


REFERENCE_SCENARIO = {
    "scenario": {
        "working_crs": "EPSG:31982",
    },

    "antennas": {
        "lte_sector_0": {
            "kind": "sector",
            "model_id": "commscope_rv_65s_fvb",
            "description": "CommScope RV-65S-FVB sector at 0 deg",
            "height_m": 7.0,
            "azimuth_deg": 0.0,
            "downtilt_deg": 0.0,
            "beamwidth_deg": 120.0,
        },
        "lte_sector_120": {
            "kind": "sector",
            "model_id": "commscope_rv_65s_fvb",
            "description": "CommScope RV-65S-FVB sector at 120 deg",
            "height_m": 7.0,
            "azimuth_deg": 120.0,
            "downtilt_deg": 0.0,
            "beamwidth_deg": 120.0,
        },
        "lte_sector_240": {
            "kind": "sector",
            "model_id": "commscope_rv_65s_fvb",
            "description": "CommScope RV-65S-FVB sector at 240 deg",
            "height_m": 7.0,
            "azimuth_deg": 240.0,
            "downtilt_deg": 0.0,
            "beamwidth_deg": 120.0,
        },
        "lte_client_omni": {
            "kind": "omni",
            "model_id": "pctel_boa9028",
            "description": "Library-backed client omni antenna",
            "height_m": 7.0,
            "azimuth_deg": 0.0,
            "downtilt_deg": 0.0,
        },
    },

    "interfaces": {
        "lte_sector_0": {
            "tech": "lte",
            "freq_mhz": 915.0,
            "tx_power_dbm": 43.0,
            "antenna_id": "lte_sector_0",
            "can_relay": False,
        },
        "lte_sector_120": {
            "tech": "lte",
            "freq_mhz": 915.0,
            "tx_power_dbm": 43.0,
            "antenna_id": "lte_sector_120",
            "can_relay": False,
        },
        "lte_sector_240": {
            "tech": "lte",
            "freq_mhz": 915.0,
            "tx_power_dbm": 43.0,
            "antenna_id": "lte_sector_240",
            "can_relay": False,
        },
        "lte_client": {
            "tech": "lte",
            "freq_mhz": 915.0,
            "tx_power_dbm": 20.0,
            "antenna_id": "lte_client_omni",
            "can_relay": False,
        },
    },

    "devices": {
        "cell_sector_3x120": {
            "kind": "tower",
            "connected": True,
            "can_route": True,
            "rank": 0.0,
            "interfaces": [
                "lte_sector_0",
                "lte_sector_120",
                "lte_sector_240",
            ],
        },
        "cell_sector_2x120": {
            "kind": "tower",
            "connected": True,
            "can_route": True,
            "rank": 0.0,
            "interfaces": [
                "lte_sector_120",
                "lte_sector_240",
            ],
        },
        "lte_leaf": {
            "kind": "field",
            "connected": False,
            "can_route": False,
            "interfaces": [
                "lte_client",
            ],
        },
    },

    "metrics": {
        "lte": {
            "spec": "lte_tower_node",
        },
    },

    "instances": {
        "source": "nodes.csv",
        "format": "csv",
        "profile_column": "device_profile",
    },
}


def main():
    print("=" * 60)
    print("SCENARIO BUILDER — POC TEST")
    print("=" * 60)

    builder = ScenarioBuilder()

    # --------------------------------------------------------
    # 1. Deve começar incompleto
    # --------------------------------------------------------

    result = builder.validate()

    print("\n[1] Cenário inicial")
    print("complete:", result.complete)
    print("missing:", len(result.missing))

    assert not result.complete
    assert len(result.missing) > 0

    # --------------------------------------------------------
    # 2. Carrega cenário explicitamente
    # --------------------------------------------------------

    builder.update(REFERENCE_SCENARIO)

    result = builder.validate()

    print("\n[2] Após carregar cenário")
    print("valid:", result.valid)
    print("complete:", result.complete)

    if result.missing:
        print("missing:")
        for item in result.missing:
            print("  -", item)

    if result.errors:
        print("errors:")
        for item in result.errors:
            print("  -", item)

    assert result.complete, (
        "Cenário de referência deveria estar completo."
    )

    # --------------------------------------------------------
    # 3. Ainda não pode gerar sem confirmação
    # --------------------------------------------------------

    print("\n[3] Testando proteção contra geração sem confirmação")

    try:
        builder.generate_toml()
    except RuntimeError:
        print("OK — geração bloqueada sem confirmação.")
    else:
        raise AssertionError(
            "generate_toml() deveria exigir confirmação."
        )

    # --------------------------------------------------------
    # 4. Confirma
    # --------------------------------------------------------

    print("\n[4] Confirmando cenário")

    result = builder.confirm()

    assert result.complete
    assert builder.confirmed

    print("OK — cenário confirmado.")

    # --------------------------------------------------------
    # 5. Gera TOML
    # --------------------------------------------------------

    print("\n[5] Gerando TOML")

    toml_text = builder.generate_toml()

    print("-" * 60)
    print(toml_text)
    print("-" * 60)

    # --------------------------------------------------------
    # 6. Salva resultado
    # --------------------------------------------------------

    output = Path(
        "scenario_builder_test_output.toml"
    )

    output.write_text(
        toml_text,
        encoding="utf-8",
    )

    print(
        f"\nTOML salvo em: {output.resolve()}"
    )

    # --------------------------------------------------------
    # 7. Verificações básicas do resultado
    # --------------------------------------------------------

    assert "[scenario]" in toml_text
    assert (
        'working_crs = "EPSG:31982"'
        in toml_text
    )

    assert (
        "[antennas.lte_sector_0]"
        in toml_text
    )

    assert (
        "[interfaces.lte_sector_120]"
        in toml_text
    )

    assert (
        "[devices.cell_sector_3x120]"
        in toml_text
    )

    assert (
        "[metrics.lte]"
        in toml_text
    )

    assert "[instances]" in toml_text

    assert (
        'source = "nodes.csv"'
        in toml_text
    )

    print("\n" + "=" * 60)
    print("TESTE PASSOU")
    print("=" * 60)



def test_required_fields_regression():
    """Verifica os quatro campos obrigatórios do contrato."""
    from copy import deepcopy

    print("\\n" + "=" * 60)
    print("REGRESSÃO — CAMPOS OBRIGATÓRIOS")
    print("=" * 60)

    required_fields = [
        ("scenario", "working_crs"),
        ("instances", "source"),
        ("instances", "format"),
        ("instances", "profile_column"),
    ]

    for section, field in required_fields:
        data = deepcopy(REFERENCE_SCENARIO)
        del data[section][field]

        builder = ScenarioBuilder()
        builder.update(data)
        result = builder.validate()

        field_path = f"{section}.{field}"
        detected = (
            field_path in result.missing
            or any(
                error.startswith(field_path + " ")
                for error in result.errors
            )
        )

        assert detected, (
            f"{field_path} não foi identificado como ausente/inválido. "
            f"missing={result.missing}; errors={result.errors}"
        )
        assert not result.complete, (
            f"O cenário foi considerado completo sem {field_path}."
        )

        print(f"OK — {field_path} é obrigatório")

    builder = ScenarioBuilder()
    builder.update(deepcopy(REFERENCE_SCENARIO))
    result = builder.validate()

    assert result.valid, f"Cenário inválido: {result.errors}"
    assert result.complete, f"Cenário incompleto: {result.missing}"

    print("OK — cenário de referência continua válido e completo")


if __name__ == "__main__":
    test_required_fields_regression()
    main()


# ============================================================
# REGRESSÃO — SEÇÕES OPCIONAIS NÃO PODEM SER INFERIDAS
# ============================================================

def test_builder_does_not_insert_optional_sections():
    """O Builder vazio não deve inserir net ou sites."""
    builder = ScenarioBuilder()

    assert "net" not in builder.spec
    assert "sites" not in builder.spec


def test_to_dict_preserves_absence_of_optional_sections():
    """to_dict() deve preservar a estrutura sem seções opcionais."""
    builder = ScenarioBuilder()

    result = builder.to_dict()

    assert "net" not in result
    assert "sites" not in result


def test_update_preserves_explicit_optional_sections():
    """Se fornecidas explicitamente, as seções opcionais devem ser preservadas."""
    builder = ScenarioBuilder()

    explicit_net = {"some_setting": "explicit_value"}
    explicit_sites = [{"id": "site_test"}]

    builder.update({
        "net": explicit_net,
        "sites": explicit_sites,
    })

    result = builder.to_dict()

    assert result["net"] == explicit_net
    assert result["sites"] == explicit_sites


def test_replace_does_not_insert_optional_sections():
    """replace() não deve recriar net ou sites automaticamente."""
    builder = ScenarioBuilder()

    builder.replace({
        "scenario": {"working_crs": "EPSG:31982"},
    })

    result = builder.to_dict()

    assert "net" not in result
    assert "sites" not in result


def test_replace_preserves_explicit_optional_sections():
    """replace() deve preservar net e sites quando informados."""
    builder = ScenarioBuilder()

    explicit_net = {"some_setting": "explicit_value"}
    explicit_sites = [{"id": "site_test"}]

    builder.replace({
        "scenario": {"working_crs": "EPSG:31982"},
        "net": explicit_net,
        "sites": explicit_sites,
    })

    result = builder.to_dict()

    assert result["net"] == explicit_net
    assert result["sites"] == explicit_sites
