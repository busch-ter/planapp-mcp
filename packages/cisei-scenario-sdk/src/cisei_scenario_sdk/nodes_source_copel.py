"""Adaptador estrito dos três inventários COPEL Fase 2.

Não deduz perfis, alturas de montagem, flags ou CRS. IDs sintéticos são
estáveis para os mesmos arquivos e ordem, mas não são IDs patrimoniais.
"""
from __future__ import annotations

import csv
import math
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping


class CopelSourceError(ValueError):
    pass


@dataclass(frozen=True)
class NodeRule:
    device_profile: str
    kind: str
    connected: bool
    can_route: bool
    # Somente quando altura de montagem NÃO é dada na fonte.
    mount_height_m: float | None = None


@dataclass(frozen=True)
class CopelConfig:
    # Deve ser confirmado documentalmente; não é assumido pelo adaptador.
    source_crs: str
    substation_rule: NodeRule
    external_tower_rule: NodeRule
    automation_rules: Mapping[str, NodeRule]
    # Para subestações com ALTURA ÚTIL=0, se incluídas.
    substation_zero_height_m: float | None = None
    # Para usar altura da torre como altura de montagem, é preciso autorização.
    use_structure_height_as_mount_height: bool = False
    # Permite IDs de origem+posição quando a fonte não contém ID único.
    allow_synthetic_site_ids: bool = False


def _norm(s: str) -> str:
    s = unicodedata.normalize('NFKD', s.strip())
    return ''.join(c for c in s if not unicodedata.combining(c)).upper()


def _num(s: str, label: str) -> float:
    try:
        n = float(str(s).strip().replace('.', '').replace(',', '.')) if ',' in str(s) else float(str(s).strip())
    except (ValueError, TypeError):
        raise CopelSourceError(f'{label}: número inválido {s!r}') from None
    if not math.isfinite(n):
        raise CopelSourceError(f'{label}: número não finito')
    return n


def _read(path: Path, required: set[str]) -> list[dict[str, str]]:
    try:
        with path.open('r', encoding='cp1252', newline='') as f:
            reader = csv.DictReader(f, delimiter=';')
            headers = reader.fieldnames or []
            normalized = [_norm(h) for h in headers]
            if len(normalized) != len(set(normalized)):
                raise CopelSourceError(f'{path.name}: cabeçalhos duplicados')
            missing = required - set(normalized)
            if missing:
                raise CopelSourceError(f'{path.name}: faltam {sorted(missing)}')
            rows = []
            for line, raw in enumerate(reader, 2):
                if None in raw:
                    raise CopelSourceError(f'{path.name}:{line}: campos excedentes')
                if not any(str(v or '').strip() for v in raw.values()):
                    continue
                rows.append({_norm(k): (v or '').strip() for k, v in raw.items()})
            return rows
    except (OSError, UnicodeError, csv.Error) as e:
        raise CopelSourceError(f'{path}: falha na leitura: {e}') from e


SOURCES = {
    'substations': ({'MUNICIPIO','SUBESTACAO','TORRE','ALTURA UTIL','COORDENADA X','COORDENADA Y'}, 'COPEL-SE'),
    'towers': ({'ALTURA','FIBRA','COORDENADA X','COORDENADA Y'}, 'COPEL-TORRE'),
    'automation': ({'MUNICIPIO','TIPO','COORD X','COORD Y'}, 'COPEL-AUT'),
}


def detect_sources(data_path: Path) -> dict[str, Path]:
    """Reconhece por esquema, não por nome; exige exatamente uma fonte de cada tipo."""
    found: dict[str, Path] = {}
    for path in sorted(data_path.rglob('*')):
        if not path.is_file() or path.suffix.lower() != '.csv':
            continue
        try:
            with path.open(encoding='cp1252', newline='') as f:
                header = next(csv.reader(f, delimiter=';'), [])
        except (OSError, UnicodeError, csv.Error):
            continue
        cols = {_norm(x) for x in header}
        for key, (required, _) in SOURCES.items():
            if required.issubset(cols):
                if key in found:
                    raise CopelSourceError(f'Mais de um CSV COPEL do tipo {key}: {found[key]}, {path}')
                found[key] = path
    return found


