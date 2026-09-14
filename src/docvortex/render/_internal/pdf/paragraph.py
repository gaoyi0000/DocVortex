"""只在自有普通段落上复用最近一次换行，保持 ReportLab 的拆分与绘制契约。"""

from __future__ import annotations

from copy import deepcopy

from reportlab.platypus import Paragraph


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
