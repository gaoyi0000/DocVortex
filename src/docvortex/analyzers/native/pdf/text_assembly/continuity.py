"""共享参考条目和重叠段落的成员证据，避免最后按外框盲目拼接文本。"""

from __future__ import annotations

import re
import statistics

from ..geometry import _bbox_axis_overlap_ratio, _bbox_center_y, _rotate_bbox_to_upright
from ..line_layout import _line_effective_height
from ..layout_evidence import build_layout_evidence
from ..text_roles import text_role, metadata_field
from ..models import _LineItem, _PreparedPage
from .common import _merge_internal_text_block_group, _merge_text_line_content


def mark_document_reference_regions(pages: list[_PreparedPage]) -> None:
    """沿实际栏序处理参考文献开始及章节结束事件，同页附录不丢弃此前的有效条目。"""
    active = False
    for page in pages:
        _width, height = page.page_size
        lines = page.remaining_lines
        headings = {
            line.source_index
            for line in lines
            if re.fullmatch(r"(?:references|bibliography|参考文献)\s*[:：]?", line.text.strip(), re.IGNORECASE)
        }
        if not active and not headings:
            continue
        layout = build_layout_evidence(lines, page.page_size, barriers=[block["bbox"] for block in page.fixed_blocks])
        corridors = sorted(set(layout.corridor((lane.left, 0, lane.right, 1)) for lane in layout.lanes))
        for left, right in corridors:
            top = 0.055 * height if active else None
            members = sorted(
                [line for line in lines if left <= (line.bbox[0] + line.bbox[2]) / 2 < right], key=lambda line: line.bbox[1]
            )
            for line in members:
                if line.source_index in headings:
                    if top is not None and line.bbox[1] > top:
                        page.reference_regions.append((left, top, right, line.bbox[1]))
                    top, active = line.bbox[3], True
                elif active and (
                    re.match(r"^\s*(?:appendix\b|附录)", line.text, re.IGNORECASE)
                    or line.semantic_type == "paragraph_title"
                    and (line.structural_title or line.explicit_section_title)
                ):
                    if top is not None and line.bbox[1] > top:
                        page.reference_regions.append((left, top, right, line.bbox[1]))
                    top, active = None, False
            if top is not None and top < 0.94 * height:
                page.reference_regions.append((left, top, right, 0.94 * height))


def group_reference_lines(lines: list[_LineItem], page: _PreparedPage) -> None:
    """按稳定首行左缘与悬挂续行分组，允许连续单行条目和断词链接。"""
    group = 0
    for region in page.reference_regions:
        members = [
            line
            for line in lines
            if line.angle == 0
            and region[0] <= (line.bbox[0] + line.bbox[2]) / 2 < region[2]
            and region[1] <= _bbox_center_y(line.bbox) <= region[3]
            and line.semantic_type not in {"page_number", "page_footnote", "doc_title", "header", "footer"}
        ]
        if len(members) < 3:
            continue
        em = statistics.median(_line_effective_height(line, line.bbox) for line in members)
        left = min(line.bbox[0] for line in members)
        members.sort(key=lambda line: (_bbox_center_y(line.bbox), line.bbox[0]))
        biography_tops = [
            line.bbox[1]
            for line in members
            if re.search(r"[(（]\s*\d{4}\s*[—–-]", line.text)
            and re.search(r"研究|博士|本科|教授|research|born", line.text, re.IGNORECASE)
        ]
        biography_tops.extend(
            line.bbox[1]
            for line in members
            if re.match(
                r"^(?:publisher[’']s\s+note|author\s+(?:information|contributions)|competing\s+interests)\b",
                line.text.strip(),
                re.IGNORECASE,
            )
        )
        if biography_tops:
            members = [line for line in members if line.bbox[1] < min(biography_tops)]
        # 没有重复首行和续行缩进就不推断条目，以免普通附注变成逐行段落。
        if sum(abs(line.bbox[0] - left) <= 0.5 * em for line in members) < 1:
            continue
        if sum(0.5 * em < line.bbox[0] - left < 4 * em for line in members) < 2:
            continue
        rows: list[list[_LineItem]] = []
        for line in members:
            if (
                rows
                and abs(_bbox_center_y(line.bbox) - statistics.median(_bbox_center_y(item.bbox) for item in rows[-1]))
                < 0.6 * em
            ):
                rows[-1].append(line)
            else:
                rows.append([line])
        for index, row in enumerate(rows):
            row.sort(key=lambda line: line.bbox[0])
            starts = row[0].bbox[0] - left <= 0.5 * em or re.match(r"^(?:\[\d+\]|\d{1,3}[.])\s", row[0].text)
            if index == 0 or starts:
                group += 1
            for line in row:
                line.paragraph_group = group
                line.semantic_type = None
                line.title_suppressed = True


