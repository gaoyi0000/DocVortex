"""验证第二轮表格优化的资格判断、数值等价性和候选状态隔离。"""

from copy import deepcopy

import pytest
from reportlab.lib import colors

from docvortex.render._internal.pdf.inline import _PdfParaParser
from docvortex.render._internal.pdf.table import SpatialTableOptions
from test_pdf_structured_tables import _middle, _RecordingRenderer, _table


def _renderer(html):
    """构造不含原图干扰的单表测试上下文。"""
    renderer = _RecordingRenderer(_middle([_table(10, (40, 60, 350, 200), html, image=False)]))
    return renderer, renderer.middle_json.pages[0].blocks[0].content[0]


def _build(renderer, block, size, width=310, spatial=True):
    """经过真实表格构建入口获取当前候选，不绕过共享段落构造。"""
    return renderer._html_tables(
        block.content, page_idx=0, block=block, available_width=width, spatial=SpatialTableOptions(size) if spatial else None
    )[0]


def test_plain_fragments_are_parsed_once_across_font_sizes(monkeypatch):
    """字号改变不重复解析裸文本，并且候选仍具有独立片段和正确字号。"""
    renderer, block = _renderer("<table><tr><td>中文 Alpha 123 &amp; 数据</td></tr></table>")
    calls = []
    original = _PdfParaParser.parse

    def parse(self, *args, **kwargs):
        """统计真实 markup 解析次数，检验跨字号复用是否生效。"""
        calls.append(1)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(_PdfParaParser, "parse", parse)
    paragraphs = []
    for size in (8.5, 6, 7.3, 8.5):
        table = _build(renderer, block, size)
        paragraph = table._cellvalues[0][0][0]
        assert all(fragment.fontSize == size for fragment in paragraph.frags)
        assert paragraph.style.leading == size * 11 / 8.5
        paragraphs.append(paragraph)
        table.wrap(310, 1e9)
    assert len(calls) == 1
    assert paragraphs[0].wrap(310, 1e9) == paragraphs[-1].wrap(310, 1e9)
    assert paragraphs[0].frags[0] is not paragraphs[-1].frags[0]
    assert paragraphs[0].frags[0].us_lines is not paragraphs[-1].frags[0].us_lines


def test_fragment_template_follows_font_and_color_changes():
    """模板复用不覆盖字体、颜色或后续样式更新。"""
    renderer, block = _renderer("<table><tr><td>Alpha 中文</td></tr></table>")
    before = _build(renderer, block, 8.5)._cellvalues[0][0][0]
    renderer.styles.table_cell.fontName = "Courier"
    renderer.styles.table_cell.textColor = colors.red
    after = _build(renderer, block, 6)._cellvalues[0][0][0]
    fresh, fresh_block = _renderer(block.content)
    fresh.styles.table_cell.fontName = "Courier"
    fresh.styles.table_cell.textColor = colors.red
    expected = _build(fresh, fresh_block, 6)._cellvalues[0][0][0]
    assert vars(after.frags[0]) == vars(expected.frags[0])
    assert after.frags[0].fontName != before.frags[0].fontName
    assert after.frags[0].textColor == colors.red
    assert before.frags[0].textColor != colors.red


@pytest.mark.parametrize(
    "html,spatial",
    [
        ("<b>Bold 中文</b>", True),
        ("H<sub>2</sub>O", True),
        ('<a href="https://example.com">LINK</a>', True),
        ("<eq>x^2</eq>", True),
        ("普通文本", False),
    ],
)
def test_complex_cells_and_reflow_do_not_use_cross_size_templates(html, spatial):
    """富文本及重排保持既有构造规则，不进入仅限 ORIGINAL 的跨字号路径。"""
    renderer, block = _renderer(f"<table><tr><td>{html}</td></tr></table>")
    before = deepcopy(renderer.middle_json)
    for size in (8.5, 6):
        _build(renderer, block, size, spatial=spatial)
    prepared = renderer._table_contents[id(block)]
    assert all(cell.text_template is None for cell in prepared._cells.values())
    assert renderer.middle_json == before


@pytest.mark.parametrize(
    "text", ["中文", "中文 Alpha 12.3", "中文  A &amp; B  末尾 ", "中文 • Ω 日文カナ 한글", "中文&#160;空格"]
)
@pytest.mark.parametrize("size", [6.0, 6.1, 7.3, 8.5])
def test_simple_cjk_widths_exactly_match_reportlab(text, size):
    """直接测宽必须与原生自然宽度的浮点结果完全相等，而非仅近似相等。"""
    from docvortex.render._internal.pdf.table import _simple_cjk_widths, _paragraph_minimum_width

    renderer, block = _renderer(f"<table><tr><td>{text}</td></tr></table>")
    paragraph = _build(renderer, block, size)._cellvalues[0][0][0]
    actual = _simple_cjk_widths(paragraph, renderer._table_contents[id(block)])
    minimum = _paragraph_minimum_width(paragraph)
    paragraph.wrap(1e6, 1e9)
    assert actual == (minimum, max([0.0, *paragraph.getActualLineWidths0()]))


