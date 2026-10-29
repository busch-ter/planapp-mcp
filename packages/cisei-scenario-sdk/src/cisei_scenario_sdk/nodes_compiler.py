from __future__ import annotations

import csv
import itertools
import math
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable, Mapping


class NodesValidationError(ValueError):
    """Dados insuficientes, ambíguos ou inconsistentes para gerar nodes.csv."""


@dataclass(frozen=True)
class SourceAssessment:
    path: str
    recognized_columns: tuple[str, ...]
    rows: int
    usable: bool
    reason: str


@dataclass(frozen=True)
class CompilationReport:
    output_path: str | None
    selected_sources: tuple[str, ...]
    rows_written: int
    strategy: str
    assessments: tuple[SourceAssessment, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "output_path": self.output_path,
            "selected_sources": list(self.selected_sources),
            "rows_written": self.rows_written,
            "strategy": self.strategy,
            "assessments": [asdict(item) for item in self.assessments],
        }


@dataclass
class _TableSource:
    path: Path
    headers: tuple[str, ...]
    rows: list[dict[str, str]]
    errors: tuple[str, ...] = ()

    @property
    def canonical_headers(self) -> set[str]:
        return set(self.headers).intersection(NodesCompiler.COLUMNS)


class NodesCompiler:
    """
    Descobre quais arquivos de data/ bastam para gerar nodes.csv canônico.

    Estratégia:
      1. Examina o conteúdo tabular dos arquivos em data/ (não seus nomes).
      2. Procura primeiro um único arquivo que já seja suficiente.
      3. Só se nenhum arquivo isolado servir, tenta combinar fontes por site_id.
      4. Não infere aliases, perfis, alturas, CRS, coordenadas nem outros valores.
      5. Rejeita conflitos e ambiguidades em vez de escolher dados silenciosamente.
      6. Nunca modifica fontes e nunca sobrescreve a saída sem autorização explícita.

    Arquivos não canônicos, como exportações KML/GeoJSON com campos `nome`,
    `pasta` e `atributos`, são inventariados como não utilizáveis diretamente.
    Para convertê-los em nós é necessário um mapeamento semântico explícito;
    este módulo não adivinha que coluna equivale a site_id ou a perfil técnico.
    """

    COLUMNS = (
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
    )

    REQUIRED = (
        "site_id",
        "device_profile",
        "kind",
        "lat",
        "lon",
        "mount_height_m",
        "connected",
        "can_route",
    )

    OPTIONAL = ("x", "y", "rank")
    NUMERIC_FIELDS = ("lat", "lon", "x", "y", "mount_height_m", "rank")
    KINDS = {"leaf", "cell"}
    BOOLEANS = {"true", "false"}
    MAX_COMBINATIONS_TO_TEST = 20_000

    def __init__(self, project_path: str | Path, *, copel_config=None) -> None:
        self.project_path = Path(project_path).resolve()
        self.data_path = self.project_path / "data"
        self.default_output = self.project_path / "nodes.csv"
        self.last_report: CompilationReport | None = None
        self.copel_config = copel_config
        self.nodes_config_path = self.project_path / "nodes_config.toml"

    def inspect_sources(self) -> list[Path]:
        """Lista arquivos regulares encontrados recursivamente em data/."""
        if not self.data_path.is_dir():
            return []
        return sorted(
            (path for path in self.data_path.rglob("*") if path.is_file()),
            key=lambda path: path.as_posix().casefold(),
        )

    @staticmethod
    def _number(
        value: Any,
        *,
        field: str,
        row_number: int,
        required: bool = True,
    ) -> float | None:
        text = "" if value is None else str(value).strip()
        if not text:
            if required:
                raise ValueError(f"campo '{field}' ausente.")
            return None
        try:
            number = float(text)
        except (TypeError, ValueError):
            raise ValueError(
                f"'{field}' deve ser numérico; recebido {text!r}."
            ) from None
        if not math.isfinite(number):
            raise ValueError(f"'{field}' não é finito.")
        return number

    @classmethod
    def validate_rows(
        cls,
        rows: Iterable[Mapping[str, Any]],
    ) -> list[dict[str, str]]:
        """Valida registros e os normaliza para as 11 colunas canônicas."""
        validated: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        errors: list[str] = []

        for row_number, source in enumerate(rows, start=2):
            row = {
                column: (
                    "" if source.get(column) is None
                    else str(source.get(column)).strip()
                )
                for column in cls.COLUMNS
            }
            try:
                for field in cls.REQUIRED:
                    if not row[field]:
                        raise ValueError(f"campo obrigatório '{field}' ausente.")

                site_id = row["site_id"]
                if site_id in seen_ids:
                    raise ValueError(f"site_id duplicado: {site_id!r}.")
                seen_ids.add(site_id)

                if row["kind"].lower() not in cls.KINDS:
                    raise ValueError(
                        f"kind inválido: {row['kind']!r}; "
                        f"valores aceitos: {sorted(cls.KINDS)}."
                    )
                row["kind"] = row["kind"].lower()

                lat = cls._number(row["lat"], field="lat", row_number=row_number)
                lon = cls._number(row["lon"], field="lon", row_number=row_number)
                height = cls._number(
                    row["mount_height_m"], field="mount_height_m", row_number=row_number
                )
                assert lat is not None and lon is not None and height is not None
                if not -90 <= lat <= 90:
                    raise ValueError("lat fora do intervalo [-90, 90].")
                if not -180 <= lon <= 180:
                    raise ValueError("lon fora do intervalo [-180, 180].")
                if height <= 0:
                    raise ValueError("mount_height_m deve ser positivo.")

                for field in ("connected", "can_route"):
                    normalized = row[field].lower()
                    if normalized not in cls.BOOLEANS:
                        raise ValueError(f"{field} deve ser TRUE ou FALSE.")
                    row[field] = normalized.upper()

                x = cls._number(row["x"], field="x", row_number=row_number, required=False)
                y = cls._number(row["y"], field="y", row_number=row_number, required=False)
                if (x is None) != (y is None):
                    raise ValueError("x e y devem estar ambos preenchidos ou ambos vazios.")
                for field in ("x", "y", "rank"):
                    if row[field]:
                        cls._number(row[field], field=field, row_number=row_number, required=False)

                validated.append(row)
            except (ValueError, AssertionError) as exc:
                errors.append(f"Linha {row_number}: {exc}")

        if errors:
            raise NodesValidationError(
                "Não foi possível validar os nós:\n- " + "\n- ".join(errors)
            )
        if not validated:
            raise NodesValidationError("Nenhum registro disponível para gerar nodes.csv.")
        return validated

    @classmethod
    def read_csv(cls, source_path: str | Path) -> list[dict[str, str]]:
        """Lê CSV canônico e rejeita cabeçalhos/linhas estruturalmente inválidos."""
        source = cls._read_table(Path(source_path))
        if source is None:
            raise NodesValidationError(
                f"Não foi possível ler um CSV tabular: {source_path}"
            )

        if source.errors:
            raise NodesValidationError(
                f"{source_path}: " + "; ".join(source.errors)
            )

        allowed = set(cls.COLUMNS)
        unknown = set(source.headers) - allowed
        if unknown:
            raise NodesValidationError(
                f"{source_path}: colunas fora do esquema canônico: "
                f"{sorted(unknown)}"
            )

        missing = set(cls.REQUIRED) - set(source.headers)
        if missing:
            raise NodesValidationError(
                f"{source_path}: faltam colunas obrigatórias: {sorted(missing)}"
            )

        return cls.validate_rows(source.rows)

    @staticmethod
    def _is_empty_row(row: Mapping[str, Any]) -> bool:
        return not any(str(value or "").strip() for value in row.values())

    @classmethod
    def _read_table(cls, path: Path) -> _TableSource | None:
        """Lê tabela delimitada e registra problemas estruturais para validação."""
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                sample = handle.read(65_536)

            if not sample.strip():
                return None

            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\\t|")
            except csv.Error:
                dialect = csv.excel

            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle, dialect=dialect)
                if not reader.fieldnames:
                    return None

                headers = tuple(
                    (name or "").strip().lstrip("\\ufeff")
                    for name in reader.fieldnames
                )
                errors: list[str] = []

                duplicates = sorted({
                    name for name in headers
                    if name and headers.count(name) > 1
                })
                if duplicates:
                    errors.append(
                        f"colunas duplicadas no cabeçalho: {duplicates}"
                    )

                if any(not name for name in headers):
                    errors.append("há coluna com cabeçalho vazio")

                normalized_rows: list[dict[str, str]] = []
                for raw in reader:
                    if raw is None:
                        continue

                    # DictReader usa a chave None para campos além do cabeçalho.
                    extra = raw.get(None)
                    if extra and any(str(value or "").strip() for value in extra):
                        errors.append(
                            f"quantidade de campos excede o cabeçalho "
                            f"na linha {reader.line_num}"
                        )

                    if cls._is_empty_row(raw):
                        continue

                    row: dict[str, str] = {}
                    for key, value in raw.items():
                        if key is None:
                            continue
                        clean_key = key.strip().lstrip("\\ufeff")
                        row[clean_key] = (
                            "" if value is None else str(value).strip()
                        )
                    normalized_rows.append(row)

                return _TableSource(
                    path=path,
                    headers=headers,
                    rows=normalized_rows,
                    errors=tuple(dict.fromkeys(errors)),
                )
        except (OSError, UnicodeError, csv.Error):
            return None

    def analyze_sources(self) -> list[SourceAssessment]:
        """Faz inventário dos arquivos e indica se têm colunas canônicas úteis."""
        assessments: list[SourceAssessment] = []
        for path in self.inspect_sources():
            table = self._read_table(path)
            rel = self._relative(path)
            if table is None:
                assessments.append(SourceAssessment(
                    rel, (), 0, False, "Não é uma tabela de texto legível ou está vazia."
                ))
                continue
            recognized = tuple(column for column in self.COLUMNS if column in table.headers)
            if "site_id" not in table.headers or len(recognized) < 2:
                assessments.append(SourceAssessment(
                    rel, recognized, len(table.rows), False,
                    "Não possui site_id e pelo menos outro campo canônico; não pode ser combinado automaticamente."
                ))
            else:
                missing_header_fields = sorted(set(self.REQUIRED) - set(table.headers))
                if missing_header_fields:
                    reason = "Fonte parcial; faltam colunas no cabeçalho: " + ", ".join(missing_header_fields)
                else:
                    reason = "Possui as colunas obrigatórias; os valores ainda precisam passar pela validação."
                assessments.append(SourceAssessment(rel, recognized, len(table.rows), True, reason))
        return assessments

    def compile_from_sources(
        self,
        *,
        output_path: str | Path | None = None,
        overwrite: bool = False,
    ) -> Path:
        """Descobre a menor fonte/conjunto suficiente e gera nodes.csv."""
        if not self.data_path.is_dir():
            raise NodesValidationError(f"Diretório de entrada não encontrado: {self.data_path}")

        files = self.inspect_sources()
        tables: list[_TableSource] = []
        preliminary: list[SourceAssessment] = []
        for path in files:
            table = self._read_table(path)
            rel = self._relative(path)
            if table is None:
                preliminary.append(SourceAssessment(
                    rel, (), 0, False, "Não é uma tabela de texto legível ou está vazia."
                ))
                continue
            recognized = tuple(column for column in self.COLUMNS if column in table.headers)
            if "site_id" not in table.headers or len(recognized) < 2:
                preliminary.append(SourceAssessment(
                    rel, recognized, len(table.rows), False,
                    "Não possui site_id e pelo menos outro campo canônico; não pode ser combinado automaticamente."
                ))
                continue
            tables.append(table)
            missing = sorted(set(self.REQUIRED) - set(table.headers))
            reason = (
                "Fonte parcial; faltam colunas no cabeçalho: " + ", ".join(missing)
                if missing else "Cabeçalho contém todos os campos obrigatórios."
            )
            preliminary.append(SourceAssessment(rel, recognized, len(table.rows), True, reason))

        if not tables and (self.copel_config is not None or self.nodes_config_path.is_file()):
            from cisei_scenario_sdk.nodes_source_copel import compile_copel
            config = self.copel_config
            if config is None:
                from cisei_scenario_sdk.nodes_config_loader import load_nodes_config
                config = load_nodes_config(self.nodes_config_path)
            records, paths = compile_copel(self.data_path, config)
            validated = self.validate_rows(records)
            source_tables = [_TableSource(path=p, headers=(), rows=[]) for p in paths]
            return self._write_result(
                validated, source_tables, output_path, overwrite,
                "copel_adapter", preliminary,
            )

        if not tables:
            self.last_report = CompilationReport(
                None, (), 0, "none", tuple(preliminary)
            )
            raise NodesValidationError(
                "Nenhuma fonte com chave explícita 'site_id' e campos canônicos foi encontrada em data/. "
                "Não vou inferir identificadores ou valores técnicos a partir de colunas como nome/atributos."
            )

        # Primeiro, validar cada fonte isoladamente. Uma fonte com cabeçalho completo
        # pode ainda representar só uma parte do inventário; por isso, só a usamos
        # sozinha se também cobrir todos os IDs encontrados nas demais fontes canônicas.
        valid_single: list[tuple[_TableSource, list[dict[str, str]]]] = []
        single_errors: dict[str, str] = {}
        for table in tables:
            try:
                valid_single.append((table, self._validate_table_as_rows(table)))
            except NodesValidationError as exc:
                single_errors[self._relative(table.path)] = str(exc)

        all_ids: set[str] = set()
        malformed_sources: list[str] = []
        for table in tables:
            ids = [str(row.get("site_id") or "").strip() for row in table.rows]
            if any(not value for value in ids):
                malformed_sources.append(
                    f"{self._relative(table.path)} contém registro sem site_id."
                )
                continue
            if len(ids) != len(set(ids)):
                malformed_sources.append(
                    f"{self._relative(table.path)} contém site_id duplicado."
                )
                continue
            all_ids.update(ids)

        if malformed_sources:
            self.last_report = CompilationReport(
                None, (), 0, "invalid_source_keys", tuple(preliminary)
            )
            raise NodesValidationError(
                "Não é seguro decidir quais fontes são suficientes porque existem "
                "chaves ausentes ou duplicadas em fontes com colunas canônicas:\n- "
                + "\n- ".join(malformed_sources)
            )

        sufficient_single: list[tuple[_TableSource, list[dict[str, str]]]] = []
        for table, rows in valid_single:
            ids = {row["site_id"] for row in rows}
            if ids != all_ids:
                continue
            if all(self._source_agrees_with_rows(other, rows) for other in tables):
                sufficient_single.append((table, rows))

        if sufficient_single:
            # Se várias fontes isoladas cobrem o mesmo inventário, escolhemos a que
            # preserva mais valores não vazios. Empates só são aceitáveis quando os
            # registros normalizados são equivalentes; conflitos nunca são ocultados.
            best_score = max(self._information_score(rows) for _, rows in sufficient_single)
            best = [(table, rows) for table, rows in sufficient_single
                    if self._information_score(rows) == best_score]
            signatures: dict[tuple[tuple[str, ...], ...], list[tuple[_TableSource, list[dict[str, str]]]]] = {}
            for table, rows in best:
                sig = tuple(sorted((tuple(row[c] for c in self.COLUMNS) for row in rows), key=lambda r: r[0]))
                signatures.setdefault(sig, []).append((table, rows))
            if len(signatures) > 1:
                sources = sorted(self._relative(item[0].path) for item in best)
                raise NodesValidationError(
                    "Há fontes isoladas que cobrem o inventário, mas divergem sem uma opção claramente mais completa. "
                    "Não é seguro escolher automaticamente. Fontes: " + ", ".join(sources)
                )
            equivalent = next(iter(signatures.values()))
            chosen, rows = min(equivalent, key=lambda item: self._relative(item[0].path).casefold())
            return self._write_result(
                rows, [chosen], output_path, overwrite, "single_source", preliminary
            )

        # Só combina fontes se nenhuma fonte isolada cobrir e representar todo o
        # inventário observado. Combinamos exclusivamente
        # pela chave explícita site_id, nunca por proximidade, nome ou coordenadas.
        tested = 0
        valid_combinations: list[tuple[tuple[_TableSource, ...], list[dict[str, str]]]] = []
        max_size = len(tables)
        for size in range(2, max_size + 1):
            for combination in itertools.combinations(tables, size):
                tested += 1
                if tested > self.MAX_COMBINATIONS_TO_TEST:
                    raise NodesValidationError(
                        f"A descoberta exigiria testar mais de {self.MAX_COMBINATIONS_TO_TEST} combinações. "
                        "Reduza ou organize as fontes em data/; nenhuma fonte foi alterada."
                    )
                try:
                    merged = self._merge_sources(combination)
                    merged_ids = {str(row.get("site_id") or "").strip() for row in merged}
                    # Não ignorar silenciosamente IDs fornecidos por outra fonte
                    # canônica: a combinação precisa cobrir todo o inventário
                    # identificado nas fontes reconhecidas.
                    if merged_ids != all_ids:
                        continue
                    rows = self.validate_rows(merged)
                except NodesValidationError:
                    continue
                valid_combinations.append((combination, rows))
            if valid_combinations:
                break  # achou a menor cardinalidade suficiente

        if not valid_combinations:
            detail = self._summarize_single_errors(single_errors)
            self.last_report = CompilationReport(None, (), 0, "insufficient_sources", tuple(preliminary))
            raise NodesValidationError(
                "Nenhuma fonte isolada nem combinação por site_id produz nodes.csv válido. "
                "Os campos obrigatórios devem estar presentes explicitamente e sem conflitos."
                + detail
            )

        result_signatures: dict[tuple[tuple[str, ...], ...], list[tuple[tuple[_TableSource, ...], list[dict[str, str]]]]] = {}
        for combination, rows in valid_combinations:
            sig = tuple(tuple(row[c] for c in self.COLUMNS) for row in rows)
            result_signatures.setdefault(sig, []).append((combination, rows))
        if len(result_signatures) > 1:
            choices = [
                " + ".join(self._relative(table.path) for table in combination)
                for combination, _ in valid_combinations
            ]
            raise NodesValidationError(
                "Há combinações mínimas válidas que produzem resultados diferentes. "
                "É necessária uma decisão explícita sobre as fontes: " + "; ".join(choices)
            )

        equivalent = next(iter(result_signatures.values()))
        chosen_combo, rows = min(
            equivalent,
            key=lambda item: tuple(self._relative(t.path).casefold() for t in item[0]),
        )
        return self._write_result(
            rows, list(chosen_combo), output_path, overwrite, "merged_by_site_id", preliminary
        )


    def prepare_output(self, *, overwrite_existing: bool = False) -> Path:
        """Garante que o nodes.csv do projeto exista e seja válido.

        Deve ser chamado na preparação do projeto, antes de iniciar a conversa
        com o LLM. Um nodes.csv existente é validado e reutilizado por padrão;
        para reconstruí-lo a partir de data/, é necessária autorização explícita
        com overwrite_existing=True.
        """
        destination = self.default_output
        if destination.exists() and not overwrite_existing:
            rows = self.read_csv(destination)
            self.last_report = CompilationReport(
                output_path=str(destination),
                selected_sources=(self._relative(destination),),
                rows_written=len(rows),
                strategy="validated_existing",
                assessments=tuple(self.analyze_sources()),
            )
            return destination

        return self.compile_from_sources(
            output_path=destination,
            overwrite=overwrite_existing,
        )

    def compile(
        self,
        records: Iterable[Mapping[str, Any]],
        *,
        output_path: str | Path | None = None,
        overwrite: bool = False,
    ) -> Path:
        """Valida registros já consolidados e grava o CSV sem sobrescrever por padrão."""
        destination = self._destination(output_path)
        self._check_output(destination, overwrite)
        validated = self.validate_rows(records)
        return self._write_result(
            validated, [], destination, overwrite, "provided_records", list(self.analyze_sources())
        )

    def _validate_table_as_rows(self, table: _TableSource) -> list[dict[str, str]]:
        # Campos opcionais ausentes no cabeçalho são representados por string vazia.
        return self.validate_rows(table.rows)

    @classmethod
    def _source_agrees_with_rows(
        cls, source: _TableSource, complete_rows: list[dict[str, str]]
    ) -> bool:
        """True se a fonte não tem IDs/dados conflitantes com um resultado completo."""
        if "site_id" not in source.headers:
            return False
        complete_by_id = {row["site_id"]: row for row in complete_rows}
        seen: set[str] = set()
        for raw in source.rows:
            site_id = str(raw.get("site_id") or "").strip()
            if not site_id or site_id in seen or site_id not in complete_by_id:
                return False
            seen.add(site_id)
            canonical = complete_by_id[site_id]
            for field in cls.COLUMNS:
                if field == "site_id" or field not in source.headers:
                    continue
                incoming = str(raw.get(field) or "").strip()
                current = canonical.get(field, "")
                if incoming and current and not cls._equivalent_values(field, current, incoming):
                    return False
                # Se a fonte tem um valor mas o candidato completo não tem, esse
                # candidato não preservaria todas as informações explícitas.
                if incoming and not current:
                    return False
        return True

    @staticmethod
    def _information_score(rows: list[dict[str, str]]) -> int:
        return sum(bool(str(row.get(field) or "").strip())
                   for row in rows for field in NodesCompiler.COLUMNS)

    @classmethod
    def _merge_sources(
        cls,
        sources: tuple[_TableSource, ...],
    ) -> list[dict[str, str]]:
        combined: dict[str, dict[str, str]] = {}
        source_ids: dict[Path, set[str]] = {}
        errors: list[str] = []
        for source in sources:
            headers = set(source.headers)
            ids_in_this_source: set[str] = set()
            for row_number, raw in enumerate(source.rows, start=2):
                site_id = str(raw.get("site_id") or "").strip()
                if not site_id:
                    errors.append(f"{source.path.name}, linha {row_number}: site_id ausente.")
                    continue
                if site_id in ids_in_this_source:
                    errors.append(f"{source.path.name}, linha {row_number}: site_id duplicado {site_id!r} dentro da mesma fonte.")
                    continue
                ids_in_this_source.add(site_id)
                target = combined.setdefault(site_id, {column: "" for column in cls.COLUMNS})
                target["site_id"] = site_id
                for column in cls.COLUMNS:
                    if column == "site_id" or column not in headers:
                        continue
                    incoming = str(raw.get(column) or "").strip()
                    if not incoming:
                        continue
                    current = target[column]
                    if not current:
                        target[column] = incoming
                    elif not cls._equivalent_values(column, current, incoming):
                        errors.append(
                            f"conflito para site_id={site_id!r}, campo={column!r}: "
                            f"{current!r} versus {incoming!r} em {source.path.name}."
                        )
            source_ids[source.path] = ids_in_this_source
        if errors:
            raise NodesValidationError("Conflitos ao combinar fontes:\n- " + "\n- ".join(errors))
        return [combined[site_id] for site_id in sorted(combined)]

    @classmethod
    def _equivalent_values(cls, field: str, left: str, right: str) -> bool:
        if field in cls.NUMERIC_FIELDS:
            try:
                return float(left) == float(right)
            except ValueError:
                return False
        if field in ("connected", "can_route"):
            return left.lower() == right.lower()
        if field == "kind":
            return left.lower() == right.lower()
        return left.strip() == right.strip()

    def _write_result(
        self,
        rows: list[dict[str, str]],
        selected_tables: list[_TableSource],
        output_path: str | Path | None,
        overwrite: bool,
        strategy: str,
        assessments: list[SourceAssessment],
    ) -> Path:
        destination = self._destination(output_path)
        self._check_output(destination, overwrite)
        destination.parent.mkdir(parents=True, exist_ok=True)
        # CSV temporário e replace só após gravação completa, para evitar arquivo parcial.
        temporary = destination.with_name(destination.name + ".tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=self.COLUMNS, extrasaction="raise")
                writer.writeheader()
                writer.writerows(rows)
            if destination.exists() and not overwrite:
                raise FileExistsError(
                    f"O arquivo já existe: {destination}. Para substituí-lo, informe overwrite=True."
                )
            temporary.replace(destination)
        finally:
            if temporary.exists():
                temporary.unlink()
        selected = tuple(self._relative(table.path) for table in selected_tables)
        self.last_report = CompilationReport(
            output_path=str(destination),
            selected_sources=selected,
            rows_written=len(rows),
            strategy=strategy,
            assessments=tuple(assessments),
        )
        return destination

    def _destination(self, output_path: str | Path | None) -> Path:
        destination = Path(output_path) if output_path is not None else self.default_output
        if not destination.is_absolute():
            destination = self.project_path / destination
        destination = destination.resolve()
        if not destination.is_relative_to(self.project_path):
            raise ValueError("O arquivo de saída deve estar dentro do projeto.")
        return destination

    @staticmethod
    def _check_output(destination: Path, overwrite: bool) -> None:
        if destination.exists() and not overwrite:
            raise FileExistsError(
                f"O arquivo já existe: {destination}. Para substituí-lo, informe overwrite=True."
            )

    def _relative(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.project_path).as_posix()
        except ValueError:
            return path.as_posix()

    @staticmethod
    def _summarize_single_errors(errors: Mapping[str, str]) -> str:
        if not errors:
            return ""
        # Evita mensagem gigantesca caso existam muitos CSVs.
        items = list(errors.items())[:5]
        rendered = "\nDiagnóstico das primeiras fontes:\n" + "\n".join(
            f"- {name}: {message.splitlines()[0]}" for name, message in items
        )
        if len(errors) > len(items):
            rendered += f"\n- ... e mais {len(errors) - len(items)} fontes."
        return rendered



def prepare_project_nodes(
    project_path: str | Path,
    *,
    overwrite_existing: bool = False,
    copel_config=None,
) -> tuple[Path, CompilationReport]:
    """Prepara nodes.csv antes da inicialização do agente/LLM.

    Em projeto novo, descobre a menor fonte ou combinação suficiente em data/
    e gera nodes.csv. Se nodes.csv já existir, valida e reutiliza sem sobrescrever.
    Para reconstruí-lo explicitamente, use overwrite_existing=True.
    """
    compiler = NodesCompiler(project_path, copel_config=copel_config)
    output = compiler.prepare_output(overwrite_existing=overwrite_existing)
    if compiler.last_report is None:  # proteção defensiva
        raise RuntimeError("O compilador não produziu relatório de preparação.")
    return output, compiler.last_report


__all__ = [
    "NodesCompiler",
    "NodesValidationError",
    "SourceAssessment",
    "CompilationReport",
    "prepare_project_nodes",
]