def _reassemble_member_lines(members: list[_LineItem], previous_content: str = "") -> str:
    """按实际行和水平顺序重建合并内容，嵌在段落中间的短 run 不会被追加到段尾。"""
    unique = {line.source_index: line for line in members}
    ordered = sorted(unique.values(), key=lambda line: (_bbox_center_y(line.ink_bbox or line.bbox), line.bbox[0]))
    rows: list[list[_LineItem]] = []
    for line in ordered:
        bbox = line.ink_bbox or line.bbox
        if rows:
            row = rows[-1]
            center = statistics.median(_bbox_center_y(item.ink_bbox or item.bbox) for item in row)
            em = max(
                _line_effective_height(line, bbox), statistics.median(_line_effective_height(item, item.bbox) for item in row)
            )
            if abs(_bbox_center_y(bbox) - center) <= 0.55 * em:
                row.append(line)
                continue
        rows.append([line])
    contents = []
    for row in rows:
        ordered_row = sorted(row, key=lambda item: item.bbox[0])
        content = ordered_row[0].text
        for previous, line in zip(ordered_row, ordered_row[1:]):
            if re.match(r"^\[\d+\]", line.text) and previous.text[-1:].isalnum() and previous.bbox[2] >= line.bbox[0]:
                content += line.text
            else:
                content = _merge_text_line_content([content, line.text])
        contents.append(content)
    rebuilt = _merge_text_line_content(contents)
    # 仅当成员次序需要修复时重建文字，已完成的空格与断词恢复不能被原始 run 覆盖。
    if previous_content and re.sub(r"\s+", "", previous_content) == re.sub(r"\s+", "", rebuilt):
        return previous_content
    return rebuilt


def group_front_matter_lines(lines: list[_LineItem], page_size: tuple) -> None:
    """以首页摘要之前连续的机构编号组织作者附属信息，邮箱不另立小标题。"""
    abstracts = [line for line in lines if text_role(line.text) == "abstract"]
    if not abstracts:
        return
    end = min(line.bbox[1] for line in abstracts)
    candidates = [line for line in lines if 0.12 * page_size[1] <= line.bbox[1] < end and line.angle == 0]
    markers = [(line, re.match(r"^\s*(\d{1,2})\s+\D", line.text)) for line in candidates]
    markers = [(line, int(match.group(1))) for line, match in markers if match is not None]
    if not markers:
        return
    # 单个机构也可成立，但须有机构或联系方式证据，避免把首页普通编号列表当作者单位。
    if not any(
        re.search(
            r"university|institute|department|laboratory|centre|center|大学|学院|研究所|实验室|医院", line.text, re.IGNORECASE
        )
        or metadata_field(line.text) == "contact"
        for line in candidates
    ):
        return
    first_y = min(line.bbox[1] for line, _ in markers)
    marker_left = statistics.median(line.bbox[0] for line, _ in markers)
    marker_by_source = {line.source_index: number for line, number in markers}
    for line in candidates:
        if re.fullmatch(r"\d{1,2}", line.text.strip()) and abs(line.bbox[0] - marker_left) < line.effective_height:
            marker_by_source[line.source_index] = int(line.text.strip())
    group = None
    previous = None
    for line in sorted(candidates, key=lambda line: (_bbox_center_y(line.ink_bbox or line.bbox), line.bbox[0])):
        if line.bbox[1] < first_y:
            continue
        if line.source_index in marker_by_source:
            group = -marker_by_source[line.source_index]
        elif previous is not None and line.bbox[1] - previous.bbox[3] > 1.5 * max(
            line.effective_height, previous.effective_height
        ):
            group = None
        if re.match(r"^(?:received|accepted|date|draft)\b", line.text, re.IGNORECASE):
            group = None
        if group is not None:
            line.paragraph_group = group
            line.semantic_type = None
        previous = line


