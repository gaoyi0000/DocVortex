"""验证原始版式的结构表格、内容列宽、旋转和按块失败兜底。"""

from __future__ import annotations

import base64
from copy import deepcopy
from io import BytesIO

import pytest
from PIL import Image
from pypdf import PdfReader
from reportlab.platypus import Table

from docvortex.render import PdfLayout, render_pdf
from docvortex.render._internal.pdf.diagnostics import collect_pdf_diagnostics
from docvortex.render._internal.pdf.font_plan import PreparedBlock
from docvortex.render._internal.pdf.original import OriginalPdfRenderer
from docvortex.render._internal.pdf.table import SpatialTableOptions
from docvortex.render._internal.pdf.table_layout import SpatialTableContent
from docvortex.schema import BlockBase, MiddleJson, PageInfo


def _png() -> str:
    """生成与结构表格可区分的纯色区域图。"""
    stream = BytesIO()
    Image.new("RGB", (120, 60), "red").save(stream, format="PNG")
    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode()


def _text(index: int, rect: tuple, text: str, kind: str = "text") -> dict:
    """用 point 坐标构造具有独立原框的文字块。"""
    return {
        "type": kind,
        "index": index,
        "bbox": [rect[0] / 400, rect[1] / 600, rect[2] / 400, rect[3] / 600],
        "content": [{"type": "text", "content": text}],
    }


def _table(index: int, rect: tuple, html: str, *, image: bool = True, caption: bool = False, missing: bool = False) -> dict:
    """构造可带原图、表题和缺失子框的严格表格。"""
    bbox = [rect[0] / 400, rect[1] / 600, rect[2] / 400, rect[3] / 600]
    body = {"type": "table_body", "index": index, "bbox": None if missing else bbox, "content": html}
    if image:
        body["image_base64"] = _png()
    content = [body]
    if caption:
        label = _text(index + 1, (rect[0], rect[3] + 5, rect[2], rect[3] + 25), "UNIQUE CAPTION", "table_caption")
        if missing:
            label["bbox"] = None
        content.append(label)
    return {"type": "table", "index": index, "bbox": bbox, "content": content}


def _middle(blocks: list[dict], angle: int = 0) -> MiddleJson:
    """构造一页测试协议，旋转元数据只绑定编号为 10 的表格主体。"""
    return MiddleJson(
        pages=[PageInfo.model_validate({"page_idx": 0, "blocks": blocks})],
        is_full_document=True,
        metadata={"file_suffix": "pdf", "producer": {"name": "test", "version": "1"}},
        extensions={
            "docvortex_layout": {
                "version": 1,
                "pages": [
                    {
                        "page_idx": 0,
                        "width_pt": 400,
                        "height_pt": 600,
                        "image_rotations": {"10": angle},
                    }
                ],
            }
        },
    )


class _RecordingRenderer(OriginalPdfRenderer):
    """通过正常渲染链路保存临时绘制计划，验证真实最终几何。"""

    def __init__(self, middle: MiddleJson) -> None:
        """创建只属于本次测试的 renderer 与绘制计划索引。"""
        super().__init__(middle, asset_resolver=None, document_title="test", page_sizes={0: (400, 600)})
        self.items: dict[int, PreparedBlock] = {}

    def _prepare_block(
        self,
        block: BlockBase,
        page_idx: int,
        page_width: float,
        page_height: float,
        *,
        index_entry: bool = False,
    ) -> list[PreparedBlock]:
        """记录父框或叶子框的实际准备结果，不替换生产布局算法。"""
        items = super()._prepare_block(block, page_idx, page_width, page_height, index_entry=index_entry)
        self.items.update({item.block.index: item for item in items})
        return items


@pytest.mark.parametrize("layout", [PdfLayout.AUTO, PdfLayout.ORIGINAL])
def test_default_structure_keeps_cells_and_caption_without_region_image(layout: PdfLayout) -> None:
    """两种原版式入口默认保留合并格、空单元格和表题，且不改变输入数据。"""
    html = "<table><tr><th colspan='2'>HEADER</th></tr><tr><td></td><td>SELECTABLE</td></tr></table>"
    middle = _middle([_table(10, (40, 60, 350, 220), html, caption=True)])
    before = deepcopy(middle)
    with collect_pdf_diagnostics() as diagnostics:
        payload = render_pdf(middle, layout=layout)
    page = PdfReader(BytesIO(payload)).pages[0]
    text = page.extract_text()
    assert "SELECTABLE" in text and "HEADER" in text
    assert text.count("UNIQUE CAPTION") == 1
    assert len(page.images) == 0
    assert not any(d.code == "pdf_table_fallback" for d in diagnostics)
    assert middle == before


