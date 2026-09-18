# ============================================================================
# PLANAPP AI — REPORT GENERATOR
#
# Geração de relatório técnico a partir da análise final do agente.
#
# Responsabilidades:
#   - receber a análise técnica produzida pelo agente;
#   - preservar o texto da análise como conteúdo principal do relatório;
#   - converter Markdown simples para PDF;
#   - incluir mapa OSM estático;
#   - incluir visualizações geradas pelo PlanApp;
#   - manter compatibilidade com o relatório técnico anterior;
#   - salvar PDFs em:
#
#       <planapp-mcp>/reports/
#
# ============================================================================

from __future__ import annotations

import html
import json
import math
import re

from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import (
    ParagraphStyle,
    getSampleStyleSheet,
)
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image as ReportLabImage,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    KeepTogether,
)

PROJECT_DIR = Path(__file__).resolve().parent
REPORT_DIR = PROJECT_DIR / "reports"


# ============================================================================
# FUNÇÕES AUXILIARES
# ============================================================================

def _is_number(value: Any) -> bool:

    if isinstance(value, bool):
        return False

    if isinstance(value, (int, float)):
        return math.isfinite(float(value))

    return False


def _fmt_number(
    value: Any,
    decimals: int = 2,
    suffix: str = "",
) -> str:

    if not _is_number(value):
        return "Não informado"

    return f"{float(value):.{decimals}f}{suffix}"


def _fmt_bool(value: Any) -> str:

    if value is True:
        return "Sim"

    if value is False:
        return "Não"

    return "Não informado"


def _safe_json_loads(value: Any) -> Any:

    if not isinstance(value, str):
        return value

    text = value.strip()

    if not text:
        return value

    try:
        return json.loads(text)

    except Exception:
        return value


def _clean_text(value: Any) -> str:

    if value is None:
        return ""

    if isinstance(value, str):
        return value.strip()

    return str(value).strip()


def _escape_pdf_text(value: Any) -> str:

    text = _clean_text(value)

    if not text:
        return ""

    return html.escape(
        text,
        quote=False,
    )


def _format_inline_markup(
    text: str,
) -> str:

    escaped = _escape_pdf_text(text)

    # Negrito Markdown
    escaped = re.sub(
        r"\*\*(.+?)\*\*",
        r"<b>\1</b>",
        escaped,
    )

    # Itálico Markdown simples
    escaped = re.sub(
        r"(?<!\*)\*([^*]+)\*(?!\*)",
        r"<i>\1</i>",
        escaped,
    )

    return escaped


def _dict_contains_technical_data(
    data: Dict[str, Any],
) -> bool:

    technical_keys = {
        "fspl",
        "dist_m",
        "distance_m",
        "delta_diffra",
        "terrain",
        "vegetation",
        "buildings",
        "terrain_peaks_vv",
        "max_obstruction_angle_rad",
        "tx_near_terminal_clearance_m",
        "rx_near_terminal_clearance_m",
        "tx_rx_elevation_angle_rad",
    }

    return any(
        key in data
        for key in technical_keys
    )


def _recursive_find_technical_dict(
    value: Any,
    max_depth: int = 8,
    _depth: int = 0,
) -> Optional[Dict[str, Any]]:

    if _depth > max_depth:
        return None

    value = _safe_json_loads(value)

    if isinstance(value, dict):

        if _dict_contains_technical_data(value):
            return value

        priority_keys = (
            "technical_result",
            "evaluate_result",
            "evaluate_link",
            "link_features",
            "data",
            "result",
            "output",
        )

        for key in priority_keys:

            if key not in value:
                continue

            found = _recursive_find_technical_dict(
                value[key],
                max_depth=max_depth,
                _depth=_depth + 1,
            )

            if found is not None:
                return found

        for child in value.values():

            found = _recursive_find_technical_dict(
                child,
                max_depth=max_depth,
                _depth=_depth + 1,
            )

            if found is not None:
                return found

    elif isinstance(value, list):

        for child in value:

            found = _recursive_find_technical_dict(
                child,
                max_depth=max_depth,
                _depth=_depth + 1,
            )

            if found is not None:
                return found

    return None


