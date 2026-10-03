from __future__ import annotations

import re
from dataclasses import dataclass
from statistics import median
from time import perf_counter

from app.models import LedgerMetrics, SourceBlock, SourceLedger, SourceUnit
from app.services.ledger_ids import derived_id
from app.services.extraction.language_scores import EXAM_NAME, EXAM_SUFFIX, SCORE


@dataclass
class _ExamCell:
    units: list[SourceUnit]

    @property
    def primary(self) -> SourceUnit:
        return self.units[0]

    @property
    def center(self) -> tuple[float, float]:
        box = self.primary.box
        return box.x + box.width / 2, box.y + box.height / 2


@dataclass
class _ExamPair:
    header: _ExamCell
    suffixes: list[_ExamCell]
    score: _ExamCell
    orientation: str

    @property
    def label(self) -> str:
        return " ".join(
            cell.primary.source_text.strip() for cell in [self.header, *self.suffixes]
        )

    @property
    def source_ids(self) -> set[str]:
        return {
            unit.id
            for cell in [self.header, *self.suffixes, self.score]
            for unit in cell.units
        }


def _same_cell(left: SourceUnit, right: SourceUnit) -> bool:
    if (
        re.sub(r"\s+", "", left.source_text).casefold()
        != re.sub(r"\s+", "", right.source_text).casefold()
    ):
        return False
    a, b = left.box, right.box
    width = max(0, min(a.x + a.width, b.x + b.width) - max(a.x, b.x))
    height = max(0, min(a.y + a.height, b.y + b.height) - max(a.y, b.y))
    intersection = width * height
    union = a.width * a.height + b.width * b.height - intersection
    return union > 0 and intersection / union >= 0.6


def _exam_cells(units: list[SourceUnit]) -> list[_ExamCell]:
    cells: list[_ExamCell] = []
    for unit in units:
        cell = next((cell for cell in cells if _same_cell(unit, cell.primary)), None)
        if cell:
            cell.units.append(unit)
        else:
            cells.append(_ExamCell([unit]))
    return cells


def _attached_suffixes(header: _ExamCell, suffixes: list[_ExamCell]) -> list[_ExamCell]:
    return sorted(
        [
            cell
            for cell in suffixes
            if abs(cell.center[0] - header.center[0]) <= 0.025
            and 0 < cell.center[1] - header.center[1] <= 0.05
        ],
        key=lambda cell: cell.center[1],
    )


