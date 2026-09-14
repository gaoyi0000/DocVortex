"""单张 PDF 表格的只读内容准备及有界测量缓存，不共享可变试排对象。"""

from __future__ import annotations

from copy import copy
from dataclasses import dataclass
from typing import Callable

from bs4 import Tag
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph

from ....schema import InlineSpan, TextSpan
from ..common.html_table import HtmlTableGrid, HtmlTableSource


@dataclass
class PreparedCell:
    """保留解析后的单元格内容，以及尚未 wrap 的最近一套纯文本片段。"""

    spans: list[InlineSpan]
    images: tuple[tuple[str, str], ...]
    nested: tuple[Tag, ...]
    template: Paragraph | None = None
    template_key: tuple | None = None

    @property
    def plain(self) -> bool:
        """只有普通文本能安全复用解析片段，不跳过公式或链接产生的定位诊断。"""
        return not self.images and not self.nested and all(isinstance(span, TextSpan) for span in self.spans)

    def paragraph(self, build: Callable, style: ParagraphStyle, width: float, key: tuple) -> Paragraph:
        """从未参与试排的文本模板复制片段；每个候选得到独立 Paragraph 和 fragment。"""
        if not self.plain:
            return build(self.spans, style, width)
        if self.template is None or self.template_key != key:
            spans = self.spans or [TextSpan(type="text", content=" ")]
            self.template = build(spans, style, width)
            self.template_key = key
        template = self.template
        return type(template)(
            "", template.style, bulletText=template.bulletText, frags=[copy(fragment) for fragment in template.frags]
        )


class PdfTableContent:
    """绑定单张表格的解析树；缓存只在一次 renderer 生命周期内存在。"""

    def __init__(self, source: HtmlTableSource) -> None:
        """预检顶层 HTML，嵌套网格和单元格按首次使用准备，保留既有异常顺序。"""
        self.source = source
        self._grids: dict[str | int, tuple[HtmlTableGrid, ...]] = {}
        self._cells: dict[int, PreparedCell] = {}
        self._styles: dict[int, tuple[ParagraphStyle, tuple]] = {}
        self.widths: dict[tuple, tuple[float, float]] = {}
        self.grids(source)

    def grids(self, source: HtmlTableSource) -> tuple[HtmlTableGrid, ...]:
        """复用相同原始字符串或存活的嵌套 Tag，避免各字号重复解析占位网格。"""
        from .table import parse_html_tables

        key = source if isinstance(source, str) else id(source)
        if key not in self._grids:
            self._grids[key] = parse_html_tables(source)
        return self._grids[key]

    def style_key(self, style: ParagraphStyle) -> tuple:
        """为当前构造的正文和表头样式计算完整签名，仅暂存最近两套样式。"""
        cached = self._styles.get(id(style))
        if cached is not None:
            return cached[1]
        key = tuple(sorted((name, repr(value)) for name, value in vars(style).items()))
        if len(self._styles) >= 2:
            self._styles.pop(next(iter(self._styles)))
        self._styles[id(style)] = (style, key)
        return key

    def begin_build(self) -> None:
        """每次试排重新捕获样式，外部更新样式后不会命中旧的宽度或片段缓存。"""
        self._styles.clear()

    def cell(self, tag: Tag) -> PreparedCell:
        """逐单元格准备文本、图片引用和直接嵌套表，保留原有顺序及过滤规则。"""
        from .table import _html_cell_spans

        key = id(tag)
        if key not in self._cells:
            images = []
            for image in tag.find_all("img"):
                if image.find_parent("table") is not tag.find_parent("table"):
                    continue
                source = image.get("src", "")
                alt = image.get("alt", "image")
                images.append(
                    (
                        "" if isinstance(source, list) else str(source),
                        " ".join(str(item) for item in alt) if isinstance(alt, list) else str(alt),
                    )
                )
            nested = tuple(table for table in tag.find_all("table") if table.find_parent(("td", "th")) is tag)
            self._cells[key] = PreparedCell(_html_cell_spans(tag), tuple(images), nested)
        return self._cells[key]

    def remember_widths(self, key: tuple, value: tuple[float, float]) -> None:
        """只缓存标量固有宽度，限制长表、多字号试排的额外内存。"""
        if len(self.widths) >= 4096 and key not in self.widths:
            self.widths.pop(next(iter(self.widths)))
        self.widths[key] = value

    def release_templates(self) -> None:
        """已排版页释放解析树和模板，尚未试排的后续页面仍保留一次解析的网格。"""
        if self._cells:
            self._cells.clear()
            self._grids.clear()
        self.widths.clear()
        self._styles.clear()
