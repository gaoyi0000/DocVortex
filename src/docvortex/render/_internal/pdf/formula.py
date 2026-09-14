"""ZiaMath LaTeX 到受控 ReportLab 矢量路径的转换。"""

from __future__ import annotations

from dataclasses import dataclass, replace
import re
from threading import RLock
from typing import Any
from xml.etree import ElementTree

from fontTools.pens.basePen import BasePen
from fontTools.svgLib.path import parse_path
from reportlab.graphics.shapes import Drawing, Group, Path, Rect
from reportlab.lib.colors import Color, toColor
from reportlab.platypus import Flowable
import ziamath
from ziamath.tex import tex2mml

from .diagnostics import report_pdf_diagnostic

MAX_FORMULA_CHARACTERS = 20_000
MAX_CACHED_FORMULAS = 512
_MAX_SVG_NODES = 20_000
_MAX_SVG_PATH_CHARACTERS = 20_000_000
_SVG_NAMESPACE = "http://www.w3.org/2000/svg"
_ZIAMATH_LOCK = RLock()
_SVG_PATH_COMMAND_RE = re.compile(r"[A-DF-Za-df-z]")


class PdfFormulaError(ValueError):
    """表示 LaTeX 或 ZiaMath SVG 无法安全转换为 PDF 矢量对象。"""


@dataclass(frozen=True, slots=True)
class FormulaVector:
    """保存一个公式的 ReportLab Drawing 与基线几何。"""

    drawing: Drawing
    width: float
    height: float
    ascent: float
    descent: float
    axis_height: float = 0.0
    multiline: bool = False

    def scaled(self, factor: float) -> FormulaVector:
        """返回仅调整展示几何、不复制 Drawing 的等比公式对象。"""
        return FormulaVector(
            drawing=self.drawing,
            width=self.width * factor,
            height=self.height * factor,
            ascent=self.ascent * factor,
            descent=self.descent * factor,
            axis_height=self.axis_height * factor,
            multiline=self.multiline,
        )


@dataclass(frozen=True, slots=True)
class InlineFormulaImage:
    """作为 ReportLab Paragraph 行内图片占位的矢量公式代理。"""

    vector: FormulaVector


class FormulaRenderer:
    """维护单份 PDF 文档内有界且无跨文档状态的公式缓存。"""

    def __init__(self) -> None:
        """初始化最多缓存 512 个唯一公式的文档级缓存。"""
        self._cache: dict[tuple[str, bool, float, str], FormulaVector] = {}

    def render(
        self,
        latex: str,
        *,
        inline: bool,
        font_size: float,
        color: str = "#1f2937",
    ) -> FormulaVector:
        """把一个裸 LaTeX 公式转换为行内或行间矢量对象。"""
        if not isinstance(latex, str) or not latex.strip():
            raise PdfFormulaError("formula must contain non-blank LaTeX")
        if not isinstance(font_size, (int, float)) or isinstance(font_size, bool) or font_size <= 0:
            raise PdfFormulaError("font_size must be a positive number")
        if len(latex) > MAX_FORMULA_CHARACTERS:
            raise PdfFormulaError(f"formula exceeds max_formula_characters={MAX_FORMULA_CHARACTERS}")

        key = (latex, inline, float(font_size), color)
        if key in self._cache:
            return self._cache[key]

        vector = _render_ziamath_formula(latex, inline=inline, font_size=float(font_size), color=color)
        if len(self._cache) < MAX_CACHED_FORMULAS:
            self._cache[key] = vector
        return vector