def _exam_tables(units: list[SourceUnit]) -> tuple[list[list[_ExamPair]], set[str]]:
    """Associate score cells from unique geometry, retaining every observation."""
    # Only compact exam-like cells participate in geometry comparisons; prose
    # remains untouched and does not make this pass quadratic in page length.
    candidates = [
        unit
        for unit in units
        if EXAM_NAME.fullmatch(unit.source_text.strip())
        or EXAM_SUFFIX.fullmatch(unit.source_text.strip())
        or SCORE.fullmatch(unit.source_text.strip())
        or re.fullmatch(r"[A-Za-z0-9() -]{2,20}", unit.source_text.strip())
    ]
    cells = _exam_cells(candidates)
    headers = [
        cell for cell in cells if EXAM_NAME.fullmatch(cell.primary.source_text.strip())
    ]
    scores = [
        cell for cell in cells if SCORE.fullmatch(cell.primary.source_text.strip())
    ]
    suffixes = [
        cell
        for cell in cells
        if EXAM_SUFFIX.fullmatch(cell.primary.source_text.strip())
    ]
    pairs: list[_ExamPair] = []
    ambiguous: set[str] = set()
    for score in scores:
        score_x, score_y = score.center
        candidates: list[tuple[_ExamCell, str]] = []
        for header in headers:
            header_x, header_y = header.center
            attached = _attached_suffixes(header, suffixes)
            row_aligned = (
                abs(header_y - score_y)
                <= max(header.primary.box.height, score.primary.box.height) / 2
            )
            if attached:
                bottom = max(
                    cell.primary.box.y + cell.primary.box.height for cell in attached
                )
                row_aligned |= header.primary.box.y <= score_y <= bottom
            if abs(header_x - score_x) <= 0.025 and 0 < score_y - header_y <= 0.06:
                candidates.append((header, "columns"))
            elif row_aligned and 0 < score_x - header_x <= 0.6:
                # An intervening label belongs to the nearer printed cell.
                if not any(
                    header_x < other.center[0] < score_x
                    and abs(other.center[1] - score_y)
                    <= max(other.primary.box.height, score.primary.box.height) / 2
                    for other in headers
                ):
                    candidates.append((header, "rows"))
        if len(candidates) != 1:
            if candidates:
                ambiguous.update(unit.id for unit in score.units)
                ambiguous.update(
                    unit.id for header, _ in candidates for unit in header.units
                )
            continue
        header, orientation = candidates[0]
        wrapped = [
            cell
            for cell in _attached_suffixes(header, suffixes)
            if orientation == "rows" or cell.center[1] < score_y
        ]
        base = header.primary.source_text.strip().casefold()
        unknown_suffixes = [
            cell
            for cell in cells
            if cell not in wrapped
            and cell is not header
            and cell is not score
            and orientation == "columns"
            and abs(cell.center[0] - score_x) <= 0.025
            and header.center[1] < cell.center[1] < score_y
            and re.fullmatch(r"[A-Za-z0-9() -]{2,20}", cell.primary.source_text.strip())
            and re.search(r"[A-Za-z]", cell.primary.source_text)
        ]
        if unknown_suffixes:
            ambiguous.update(
                unit.id
                for cell in [header, *unknown_suffixes, score]
                for unit in cell.units
            )
            continue
        if any(
            (
                cell.primary.source_text.strip().casefold() == "speaking"
                and base != "toeic"
            )
            or ("ibt" in cell.primary.source_text.casefold() and base != "toefl")
            for cell in wrapped
        ):
            ambiguous.update(
                unit.id for cell in [header, *wrapped, score] for unit in cell.units
            )
            continue
        pairs.append(_ExamPair(header, wrapped, score, orientation))
    # Distinct score candidates for one physical header are evidence of
    # ambiguity, even when each candidate independently aligns with it.
    for pair in pairs:
        if sum(other.header is pair.header for other in pairs) > 1:
            ambiguous.update(pair.source_ids)
    pairs = [pair for pair in pairs if not pair.source_ids & ambiguous]
    return _group_exam_pairs(pairs, ambiguous), ambiguous


def _group_exam_pairs(
    pairs: list[_ExamPair], ambiguous: set[str]
) -> list[list[_ExamPair]]:
    """Group consistently oriented pairs and reject conflicting exam labels."""
    groups: list[list[_ExamPair]] = []
    for pair in sorted(
        pairs, key=lambda item: (item.header.center[1], item.header.center[0])
    ):
        group = next(
            (
                group
                for group in groups
                if group[0].orientation == pair.orientation
                and (
                    (
                        pair.orientation == "columns"
                        and abs(group[0].header.center[1] - pair.header.center[1])
                        <= 0.025
                    )
                    or (
                        pair.orientation == "rows"
                        and abs(group[0].header.center[0] - pair.header.center[0])
                        <= 0.025
                        and abs(group[0].score.center[0] - pair.score.center[0])
                        <= 0.035
                    )
                )
            ),
            None,
        )
        if group is None:
            groups.append([pair])
        else:
            group.append(pair)
    accepted: list[list[_ExamPair]] = []
    for group in groups:
        labels: dict[str, list[_ExamPair]] = {}
        for pair in group:
            labels.setdefault(re.sub(r"[\s()]", "", pair.label).casefold(), []).append(
                pair
            )
        for repeated in labels.values():
            values = {
                SCORE.fullmatch(pair.score.primary.source_text.strip())[1].casefold()
                for pair in repeated
            }
            if len(values) > 1 and group[0].orientation == "columns":
                ambiguous.update(
                    unit_id for pair in repeated for unit_id in pair.source_ids
                )
        group = [pair for pair in group if not pair.source_ids & ambiguous]
        if len(group) >= 2:
            accepted.append(group)
    return accepted


def _append_table_cell(
    blocks: list[SourceBlock],
    units: list[SourceUnit],
    table_id: str,
    row: int,
    column: int,
) -> None:
    for unit in units:
        unit.table_id, unit.table_row, unit.table_column = table_id, row, column
        unit.section_id = table_id
    blocks.append(
        SourceBlock(
            id=derived_id("block", units[0].id),
            unit_ids=[unit.id for unit in units],
            kind="table_cell",
            section_id=table_id,
            source_text="\n".join(unit.source_text for unit in units),
            table_id=table_id,
            table_row=row,
            table_column=column,
        )
    )


