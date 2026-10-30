"""Validação offline e sem efeitos colaterais para projetos VibePlanner.

Não substitui PlanningScenario.validate() do network-service.
Não importa cisei_planning_sdk, não registra cenários e não calcula enlaces.
"""
from __future__ import annotations
import csv
import json
import math
import os
import re
import tomllib
from datetime import datetime, timezone
from pathlib import Path

REQUIRED_CSV = ('site_id', 'device_profile', 'kind', 'lat', 'lon', 'x', 'y', 'mount_height_m', 'connected', 'can_route', 'rank')


def validate_project(project: str | Path, *, toml_text: str | None = None) -> dict:
    project = Path(project).resolve(strict=True)
    errors, warnings = [], []
    info = {'project': project.name}
    scenario_file = project / 'scenario.toml'
    nodes_file = project / 'nodes.csv'
    if toml_text is None and (not scenario_file.is_file() or scenario_file.is_symlink()):
        errors.append('scenario.toml ausente ou link simbólico.')
    if not nodes_file.is_file() or nodes_file.is_symlink():
        errors.append('nodes.csv ausente ou link simbólico.')
    scenario = None
    if toml_text is not None or scenario_file.is_file() and not scenario_file.is_symlink():
        try:
            if toml_text is not None:
                scenario = tomllib.loads(toml_text)
            else:
                with scenario_file.open('rb') as f:
                    scenario = tomllib.load(f)
            if not isinstance(scenario, dict):
                errors.append('scenario.toml: raiz inválida.')
        except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
            errors.append(f'scenario.toml inválido: {exc}')
    if scenario is not None:
        required_sections = ('scenario','antennas','interfaces','devices','metrics','instances')
        for section in required_sections:
            if not isinstance(scenario.get(section), dict) or not scenario[section]:
                errors.append(f'Seção [{section}] ausente ou vazia.')
        crs = scenario.get('scenario', {}).get('working_crs') if isinstance(scenario.get('scenario'), dict) else None
        if not isinstance(crs, str) or not crs.strip():
            errors.append('scenario.working_crs obrigatório.')
        info['working_crs'] = crs
        inst = scenario.get('instances', {})
        if isinstance(inst, dict):
            for k, expected in (('source','nodes.csv'),('format','csv'),('profile_column','device_profile')):
                if inst.get(k) != expected:
                    errors.append(f'instances.{k} deve ser {expected!r} (recebido {inst.get(k)!r}).')
        ants = scenario.get('antennas', {})
        interfaces = scenario.get('interfaces', {})
        devices = scenario.get('devices', {})
        metrics = scenario.get('metrics', {})
        ants = ants if isinstance(ants, dict) else {}
        interfaces = interfaces if isinstance(interfaces, dict) else {}
        devices = devices if isinstance(devices, dict) else {}
        metrics = metrics if isinstance(metrics, dict) else {}
        for name, a in ants.items():
            if not isinstance(a, dict):
                errors.append(f'antennas.{name}: esperado objeto.'); continue
            kind = a.get('kind')
            if kind not in ('sector','omni'):
                errors.append(f'antennas.{name}.kind inválido: {kind!r}.')
            if kind == 'sector' and not _finite(a.get('beamwidth_deg'), positive=True):
                errors.append(f'antennas.{name}.beamwidth_deg deve ser positivo.')
            for k in ('height_m','azimuth_deg','downtilt_deg'):
                if k in a and not _finite(a[k]):
                    errors.append(f'antennas.{name}.{k} deve ser finito.')
        for name, iface in interfaces.items():
            if not isinstance(iface, dict):
                errors.append(f'interfaces.{name}: esperado objeto.'); continue
            if iface.get('antenna_id') not in ants:
                errors.append(f'interfaces.{name}: antenna_id inexistente: {iface.get("antenna_id")!r}.')
            if not _finite(iface.get('freq_mhz'), positive=True):
                errors.append(f'interfaces.{name}.freq_mhz deve ser positivo.')
            if not _finite(iface.get('tx_power_dbm')):
                errors.append(f'interfaces.{name}.tx_power_dbm deve ser finito.')
            tech = iface.get('tech')
            if not isinstance(tech, str) or tech not in metrics:
                errors.append(f'interfaces.{name}.tech sem metrics correspondente: {tech!r}.')
        for name, dev in devices.items():
            if not isinstance(dev, dict):
                errors.append(f'devices.{name}: esperado objeto.'); continue
            ids = dev.get('interfaces')
            if not isinstance(ids, list) or not ids:
                errors.append(f'devices.{name}.interfaces deve ser lista não vazia.')
            else:
                for iid in ids:
                    if not isinstance(iid, str) or iid not in interfaces:
                        errors.append(f'devices.{name}: interface inexistente: {iid!r}.')
        for name, m in metrics.items():
            if not isinstance(m, dict) or not isinstance(m.get('spec'), str) or not m['spec'].strip():
                errors.append(f'metrics.{name}.spec deve ser texto não vazio.')
    if nodes_file.is_file() and not nodes_file.is_symlink():
        try:
            with nodes_file.open('r', encoding='utf-8-sig', newline='') as f:
                reader = csv.DictReader(f)
                fields = reader.fieldnames or []
                missing = [k for k in REQUIRED_CSV if k not in fields]
                if missing:
                    errors.append('nodes.csv: colunas ausentes: ' + ', '.join(missing))
                ids = set()
                count = 0
                profiles = set()
                for rownum, row in enumerate(reader, 2):
                    count += 1
                    sid = (row.get('site_id') or '').strip()
                    profile = (row.get('device_profile') or '').strip()
                    if not sid: errors.append(f'nodes.csv linha {rownum}: site_id vazio.')
                    elif sid in ids: errors.append(f'nodes.csv linha {rownum}: site_id duplicado: {sid}.')
                    ids.add(sid)
                    if not profile: errors.append(f'nodes.csv linha {rownum}: device_profile vazio.')
                    profiles.add(profile)
                    for k, lo, hi in (('lat',-90,90),('lon',-180,180)):
                        value = _number(row.get(k))
                        if value is None or not lo <= value <= hi:
                            errors.append(f'nodes.csv linha {rownum}: {k} inválido.')
                    for k in ('x','y','mount_height_m'):
                        value = _number(row.get(k))
                        if value is None or (k == 'mount_height_m' and value < 0):
                            errors.append(f'nodes.csv linha {rownum}: {k} inválido.')
                    for k in ('connected','can_route'):
                        if (row.get(k) or '').strip().lower() not in ('true','false','1','0'):
                            errors.append(f'nodes.csv linha {rownum}: {k} não é booleano.')
                    rank = (row.get('rank') or '').strip()
                    if rank and _number(rank) is None:
                        errors.append(f'nodes.csv linha {rownum}: rank inválido.')
                info['nodes_count'] = count
                info['profiles_used'] = sorted(profiles)
                if count == 0: errors.append('nodes.csv sem instâncias.')
                if scenario is not None and isinstance(scenario.get('devices'), dict):
                    for profile in sorted(profiles - set(scenario['devices'])):
                        errors.append(f'Perfil usado no nodes.csv não definido em [devices]: {profile}.')
        except (OSError, UnicodeError, csv.Error) as exc:
            errors.append(f'Falha ao ler nodes.csv: {exc}')
    # A checagem do motor é intencionalmente não executada nesta versão.
    return {'timestamp': datetime.now(timezone.utc).isoformat(), 'project': project.name,
            'level1_ok': not errors, 'engine_validation': 'not_run',
            'planning_authorized': False, 'errors': errors, 'warnings': warnings,
            'info': info}


def _number(value):
    try:
        if isinstance(value, bool): return None
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _finite(value, positive=False):
    n = _number(value)
    return n is not None and (not positive or n > 0)
