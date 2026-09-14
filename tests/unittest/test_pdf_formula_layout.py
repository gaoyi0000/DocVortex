"""验证行间公式的数学样式、独立序号和原版式安全占用范围。"""

from __future__ import annotations

from copy import deepcopy
from io import BytesIO
from xml.etree import ElementTree

import pytest
import ziamath
from pypdf import PdfReader
from reportlab.graphics.shapes import Drawing
from reportlab.pdfgen.canvas import Canvas
from ziamath.tex import tex2mml

from docvortex.render import render_pdf
from docvortex.render._internal.pdf.diagnostics import collect_pdf_diagnostics
from docvortex.render._internal.pdf.font_plan import PreparedBlock
from docvortex.render._internal.pdf.formula import (
    DisplayFormulaFlowable,
    FormulaRenderer,
    FormulaVector,
    _normalize_display_mathml,
    _svg_root_to_vector,
)
from docvortex.render._internal.pdf.formula_layout import place_formulas
from docvortex.render._internal.pdf.original import OriginalPdfRenderer
from docvortex.schema import EquationBlock, MiddleJson, PageInfo, TextBlock


def _vector(width: float, height: float, *, descent: float = 2, axis: float = 3, multiline: bool = False) -> FormulaVector:
    """提供尺寸明确的矢量，独立验证排版不变量而不依赖特定字形。"""
    return FormulaVector(Drawing(width, height), width, height, height - descent, descent, axis, multiline)


@pytest.mark.parametrize("width", [80, 190, 400])
def test_number_keeps_size_right_edge_and_em_clearance(width: float) -> None:
    """短公式居中，碰撞公式左移，超长公式只缩小本体，序号保持统一字号。"""
    flow = DisplayFormulaFlowable(_vector(width, 25), _vector(20, 10))
    flow.wrap(240, 1)
    assert flow.width == 240
    assert flow.tag_rect[2] == pytest.approx(240)
    assert flow.effective_tag_font_size == 10.5
    assert flow.tag_rect[0] - flow.formula_rect[2] >= 10.5 - 1e-8
    if width == 80:
        assert sum(flow.formula_rect[::2]) / 2 == pytest.approx(120)
    if width == 190:
        assert flow.effective_font_size == 10.5
        assert flow.formula_rect[0] < (240 - width) / 2
    if width == 400:
        assert flow.effective_font_size < 10.5


def test_height_fitting_preserves_number_and_does_not_scale_column() -> None:
    """矮框只缩小高公式，最后的栏宽和序号字号不随高度比例收缩。"""
    flow = DisplayFormulaFlowable(_vector(120, 80, descent=35), _vector(12, 9))
    flow.fit_to_box(220, font_size=10.5, max_height=25)
    assert flow.height <= 25 + 1e-8
    assert flow.width == 220
    assert flow.tag_rect[2] == pytest.approx(220)
    assert flow.effective_tag_font_size == 10.5
    assert flow.effective_font_size < 6


@pytest.mark.parametrize("multiline", [False, True])
def test_number_alignment_uses_math_axis_or_multiline_center(multiline: bool) -> None:
    """不对称高公式按数学轴对齐；真正多行公式按总高度中心对齐。"""
    main = _vector(100, 70, descent=40, axis=3, multiline=multiline)
    tag = _vector(12, 10, descent=2, axis=3)
    flow = DisplayFormulaFlowable(main, tag)
    flow.wrap(240, 1000)
    if multiline:
        assert sum(flow.formula_rect[1::2]) == pytest.approx(sum(flow.tag_rect[1::2]))
    else:
        assert flow.formula_rect[1] + 43 == pytest.approx(flow.tag_rect[1] + 5)
        assert sum(flow.formula_rect[1::2]) != pytest.approx(sum(flow.tag_rect[1::2]))


def test_repeated_wrap_restores_full_size_after_narrow_and_short_trials() -> None:
    """ReportLab 多次试排的结果只依赖本次约束，不能留下以前的编号缩放。"""
    flow = DisplayFormulaFlowable(_vector(170, 45), _vector(80, 10))
    fresh = DisplayFormulaFlowable(flow.formula, flow.tag)
    flow.wrap(60, 1000)
    flow.fit_to_box(30, font_size=8, max_height=3)
    flow.wrap(400, 1000)
    fresh.wrap(400, 1000)
    assert flow.formula_rect == fresh.formula_rect
    assert flow.tag_rect == fresh.tag_rect
    assert flow.effective_tag_font_size == fresh.effective_tag_font_size == 10.5