class DisplayFormulaFlowable(Flowable):
    """在可用行宽内居中绘制公式，并把可选编号贴到右边界。"""

    def __init__(
        self,
        formula: FormulaVector,
        tag: FormulaVector | None = None,
        *,
        font_size: float = 10.5,
        location: str = "",
        page_index: int | None = None,
    ) -> None:
        """保存公式、可选编号以及延迟到 wrap 阶段计算的缩放参数。"""
        super().__init__()
        self.formula = formula
        self.tag = tag
        self.font_size = font_size
        self.location = location
        self.page_index = page_index
        self._available_width = formula.width
        self._formula_scale = 1.0
        self._tag_scale = 1.0
        self.width = formula.width
        self.height = formula.height
        self.formula_rect = (0.0, 0.0, formula.width, formula.height)
        self.tag_rect: tuple[float, float, float, float] | None = None

    @property
    def effective_font_size(self) -> float:
        """返回公式本体在最终绘制时的基准字号。"""
        return self.font_size * self._formula_scale

    @property
    def effective_tag_font_size(self) -> float | None:
        """返回独立缩放后的序号字号，无序号时返回空值。"""
        return self.font_size * self._tag_scale if self.tag is not None else None

    def wrap(self, avail_width: float, _avail_height: float) -> tuple[float, float]:
        """重排版只按行宽试排，页尾剩余高度交给分页器处理。"""
        self.fit_to_box(avail_width, font_size=self.font_size)
        return self.width, self.height

    def fit_to_box(self, width: float, *, font_size: float, max_height: float | None = None) -> None:
        """每次从原始矢量重新试排；高度不足优先缩小本体，始终保留整栏坐标。"""
        self.width = self._available_width = max(0.001, width)
        target_scale = font_size / self.font_size
        gap = font_size if self.tag is not None else 0.0
        tag_scale = min(target_scale, self.width / self.tag.width) if self.tag is not None else target_scale
        tag_width = self.tag.width * tag_scale if self.tag is not None else 0.0
        # 编号很长或栏宽小于一个字时，独占末行比把编号压成微小文字更可读。
        stacked = self.tag is not None and (tag_width > self.width * 0.4 or self.width - tag_width - gap < font_size)
        main_limit = self.width if stacked else max(0.001, self.width - tag_width - gap)
        formula_scale = min(target_scale, main_limit / self.formula.width)
        self._position(formula_scale, tag_scale, gap, stacked)
        if max_height is None or self.height <= max_height:
            return
        height_limit = max(0.001, max_height)
        # 先判断序号本身是否能保留目标字号；极窄矮框才同比缩小序号及行间隔。
        self._position(0.0, tag_scale, gap, stacked)
        if self.height >= height_limit:
            ratio = height_limit / max(self.height, 0.001) * 0.5
            tag_scale *= ratio
            gap *= ratio
        low, high = 0.0, formula_scale
        for _ in range(40):
            candidate = (low + high) / 2
            self._position(candidate, tag_scale, gap, stacked)
            if self.height <= height_limit:
                low = candidate
            else:
                high = candidate
        self._position(low, tag_scale, gap, stacked)

    def _position(self, formula_scale: float, tag_scale: float, gap: float, stacked: bool) -> None:
        """统一计算本体和序号的最终矩形，单行使用数学轴，多行使用垂直中心。"""
        self._formula_scale, self._tag_scale = formula_scale, tag_scale
        fw, fh = self.formula.width * formula_scale, self.formula.height * formula_scale
        fx, fy = max(0.0, (self.width - fw) / 2), 0.0
        self.tag_rect = None
        self.height = fh
        if self.tag is not None:
            tw, th = self.tag.width * tag_scale, self.tag.height * tag_scale
            tx = self.width - tw
            if stacked:
                fy, ty = th + gap, 0.0
            else:
                fx = max(0.0, min(fx, tx - gap - fw))
                if self.formula.multiline:
                    ty = (fh - th) / 2
                else:
                    ty = (self.formula.descent + self.formula.axis_height) * formula_scale
                    ty -= (self.tag.descent + self.tag.axis_height) * tag_scale
                fy = max(0.0, -ty)
                ty += fy
            self.tag_rect = (tx, ty, tx + tw, ty + th)
            self.height = max(fy + fh, ty + th)
        self.formula_rect = (fx, fy, fx + fw, fy + fh)

    def draw(self) -> None:
        """使用最后一次试排结果绘制；过小公式在两种版式中均报告可读性诊断。"""
        if min(self.effective_font_size, self.effective_tag_font_size or self.effective_font_size) < 6 - 0.001:
            report_pdf_diagnostic(
                "pdf_layout_small_text",
                f"Formula below 6 pt: formula={self.effective_font_size:.4f}, "
                f"tag={self.effective_tag_font_size}, {self.location}",
                self.page_index,
            )
        _draw_vector(self.canv, self.formula, *self.formula_rect[:2], self._formula_scale)
        if self.tag is not None and self.tag_rect is not None:
            _draw_vector(self.canv, self.tag, *self.tag_rect[:2], self._tag_scale)