def test_content_widths_reserve_name_column_and_respect_colspan() -> None:
    """长名称列比纯数字列宽，跨列标题不把各数字列单独撑宽。"""
    html = (
        "<table><tr><th rowspan='2'>Catchment</th><th colspan='2'>Percentile</th></tr>"
        "<tr><th>10</th><th>20</th></tr>"
        "<tr><td>Lambrechtsbos A (South Africa)</td><td>0.8</td><td>0.9</td></tr></table>"
    )
    renderer = _RecordingRenderer(_middle([_table(10, (40, 80, 350, 250), html)]))
    renderer.render()
    content = renderer.items[10].flowables[0]
    widths = content.tables[0]._colWidths
    assert widths[0] > widths[1] * 1.5
    assert widths[1] == pytest.approx(widths[2])
    assert sum(widths) * content.scale == pytest.approx(310)


@pytest.mark.parametrize("angle", [0, 90, 180, 270])
def test_rotated_structured_text_has_correct_direction_and_stays_in_box(angle: int) -> None:
    """从真实 PDF 文字坐标验证结构表方向，而不只检查 Flowable 的角度字段。"""
    html = "<table><tr><td>FIRSTROW</td></tr><tr><td>LASTROW</td></tr></table>"
    renderer = _RecordingRenderer(_middle([_table(10, (60, 80, 200, 350), html)], angle))
    payload = renderer.render()
    positions = {}

    def visit(text: str, cm: list, tm: list, font: object, size: float) -> None:
        """把文字局部坐标乘以当前画布矩阵得到页面坐标。"""
        if text.strip():
            positions[text.strip()] = (tm[4] * cm[0] + tm[5] * cm[2] + cm[4], tm[4] * cm[1] + tm[5] * cm[3] + cm[5])

    page = PdfReader(BytesIO(payload)).pages[0]
    page.extract_text(visitor_text=visit)
    first, last = positions["FIRSTROW"], positions["LASTROW"]
    if angle == 0:
        assert first[1] > last[1]
    elif angle == 180:
        assert first[1] < last[1]
    elif angle == 90:
        assert first[0] > last[0]
    else:
        assert first[0] < last[0]
    for x, y in (first, last):
        assert 60 <= x <= 200 and 250 <= y <= 520
    assert len(page.images) == 0


def test_safe_expansion_respects_frozen_text_and_adjacent_table() -> None:
    """表格只借用安全空白，预留下一张表的原框，正文的位置不被挪动。"""
    html = "<table>" + "<tr><td>ROW</td><td>123</td></tr>" * 8 + "</table>"
    middle = _middle(
        [
            _text(0, (40, 40, 180, 100), "A substantial paragraph above the table."),
            _table(10, (40, 110, 180, 125), html),
            _table(20, (40, 230, 180, 245), html),
            _text(30, (40, 365, 180, 425), "A substantial paragraph below both tables."),
            _text(40, (220, 40, 360, 425), "The other column remains occupied."),
        ]
    )
    renderer = _RecordingRenderer(middle)
    renderer.render()
    first, second = renderer.items[10], renderer.items[20]
    assert first.draw_rect[3] > first.original_rect[3]
    assert first.draw_rect[3] + 2 <= second.draw_rect[1] + 1e-6
    assert first.draw_rect[1] >= 102 and second.draw_rect[3] <= 363
    assert first.draw_rect[2] <= 180 and second.draw_rect[2] <= 180
    assert renderer.items[0].draw_rect is None and renderer.items[30].draw_rect is None


def test_tiny_region_retains_structure_below_six_points_and_full_width() -> None:
    """没有可借空白时继续缩小结构表并报告低字号，不因可读性限制回退原图。"""
    html = "<table>" + "<tr><td>RETAINED</td><td>123</td></tr>" * 16 + "</table>"
    renderer = _RecordingRenderer(
        _middle(
            [
                _text(0, (40, 50, 180, 100), "BEFORE"),
                _table(10, (40, 102, 180, 109), html),
                _text(20, (40, 111, 180, 155), "AFTER"),
            ]
        )
    )
    with collect_pdf_diagnostics() as diagnostics:
        payload = renderer.render()
    page = PdfReader(BytesIO(payload)).pages[0]
    flow = renderer.items[10].flowables[0]
    assert flow.effective_font_size < 6
    assert flow.width == pytest.approx(140)
    assert flow.height <= 7 + 1e-6
    assert page.extract_text().count("RETAINED") == 16
    assert len(page.images) == 0
    assert any(d.code == "pdf_layout_small_text" and "Structured table" in d.message for d in diagnostics)
    assert not any(d.code == "pdf_table_fallback" for d in diagnostics)


