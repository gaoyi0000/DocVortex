"""只在自有普通段落上复用最近一次换行，保持 ReportLab 的拆分与绘制契约。"""

from __future__ import annotations

from copy import deepcopy
from types import FunctionType

from reportlab.platypus import Paragraph
from reportlab.platypus import paragraph as rl_paragraph
from reportlab.platypus.paraparser import ParaFrag


_STYLE_FIELDS = ("fontName", "fontSize", "textColor", "rise", "us_lines", "link", "backColor", "nobr")
_MISSING = object()


def _same_plain_style(first, second) -> bool:
    """普通片段按身份或样式字典比较，避免逐字符触发动态属性查找和缺失属性异常。"""
    if first is second:
        return True
    left, right = first.__dict__, second.__dict__
    # 保留原生比较中「属性不存在」与「属性值为 None」的区别。
    return [left.get(name, _MISSING) for name in _STYLE_FIELDS] == [right.get(name, _MISSING) for name in _STYLE_FIELDS]


def _plain_cjk_breaker():
    """仅为自有段落绑定局部比较函数，不复制断行算法，也不修改 ReportLab 模块全局。"""
    replacement = _same_plain_style
    for function, dependency in (
        (getattr(rl_paragraph, "makeCJKParaLine", None), "sameFrag"),
        (getattr(rl_paragraph, "cjkFragSplit", None), "makeCJKParaLine"),
        (Paragraph.breakLinesCJK, "cjkFragSplit"),
    ):
        # ReportLab 内部实现变化或已被外部包装时，保守回到其原有入口。
        if not isinstance(function, FunctionType) or dependency not in function.__code__.co_names:
            return None
        namespace = function.__globals__.copy()
        namespace[dependency] = replacement
        replacement = FunctionType(function.__code__, namespace, function.__name__, function.__defaults__, function.__closure__)
        replacement.__kwdefaults__ = function.__kwdefaults__
    return replacement


_PLAIN_CJK_BREAK = _plain_cjk_breaker()


class PlainCJKParagraph(Paragraph):
    """仅普通 CJK 组行使用局部比较，复杂内容和拆分后的段落仍交给原入口。"""

    def breakLinesCJK(self, maxWidths):
        """每次检查当前片段，内容变更后不沿用旧资格或样式比较缓存。"""
        if (
            _PLAIN_CJK_BREAK is not None
            and len(self.frags) > 1
            and not self.bulletText
            and not self.style.endDots
            and not getattr(self, "_splitpara", False)
            and all(
                type(fragment) is ParaFrag
                and type(getattr(fragment, "text", None)) is str
                and "cbDefn" not in fragment.__dict__
                and "lineBreak" not in fragment.__dict__
                and not any(fragment.__dict__.get(name) for name in ("link", "us_lines", "rise", "nobr"))
                for fragment in self.frags
            )
        ):
            return _PLAIN_CJK_BREAK(self, maxWidths)
        return super().breakLinesCJK(maxWidths)


class MeasuredParagraph(Paragraph):
    """缓存仍保存在本对象中的完整排版状态，不跨段落分享 blPara 或 fragments。"""

    def _measurement_key(self, width: float) -> tuple | None:
        """检查内容、样式及已保存几何；复杂回调和处理后的词列表保守重新测量。"""
        if any(not hasattr(fragment, "__dict__") or hasattr(fragment, "cbDefn") for fragment in self.frags):
            return None
        style = vars(self.style).copy()
        # ReportLab 已把继承值复制到当前样式，parent 本身不参与 wrap，不能按对象身份比较其深副本。
        style.pop("parent", None)
        return (
            width,
            style,
            getattr(self, "autoLeading", None),
            tuple(vars(fragment) for fragment in self.frags),
            id(getattr(self, "blPara", None)),
            getattr(self, "width", None),
            getattr(self, "height", None),
            tuple(getattr(self, "_wrapWidths", ())),
        )

    def wrap(self, availWidth: float, availHeight: float) -> tuple[float, float]:
        """同宽且状态未变时复用现有换行；Paragraph 本身不使用可用高度决定换行。"""
        key = self._measurement_key(availWidth)
        cached = getattr(self, "_measurement_cache", None)
        if key is not None and cached is not None and key == cached[0]:
            return cached[1]
        self._measurement_cache = None
        result = super().wrap(availWidth, availHeight)
        key = self._measurement_key(availWidth)
        if key is not None:
            # 只在真实换行后保存独立快照；命中时用字典比较，避免逐次序列化样式和长文本。
            self._measurement_cache = (deepcopy(key), result)
        return result

    def split(self, availWidth: float, availHeight: float) -> list:
        """拆分可能修改行布局，返回的新段落独立缓存，原对象随后重新测量。"""
        self._measurement_cache = None
        try:
            return super().split(availWidth, availHeight)
        finally:
            self._measurement_cache = None

    def draw(self) -> None:
        """绘制可能更新行内状态，绘制后不再把旧结果当作未改变的试排状态。"""
        try:
            super().draw()
        finally:
            self._measurement_cache = None


class MeasuredCJKParagraph(MeasuredParagraph, PlainCJKParagraph):
    """组合普通 CJK 比较与原有测量复用，拆分段落继续拥有独立排版状态。"""