def normalize_result(
    result: Any,
) -> Dict[str, Any]:

    result = _safe_json_loads(result)

    if result is None:
        return {}

    if isinstance(result, dict):

        if _dict_contains_technical_data(result):
            return dict(result)

        found = _recursive_find_technical_dict(result)

        if found is not None:

            normalized = dict(found)

            if (
                "status" not in normalized
                and "status" in result
            ):
                normalized["status"] = result["status"]

            return normalized

        return dict(result)

    return {
        "raw_result": result
    }


# ============================================================================
# REPORT GENERATOR
# ============================================================================

class ReportGenerator:

    def __init__(
        self,
        requested_params: Optional[Dict[str, Any]] = None,
        effective_params: Optional[Dict[str, Any]] = None,
        technical_result: Any = None,
        geocoded_points: Optional[
            List[Dict[str, Any]]
        ] = None,
        map_image: Optional[Any] = None,
        visualization_images: Optional[
            List[Dict[str, Any]]
        ] = None,
        user_request: Optional[str] = None,

        # NOVO:
        # Texto final produzido pelo agente
        analysis_text: Optional[str] = None,
    ):

        self.requested_params = (
            requested_params or {}
        )

        self.effective_params = (
            effective_params or {}
        )

        self.raw_result = technical_result

        self.result = normalize_result(
            technical_result
        )

        self.geocoded_points = (
            geocoded_points or []
        )

        self.map_image = map_image

        self.visualization_images = (
            visualization_images or []
        )

        self.user_request = (
            user_request or ""
        )

        # --------------------------------------------------------------------
        # NOVO
        #
        # Quando preenchido, este texto passa a ser o conteúdo principal
        # do relatório.
        #
        # O ReportGenerator NÃO gera uma segunda análise.
        # --------------------------------------------------------------------

        self.analysis_text = (
            analysis_text.strip()
            if isinstance(analysis_text, str)
            else ""
        )

        self.styles = None

    # ========================================================================
    # ACESSO A DADOS
    # ========================================================================

    def _get(
        self,
        *keys,
        default=None,
    ):

        for key in keys:

            if key in self.result:

                value = self.result[key]

                if value is not None:
                    return value

        return default

    def _first(
        self,
        data: Any,
        keys: List[str],
        default=None,
    ):

        if not isinstance(data, dict):
            return default

        for key in keys:

            if key in data:

                value = data[key]

                if value is not None:
                    return value

        return default

    # ========================================================================
    # PONTOS
    # ========================================================================

    def _unique_points(
        self,
    ) -> List[Dict[str, Any]]:

        points = []

        for point in self.geocoded_points:

            if not isinstance(point, dict):
                continue

            lat = point.get("lat")
            lon = point.get("lon")

            if not (
                _is_number(lat)
                and _is_number(lon)
            ):
                continue

            duplicate = False

            for existing in points:

                if (
                    abs(
                        float(existing["lat"])
                        - float(lat)
                    )
                    < 1e-9
                    and
                    abs(
                        float(existing["lon"])
                        - float(lon)
                    )
                    < 1e-9
                ):

                    duplicate = True
                    break

            if not duplicate:
                points.append(point)

        return points

    # ========================================================================
    # RELATÓRIO LEGADO
    #
    # Mantido para compatibilidade.
    #
    # Só será utilizado quando analysis_text não estiver disponível.
    # ========================================================================

    def _legacy_report(
        self,
        include_raw_result: bool = False,
    ) -> str:

        sections = []

        sections.append(
            "# Relatório Técnico — PlanApp AI"
        )

        sections.append(
            "Data/hora de geração: "
            + datetime.now().strftime(
                "%d/%m/%Y %H:%M:%S"
            )
        )

        sections.append("")

        sections.extend(
            self._section_user_request()
        )

        sections.append("")

        sections.extend(
            self._section_link_endpoints()
        )

        sections.append("")

        sections.extend(
            self._section_parameters()
        )

        sections.append("")

        sections.extend(
            self._section_link_characteristics()
        )

        sections.append("")

        sections.extend(
            self._section_terrain()
        )

        sections.append("")

        sections.extend(
            self._section_vegetation()
        )

        sections.append("")

        sections.extend(
            self._section_buildings()
        )

        sections.append("")

        sections.extend(
            self._section_geometry()
        )

        sections.append("")

        sections.extend(
            self._section_interpretation()
        )

        if include_raw_result:

            sections.append("")

            sections.extend(
                self._section_raw_result()
            )

        return "\n".join(
            sections
        )

    # ========================================================================
    # SOLICITAÇÃO DO USUÁRIO
    # ========================================================================

    def _section_user_request(
        self,
    ) -> List[str]:

        lines = [
            "## Solicitação do usuário"
        ]

        if self.user_request.strip():

            lines.append(
                self.user_request.strip()
            )

        else:

            lines.append(
                "Texto da solicitação não registrado."
            )

        return lines

    # ========================================================================
    # IDENTIFICAÇÃO DO ENLACE
    # ========================================================================

    def _section_link_endpoints(
        self,
    ) -> List[str]:

        lines = [
            "## Identificação do enlace"
        ]

        points = self._unique_points()

        if not points:

            lines.append(
                "- Não foram registrados pontos geográficos."
            )

            return lines

        labels = [
            "TX",
            "RX",
        ]

        for index, point in enumerate(
            points[:2]
        ):

            label = labels[index]

            name = (
                point.get("name")
                or point.get("query")
                or point.get("label")
                or ""
            )

            name = _clean_text(name)

            if name.upper() in {
                "TX",
                "RX",
            }:
                name = ""

            lat = point.get("lat")
            lon = point.get("lon")

            if name:

                endpoint = (
                    f"{label}: {name}"
                )

            else:

                endpoint = (
                    f"{label}: nome não informado"
                )

            if (
                _is_number(lat)
                and _is_number(lon)
            ):

                endpoint += (
                    " — "
                    f"{float(lat):.7f}, "
                    f"{float(lon):.7f}"
                )

            lines.append(
                f"- {endpoint}"
            )

        return lines

    # ========================================================================
    # PARÂMETROS
    # ========================================================================

    def _section_parameters(
        self,
    ) -> List[str]:

        lines = [
            "## Parâmetros do enlace"
        ]

        requested_freq = (
            self.requested_params.get(
                "frequency_text"
            )
        )

        if requested_freq is None:

            requested_freq = (
                self.requested_params.get(
                    "frequency"
                )
            )

        lines.append(
            "- Frequência solicitada: "
            + (
                _clean_text(requested_freq)
                if requested_freq is not None
                else "Não informada"
            )
        )

        tx_ha = self.requested_params.get(
            "tx_ha"
        )

        rx_ha = self.requested_params.get(
            "rx_ha"
        )

        lines.append(
            "- Altura TX solicitada: "
            + _fmt_number(
                tx_ha,
                2,
                " m",
            )
        )

        lines.append(
            "- Altura RX solicitada: "
            + _fmt_number(
                rx_ha,
                2,
                " m",
            )
        )

        freq_mhz = (
            self.effective_params.get(
                "freq_mhz"
            )
        )

        effective_tx = (
            self.effective_params.get(
                "tx_ha"
            )
        )

        effective_rx = (
            self.effective_params.get(
                "rx_ha"
            )
        )

        rooftop = (
            self.effective_params.get(
                "on_rooftop"
            )
        )

        lines.append(
            "- Frequência efetiva enviada ao PlanApp: "
            + _fmt_number(
                freq_mhz,
                3,
                " MHz",
            )
        )

        lines.append(
            "- Altura TX efetiva: "
            + _fmt_number(
                effective_tx,
                2,
                " m",
            )
        )

        lines.append(
            "- Altura RX efetiva: "
            + _fmt_number(
                effective_rx,
                2,
                " m",
            )
        )

        lines.append(
            "- Rooftop: "
            + _fmt_bool(rooftop)
        )

        return lines

    # ========================================================================
    # CARACTERÍSTICAS
    # ========================================================================

    def _section_link_characteristics(
        self,
    ) -> List[str]:

        lines = [
            "## Características do enlace"
        ]

        distance = self._get(
            "dist_m",
            "distance_m",
            "distance",
        )

        fspl = self._get(
            "fspl"
        )

        status = self._get(
            "status"
        )

        lines.append(
            "- Distância: "
            + _fmt_number(
                distance,
                2,
                " m",
            )
        )

        lines.append(
            "- FSPL: "
            + _fmt_number(
                fspl,
                2,
                " dB",
            )
        )

        if status is not None:

            lines.append(
                "- Status retornado pelo PlanApp: "
                + _clean_text(status)
            )

        return lines

    # ========================================================================
    # TERRENO
    # ========================================================================

    def _section_terrain(
        self,
    ) -> List[str]:

        lines = [
            "## Terreno"
        ]

        terrain = self._get(
            "terrain"
        )

        if isinstance(
            terrain,
            dict,
        ):

            for key, value in terrain.items():

                lines.append(
                    f"- {key}: "
                    f"{_clean_text(value)}"
                )

        elif terrain is not None:

            lines.append(
                "- Resultado: "
                + _clean_text(terrain)
            )

        else:

            keys = [
                "terrain_peaks_vv",
                "max_obstruction_angle_rad",
                "tx_near_terminal_clearance_m",
                "rx_near_terminal_clearance_m",
            ]

            found = False

            for key in keys:

                value = self._get(key)

                if value is None:
                    continue

                found = True

                lines.append(
                    f"- {key}: "
                    f"{_clean_text(value)}"
                )

            if not found:

                lines.append(
                    "- Dados de terreno não informados."
                )

        return lines

    # ========================================================================
    # VEGETAÇÃO
    # ========================================================================

    def _section_vegetation(
        self,
    ) -> List[str]:

        lines = [
            "## Vegetação / cobertura do solo"
        ]

        vegetation = self._get(
            "vegetation",
            "lulc",
            "cover",
        )

        if isinstance(
            vegetation,
            dict,
        ):

            for key, value in vegetation.items():

                lines.append(
                    f"- {key}: "
                    f"{_clean_text(value)}"
                )

        elif vegetation is not None:

            lines.append(
                "- Resultado: "
                + _clean_text(vegetation)
            )

        else:

            lines.append(
                "- Dados de vegetação/cobertura "
                "não informados."
            )

        return lines

    # ========================================================================
    # BUILDINGS
    # ========================================================================

    def _section_buildings(
        self,
    ) -> List[str]:

        lines = [
            "## Edificações"
        ]

        buildings = self._get(
            "buildings",
            "building",
        )

        if isinstance(
            buildings,
            dict,
        ):

            for key, value in buildings.items():

                lines.append(
                    f"- {key}: "
                    f"{_clean_text(value)}"
                )

        elif buildings is not None:

            lines.append(
                "- Resultado: "
                + _clean_text(buildings)
            )

        else:

            lines.append(
                "- Dados de edificações não informados."
            )

        return lines

    # ========================================================================
    # GEOMETRIA
    # ========================================================================

    def _section_geometry(
        self,
    ) -> List[str]:

        lines = [
            "## Geometria"
        ]

        keys = [
            "delta_diffra",
            "terrain_peaks_vv",
            "max_obstruction_angle_rad",
            "tx_near_terminal_clearance_m",
            "rx_near_terminal_clearance_m",
            "tx_rx_elevation_angle_rad",
        ]

        found = False

        for key in keys:

            value = self._get(key)

            if value is None:
                continue

            found = True

            lines.append(
                f"- {key}: "
                f"{_clean_text(value)}"
            )

        if not found:

            lines.append(
                "- Dados geométricos não informados."
            )

        return lines

    # ========================================================================
    # INTERPRETAÇÃO LEGADA
    # ========================================================================

    def _section_interpretation(
        self,
    ) -> List[str]:

        lines = [
            "## Observações"
        ]

        lines.append(
            "- Os valores apresentados nesta seção "
            "correspondem aos dados retornados pelo PlanApp."
        )

        lines.append(
            "- O relatório não recalcula os resultados "
            "técnicos retornados pela aplicação."
        )

        lines.append(
            "- O status de execução não deve ser interpretado "
            "isoladamente como classificação de viabilidade "
            "do enlace."
        )

        return lines

    # ========================================================================
    # RESULTADO BRUTO
    # ========================================================================

    def _section_raw_result(
        self,
    ) -> List[str]:

        lines = [
            "## Resultado técnico retornado"
        ]

        try:

            raw = json.dumps(
                self.raw_result,
                ensure_ascii=False,
                indent=2,
                default=str,
            )

            lines.append(
                "```json"
            )

            lines.extend(
                raw.splitlines()
            )

            lines.append(
                "```"
            )

        except Exception:

            lines.append(
                _clean_text(
                    self.raw_result
                )
            )

        return lines

    # ========================================================================
    # GERAÇÃO DO RELATÓRIO TEXTUAL
    # ========================================================================

    def generate_report(
        self,
        include_raw_result: bool = False,
    ) -> str:

        # --------------------------------------------------------------------
        # NOVO COMPORTAMENTO
        #
        # Se o agente produziu uma análise final, ela é o relatório.
        #
        # NÃO acrescentamos uma segunda análise.
        # NÃO reescrevemos o texto.
        # NÃO misturamos o JSON técnico ao corpo.
        # --------------------------------------------------------------------

        if self.analysis_text:

            return self.analysis_text.strip()

        # --------------------------------------------------------------------
        # COMPATIBILIDADE COM O COMPORTAMENTO ANTERIOR
        # --------------------------------------------------------------------

        return self._legacy_report(
            include_raw_result=include_raw_result
        )

    # ========================================================================
    # PDF — IMAGENS
    # ========================================================================

    def _image_flowable(
        self,
        image_data: Any,
        max_width: float,
        max_height: float,
    ):

        if image_data is None:
            return None

        if isinstance(
            image_data,
            memoryview,
        ):

            image_data = image_data.tobytes()

        elif isinstance(
            image_data,
            bytearray,
        ):

            image_data = bytes(
                image_data
            )

        if not isinstance(
            image_data,
            bytes,
        ):
            return None

        try:

            image = ReportLabImage(
                BytesIO(image_data)
            )

            width = float(
                image.imageWidth
            )

            height = float(
                image.imageHeight
            )

            if width <= 0 or height <= 0:
                return None

            scale = min(
                max_width / width,
                max_height / height,
                1.0,
            )

            image.drawWidth = (
                width * scale
            )

            image.drawHeight = (
                height * scale
            )

            return image

        except Exception:

            return None

    # ========================================================================
    # PDF — MAPA
    # ========================================================================

    def _map_story(
        self,
    ) -> List[Any]:

        story = []

        if self.map_image is None:
            return story

        image = self._image_flowable(
            self.map_image,
            max_width=170 * mm,
            max_height=105 * mm,
        )

        if image is None:
            return story

        story.append(
            Paragraph(
                "Mapa do enlace",
                self.styles["PlanAppHeading2"],
            )
        )

        story.append(
            Spacer(
                1,
                4 * mm,
            )
        )

        story.append(
            image
        )

        story.append(
            Spacer(
                1,
                8 * mm,
            )
        )

        return story

    # ========================================================================
    # PDF — VISUALIZAÇÕES
    # ========================================================================

    def _visualization_story(
        self,
    ) -> List[Any]:

        story = []

        for item in self.visualization_images:

            if not isinstance(
                item,
                dict,
            ):
                continue

            title = (
                item.get("title")
                or "Visualização"
            )

            data = item.get(
                "data"
            )

            image = self._image_flowable(
                data,
                max_width=170 * mm,
                max_height=115 * mm,
            )

            if image is None:
                continue

            block = []

            block.append(
                Paragraph(
                    _format_inline_markup(
                        str(title)
                    ),
                    self.styles["PlanAppHeading3"],
                )
            )

            block.append(
                Spacer(
                    1,
                    3 * mm,
                )
            )

            block.append(
                image
            )

            block.append(
                Spacer(
                    1,
                    7 * mm,
                )
            )

            story.append(
                KeepTogether(
                    block
                )
            )

        return story

    # ========================================================================
    # PDF — MARKDOWN
    # ========================================================================

    def _markdown_to_pdf_story(
        self,
        report_text: str,
    ) -> List[Any]:

        story = []

        lines = report_text.splitlines()

        paragraph_buffer = []

        def flush_paragraph():

            nonlocal paragraph_buffer

            if not paragraph_buffer:
                return

            text = " ".join(
                paragraph_buffer
            ).strip()

            if text:

                story.append(
                    Paragraph(
                        _format_inline_markup(
                            text
                        ),
                        self.styles[
                            "PlanAppBodyText"
                        ],
                    )
                )

                story.append(
                    Spacer(
                        1,
                        2.5 * mm,
                    )
                )

            paragraph_buffer = []

        for line in lines:

            stripped = line.strip()

            if not stripped:

                flush_paragraph()

                continue

            # ------------------------------------------------------------
            # BLOCO DE CÓDIGO
            # ------------------------------------------------------------

            if stripped.startswith(
                "```"
            ):

                flush_paragraph()

                continue

            # ------------------------------------------------------------
            # MARKDOWN H1
            # ------------------------------------------------------------

            if stripped.startswith(
                "# "
            ):

                flush_paragraph()

                story.append(
                    Paragraph(
                        _format_inline_markup(
                            stripped[2:]
                        ),
                        self.styles[
                            "PlanAppTitle"
                        ],
                    )
                )

                story.append(
                    Spacer(
                        1,
                        4 * mm,
                    )
                )

                continue

            # ------------------------------------------------------------
            # MARKDOWN H2
            # ------------------------------------------------------------

            if stripped.startswith(
                "## "
            ):

                flush_paragraph()

                story.append(
                    Paragraph(
                        _format_inline_markup(
                            stripped[3:]
                        ),
                        self.styles[
                            "PlanAppHeading2"
                        ],
                    )
                )

                story.append(
                    Spacer(
                        1,
                        2 * mm,
                    )
                )

                continue

            # ------------------------------------------------------------
            # MARKDOWN H3
            # ------------------------------------------------------------

            if stripped.startswith(
                "### "
            ):

                flush_paragraph()

                story.append(
                    Paragraph(
                        _format_inline_markup(
                            stripped[4:]
                        ),
                        self.styles[
                            "PlanAppHeading3"
                        ],
                    )
                )

                story.append(
                    Spacer(
                        1,
                        2 * mm,
                    )
                )

                continue

            # ------------------------------------------------------------
            # TÍTULOS NUMERADOS
            #
            # Exemplo:
            #
            # 1. RESUMO EXECUTIVO
            # 2. IDENTIFICAÇÃO DO ENLACE
            #
            # O prompt atual do agente usa exatamente esse formato.
            # ------------------------------------------------------------

            numbered_heading = re.match(
                r"^(\d+)\.\s+(.+)$",
                stripped,
            )

            if numbered_heading:

                flush_paragraph()

                heading_number = (
                    numbered_heading.group(1)
                )

                heading_text = (
                    numbered_heading.group(2)
                )

                story.append(
                    Paragraph(
                        _format_inline_markup(
                            f"{heading_number}. "
                            f"{heading_text}"
                        ),
                        self.styles[
                            "PlanAppHeading2"
                        ],
                    )
                )

                story.append(
                    Spacer(
                        1,
                        2 * mm,
                    )
                )

                continue

            # ------------------------------------------------------------
            # LISTA
            # ------------------------------------------------------------

            if stripped.startswith(
                "- "
            ):

                flush_paragraph()

                bullet = _format_inline_markup(
                    stripped[2:]
                )

                story.append(
                    Paragraph(
                        "• " + bullet,
                        self.styles[
                            "PlanAppBodyText"
                        ],
                    )
                )

                story.append(
                    Spacer(
                        1,
                        1.2 * mm,
                    )
                )

                continue

            # ------------------------------------------------------------
            # LISTA COM *
            # ------------------------------------------------------------

            if stripped.startswith(
                "* "
            ):

                flush_paragraph()

                bullet = _format_inline_markup(
                    stripped[2:]
                )

                story.append(
                    Paragraph(
                        "• " + bullet,
                        self.styles[
                            "PlanAppBodyText"
                        ],
                    )
                )

                story.append(
                    Spacer(
                        1,
                        1.2 * mm,
                    )
                )

                continue

            # ------------------------------------------------------------
            # TEXTO NORMAL
            # ------------------------------------------------------------

            paragraph_buffer.append(
                stripped
            )

        flush_paragraph()

        return story

    # ========================================================================
    # PDF
    # ========================================================================

    def generate_pdf(
        self,
        report_text: Optional[str] = None,
        include_raw_result: bool = False,
    ) -> str:

        REPORT_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        if report_text is None:

            report_text = (
                self.generate_report(
                    include_raw_result=
                    include_raw_result
                )
            )

        timestamp = datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )

        pdf_path = (
            REPORT_DIR
            / (
                "planapp_ai_relatorio_"
                f"{timestamp}.pdf"
            )
        )

        # --------------------------------------------------------------------
        # ESTILOS
        # --------------------------------------------------------------------

        styles = getSampleStyleSheet()

        self.styles = styles

        styles.add(
            ParagraphStyle(
                name="PlanAppBodyText",
                parent=styles["BodyText"],
                fontSize=9.5,
                leading=13,
                alignment=TA_LEFT,
                spaceAfter=2 * mm,
            )
        )

        styles.add(
            ParagraphStyle(
                name="PlanAppTitle",
                parent=styles["Title"],
                fontSize=18,
                leading=22,
                alignment=TA_CENTER,
                spaceAfter=6 * mm,
            )
        )

        styles.add(
            ParagraphStyle(
                name="PlanAppHeading2",
                parent=styles["Heading2"],
                fontSize=13,
                leading=16,
                spaceBefore=4 * mm,
                spaceAfter=3 * mm,
            )
        )

        styles.add(
            ParagraphStyle(
                name="PlanAppHeading3",
                parent=styles["Heading3"],
                fontSize=11,
                leading=14,
                spaceBefore=3 * mm,
                spaceAfter=2 * mm,
            )
        )

        # --------------------------------------------------------------------
        # DOCUMENTO
        # --------------------------------------------------------------------

        doc = SimpleDocTemplate(
            str(pdf_path),
            pagesize=A4,
            rightMargin=18 * mm,
            leftMargin=18 * mm,
            topMargin=18 * mm,
            bottomMargin=18 * mm,
            title="Relatório Técnico — PlanApp AI",
            author="PlanApp AI",
        )

        # --------------------------------------------------------------------
        # O TEXTO DO AGENTE É O CORPO PRINCIPAL DO PDF
        # --------------------------------------------------------------------

        story = self._markdown_to_pdf_story(
            report_text
        )

        # --------------------------------------------------------------------
        # MAPA
        #
        # O mapa é anexado depois da análise.
        # --------------------------------------------------------------------

        map_story = self._map_story()

        if map_story:

            story.append(
                Spacer(
                    1,
                    4 * mm,
                )
            )

            story.extend(
                map_story
            )

        # --------------------------------------------------------------------
        # VISUALIZAÇÕES
        # --------------------------------------------------------------------

        if self.visualization_images:

            story.append(
                Paragraph(
                    "Visualizações da avaliação",
                    styles["PlanAppHeading2"],
                )
            )

            story.append(
                Spacer(
                    1,
                    2 * mm,
                )
            )

            visualization_story = (
                self._visualization_story()
            )

            story.extend(
                visualization_story
            )

        # --------------------------------------------------------------------
        # GERAÇÃO
        # --------------------------------------------------------------------

        doc.build(
            story
        )

        return str(
            pdf_path
        )


