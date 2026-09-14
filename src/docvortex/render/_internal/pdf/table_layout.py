"""原始版式结构表格的区域适配、旋转及安全空白分配。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from math import isfinite
from statistics import median
from typing import Callable

from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Flowable, Table

from ....schema import PAGE_AUXILIARY_BLOCK_TYPES
from .diagnostics import report_pdf_diagnostic
from .font_plan import BlockFit, PreparedBlock
from .formula_layout import _body_candidates, _safe_area, _same_column
from .table import PdfTableError

Rect = tuple[float, float, float, float]


@dataclass(frozen=True)
class _TableMeasurement:
    """持有一次试排独占的实际表格与标量，不复制已经完成测量的行布局。"""

    tables: list[Table]
    heights: list[float]
    font_size: float
    scale: float
    width_ratio: float


class SpatialTableContent(Flowable):
    """保存结构表格的构造回调，所有试排均从目标逻辑宽度重新物化。"""

    def __init__(
        self,
        build: Callable[[float, float], list[Table]],
        fallback: Callable[[float, float, str], Flowable],
        validate: Callable[[Flowable], None],
        *,
        angle: int,
        location: str,
        page_idx: int,
    ) -> None:
        """绑定本表上下文和已物化素材来源，不读取源 PDF 或修改语义树。"""
        super().__init__()
        self.build = build
        self.fallback = fallback
        self.validate = validate
        self.angle = angle
        self.location = location
        self.page_idx = page_idx
        self.font_size = 8.5
        self.scale = 1.0
        self.width_ratio = 1.0
        self.tables: list[Table] = []
        self.heights: list[float] = []
        self.failure: str | None = None
        self.fallback_flow: Flowable | None = None
        self.width = self.height = 0.0

    def fork(self) -> SpatialTableContent:
        """为另一候选区域创建独立布局状态，只复用只读内容构造回调。"""
        candidate = SpatialTableContent(
            self.build, self.fallback, self.validate, angle=self.angle, location=self.location, page_idx=self.page_idx
        )
        # 已确认的结构或绘制错误继续沿用既有按块回退契约。
        candidate.failure = self.failure
        return candidate

    def _snapshot(self) -> _TableMeasurement:
        """保留当前成功测量结果，后续试排会重新构造自己的 Table。"""
        return _TableMeasurement(self.tables, self.heights, self.font_size, self.scale, self.width_ratio)

    def _restore(self, measurement: _TableMeasurement) -> float:
        """直接恢复最佳候选，保持原数值计算顺序而不再次构造或测量。"""
        self.tables, self.heights = measurement.tables, measurement.heights
        self.font_size, self.scale, self.width_ratio = measurement.font_size, measurement.scale, measurement.width_ratio
        return (sum(self.heights) + 2 * (len(self.heights) - 1)) * self.scale

    @property
    def effective_font_size(self) -> float:
        """返回当前区域内经过最终缩放后的表格基准字号。"""
        return self.font_size * self.scale

    def _measure(self, width: float, font_size: float, scale: float = 1.0) -> float:
        """重新计算列宽和行高；即使低于 6 pt，缩放后的表宽也仍覆盖目标宽度。"""
        self.tables = self.build(width / scale, font_size)
        if not self.tables:
            raise PdfTableError("HTML contains no materializable table")
        measurements = [table.wrap(width / scale, 1e9) for table in self.tables]
        if any(not isfinite(w + h) or w <= 0 or h <= 0 for w, h in measurements):
            raise PdfTableError("Invalid structured table dimensions")
        self.width_ratio = max(w * scale / width for w, _ in measurements)
        self.heights = [height for _, height in measurements]
        self.font_size, self.scale = font_size, scale
        return (sum(self.heights) + 2 * (len(self.heights) - 1)) * scale

    def fit(self, width: float, height: float) -> None:
        """先寻找最大可用字号，再在 6 pt 基础上缩放；排版或绘制失败才回退素材。"""
        width, height = max(0.001, width), max(0.001, height)
        if self.failure is not None:
            self._fit_fallback(width, height)
            return
        logical_width, logical_height = (height, width) if self.angle in (90, 270) else (width, height)
        try:
            # 候选只有 26 档，逐档测量可避免列宽重分配导致高度非单调时漏掉最大字号。
            for size in range(85, 59, -1):
                content_height = self._measure(logical_width, size / 10)
                if content_height <= logical_height + 0.001 and self.width_ratio <= 1 + 1e-8:
                    break
            else:
                high, low = 1.0, min(0.5, logical_height / content_height, 1 / self.width_ratio)
                while self._measure(logical_width, 6.0, low) > logical_height or self.width_ratio > 1 + 1e-8:
                    low /= 2
                best = self._snapshot()
                for _ in range(18):
                    candidate = (low + high) / 2
                    if self._measure(logical_width, 6.0, candidate) <= logical_height and self.width_ratio <= 1 + 1e-8:
                        low = candidate
                        best = self._snapshot()
                    else:
                        high = candidate
                content_height = self._restore(best)
            self.width, self.height = (
                (content_height, logical_width) if self.angle in (90, 270) else (logical_width, content_height)
            )
            self.validate(self)
        except Exception as exc:
            self.failure = f"{type(exc).__name__}: {str(exc)[:200]}"
            self._fit_fallback(width, height)

    def _fit_fallback(self, width: float, height: float) -> None:
        """使用调用方提供的按块兜底，并将文字兜底完整适配进区域。"""
        self.fallback_flow = self.fallback(width, height, self.failure or "unavailable HTML")
        measured_width, measured_height = self.fallback_flow.wrap(width, 1e9)
        self.scale = min(1.0, width / max(measured_width, 0.001), height / max(measured_height, 0.001))
        self.width, self.height = measured_width * self.scale, measured_height * self.scale

    def wrap(self, availWidth: float, availHeight: float) -> tuple[float, float]:
        """返回最后一次区域适配结果，不在绘制阶段重复试排。"""
        return self.width, self.height

    def draw(self) -> None:
        """恢复源方向后绘制原生表格，图片兜底已经包含方向变换。"""
        self.canv.saveState()
        try:
            if self.fallback_flow is not None:
                self.canv.scale(self.scale, self.scale)
                self.fallback_flow.drawOn(self.canv, 0, 0)
                return
            if self.angle == 90:
                self.canv.translate(0, self.height)
                self.canv.rotate(-90)
            elif self.angle == 270:
                self.canv.translate(self.width, 0)
                self.canv.rotate(90)
            elif self.angle == 180:
                self.canv.translate(self.width, self.height)
                self.canv.rotate(180)
            self.canv.scale(self.scale, self.scale)
            cursor = sum(self.heights) + 2 * (len(self.heights) - 1)
            for table, height in zip(self.tables, self.heights):
                cursor -= height
                table.drawOn(self.canv, 0, cursor)
                cursor -= 2
        finally:
            self.canv.restoreState()


def has_spatial_table(item: PreparedBlock) -> bool:
    """识别独立表格及缺子框时包含表格的父框组合。"""
    return any(isinstance(flow, SpatialTableContent) for flow in item.flowables)


def _fit_group(item: PreparedBlock, area: Rect, canvas: Canvas) -> BlockFit:
    """为表题表注预留空间；父框极小时同步缩放组合并重新按补偿宽度测量。"""
    # 候选持有独立的段落、图片和表格状态，原框胜出时无需撤销另一区域的试排。
    item.flowables = [flow.fork() if isinstance(flow, SpatialTableContent) else deepcopy(flow) for flow in item.flowables]
    width, height = area[2] - area[0], area[3] - area[1]
    scale = 1.0
    for _ in range(80):
        measured: list[tuple[Flowable, float, float, float]] = []
        fixed_height = previous_after = 0.0
        for index, flow in enumerate(item.flowables):
            gap = max(previous_after, flow.getSpaceBefore()) if index else 0.0
            w, h = (0.0, 0.0) if isinstance(flow, SpatialTableContent) else flow.wrapOn(canvas, width / scale, 1e9)
            measured.append((flow, w, h, gap))
            fixed_height += h + gap
            previous_after = flow.getSpaceAfter()
        if fixed_height * scale < height * 0.75:
            break
        scale *= 0.8
    tables = [flow for flow in item.flowables if isinstance(flow, SpatialTableContent)]
    allocation = max(0.001, height / scale - fixed_height) / len(tables)
    measurements = []
    for flow, w, h, gap in measured:
        if isinstance(flow, SpatialTableContent):
            flow.fit(width / scale, allocation)
            w, h = flow.width, flow.height
        measurements.append((flow, w, h, gap))
    return BlockFit(
        scale,
        max(w for _, w, _, _ in measurements) * scale,
        sum(h + gap for _, _, h, gap in measurements) * scale,
        measurements,
    )


def _quality(item: PreparedBlock, fit: BlockFit) -> float:
    """以组合内最小表格字号比较候选区域，失败回退不参与可读字号竞争。"""
    return min(
        flow.effective_font_size * fit.scale if flow.failure is None else 8.5
        for flow in item.flowables
        if isinstance(flow, SpatialTableContent)
    )


def place_tables(blocks: list[PreparedBlock], page_width: float, canvas: Canvas) -> None:
    """在正文、标题和公式冻结后安排表格，优先原框，必要时才借用同栏安全空白。"""
    bodies = _body_candidates(blocks)
    content_rects = [item.original_rect for item in blocks if item.block.type not in PAGE_AUXILIARY_BLOCK_TYPES]
    content_top = min((rect[1] for rect in content_rects), default=0.0)
    content_bottom = max((rect[3] for rect in content_rects), default=0.0)
    for item in blocks:
        if not has_spatial_table(item):
            continue
        original = item.original_rect
        best_area = original
        best_fit = _fit_group(item, original, canvas)
        best_quality = _quality(item, best_fit)
        if best_quality < 8.5 - 0.001:
            column = [body for body in bodies if _same_column(item, body)]
            left = min(original[0], median(body.original_rect[0] for body in column)) if column else original[0]
            right = max(original[2], median(body.original_rect[2] for body in column)) if column else original[2]
            safe = _safe_area(item, blocks, max(0.0, left), min(page_width, right))
            if safe is not None:
                # 安全空白不包括原页面外边距，尤其避免旋转表格把整列拉到纸张边缘。
                safe = (safe[0], max(safe[1], content_top), safe[2], min(safe[3], content_bottom))
                if safe[3] <= safe[1]:
                    safe = None
            if safe is not None and safe != original:
                trial = _fit_group(item, safe, canvas)
                if _quality(item, trial) > best_quality + 0.001:
                    best_area = safe
                    best_fit = trial
            elif safe is None:
                report_pdf_diagnostic("pdf_table_clearance_unavailable", f"Original box retained: {original}", item.page_idx)
            item.flowables = [flow for flow, _, _, _ in best_fit.measurements]
        top = min(max(original[1], best_area[1]), best_area[3] - best_fit.height)
        item.draw_rect = (best_area[0], top, best_area[0] + best_fit.width, top + best_fit.height)
        item.fit = best_fit
        for flow in item.flowables:
            if not isinstance(flow, SpatialTableContent):
                continue
            size = flow.effective_font_size * best_fit.scale
            source = "html" if flow.failure is None else "fallback"
            report_pdf_diagnostic(
                "pdf_table_layout",
                f"source={source}, angle={flow.angle}, font_size={size:.4f}, "
                f"original_bbox_pt={original}, draw_bbox_pt={item.draw_rect}; {flow.location}",
                item.page_idx,
            )
            if flow.failure is None and size < 6 - 0.001:
                report_pdf_diagnostic(
                    "pdf_layout_small_text", f"Structured table retained below 6 pt: {size:.4f}; {flow.location}", item.page_idx
                )