def test_missing_child_boxes_reserve_caption_inside_parent() -> None:
    """缺子框的父表组合仍保留完整结构和表题，不把表题覆盖在单元格上。"""
    html = "<table>" + "<tr><td>GROUP CELL</td></tr>" * 5 + "</table>"
    renderer = _RecordingRenderer(_middle([_table(10, (40, 60, 240, 150), html, caption=True, missing=True)]))
    page = PdfReader(BytesIO(renderer.render())).pages[0]
    item = renderer.items[10]
    assert page.extract_text().count("GROUP CELL") == 5
    assert page.extract_text().count("UNIQUE CAPTION") == 1
    assert item.fit.height <= 90 + 1e-6
    assert len(page.images) == 0
    assert len(item.fit.measurements) == 2


@pytest.mark.parametrize(
    "html,image",
    [
        ("", True),
        ("<table><tr><td rowspan='3'>BROKEN</td></tr></table>", True),
        ("<table><tr><td rowspan='3'>VISIBLE</td></tr></table>", False),
        ("", False),
    ],
)
def test_missing_or_invalid_html_uses_image_text_or_placeholder(html: str, image: bool) -> None:
    """HTML 不可用时按块兜底，图片缺失不会中断整本 PDF。"""
    with collect_pdf_diagnostics() as diagnostics:
        payload = render_pdf(_middle([_table(10, (40, 60, 240, 180), html, image=image)]))
    page = PdfReader(BytesIO(payload)).pages[0]
    assert len(page.images) == int(image)
    if not image:
        assert ("VISIBLE" if html else "table unavailable") in page.extract_text()
    assert any(d.code == "pdf_table_fallback" for d in diagnostics)


def test_drawing_failure_is_detected_before_final_canvas(monkeypatch: pytest.MonkeyPatch) -> None:
    """真实绘制阶段出错时丢弃预绘制画布，不把部分结构内容叠在回退图上。"""

    class BrokenTable(Table):
        def draw(self) -> None:
            """模拟 ReportLab 在绘制过程中才发现异常。"""
            self.canv.drawString(0, 0, "PARTIAL TABLE")
            raise ValueError("drawing rejected")

    def broken(self: OriginalPdfRenderer, content: str, **kwargs: object) -> list[Table]:
        """只替换表格物化结果，仍执行真实 fit、预绘制及素材兜底。"""
        return [BrokenTable([["CELL"]], colWidths=[100])]

    monkeypatch.setattr(OriginalPdfRenderer, "_html_tables", broken)
    with collect_pdf_diagnostics() as diagnostics:
        payload = render_pdf(_middle([_table(10, (40, 60, 240, 180), "<table><tr><td>CELL</td></tr></table>")]))
    page = PdfReader(BytesIO(payload)).pages[0]
    assert len(page.images) == 1
    assert "PARTIAL TABLE" not in page.extract_text()
    assert any("drawing rejected" in d.message for d in diagnostics)


def test_rich_nested_cells_and_images_are_preserved() -> None:
    """嵌套表、上下标、中英混排、公式、链接及单元格图片仍由共享单元格渲染处理。"""
    html = (
        "<table><tr><th colspan='2'>标题 Header</th></tr><tr><td rowspan='2'>"
        "<b>Bold</b> H<sub>2</sub>O <eq>x^2</eq><a href='https://example.com'>LINK</a></td>"
        "<td><table><tr><td>Nested</td></tr></table></td></tr>"
        f"<tr><td><img src='{_png()}'></td></tr></table>"
    )
    with collect_pdf_diagnostics() as diagnostics:
        payload = render_pdf(_middle([_table(10, (40, 60, 360, 400), html)]))
    page = PdfReader(BytesIO(payload)).pages[0]
    text = page.extract_text()
    assert all(word in text for word in ["Header", "Bold", "Nested", "LINK"])
    assert len(page.images) == 1
    assert len(page.get("/Annots", [])) == 1
    assert not any(d.code == "pdf_table_fallback" for d in diagnostics)


def test_repeated_fit_rebuilds_columns_and_restores_font_size() -> None:
    """窄矮试排后再次放宽时，列宽、字号和高度恢复到全新物化结果。"""
    html = "<table><tr><td>Name</td><td>Value</td></tr><tr><td>Long descriptive name</td><td>12</td></tr></table>"
    renderer = _RecordingRenderer(_middle([_table(10, (40, 60, 360, 400), html)]))
    renderer.render()
    flow = renderer.items[10].flowables[0]
    assert isinstance(flow, SpatialTableContent)
    flow.fit(320, 300)
    expected = (flow.width, flow.height, flow.font_size, tuple(flow.tables[0]._colWidths))
    flow.fit(15, 5)
    flow.fit(320, 300)
    assert (flow.width, flow.height, flow.font_size, tuple(flow.tables[0]._colWidths)) == expected
    assert flow.failure is None
    assert renderer.styles.table_cell.fontSize == 8.5
    assert renderer.styles.table_cell.leading == 11


