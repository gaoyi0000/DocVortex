"""单张 PDF 表格的只读内容准备及有界测量缓存，不共享可变试排对象。"""

from __future__ import annotations

from copy import copy
from collections import OrderedDict
from dataclasses import dataclass
from math import isfinite
from typing import Callable

from bs4 import Tag
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import Paragraph

from ....schema import InlineSpan, TextSpan
from ..common.html_table import HtmlTableGrid, HtmlTableSource
from .styles import PdfStyleSet


@dataclass(frozen=True, slots=True)
class _TextTemplate:
    """保存从未参与换行的普通文本片段，只把独立副本交给候选段落。"""

    key: tuple
    fragments: tuple
    word_wrap: str | None
    paragraph_type: type[Paragraph]


@dataclass
class PreparedCell:
    """保留解析后的单元格内容，以及尚未 wrap 的最近一套纯文本片段。"""

    spans: list[InlineSpan]
    images: tuple[tuple[str, str], ...]
    nested: tuple[Tag, ...]
    template: Paragraph | None = None
    template_key: tuple | None = None
    text_template: _TextTemplate | None = None

    @property
    def plain(self) -> bool:
        """只有普通文本能安全复用解析片段，不跳过公式或链接产生的定位诊断。"""
        return not self.images and not self.nested and all(isinstance(span, TextSpan) for span in self.spans)

    @property
    def unstyled(self) -> bool:
        """排除字号相关的上下标等样式，只有裸文本片段可以跨字号复用。"""
        return self.plain and not any(span.styles for span in self.spans)

    def _text_paragraph(self, build: Callable, style: ParagraphStyle, width: float, key: tuple) -> Paragraph:
        """仅重新指定目标字号，沿用当前样式的 leading，不近似缩放字体度量。"""
        template = self.text_template
        if template is None or template.key != key:
            paragraph = build(self.spans or [TextSpan(type="text", content=" ")], style, width)
            if paragraph.bulletText or any(hasattr(fragment, "cbDefn") for fragment in paragraph.frags):
                return paragraph
            template = self.text_template = _TextTemplate(
                key, tuple(paragraph.frags), paragraph.style.wordWrap, type(paragraph)
            )
        actual_style = (
            style.clone(style.name + " CJK", wordWrap="CJK")
            if template.word_wrap == "CJK" and style.wordWrap != "CJK"
            else style
        )
        fragments = []
        for source in template.fragments:
            fragment = copy(source)
            fragment.fontSize = style.fontSize
            # 普通文本仍有空的装饰/链接列表，候选不能修改模板或其它候选的这些列表。
            for name in ("us_lines", "link"):
                value = getattr(fragment, name, None)
                if isinstance(value, list):
                    setattr(fragment, name, value.copy())
            fragments.append(fragment)
        return template.paragraph_type("", actual_style, frags=fragments)

    def paragraph(
        self,
        build: Callable,
        style: ParagraphStyle,
        width: float,
        key: tuple,
        *,
        consume: bool,
        fragment_key: tuple | None = None,
    ) -> Paragraph:
        """从未参与试排的文本模板复制片段；每个候选得到独立 Paragraph 和 fragment。"""
        if not self.plain:
            return build(self.spans, style, width)
        if fragment_key is not None and self.unstyled:
            return self._text_paragraph(build, style, width, fragment_key)
        if self.template is None or self.template_key != key:
            spans = self.spans or [TextSpan(type="text", content=" ")]
            self.template = build(spans, style, width)
            self.template_key = key
        template = self.template
        if consume:
            # 列宽测量完成后把未 wrap 的模板交给实际单元格，避免同时持有模板和最终段落。
            self.template = None
            self.template_key = None
            return template
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
        self._styles: dict[int, tuple[ParagraphStyle, tuple, tuple]] = {}
        self.widths: dict[tuple, tuple[float, float]] = {}
        self._glyphs: OrderedDict[tuple[str, float, str], float] = OrderedDict()
        self._height_bound: tuple[tuple, int | None] | None = None
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
        self._styles[id(style)] = (
            style,
            key,
            tuple((name, value) for name, value in key if name not in ("fontSize", "leading")),
        )
        return key

    def fragment_key(self, style: ParagraphStyle) -> tuple:
        """每套样式仅计算一次字号无关签名，字体、颜色等其它属性仍参与失效判断。"""
        self.style_key(style)
        return self._styles[id(style)][2]

    def begin_build(self) -> None:
        """每次试排重新捕获样式，外部更新样式后不会命中旧的宽度或片段缓存。"""
        self._styles.clear()

    def unstyled_grids(self) -> tuple[HtmlTableGrid, ...] | None:
        """只为不含资源、链接和富文本的表提供确定性试排优化资格。"""
        grids = self.grids(self.source)
        if all(self.cell(cell.tag).unstyled for grid in grids for cell in grid.cells):
            return grids
        return None

    def minimum_height(self, font_size: float, styles: PdfStyleSet) -> float | None:
        """只统计可证明有正文的一行，空白行、合并行和富内容不作过强推断。"""
        from .inline import _font_for_character
        from .table import _spatial_leading, _SPATIAL_VERTICAL_PADDING

        key = (repr(vars(styles.table_cell)), repr(vars(styles.table_header)))
        if self._height_bound is None or self._height_bound[0] != key:
            count = None
            try:
                grids = self.unstyled_grids()
                if grids is not None and len(grids) == 1 and not any(cell.rowspan > 1 for cell in grids[0].cells):
                    visible_rows = set()
                    for cell in grids[0].cells:
                        if cell.row in visible_rows:
                            continue
                        style = styles.table_header if cell.is_header else styles.table_cell
                        for span in self.cell(cell.tag).spans:
                            if any(
                                character.isalnum()
                                and isfinite(
                                    advance := pdfmetrics.stringWidth(
                                        character, _font_for_character(character) or style.fontName, style.fontSize
                                    )
                                )
                                and advance > 0
                                for character in span.content
                            ):
                                visible_rows.add(cell.row)
                                break
                    count = len(visible_rows)
            except Exception:
                # 优化资格判断失败时回到实际构造，让原流程保留原本的异常和定位信息。
                count = None
            self._height_bound = (key, count)
        count = self._height_bound[1]
        if count is None:
            return None
        height = count * (_spatial_leading(font_size) + 2 * _SPATIAL_VERTICAL_PADDING)
        return height if isfinite(height) else None

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

    def character_width(self, font_name: str, font_size: float, character: str) -> float:
        """按确切字体、字号和字符复用原生字宽，不用比例缩放近似，最多保存 4096 项。"""
        key = (font_name, font_size, character)
        if key in self._glyphs:
            self._glyphs.move_to_end(key)
            return self._glyphs[key]
        width = pdfmetrics.stringWidth(character, font_name, font_size)
        if len(self._glyphs) >= 4096:
            self._glyphs.popitem(last=False)
        self._glyphs[key] = width
        return width

    def release_templates(self) -> None:
        """已排版页释放解析树和模板，尚未试排的后续页面仍保留一次解析的网格。"""
        if self._cells:
            self._cells.clear()
            self._grids.clear()
        self.widths.clear()
        self._styles.clear()
        self._glyphs.clear()
        self._height_bound = None