def _rows(units: list[SourceUnit]) -> list[list[SourceUnit]]:
    rows: list[list[SourceUnit]] = []
    for unit in sorted(
        units, key=lambda item: (item.box.y + item.box.height / 2, item.box.x)
    ):
        center = unit.box.y + unit.box.height / 2
        previous = rows[-1] if rows else []
        if (
            previous
            and abs(
                center - median(item.box.y + item.box.height / 2 for item in previous)
            )
            <= max(unit.box.height, median(item.box.height for item in previous)) * 0.55
        ):
            previous.append(unit)
        else:
            rows.append([unit])
    return [sorted(row, key=lambda item: item.box.x) for row in rows]


def _short_cells(row: list[SourceUnit]) -> bool:
    return bool(row) and all(
        len(unit.source_text.strip()) <= 45 and "\n" not in unit.source_text
        for unit in row
    )


def _aligned(first: list[SourceUnit], second: list[SourceUnit]) -> bool:
    columns: dict[int, SourceUnit] = {}
    for cell in second:
        anchor = min(
            range(len(first)),
            key=lambda index: abs(
                first[index].box.x
                + first[index].box.width / 2
                - cell.box.x
                - cell.box.width / 2
            ),
        )
        header = first[anchor]
        distance = abs(
            header.box.x + header.box.width / 2 - cell.box.x - cell.box.width / 2
        )
        duplicate = (
            anchor in columns
            and re.sub(r"\s+", "", columns[anchor].source_text).casefold()
            == re.sub(r"\s+", "", cell.source_text).casefold()
        )
        if (anchor in columns and not duplicate) or distance > max(
            0.018, min(header.box.width, cell.box.width) * 0.65
        ):
            return False
        columns[anchor] = cell
    return True


def _table_groups(rows: list[list[SourceUnit]]) -> list[list[list[SourceUnit]]]:
    segments: list[list[SourceUnit]] = []
    for row in rows:
        current: list[SourceUnit] = []
        for cell in row:
            if current:
                left = current[-1]
                gap = cell.box.x - left.box.x - left.box.width
                if (
                    gap > 0.15
                    or gap > 0.075
                    and max(cell.box.width, left.box.width) > 0.25
                ):
                    segments.append(current)
                    current = []
            current.append(cell)
        if current:
            segments.append(current)
    groups: list[list[list[SourceUnit]]] = []
    consumed: set[str] = set()
    for index, row in enumerate(segments):
        if any(unit.id in consumed for unit in row):
            continue
        group = [row]
        if (
            len(group[0]) < 2
            or not _short_cells(group[0])
            or any(
                unit.confidence is not None and unit.confidence < 0.85
                for unit in group[0]
            )
        ):
            continue
        centers = [unit.box.x + unit.box.width / 2 for unit in group[0]]
        left_boundary = centers[0] - (centers[1] - centers[0]) / 2
        right_boundary = centers[-1] + (centers[-1] - centers[-2]) / 2
        for candidate in segments[index + 1 :]:
            candidate = [
                unit
                for unit in candidate
                if left_boundary <= unit.box.x + unit.box.width / 2 <= right_boundary
            ]
            if any(unit.id in consumed for unit in candidate):
                continue
            if any(
                sum(
                    unit.box.x < center < unit.box.x + unit.box.width
                    for center in centers
                )
                > 1
                for unit in candidate
            ):
                # A paragraph spanning column anchors cannot be assigned to
                # one table cell. It starts the next section instead.
                break
            if not _short_cells(candidate) or not _aligned(group[0], candidate):
                continue
            previous_bottom = max(unit.box.y + unit.box.height for unit in group[-1])
            gap = min(unit.box.y for unit in candidate) - previous_bottom
            if gap < -max(unit.box.height for unit in candidate) * 0.5:
                continue
            if gap > max(unit.box.height for unit in candidate) * 2.5:
                break
            group.append(candidate)
        # A trailing label without a value belongs to the following section,
        # rather than an extra data row in this grid.
        while (
            len(group) > 1
            and len(group[-1]) == 1
            and _aligned([group[0][0]], group[-1])
            and not re.search(r"\d", group[-1][0].source_text)
        ):
            group.pop()
        # Require both a repeated grid and literal values. Side-by-side
        # headings followed by two prose columns are not a score table.
        has_values = any(
            any(
                re.fullmatch(
                    r"(?=.*\d)[A-Za-z\d,.%+~:()/ -]+(?:원|만원|점)?(?:\s*(?:이상|이하|초과|미만))?",
                    unit.source_text.strip(),
                )
                or re.fullmatch(
                    r"[\d.()월화수목금토일년시분오전후~～–— 또는 :/-]+",
                    unit.source_text.strip(),
                )
                and re.search(r"\d", unit.source_text)
                or re.fullmatch(
                    r"(?:팀|개인)?\s*[\d,.]+\s*(?:만원|원|작품|명|인|개|점)",
                    unit.source_text.strip(),
                )
                for unit in row
            )
            for row in group
        )
        if len(group) >= 2 and has_values:
            groups.append(group)
            consumed.update(unit.id for row in group for unit in row)
    return groups