# ============================================================================
# FUNÇÕES DE CONVENIÊNCIA
# ============================================================================

def generate_report(
    requested_params: Optional[
        Dict[str, Any]
    ] = None,
    effective_params: Optional[
        Dict[str, Any]
    ] = None,
    technical_result: Any = None,
    geocoded_points: Optional[
        List[Dict[str, Any]]
    ] = None,
    map_image: Optional[Any] = None,
    visualization_images: Optional[
        List[Dict[str, Any]]
    ] = None,
    user_request: Optional[str] = None,
    include_raw_result: bool = False,

    # NOVO
    analysis_text: Optional[str] = None,
) -> str:

    generator = ReportGenerator(
        requested_params=requested_params,
        effective_params=effective_params,
        technical_result=technical_result,
        geocoded_points=geocoded_points,
        map_image=map_image,
        visualization_images=visualization_images,
        user_request=user_request,
        analysis_text=analysis_text,
    )

    return generator.generate_report(
        include_raw_result=include_raw_result
    )


def generate_report_pdf(
    requested_params: Optional[
        Dict[str, Any]
    ] = None,
    effective_params: Optional[
        Dict[str, Any]
    ] = None,
    technical_result: Any = None,
    geocoded_points: Optional[
        List[Dict[str, Any]
    ]] = None,
    map_image: Optional[Any] = None,
    visualization_images: Optional[
        List[Dict[str, Any]
    ]] = None,
    user_request: Optional[str] = None,
    include_raw_result: bool = False,

    # NOVO
    analysis_text: Optional[str] = None,
) -> str:

    generator = ReportGenerator(
        requested_params=requested_params,
        effective_params=effective_params,
        technical_result=technical_result,
        geocoded_points=geocoded_points,
        map_image=map_image,
        visualization_images=visualization_images,
        user_request=user_request,
        analysis_text=analysis_text,
    )

    report = generator.generate_report(
        include_raw_result=include_raw_result
    )

    return generator.generate_pdf(
        report_text=report,
        include_raw_result=include_raw_result,
    )