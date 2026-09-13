"""在固定正文之外为标题寻找同栏安全空白，保留原始输入坐标。"""

from __future__ import annotations

from math import floor
from typing import Callable

from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import Flowable, Paragraph
from reportlab.platypus.paragraph import paraFontSizeHeightOffset

from .font_plan import BlockFit, PreparedBlock

Rect = tuple[float, float, float, float]
_GAP = 2.0
_EPS = 0.001


class TitleContent(Flowable):
    """仅为标题保留上下标与矢量公式外伸范围，避免它们越过安全绘制框。"""

    def __init__(self, paragraph: Paragraph) -> None:
        """保存已物化段落，使用实际行高但不修改正文的样式或全局 ReportLab 设置。"""
        super().__init__()
        self.paragraph = paragraph
        paragraph.autoLeading = "max"
        self.spaceBefore = paragraph.getSpaceBefore()
        self.spaceAfter = paragraph.getSpaceAfter()
        self.bottom_padding = 0.0

    def wrap(self, width: float, height: float) -> tuple[float, float]:
        """按 ReportLab 的基线规则补足字形和公式上下外伸空间，保留原有行距。"""
        paragraph = self.paragraph
        self.width, paragraph_height = paragraph.wrap(width, height)
        layout = paragraph.blPara
        leading = paragraph.style.leading
        if layout.kind == 1 and layout.lines:
            for line in layout.lines:
                for fragment in line.words:
                    if getattr(fragment, "text", ""):
                        ascent, descent = pdfmetrics.getAscentDescent(fragment.fontName, fragment.fontSize)
                        rise = getattr(fragment, "rise", 0)
                        line.ascent = max(line.ascent, ascent + rise)
                        line.descent = min(line.descent, descent + rise)
            paragraph.height = paragraph_height = sum(max(leading, line.ascent - line.descent) for line in layout.lines)
            first = layout.lines[0]
            baseline = first.fontSize if paraFontSizeHeightOffset else first.ascent
            top, bottom, previous_descent = 0.0, 0.0, 0.0
            for index, line in enumerate(layout.lines):
                if index:
                    baseline += previous_descent + max(leading * 5 / 6, line.ascent)
                top = min(top, baseline - line.ascent)
                bottom = max(bottom, baseline - line.descent)
                previous_descent = max(leading / 6, -line.descent)
        else:
            baseline = layout.fontSize if paraFontSizeHeightOffset else layout.ascent
            top = baseline - layout.ascent
            bottom = baseline + max(0, len(layout.lines) - 1) * max(leading, layout.ascent - layout.descent) - layout.descent
        top_padding = max(0, -top)
        self.bottom_padding = max(0, bottom - paragraph_height)
        self.height = paragraph_height + top_padding + self.bottom_padding
        return self.width, self.height

    def draw(self) -> None:
        """在预留的外伸空间内绘制同一个段落，不重新构建公式或锚点。"""
        self.paragraph.drawOn(self.canv, 0, self.bottom_padding)


def _overlaps(first: Rect, second: Rect, gap: float = 0.0) -> bool:
    """判断占用矩形是否相交，或是否侵入需要保留的安全间距。"""
    return (
        min(first[2], second[2]) > max(first[0], second[0]) - gap + _EPS
        and min(first[3], second[3]) > max(first[1], second[1]) - gap + _EPS
    )


def _right_limit(title: PreparedBlock, page_width: float) -> float:
    """依据匹配正文确定栏内右边界；不能判断栏宽时只保留标题原宽。"""
    right = title.original_rect[2]
    if title.reference_block is not None:
        right = max(right, title.reference_block.original_rect[2])
    return min(page_width, right)


def _safe_areas(title: PreparedBlock, others: list[PreparedBlock], page_width: float) -> list[Rect]:
    """根据原始占用范围和标题间隙中线，计算不同候选宽度的安全竖向区域。"""
    x0, y0, x1, y1 = title.original_rect
    right = _right_limit(title, page_width)
    rights = {right, x1}
    for other in others:
        boundary = other.original_rect[0] - _GAP
        if x1 <= boundary <= right:
            rights.add(boundary)
    areas = []
    for edge in sorted(rights, reverse=True):
        top, bottom = 0.0, title.page_height
        valid = edge > x0
        for other in others:
            bx0, by0, bx1, by1 = other.original_rect
            # 相邻标题按潜在扩展后的横向范围共同分配空白，避免各自试排后相互覆盖。
            if other.group is not None:
                bx1 = _right_limit(other, page_width)
            if min(edge, bx1) <= max(x0, bx0) - _GAP + _EPS:
                continue
            if by1 <= y0 + _EPS:
                bound = (by1 + y0) / 2 + _GAP / 2 if other.group is not None else by1 + _GAP
                top = max(top, bound)
            elif by0 >= y1 - _EPS:
                bound = (y1 + by0) / 2 - _GAP / 2 if other.group is not None else by0 - _GAP
                bottom = min(bottom, bound)
            else:
                valid = False
                break
        if valid and bottom > top:
            areas.append((x0, top, edge, bottom))
    return areas


def _fits(fit: BlockFit, area: Rect) -> bool:
    """完整行高和宽度都在安全区域中时才接受目标字号。"""
    return fit.width <= area[2] - area[0] + _EPS and fit.height <= area[3] - area[1] + _EPS


def _place(title: PreparedBlock, area: Rect, fit: BlockFit) -> None:
    """优先保留原顶边，必要时向上借空白，并将本次实际绘制范围保存在上下文。"""
    top = min(max(title.original_rect[1], area[1]), area[3] - fit.height)
    title.draw_rect = (area[0], top, area[2], top + fit.height)
    title.fit = fit


def place_title(
    title: PreparedBlock,
    page_blocks: list[PreparedBlock],
    page_width: float,
    measure: Callable[[PreparedBlock, float, float], BlockFit],
    fit_small: Callable[[PreparedBlock, Rect], BlockFit],
) -> None:
    """目标字号优先利用安全空白，只有当前标题放不下时才按 0.1 pt 精度缩小。"""
    original = title.original_rect
    others = [other for other in page_blocks if other is not title]
    title.geometry_conflict = any(_overlaps(original, other.original_rect) for other in others)
    desired = title.target_font_size
    fit = measure(title, desired, title.width)
    if _fits(fit, original) and not any(_overlaps(original, other.original_rect, _GAP) for other in others):
        title.fit, title.draw_rect = fit, original
        return
    # 输入已冲突时不扩大原有占用；安全间距本来不足且无可用区域时同样保守兜底。
    areas = [] if title.geometry_conflict else _safe_areas(title, others, page_width)
    if not areas:
        title.clearance_unavailable = not title.geometry_conflict
        areas = [original]
    for area in areas:
        fit = measure(title, desired, area[2] - area[0])
        if _fits(fit, area):
            _place(title, area, fit)
            return
    best = None
    for area in areas:
        low, high = 60, floor(desired * 10 + 1e-8) - 1
        if high < low or not _fits(measure(title, 6, area[2] - area[0]), area):
            continue
        while low < high:
            candidate = (low + high + 1) // 2
            if _fits(measure(title, candidate / 10, area[2] - area[0]), area):
                low = candidate
            else:
                high = candidate - 1
        if best is None or low > best[0]:
            best = (low, area)
    if best is not None:
        size, area = best
        _place(title, area, measure(title, size / 10, area[2] - area[0]))
        return
    # 连 6 pt 都放不下时沿用完整块缩放；最终重新测量所选区域，避免保留其它试排的段落状态。
    area = max(areas, key=lambda candidate: fit_small(title, candidate).scale)
    _place(title, area, fit_small(title, area))