def _column_cut(rows: list[list[SourceUnit]]) -> float | None:
    candidates: list[float] = []
    for row in rows:
        for left, right in zip(row, row[1:]):
            edge = left.box.x + left.box.width
            if (
                right.box.x - edge >= 0.045
                and len(left.source_text) >= 8
                and len(right.source_text) >= 8
            ):
                candidates.append((edge + right.box.x) / 2)
    if len(candidates) < 2:
        return None
    cut = median(candidates)
    return cut if sum(abs(value - cut) < 0.08 for value in candidates) >= 2 else None


def _kind(unit: SourceUnit, typical_height: float) -> str:
    text = unit.source_text.strip()
    # Recognition confidence describes uncertainty, not whether text is a
    # heading, rule or topic. Longer uncertain clauses still enter paragraphs.
    if len(text) <= 2:
        return "caption"
    if unit.box and unit.box.height > typical_height * 1.35 and len(text) <= 70:
        return "heading"
    if re.match(r"^(?:[*※]|단[,\s]|다만|참고|주의)", text):
        return "condition"
    if re.match(r"^(?:\d+[.)]|[•●○▶-])", text):
        return "list"
    if len(text) <= 10 and not re.search(r"[\d.!?]|[은는을를]\s", text):
        return "heading"
    return "paragraph"