@pytest.mark.parametrize("width,height", [(100, 100), (10, 8), (1, 1)])
def test_long_number_and_extreme_box_keep_both_elements_inside(width: float, height: float) -> None:
    """长编号在必要时独占末行，极窄矮框也不产生重叠或裁切。"""
    flow = DisplayFormulaFlowable(_vector(120, 30), _vector(200, 10))
    flow.fit_to_box(width, font_size=10.5, max_height=height)
    for rect in [flow.formula_rect, flow.tag_rect]:
        assert 0 <= rect[0] <= rect[2] <= width + 1e-8
        assert 0 <= rect[1] <= rect[3] <= height + 1e-8
    assert flow.tag_rect[3] < flow.formula_rect[1]


def test_small_formula_reports_diagnostic_when_drawn() -> None:
    """低于 6 pt 的本体即使序号仍正常，也必须报告带块定位的诊断。"""
    flow = DisplayFormulaFlowable(_vector(400, 30), _vector(20, 10), location="block_index=7", page_index=2)
    flow.wrap(100, 1000)
    with collect_pdf_diagnostics() as diagnostics:
        flow.drawOn(Canvas(BytesIO()), 0, 0)
    assert any(x.code == "pdf_layout_small_text" and "block_index=7" in x.message for x in diagnostics)


def test_fraction_style_is_compact_but_explicit_styles_and_limits_survive() -> None:
    """紧凑分数必须降低真实矢量高度，同时保留作者显式要求的大算子和上下限。"""
    source = r"\frac{\sum_i^N x_i^2}{\sum_i^N y_i^2}"
    renderer = FormulaRenderer()
    compact = renderer.render(source, inline=False, font_size=14)
    old_height = ziamath.Latex(source, inline=False, size=14, margin=0).getsize()[1]
    explicit = renderer.render(source.replace(r"\sum", r"\displaystyle\sum", 1), inline=False, font_size=14)
    limits = renderer.render(source.replace(r"\sum", r"\sum\limits", 1), inline=False, font_size=14)
    assert compact.height < old_height * 0.75
    assert explicit.height > compact.height
    assert limits.height > compact.height
    root = ElementTree.fromstring(tex2mml(r"\dfrac{a}{\frac{b}{c}}"))
    _normalize_display_mathml(root)
    assert next(x for x in root.iter() if x.tag.endswith("mstyle")).get("displaystyle") == "true"
    assert renderer.render(r"\dfrac{a}{\frac{b}{c}}", inline=False, font_size=14).height > 0


def test_inline_formula_svg_is_unchanged_and_aligned_stays_multiline() -> None:
    """兼容层不触碰行内公式；现有 aligned 预处理和多行检测仍然生效。"""
    source = r"\frac{\sum_i^N x_i^2}{y}"
    vector = FormulaRenderer().render(source, inline=True, font_size=12)
    previous = ziamath.config.svg2
    try:
        ziamath.config.svg2 = False
        expected = _svg_root_to_vector(ziamath.Latex(source, inline=True, size=12, margin=0).svgxml())
    finally:
        ziamath.config.svg2 = previous
    assert (vector.width, vector.height, vector.ascent, vector.descent) == (
        expected.width,
        expected.height,
        expected.ascent,
        expected.descent,
    )
    assert FormulaRenderer().render(r"\begin{aligned}a&=b\\c&=d\end{aligned}", inline=False, font_size=12).multiline


def _prepared(index: int, rect: tuple, *, text: str | None = None, size: float = 10.5) -> PreparedBlock:
    """构造 point 坐标明确的正文或公式，用于安全区域和局部字号测试。"""
    x0, y0, x1, y1 = rect
    block = (
        TextBlock(type="text", index=index, content=[{"type": "text", "content": text}])
        if text is not None
        else EquationBlock(type="equation", index=index, content=r"\frac{a}{b}\tag{1}")
    )
    flows = [] if text is not None else [DisplayFormulaFlowable(_vector(100, 30), _vector(12, 10))]
    return PreparedBlock(
        0,
        block,
        flows,
        x0,
        600 - y1,
        x1 - x0,
        y1 - y0,
        page_height=600,
        body_font_size=size if text is not None else None,
    )


def test_original_uses_column_median_excludes_short_text_and_preserves_input() -> None:
    """同栏中位字号排除短连接词和对侧栏，并只修改临时绘制矩形。"""
    bodies = [
        _prepared(0, (40, 40, 180, 100), text="left column body paragraph" * 3, size=9),
        _prepared(1, (40, 200, 180, 250), text="left column another paragraph" * 3, size=11),
        _prepared(2, (40, 185, 180, 195), text="and", size=4),
        _prepared(3, (220, 40, 360, 250), text="right column body paragraph" * 3, size=20),
    ]
    equation = _prepared(4, (60, 130, 170, 135))
    original = deepcopy(equation.block)
    blocks = bodies + [equation]
    place_formulas(blocks, 400, 10.5)
    assert equation.target_font_size == 10
    assert equation.draw_rect[0] == 40 and equation.draw_rect[2] == 180
    assert equation.draw_rect[1] >= 102 and equation.draw_rect[3] <= 183
    assert equation.fit.scale == 1
    assert equation.flowables[0].effective_tag_font_size == 10
    assert equation.block == original
    assert all(body.draw_rect is None for body in bodies)