def test_spatial_options_do_not_change_reflow_defaults() -> None:
    """紧凑字号与内容列宽仅由原版式显式启用，共享重排表仍使用等宽列。"""
    html = "<table><tr><td>A long name here</td><td>1</td></tr></table>"
    renderer = _RecordingRenderer(_middle([_table(10, (40, 60, 350, 200), html)]))
    block = renderer.middle_json.pages[0].blocks[0].content[0]
    renderer._html_tables(html, page_idx=0, block=block, available_width=300, spatial=SpatialTableOptions(6))
    table = renderer._html_tables(html, page_idx=0, block=block, available_width=300)[0]
    assert table._colWidths == [150, 150]
    assert table._cellStyles[0][0].leftPadding == 5
    assert table._cellStyles[0][0].topPadding == 4
    assert renderer.styles.table_cell.fontSize == 8.5


def test_long_cell_formula_is_measured_at_natural_width_before_region_scaling() -> None:
    """长公式通过区域缩放容纳，测量用矢量和实际绘制的 Drawing 尺寸保持一致。"""
    formula = "+".join(f"x_{{{index}}}^2" for index in range(40))
    html = f"<table><tr><td><eq>{formula}</eq></td><td>VALUE</td></tr></table>"
    renderer = _RecordingRenderer(_middle([_table(10, (40, 60, 240, 180), html)]))
    with collect_pdf_diagnostics() as diagnostics:
        renderer.render()
    flow = renderer.items[10].flowables[0]
    assert flow.failure is None
    assert flow.width <= 200 + 1e-6
    for image in renderer.inline_context.formula_images.values():
        assert image.vector.width == pytest.approx(image.vector.drawing.width)
    assert not any(d.code == "pdf_table_fallback" for d in diagnostics)


def test_rotated_table_expansion_preserves_original_page_margins() -> None:
    """旋转表格不能为了提高字号占满原来属于页边距的留白。"""
    html = "<table>" + "<tr><td>FIRST</td><td>SECOND</td></tr>" * 14 + "</table>"
    renderer = _RecordingRenderer(_middle([_table(10, (60, 100, 180, 450), html)], 270))
    renderer.render()
    rect = renderer.items[10].draw_rect
    assert rect[1] >= 100 - 1e-6 and rect[3] <= 450 + 1e-6


def test_tall_inline_formula_reserves_its_ink_height_in_table_row() -> None:
    """单元格内高分数的实际高度必须进入行高，不能穿过相邻行边框。"""
    source = r"\frac{\sum_{i=1}^N x_i^2}{\frac{a}{b}}"
    html = f"<table><tr><td><eq>{source}</eq></td></tr><tr><td>NEXT ROW</td></tr></table>"
    renderer = _RecordingRenderer(_middle([_table(10, (40, 60, 360, 300), html)]))
    renderer.render()
    flow = renderer.items[10].flowables[0]
    assert flow.failure is None
    vectors = [image.vector for image in renderer.inline_context.formula_images.values()]
    assert flow.tables[0]._rowHeights[0] >= max(vector.height for vector in vectors) + 2 - 0.01


def test_long_cjk_cell_wraps_without_forcing_entire_table_to_tiny_font() -> None:
    """连续中文按已有 CJK 规则换行，不能把整段误当最小列宽而缩小全表。"""
    text = "这是用于验证表格换行和字号的中文内容" * 5
    html = f"<table><tr><td>{text}</td><td>123</td></tr></table>"
    renderer = _RecordingRenderer(_middle([_table(10, (40, 60, 260, 350), html)]))
    renderer.render()
    flow = renderer.items[10].flowables[0]
    assert flow.failure is None
    assert flow.font_size == 8.5 and flow.scale == 1.0
    assert flow.height > 20


def test_short_nested_table_does_not_claim_entire_parent_width() -> None:
    """嵌套短表使用内容固有宽度，不把外层分配的空白强制变成最小列宽。"""
    html = "<table><tr><td>LEFT</td><td><table><tr><td>Nested</td></tr></table></td></tr></table>"
    renderer = _RecordingRenderer(_middle([_table(10, (40, 60, 280, 240), html)]))
    renderer.render()
    flow = renderer.items[10].flowables[0]
    assert flow.failure is None
    assert flow.font_size == 8.5 and flow.scale == 1.0