class _ReportLabPathPen(BasePen):
    """把 FontTools SVG path 回调写入 ReportLab Path。"""

    def __init__(self) -> None:
        """创建不依赖 glyphSet 的空 ReportLab 路径。"""
        super().__init__(None)
        self.path = Path()

    def _moveTo(self, point: tuple[float, float]) -> None:
        """把 SVG move 命令写入目标路径。"""
        self.path.moveTo(*point)

    def _lineTo(self, point: tuple[float, float]) -> None:
        """把 SVG line 命令写入目标路径。"""
        self.path.lineTo(*point)

    def _curveToOne(
        self,
        point1: tuple[float, float],
        point2: tuple[float, float],
        point3: tuple[float, float],
    ) -> None:
        """把三次曲线写入目标路径，二次曲线由 BasePen 自动转换。"""
        self.path.curveTo(*point1, *point2, *point3)

    def _closePath(self) -> None:
        """闭合当前 ReportLab 子路径。"""
        self.path.closePath()

    def _endPath(self) -> None:
        """结束不闭合的 SVG 子路径。"""


def split_formula_tag(content: str) -> tuple[str, str | None]:
    """剥离公式末尾括号平衡的 ``\\tag{...}``，并返回正文与编号。"""
    stripped_end = len(content.rstrip())
    if stripped_end == 0 or content[stripped_end - 1] != "}":
        return content, None
    search_end = stripped_end
    while (tag_start := content.rfind(r"\tag", 0, search_end)) >= 0:
        if not _is_escaped_character(content, tag_start):
            opening_brace = _find_tag_opening_brace(content, tag_start, stripped_end)
            if opening_brace is not None:
                closing_brace = _find_balanced_closing_brace(content, opening_brace, stripped_end)
                if closing_brace == stripped_end - 1:
                    return content[:tag_start].rstrip(), content[opening_brace + 1 : closing_brace].strip()
        search_end = tag_start
    return content, None


def draw_inline_formula(
    canvas: Any,
    image: InlineFormulaImage,
    x: float,
    y: float,
    width: float,
    height: float,
) -> tuple[float, float]:
    """由自定义 Canvas 在 Paragraph 计算的位置绘制一个行内矢量公式。"""
    vector = image.vector
    scale = min(width / max(vector.width, 1.0), height / max(vector.height, 1.0))
    _draw_vector(canvas, vector, x, y, scale)
    return width, height


def _render_ziamath_formula(latex: str, *, inline: bool, font_size: float, color: str) -> FormulaVector:
    """在全局锁内临时关闭 SVG2 symbols，并转换单个 ZiaMath 结果。"""
    try:
        with _ZIAMATH_LOCK:
            previous_svg2 = ziamath.config.svg2
            ziamath.config.svg2 = False
            try:
                if inline:
                    formula = ziamath.Latex(latex, inline=True, size=font_size, color=color, margin=0)
                else:
                    # 使用 ZiaMath 自身的转换保留 aligned、运算符等现有 LaTeX 预处理。
                    mathml = ElementTree.fromstring(tex2mml(latex, inline=False))
                    _normalize_display_mathml(mathml)
                    mathml.set("mathcolor", color)
                    formula = ziamath.Math(mathml, size=font_size, margin=0)
                root = formula.svgxml()
                axis_height = font_size * formula.font.math.consts.axisHeight / formula.font.info.layout.unitsperem
            finally:
                ziamath.config.svg2 = previous_svg2
        return replace(
            _svg_root_to_vector(root),
            axis_height=axis_height,
            multiline=bool(re.search(r"\\begin\s*\{(?:aligned|align\*?|gathered|gather\*?|split|eqnarray\*?)\}", latex)),
        )
    except PdfFormulaError:
        raise
    except Exception as exc:
        raise PdfFormulaError(f"LaTeX formula cannot be rendered: {_formula_preview(latex)!r}") from exc