def test_adjacent_formulas_respect_final_title_and_previous_formula_rectangles() -> None:
    """相邻公式按顺序借用空白，并避开标题已经扩展后的真实占用范围。"""
    top = _prepared(0, (40, 40, 180, 100), text="body text used as reference" * 3)
    title = _prepared(1, (40, 210, 180, 220), text="title")
    title.draw_rect = (40, 195, 180, 220)
    first = _prepared(2, (40, 125, 180, 130))
    second = _prepared(3, (40, 160, 180, 165))
    place_formulas([top, title, first, second], 400, 10.5)
    assert first.draw_rect[3] + 2 <= second.draw_rect[1] + 1e-8
    assert second.draw_rect[3] + 2 <= title.draw_rect[1] + 1e-8
    assert first.draw_rect[1] >= 102
    assert title.draw_rect == (40, 195, 180, 220)


def test_original_font_fallbacks_and_unavailable_clearance() -> None:
    """无同栏正文时使用页中位数，无正文时使用默认字号，冲突输入不扩框。"""
    equation = _prepared(0, (40, 125, 180, 130))
    other_column = _prepared(1, (220, 40, 360, 250), text="another column paragraph" * 3, size=9)
    place_formulas([equation, other_column], 400, 10.5)
    assert equation.target_font_size == 9
    equation = _prepared(0, (40, 125, 180, 130))
    obstacle = _prepared(2, (40, 120, 180, 135), text="short")
    with collect_pdf_diagnostics() as diagnostics:
        place_formulas([equation, obstacle], 400, 10.5)
    assert equation.target_font_size == 10.5
    assert equation.draw_rect == pytest.approx(equation.original_rect)
    assert any(x.code == "pdf_formula_clearance_unavailable" for x in diagnostics)


def test_real_original_render_avoids_tiny_equation_four_and_preserves_document() -> None:
    """用样张的真实公式及窄矮框验证完整 PDF 路径、独立编号和输入不变性。"""
    source = r"E=1.0-\frac{\sum_{i=1}^N(O_i-P_i)^2}{\sum_{i=1}^N(O_i-\bar O)^2}\tag{4}"
    middle = MiddleJson(
        pages=[
            PageInfo(
                page_idx=0,
                blocks=[
                    TextBlock(
                        type="text",
                        index=0,
                        bbox=(0.52, 0.273, 0.927, 0.371),
                        content=[{"type": "text", "content": "A substantial paragraph before the formula. " * 8}],
                    ),
                    EquationBlock(type="equation", index=1, bbox=(0.521, 0.377, 0.923, 0.418), content=source),
                    TextBlock(
                        type="text",
                        index=2,
                        bbox=(0.52, 0.425, 0.926, 0.601),
                        content=[{"type": "text", "content": "A substantial paragraph after the formula. " * 8}],
                    ),
                ],
            )
        ],
        metadata={"file_suffix": "pdf", "producer": {"name": "test", "version": "1"}},
        extensions={"docvortex_layout": {"version": 1, "pages": [{"page_idx": 0, "width_pt": 544, "height_pt": 743}]}},
        is_full_document=True,
    )
    before = deepcopy(middle)
    with collect_pdf_diagnostics() as diagnostics:
        payload = render_pdf(middle)
    assert middle == before
    reader = PdfReader(BytesIO(payload))
    assert len(reader.pages) == 1
    assert "after the formula" in reader.pages[0].extract_text()
    assert not any(x.code in {"pdf_formula_fallback", "pdf_layout_small_text"} for x in diagnostics)
    assert any(x.code == "pdf_formula_layout" for x in diagnostics)


def test_plain_alphanumeric_tag_uses_upright_glyphs_at_body_size() -> None:
    """普通字母编号不能继承数学斜体，序号与本体从相同正文基准字号构建。"""
    middle = MiddleJson(
        pages=[],
        metadata={"file_suffix": "pdf", "producer": {"name": "test", "version": "1"}},
        extensions={"docvortex_layout": {"version": 1, "pages": []}},
        is_full_document=False,
    )
    renderer = OriginalPdfRenderer(middle, asset_resolver=None, document_title="test", page_sizes={})
    flow = renderer._render_equation(EquationBlock(type="equation", index=0, content=r"x=y\tag{A.1}"), 0)[0]
    expected = FormulaRenderer().render(r"\mathrm{(A.1)}", inline=True, font_size=10.5)
    flow.wrap(200, 1000)
    assert flow.tag.width == pytest.approx(expected.width)
    assert flow.effective_font_size == flow.effective_tag_font_size == 10.5