@pytest.mark.parametrize("option", ["linebreak", "indent", "callback", "dots", "bullet", "oversized", "latin"])
def test_width_fast_path_rejects_unsupported_paragraphs(option):
    """强制换行、缩进、回调等不满足等价前提时保守回退。"""
    from docvortex.render._internal.pdf.table import _simple_cjk_widths

    text = {"linebreak": "中文<br>第二行", "callback": "中文<eq>x^2</eq>", "latin": "English"}.get(option, "中文 Alpha")
    renderer, block = _renderer(f"<table><tr><td>{text}</td></tr></table>")
    paragraph = _build(renderer, block, 8.5)._cellvalues[0][0][0]
    if option == "indent":
        paragraph.style.leftIndent = 3
    elif option == "dots":
        paragraph.style.endDots = "..."
    elif option == "bullet":
        paragraph.bulletText = "1."
    elif option == "oversized":
        paragraph.frags[0].fontSize = 2e6
    assert _simple_cjk_widths(paragraph, renderer._table_contents[id(block)]) is None


def test_character_width_cache_is_bounded():
    """大量字符和字号组合不能让单表的字宽缓存无限增长。"""
    renderer, block = _renderer("<table><tr><td>中文</td></tr></table>")
    prepared = renderer._table_content(block, block.content)
    for i in range(4200):
        prepared.character_width("Helvetica", 6 + i / 1000, "A")
    assert len(prepared._glyphs) == 4096
    prepared.release_templates()
    assert not prepared._glyphs


def test_trial_cache_reuses_measurements_but_materializes_independent_winners(monkeypatch):
    """不同高度区域复用同宽测量，仍保留各自独立的获选表格与预绘制。"""
    from docvortex.render._internal.pdf.table_layout import SpatialTableContent

    renderer, block = _renderer("<table>" + "<tr><td>中文数据 Alpha</td></tr>" * 15 + "</table>")
    flow = renderer._structured_table(block, 0)
    flow.minimum_height = None
    calls = []
    original = flow.build

    def build(width, size):
        """只统计真实 Table 物化，不改变确定性内容。"""
        calls.append((width, size))
        return original(width, size)

    flow.build = build
    assert isinstance(flow, SpatialTableContent)
    flow.fit(310, 165)
    first_calls = len(calls)
    first_table = flow.tables[0]
    assert first_calls > 1
    other = flow.fork()
    other.fit(310, 166)
    assert len(calls) <= first_calls + 2
    assert other.tables[0] is not first_table
    fresh, fresh_block = _renderer(block.content)
    expected = fresh._structured_table(fresh_block, 0)
    expected.fit(310, 166)
    assert (other.width, other.height, other.font_size, other.scale) == (
        expected.width,
        expected.height,
        expected.font_size,
        expected.scale,
    )


def test_trial_cache_follows_content_and_style_changes():
    """内容和样式变化后不能使用旧试排摘要作出字号决策。"""
    renderer, block = _renderer("<table><tr><td>MMMM 中文</td></tr></table>")
    flow = renderer._structured_table(block, 0)
    flow.fit(100, 30)
    block.content = "<table><tr><td>changed 中文文字 " + "long text " * 25 + "</td></tr></table>"
    renderer.styles.table_cell.fontName = "Courier"
    flow.fit(100, 30)
    fresh, fresh_block = _renderer(block.content)
    fresh.styles.table_cell.fontName = "Courier"
    expected = fresh._structured_table(fresh_block, 0)
    expected.fit(100, 30)
    assert flow.failure is None
    assert (flow.width, flow.height, flow.font_size, flow.scale) == (
        expected.width,
        expected.height,
        expected.font_size,
        expected.scale,
    )


