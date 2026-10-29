"""Carregador estrito do nodes_config.toml de cada projeto; sem execução de Python."""
from __future__ import annotations
import tomllib
from pathlib import Path
from cisei_scenario_sdk.nodes_source_copel import CopelConfig, NodeRule


def load_nodes_config(path: str | Path) -> CopelConfig:
    path = Path(path)
    with path.open('rb') as f:
        d = tomllib.load(f)
    compiler = d.get('compiler', {})
    if compiler.get('adapter') != 'copel':
        raise ValueError(f'{path.name}: adapter não suportado: {compiler.get("adapter")!r}')
    if compiler.get('output', 'nodes.csv') != 'nodes.csv':
        raise ValueError('A saída canônica obrigatória é nodes.csv')
    for key in ('source_crs', 'allow_synthetic_site_ids', 'use_structure_height_as_mount_height', 'substation_zero_height_m'):
        if key not in compiler:
            raise ValueError(f'{path.name}: falta [compiler].{key}')
    def rule(section, *, automation=False):
        values = d.get(section, {})
        keys = ('device_profile', 'kind', 'connected', 'can_route') + (('mount_height_m',) if automation else ())
        missing = [k for k in keys if k not in values or values[k] == 'PREENCHER']
        if missing:
            raise ValueError(f'{path.name}: faltam campos em [{section}]: {", ".join(missing)}')
        if not isinstance(values['connected'], bool) or not isinstance(values['can_route'], bool):
            raise ValueError(f'{path.name}: [{section}] flags devem ser booleanos')
        return NodeRule(**{k: values[k] for k in keys})
    sub = rule('substations')
    tower = rule('external_towers')
    auto = rule('automation', automation=True)
    types = d.get('automation', {}).get('types')
    if not isinstance(types, list) or not types or not all(isinstance(x, str) and x.strip() for x in types):
        raise ValueError(f'{path.name}: [automation].types deve ser uma lista de tipos')
    return CopelConfig(
        source_crs=compiler['source_crs'],
        substation_rule=sub,
        external_tower_rule=tower,
        automation_rules={typ: auto for typ in types},
        substation_zero_height_m=compiler['substation_zero_height_m'],
        use_structure_height_as_mount_height=compiler['use_structure_height_as_mount_height'],
        allow_synthetic_site_ids=compiler['allow_synthetic_site_ids'],
    )
