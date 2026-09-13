"""一次原布局导出的标题字号分组、测量计划与内部验收统计。"""

from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from math import ceil
from statistics import median
from typing import Iterator

from reportlab.platypus import Flowable

from ....schema import BlockBase


@dataclass
class BlockFit:
    """保存实际测量结果，正文测量一次后直接按相同换行与比例绘制。"""

    scale: float
    width: float
    height: float
    measurements: list[tuple[Flowable, float, float, float]]
    small_text: bool = False


@dataclass
class PreparedBlock:
    """保存只物化一次的内容对象及原框，不持有或修改输入协议的派生字段。"""

    page_idx: int
    block: BlockBase
    flowables: list[Flowable]
    x: float
    y: float
    width: float
    height: float
    group: str | None = None
    base_font_size: float | None = None
    target_font_size: float | None = None
    page_height: float = 0.0
    body_base_font_size: float | None = None
    body_font_size: float | None = None
    reference_font_size: float | None = None
    reference_block: PreparedBlock | None = None
    fit: BlockFit | None = None
    draw_rect: tuple[float, float, float, float] | None = None
    geometry_conflict: bool = False
    clearance_unavailable: bool = False

    @property
    def original_rect(self) -> tuple[float, float, float, float]:
        """返回 point 单位、左上原点的原始占用范围，不回写输入 bbox。"""
        return self.x, self.page_height - self.y - self.height, self.x + self.width, self.page_height - self.y


@dataclass
class FontGroupPlan:
    """记录组内基础字号及实际覆盖情况，供测试和本地对比工具使用。"""

    group: str
    default_font_size: float
    target_font_size: float
    block_count: int
    fitting_count: int = 0
    exception_count: int = 0
    expanded_count: int = 0
    local_increase_count: int = 0
    titles: list[dict] = field(default_factory=list)


_statistics: ContextVar[list[FontGroupPlan] | None] = ContextVar("pdf_font_statistics", default=None)


@contextmanager
def collect_font_plans() -> Iterator[list[FontGroupPlan]]:
    """隔离本次验收统计，不改变公开接口，也不让并发导出的字号计划相互污染。"""
    plans: list[FontGroupPlan] = []
    token = _statistics.set(plans)
    try:
        yield plans
    finally:
        _statistics.reset(token)


def record_font_plans(plans: list[FontGroupPlan]) -> None:
    """仅在成功绘制后向当前内部验收上下文提交统计。"""
    collected = _statistics.get()
    if collected is not None:
        collected.extend(plans)


def _ceil_font_size(size: float) -> float:
    """向上取整到 0.1 pt，保证标题不因小数截断低于正文加字号增量。"""
    return ceil(size * 10 - 1e-8) / 10


def _reference_body(title: PreparedBlock, bodies: list[PreparedBlock], order: dict[int, int]) -> PreparedBlock | None:
    """优先选择同页同栏的后续正文；没有后续正文时选择最近的同栏正文。"""
    x0, y0, x1, y1 = title.original_rect
    candidates = []
    for body in bodies:
        if body.page_idx != title.page_idx:
            continue
        bx0, by0, bx1, by1 = body.original_rect
        overlap = min(x1, bx1) - max(x0, bx0)
        # 小范围左缘差异允许首行缩进；不借用另一栏或仅擦边的段落判断栏宽。
        if bx0 - 6 <= x0 < bx1 and overlap >= 0.5 * min(x1 - x0, bx1 - bx0):
            candidates.append(body)
    following = [body for body in candidates if order[id(body)] > order[id(title)] and body.original_rect[1] >= y0]
    if following:
        return min(following, key=lambda body: (body.original_rect[1] - y0, order[id(body)]))
    return min(
        candidates,
        key=lambda body: (abs((body.original_rect[1] + body.original_rect[3]) - (y0 + y1)), order[id(body)]),
        default=None,
    )


def plan_font_sizes(blocks: list[PreparedBlock]) -> list[FontGroupPlan]:
    """从实际正文字号制定标题目标，不再根据原框容量或九成覆盖率压低整组标题。"""
    bodies = [block for block in blocks if block.body_font_size is not None]
    fallback = median(body.body_font_size for body in bodies) if bodies else 10.5
    order = {id(block): index for index, block in enumerate(blocks)}
    groups: dict[str, list[PreparedBlock]] = defaultdict(list)
    for block in blocks:
        if block.group is not None and block.base_font_size is not None:
            block.reference_block = _reference_body(block, bodies, order)
            block.reference_font_size = block.reference_block.body_font_size if block.reference_block is not None else fallback
            groups[block.group].append(block)
    plans = []
    chapter_targets = []
    for name, members in groups.items():
        if not name.startswith("paragraph_title:"):
            continue
        target = _ceil_font_size(median(member.reference_font_size for member in members) + 2)
        for member in members:
            member.target_font_size = _ceil_font_size(max(target, member.reference_font_size + 2))
            chapter_targets.append(member.target_font_size)
        plans.append(FontGroupPlan(name, min(member.base_font_size for member in members), target, len(members)))
    for name, members in groups.items():
        if not name.startswith("doc_title:"):
            continue
        target = _ceil_font_size(
            max(chapter_targets) + 2 if chapter_targets else median(member.reference_font_size for member in members) + 4
        )
        for member in members:
            member.target_font_size = _ceil_font_size(max(target, member.reference_font_size + 4))
        plans.append(FontGroupPlan(name, min(member.base_font_size for member in members), target, len(members)))
    return plans