def test_trial_summary_cache_is_bounded_and_failures_are_not_cached():
    """摘要缓存最多 128 项，不记录构造异常，并支持显式释放。"""
    from reportlab.platypus import Table
    from docvortex.render._internal.pdf.table_layout import SpatialTableContent

    def build(width, size):
        """用确定尺寸的原生表格隔离摘要缓存行为。"""
        if width < 0:
            raise ValueError("rejected")
        return [Table([["cell"]], colWidths=[width], rowHeights=[size])]

    flow = SpatialTableContent(build, None, None, angle=0, location="test", page_idx=0, trial_key=lambda: ("v1",))
    flow._measurement_context = ("v1",)
    for width in range(1, 140):
        flow._measure(width, 8.5)
    assert len(flow._trial_cache) == 128
    with pytest.raises(ValueError, match="rejected"):
        flow._measure(-1, 8.5)
    assert len(flow._trial_cache) == 128
    flow.clear_trials()
    assert not flow._trial_cache


@pytest.mark.parametrize("height", [5, 100, 130, 130.0009, 129.9989, 500])
@pytest.mark.parametrize("width", [12, 300])
def test_height_pruning_preserves_font_scale_and_selected_geometry(height, width):
    """临界高度、极窄框及 6 pt 以下缩放必须与禁用剪枝的原流程完全一致。"""
    html = "<table>" + "<tr><td>中文数据</td><td>12345</td></tr>" * 10 + "</table>"
    renderer, block = _renderer(html)
    flow = renderer._structured_table(block, 0)
    baseline_renderer, baseline_block = _renderer(html)
    baseline = baseline_renderer._structured_table(baseline_block, 0)
    baseline.minimum_height = None
    baseline.trial_key = None
    flow.fit(width, height)
    baseline.fit(width, height)
    assert flow.failure is None and baseline.failure is None
    assert (flow.width, flow.height, flow.font_size, flow.scale) == (
        baseline.width,
        baseline.height,
        baseline.font_size,
        baseline.scale,
    )
    assert flow.tables[0]._colWidths == baseline.tables[0]._colWidths
    assert flow.tables[0]._rowHeights == baseline.tables[0]._rowHeights


def test_height_pruning_keeps_full_six_point_measurement(monkeypatch):
    """不可能放下的高字号可以跳过，6 pt 的完整度量必须用于初始化缩放搜索。"""
    renderer, block = _renderer("<table>" + "<tr><td>Visible 中文</td></tr>" * 20 + "</table>")
    flow = renderer._structured_table(block, 0)
    sizes = []
    original = flow.build

    def build(width, size):
        """统计实际构造字号，保留其原生度量结果。"""
        sizes.append(size)
        return original(width, size)

    flow.build = build
    flow.fit(300, 50)
    assert sizes and set(sizes) == {6.0}
    assert flow.scale < 1


@pytest.mark.parametrize(
    "html,expected",
    [
        ("<tr><td></td></tr>", 0),
        ("<tr><td>  <br></td></tr>", 0),
        ("<tr><td>中文</td></tr><tr><td></td></tr>", 13),
        ("<tr><td rowspan='2'>A</td><td>B</td></tr><tr><td>C</td></tr>", None),
        ("<tr><td>H<sub>2</sub>O</td></tr>", None),
        ("<tr><td><eq>x</eq></td></tr>", None),
    ],
)
def test_height_lower_bound_is_conservative_for_empty_and_complex_cells(html, expected):
    """空白行不假定存在正文；合并行或富文本没有可证明下界时停用剪枝。"""
    renderer, block = _renderer(f"<table>{html}</table>")
    prepared = renderer._table_content(block, block.content)
    assert prepared.minimum_height(8.5, renderer.styles) == expected


def test_custom_table_builder_does_not_enable_trial_cache_or_pruning(monkeypatch):
    """替换底层构造回调后不假定其纯函数性质，必须沿用真实构造与预绘制。"""
    from docvortex.render._internal.pdf.renderer import _PdfRenderer

    renderer, block = _renderer("<table><tr><td>中文</td></tr></table>")
    original = _PdfRenderer._html_tables

    def build(self, *args, **kwargs):
        """模拟调用方替换构造方法，而非修改输入协议。"""
        return original(self, *args, **kwargs)

    monkeypatch.setattr(_PdfRenderer, "_html_tables", build)
    flow = renderer._structured_table(block, 0)
    assert flow.trial_key() is None
    assert flow.minimum_height(8.5) is None
    flow.fit(200, 100)
    assert not flow._trial_cache


def test_finished_page_releases_trial_summaries():
    """实际导出结束后即使测试持有布局对象，也不继续保留试排摘要和模板。"""
    from docvortex.render._internal.pdf.table_layout import SpatialTableContent

    renderer, _ = _renderer("<table>" + "<tr><td>中文数据</td></tr>" * 20 + "</table>")
    renderer.render()
    for item in renderer.items.values():
        for flow in item.flowables:
            if isinstance(flow, SpatialTableContent):
                assert not flow._trial_cache
    assert all(not content._cells and not content._glyphs for content in renderer._table_contents.values())