def compile_copel(data_path: Path, config: CopelConfig) -> tuple[list[dict[str, str]], list[Path]]:
    if not config.source_crs.strip():
        raise CopelSourceError('Informe o CRS UTM de origem confirmado (ex.: EPSG:31982).')
    if not config.allow_synthetic_site_ids:
        raise CopelSourceError('As fontes não contêm site_id único: autorize IDs sintéticos explicitamente.')
    try:
        from pyproj import CRS, Transformer
    except ImportError as e:
        raise CopelSourceError('Dependência ausente: instale pyproj no ambiente de execução.') from e
    try:
        source_crs = CRS.from_user_input(config.source_crs)
        if not source_crs.is_projected:
            raise ValueError('CRS de origem não é projetado')
        transform = Transformer.from_crs(source_crs, 'EPSG:4326', always_xy=True)
    except Exception as e:
        raise CopelSourceError(f'CRS inválido: {e}') from e
    files = detect_sources(data_path)
    if set(files) != set(SOURCES):
        raise CopelSourceError(f'Fontes COPEL esperadas: {sorted(SOURCES)}; encontradas: {sorted(files)}')
    tables = {key: _read(files[key], SOURCES[key][0]) for key in SOURCES}
    types = {_norm(r['TIPO']) for r in tables['automation']}
    missing = types - {_norm(k) for k in config.automation_rules}
    if missing:
        raise CopelSourceError(f'Sem regras para tipos de automação: {sorted(missing)}')
    rules = {_norm(k): v for k,v in config.automation_rules.items()}
    out: list[dict[str, str]] = []
    for category, rows in tables.items():
        for index, raw in enumerate(rows, 2):
            label = f'{files[category].name}:{index}'
            rule = (config.substation_rule if category == 'substations' else
                    config.external_tower_rule if category == 'towers' else rules[_norm(raw['TIPO'])])
            if not isinstance(rule.device_profile, str) or not rule.device_profile.strip() or rule.kind not in ('cell','leaf'):
                raise CopelSourceError(f'{label}: regra incompleta de perfil/kind')
            if not isinstance(rule.connected, bool) or not isinstance(rule.can_route, bool):
                raise CopelSourceError(f'{label}: connected e can_route devem ser booleanos explícitos')
            xkey, ykey = ('COORD X', 'COORD Y') if category == 'automation' else ('COORDENADA X','COORDENADA Y')
            x, y = _num(raw[xkey], label+' X'), _num(raw[ykey], label+' Y')
            lon, lat = transform.transform(x, y)
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise CopelSourceError(f'{label}: transformação fora dos limites geográficos')
            height = rule.mount_height_m
            if category != 'automation' and height is None:
                if not config.use_structure_height_as_mount_height:
                    raise CopelSourceError(f'{label}: falta altura de montagem; altura da estrutura não é equivalente automaticamente')
                height = _num(raw['ALTURA UTIL' if category == 'substations' else 'ALTURA'], label+' altura')
                if category == 'substations' and height == 0:
                    height = config.substation_zero_height_m
            if height is None or not math.isfinite(float(height)) or height <= 0:
                raise CopelSourceError(f'{label}: mount_height_m positivo não definido')
            prefix = SOURCES[category][1]
            out.append({
                'site_id': f'{prefix}-{index-1:05d}',
                'device_profile': rule.device_profile,
                'kind': rule.kind,
                'lat': f'{lat:.8f}', 'lon': f'{lon:.8f}',
                'x': str(x), 'y': str(y),
                'mount_height_m': str(height),
                'connected': str(rule.connected).upper(),
                'can_route': str(rule.can_route).upper(),
                'rank': '',
            })
    return out, [files[k] for k in SOURCES]