def merge_overlapping_member_blocks(blocks: list[dict], page_size: tuple) -> list[dict]:
    """以同栏实际行的重叠关系回收段内小块，不能仅因外接矩形相交就跨栏合并。"""
    output = list(blocks)
    layouts = {
        angle: build_layout_evidence(
            [line for block in blocks for line in block.get("_text_lines", [])], page_size, angle=angle
        )
        for angle in {line.angle for block in blocks for line in block.get("_text_lines", [])}
    }
    groups: dict[int, list[int]] = {}
    for index, block in enumerate(output):
        if block.get("_reference_group") is not None:
            groups.setdefault(block["_reference_group"], []).append(index)
    consumed = set()
    for indices in groups.values():
        merged = _merge_internal_text_block_group(output, indices)
        merged["content"] = _reassemble_member_lines(merged["_text_lines"], merged["content"])
        output[indices[0]] = merged
        consumed.update(indices[1:])
    output = [block for index, block in enumerate(output) if index not in consumed]
    while True:
        match = None
        for i, first in enumerate(output):
            if first.get("type") != "text" or not first.get("_text_lines"):
                continue
            for j in range(i + 1, len(output)):
                second = output[j]
                if second.get("type") != "text" or not second.get("_text_lines"):
                    continue
                fb, sb = first["bbox"], second["bbox"]
                later = second if sb[1] >= fb[1] else first
                if later.get("_geometry_break_before"):
                    continue
                if later.get("_explicit_break_before") or later.get("_rule_break_before"):
                    if not (first.get("_visual_row_ids", set()) & second.get("_visual_row_ids", set())):
                        continue
                first_text = str(first.get("content", "")).rstrip()
                continuation = (
                    first_text.endswith("-")
                    and str(second.get("content", ""))[:1].islower()
                    or re.match(r"^[•●▪]", first_text)
                    and first_text.endswith((":", "："))
                )
                em = statistics.median(_line_effective_height(line, line.bbox) for line in first["_text_lines"])
                adjacent = continuation and 0 <= sb[1] - fb[3] <= 1.5 * em
                numbered_continuation = (
                    re.match(r"^\d{1,2}[.]\s", first_text) is not None
                    and 0.5 * em <= sb[0] - fb[0] <= 4 * em
                    and 0 <= sb[1] - fb[3] <= em
                    and second.get("_protected_hard_break_before") is not True
                )
                adjacent = adjacent or numbered_continuation
                math_continuation = (
                    (
                        first.get("_inline_math_regions")
                        or first.get("_paragraph_formula_context")
                        or any(line.paragraph_formula_context for line in first["_text_lines"])
                    )
                    and str(second.get("content", ""))[:1].islower()
                    and not re.search(r"[.!?。！？]$", first_text)
                    and abs(fb[0] - sb[0]) <= em
                    and -em <= sb[1] - fb[3] <= em
                    and second.get("_protected_hard_break_before") is not True
                )
                adjacent = adjacent or bool(math_continuation)
                if not adjacent and min(fb[3], sb[3]) <= max(fb[1], sb[1]) or _bbox_axis_overlap_ratio(fb, sb, axis="x") < 0.75:
                    continue
                if first.get("_reference_group") != second.get("_reference_group"):
                    continue
                if not adjacent and first.get("_hanging_indent_group") != second.get("_hanging_indent_group"):
                    continue
                connected = adjacent
                for a in [] if connected else first["_text_lines"]:
                    for b in second["_text_lines"]:
                        if a.angle != b.angle:
                            continue
                        ab, bb = a.ink_bbox or a.bbox, b.ink_bbox or b.bbox
                        em = max(_line_effective_height(a, ab), _line_effective_height(b, bb))
                        # 两条完整文字行横向分离时是相邻栏，外接矩形重叠不能让它们互相认领。
                        # 小型上下标、公式碎片仍可依靠邻接归入宿主正文。
                        across_columns = layouts[a.angle].separated(
                            _rotate_bbox_to_upright(ab, page_size, a.angle),
                            _rotate_bbox_to_upright(bb, page_size, b.angle),
                        )
                        if across_columns and max(ab[0] - bb[2], bb[0] - ab[2]) > 0.5 * em:
                            continue
                        if (
                            _bbox_axis_overlap_ratio(ab, bb, axis="y") >= 0.25
                            and max(0.0, ab[0] - bb[2], bb[0] - ab[2]) <= 5 * em
                        ):
                            connected = True
                            break
                    if connected:
                        break
                if connected:
                    match = (i, j)
                    break
            if match:
                break
        if match is None:
            return output
        i, j = match
        merged = _merge_internal_text_block_group(output, [i, j])
        widths = [output[index]["bbox"][2] - output[index]["bbox"][0] for index in (i, j)]
        heights = [_line_effective_height(line, line.bbox) for index in (i, j) for line in output[index]["_text_lines"]]
        if min(widths) < 0.4 * max(widths) and min(heights) < 0.85 * max(heights):
            merged["_paragraph_formula_context"] = True
        merged["content"] = _reassemble_member_lines(merged["_text_lines"], merged["content"])
        output[i] = merged
        output.pop(j)