def _normalize_display_mathml(element: ElementTree.Element, displaystyle: bool = True) -> None:
    """在临时树中补充分数子项的紧凑样式，保留显式样式及 limits 的节点结构。"""
    displaystyle = element.get("displaystyle", str(displaystyle).lower()) == "true"
    name = _local_name(element.tag)
    if name == "mo" and element.text == "∑" and not displaystyle:
        element.attrib.setdefault("stretchy", "false")
    for child in element:
        if name == "mfrac":
            # 显式 displaystyle 属性及后代 mstyle 可覆盖默认继承，不改原 LaTeX。
            child.attrib.setdefault("displaystyle", "false")
        _normalize_display_mathml(child, displaystyle)


def _svg_root_to_vector(root: ElementTree.Element) -> FormulaVector:
    """把 ZiaMath 的固定 SVG 子集转换为坐标已翻转的 ReportLab Drawing。"""
    namespace = root.get("xmlns") if root.tag == "svg" else root.tag.removeprefix("{").split("}", 1)[0]
    if _local_name(root.tag) != "svg" or namespace != _SVG_NAMESPACE:
        raise PdfFormulaError("ZiaMath output must contain an SVG root")
    view_box = _parse_number_list(root.get("viewBox"), count=4, field="viewBox")
    min_x, min_y, width, height = view_box
    if width <= 0 or height <= 0:
        raise PdfFormulaError("ZiaMath SVG dimensions must be positive")
    drawing = Drawing(width, height)
    root_group = Group()
    root_group.transform = (1, 0, 0, -1, -min_x, min_y + height)
    node_counter = [0]
    path_budget = [0]
    for child in root:
        _append_svg_element(
            root_group,
            child,
            inherited={},
            node_counter=node_counter,
            path_budget=path_budget,
        )
    drawing.add(root_group)
    ascent = max(0.0, -min_y)
    descent = max(0.0, min_y + height)
    return FormulaVector(drawing=drawing, width=width, height=height, ascent=ascent, descent=descent)


def _append_svg_element(
    parent: Group,
    element: ElementTree.Element,
    *,
    inherited: dict[str, str],
    node_counter: list[int],
    path_budget: list[int],
) -> None:
    """递归转换 ZiaMath 允许的 group、path 与 rect 节点。"""
    node_counter[0] += 1
    if node_counter[0] > _MAX_SVG_NODES:
        raise PdfFormulaError("ZiaMath SVG exceeds its node limit")
    tag = _local_name(element.tag)
    if tag == "g":
        _reject_unknown_attributes(element, {"fill", "stroke", "stroke-width"})
        group_style = {**inherited, **element.attrib}
        group = Group()
        for child in element:
            _append_svg_element(
                group,
                child,
                inherited=group_style,
                node_counter=node_counter,
                path_budget=path_budget,
            )
        parent.add(group)
        return
    if tag == "path":
        _reject_unknown_attributes(element, {"d", "fill", "stroke", "stroke-width"})
        path_data = element.get("d", "")
        path_budget[0] += len(path_data)
        if not path_data or path_budget[0] > _MAX_SVG_PATH_CHARACTERS:
            raise PdfFormulaError("ZiaMath SVG path data is empty or exceeds its limit")
        commands = set(_SVG_PATH_COMMAND_RE.findall(path_data))
        if not commands.issubset({"M", "L", "Q", "Z"}):
            raise PdfFormulaError(f"Unsupported ZiaMath SVG path commands: {', '.join(sorted(commands))}")
        pen = _ReportLabPathPen()
        try:
            parse_path(path_data, pen)
        except Exception as exc:
            raise PdfFormulaError("ZiaMath SVG path data is invalid") from exc
        _apply_paint(pen.path, element.attrib, inherited)
        parent.add(pen.path)
        return
    if tag == "rect":
        _reject_unknown_attributes(element, {"x", "y", "width", "height", "fill", "stroke", "stroke-width"})
        x, y, width, height = (_parse_number(element.get(name, "0"), field=name) for name in ("x", "y", "width", "height"))
        if width < 0 or height < 0:
            raise PdfFormulaError("ZiaMath SVG rect dimensions must not be negative")
        rectangle = Rect(x, y, width, height)
        _apply_paint(rectangle, element.attrib, inherited)
        parent.add(rectangle)
        return
    raise PdfFormulaError(f"Unsupported ZiaMath SVG element: {tag}")