def build_source_ledger(
    units: list[SourceUnit], *, ocr_ms: int = 0, layout_ms: int = 0
) -> SourceLedger:
    """Partition all observations without replacing the source inventory."""
    started = perf_counter()
    ledger = SourceLedger(units=[unit.model_copy(deep=True) for unit in units])
    for unit in ledger.units:
        unit.block_id = unit.section_id = ""
        unit.table_id = unit.table_row = unit.table_column = None
        unit.english = ""
        unit.translation_provider = "pending"
        unit.translation_status = "pending"
        unit.translation_source_ids = []
        unit.semantic_refs = []
        unit.display_destinations = []
        unit.recovered_source_text = None
        unit.recovery_source = None
    blocks: list[SourceBlock] = []
    for page in sorted({unit.page_number for unit in ledger.units}):
        page_units = [unit for unit in ledger.units if unit.page_number == page]
        positioned = [unit for unit in page_units if unit.box]
        table_members: set[str] = set()
        exam_groups, ambiguous_exams = _exam_tables(positioned)
        for table_index, group in enumerate(exam_groups):
            table_id = f"page-{page}-exams-{table_index}"
            group.sort(
                key=lambda pair: pair.header.center[0]
                if pair.orientation == "columns"
                else pair.header.center[1]
            )
            for index, pair in enumerate(group):
                header_units = [
                    unit
                    for cell in [pair.header, *pair.suffixes]
                    for unit in cell.units
                ]
                header_row, header_column = (
                    (0, index) if pair.orientation == "columns" else (index, 0)
                )
                value_row, value_column = (
                    (1, index) if pair.orientation == "columns" else (index, 1)
                )
                _append_table_cell(
                    blocks, header_units, table_id, header_row, header_column
                )
                _append_table_cell(
                    blocks, pair.score.units, table_id, value_row, value_column
                )
                table_members.update(
                    unit.id for unit in [*header_units, *pair.score.units]
                )
        for unit in positioned:
            if unit.id in ambiguous_exams:
                blocks.append(
                    SourceBlock(
                        id=derived_id("block", unit.id),
                        unit_ids=[unit.id],
                        kind="caption",
                        section_id=f"page-{page}-ambiguous-exams",
                        source_text=unit.source_text,
                    )
                )
                unit.section_id = f"page-{page}-ambiguous-exams"
                ledger.coverage.protected_value_gaps.append(
                    f"{unit.id}: ambiguous English-test geometry"
                )
                table_members.add(unit.id)
        # A decoded QR occupies an image area, not a printed table cell.
        rows = _rows(
            [
                unit
                for unit in positioned
                if unit.id not in table_members
                and not any(
                    candidate.pass_name == "qr" for candidate in unit.alternatives
                )
            ]
        )
        for table_index, group in enumerate(_table_groups(rows)):
            table_id = f"page-{page}-table-{table_index}"
            for row_index, row in enumerate(group):
                for unit in row:
                    column = min(
                        range(len(group[0])),
                        key=lambda index: abs(
                            group[0][index].box.x
                            + group[0][index].box.width / 2
                            - unit.box.x
                            - unit.box.width / 2
                        ),
                    )
                    table_members.add(unit.id)
                    _append_table_cell(blocks, [unit], table_id, row_index, column)
        cut = _column_cut(
            [row for row in rows if not any(unit.id in table_members for unit in row)]
        )
        prose = [unit for unit in page_units if unit.id not in table_members]
        typical_height = (
            median(unit.box.height for unit in positioned) if positioned else 0.02
        )
        columns: dict[int, list[SourceUnit]] = {}
        for unit in prose:
            if not unit.box:
                column = 3
            elif (
                cut
                and unit.box.x < cut < unit.box.x + unit.box.width
                and min(cut - unit.box.x, unit.box.x + unit.box.width - cut) > 0.12
                and _kind(unit, typical_height) == "heading"
            ):
                column = 0  # Full-width headings precede the column bodies.
            else:
                # A long paragraph line can cross the gutter while its shorter
                # continuation ends before it. Keep both at their left origin.
                column = 2 if cut and unit.box.x >= cut else 1
            columns.setdefault(column, []).append(unit)
        for column, members in sorted(columns.items()):
            members.sort(
                key=lambda item: (
                    item.box.y if item.box else item.order,
                    item.box.x if item.box else 0,
                    item.order,
                )
            )
            section = f"page-{page}-column-{column}"
            previous: SourceBlock | None = None
            last: SourceUnit | None = None
            for unit in members:
                kind = _kind(unit, typical_height)
                gap = (
                    unit.box.y - (last.box.y + last.box.height)
                    if unit.box and last and last.box
                    else 1
                )
                aligned = bool(
                    unit.box
                    and last
                    and last.box
                    and abs(unit.box.x - last.box.x) < 0.045
                )
                # A normal-sized short phrase often completes the preceding
                # option or condition. Large or separated headings start anew.
                if (
                    kind == "heading"
                    and previous
                    and previous.kind in {"paragraph", "list", "condition"}
                    and aligned
                    and unit.box
                    and unit.box.height <= typical_height * 1.35
                    and -typical_height * 0.5 <= gap <= typical_height * 0.8
                ):
                    kind = "paragraph"
                if kind == "heading":
                    section = derived_id("section", unit.id)
                unit.section_id = section
                continuation = (
                    previous
                    and previous.section_id == section
                    and previous.kind in {"paragraph", "list", "condition"}
                    and kind == "paragraph"
                    and aligned
                    and -typical_height * 0.5 <= gap <= typical_height * 0.8
                )
                if continuation:
                    previous.unit_ids.append(unit.id)
                    previous.source_text += "\n" + unit.source_text
                else:
                    previous = SourceBlock(
                        id=derived_id("block", unit.id),
                        unit_ids=[unit.id],
                        kind=kind,
                        section_id=section,
                        source_text=unit.source_text,
                    )
                    blocks.append(previous)
                last = unit
    unit_lookup = {unit.id: unit for unit in ledger.units}
    for block in blocks:
        for unit_id in block.unit_ids:
            unit_lookup[unit_id].block_id = block.id
    # Block order follows the reconstructed columns; physical source orders
    # and IDs remain unchanged for reconciliation and provenance.
    ledger.blocks = blocks
    ledger.coverage.source_unit_ids = [unit.id for unit in ledger.units]
    ledger.metrics = LedgerMetrics(
        ocr_ms=ocr_ms, layout_ms=layout_ms + round((perf_counter() - started) * 1000)
    )
    return ledger