def _apply_paint(shape: Any, attributes: dict[str, str], inherited: dict[str, str]) -> None:
    """把受控 SVG fill、stroke 与 stroke-width 映射到 ReportLab shape。"""
    fill = attributes.get("fill", inherited.get("fill", "black"))
    stroke = attributes.get("stroke", inherited.get("stroke", "none"))
    shape.fillColor = _parse_color(fill)
    shape.strokeColor = _parse_color(stroke)
    stroke_width = attributes.get("stroke-width", inherited.get("stroke-width", "1"))
    shape.strokeWidth = _parse_number(stroke_width, field="stroke-width")


def _parse_color(value: str) -> Color | None:
    """解析 ZiaMath 生成的静态颜色，none 映射为透明。"""
    if value.strip().casefold() == "none":
        return None
    try:
        return toColor(value)
    except Exception as exc:
        raise PdfFormulaError(f"Unsupported ZiaMath SVG color: {value!r}") from exc


def _parse_number(value: str, *, field: str) -> float:
    """严格读取不含 CSS 单位的有限 SVG 数值。"""
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise PdfFormulaError(f"Invalid ZiaMath SVG {field}: {value!r}") from exc
    if number != number or number in (float("inf"), float("-inf")):
        raise PdfFormulaError(f"Invalid ZiaMath SVG {field}: {value!r}")
    return number


def _parse_number_list(value: str | None, *, count: int, field: str) -> tuple[float, ...]:
    """读取固定长度的空白或逗号分隔 SVG 数值列表。"""
    if value is None:
        raise PdfFormulaError(f"ZiaMath SVG is missing {field}")
    values = tuple(_parse_number(item, field=field) for item in value.replace(",", " ").split())
    if len(values) != count:
        raise PdfFormulaError(f"ZiaMath SVG {field} must contain {count} numbers")
    return values


def _reject_unknown_attributes(element: ElementTree.Element, allowed: set[str]) -> None:
    """拒绝 ZiaMath 固定子集之外的 SVG 属性。"""
    unexpected = set(element.attrib) - allowed
    if unexpected:
        raise PdfFormulaError(f"Unsupported ZiaMath SVG attributes: {', '.join(sorted(unexpected))}")


def _local_name(tag: str) -> str:
    """返回可带 XML namespace 的元素本地名称。"""
    return tag.rsplit("}", 1)[-1]


def _formula_preview(latex: str) -> str:
    """为诊断生成有界 LaTeX 摘要，避免超长公式污染日志。"""
    return latex if len(latex) <= 200 else f"{latex[:197]}..."


def _draw_vector(canvas: Any, vector: FormulaVector, x: float, y: float, scale: float) -> None:
    """在 canvas 上按给定位置和比例绘制公式 Drawing。"""
    canvas.saveState()
    try:
        canvas.translate(x, y)
        canvas.scale(scale, scale)
        vector.drawing.drawOn(canvas, 0, 0)
    finally:
        canvas.restoreState()


def _find_tag_opening_brace(content: str, tag_start: int, content_end: int) -> int | None:
    """查找 tag 命令允许空白后的左花括号。"""
    cursor = tag_start + len(r"\tag")
    while cursor < content_end and content[cursor].isspace():
        cursor += 1
    return cursor if cursor < content_end and content[cursor] == "{" else None


def _find_balanced_closing_brace(content: str, opening_brace: int, content_end: int) -> int | None:
    """查找与 tag 左花括号配对的右花括号，并忽略转义花括号。"""
    depth = 0
    for cursor in range(opening_brace, content_end):
        character = content[cursor]
        if character not in "{}" or _is_escaped_character(content, cursor):
            continue
        depth += 1 if character == "{" else -1
        if depth == 0:
            return cursor
        if depth < 0:
            return None
    return None


def _is_escaped_character(content: str, position: int) -> bool:
    """判断指定字符前是否存在奇数个连续反斜杠。"""
    preceding_backslashes = 0
    cursor = position - 1
    while cursor >= 0 and content[cursor] == "\\":
        preceding_backslashes += 1
        cursor -= 1
    return preceding_backslashes % 2 == 1


__all__ = [
    "DisplayFormulaFlowable",
    "FormulaRenderer",
    "FormulaVector",
    "InlineFormulaImage",
    "MAX_CACHED_FORMULAS",
    "MAX_FORMULA_CHARACTERS",
    "PdfFormulaError",
    "draw_inline_formula",
    "split_formula_tag",
]
