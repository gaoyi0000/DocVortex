"""验证表格缓存只复用内容和标量，不泄漏候选的可变排版状态。"""

from io import BytesIO

from pypdf import PdfReader

from docvortex.render._internal.pdf import table as table_module
from docvortex.render._internal.pdf.table import SpatialTableOptions
from docvortex.render._internal.pdf.table_layout import SpatialTableContent
from test_pdf_structured_tables import _middle, _RecordingRenderer, _table


def test_table_content_is_parsed_once_across_sizes_and_widths(monkeypatch):
    """反复改变字号和区域宽度只解析一份 HTML 与每个单元格一次。"""
    calls = {"grid": 0, "cell": 0}
    parse_grid, parse_cell = table_module.parse_html_tables, table_module._html_cell_spans

    def grid(*args, **kwargs):
        """统计真实占位网格解析次数。"""
        calls["grid"] += 1
        return parse_grid(*args, **kwargs)

    def cell(*args, **kwargs):
        """统计严格单元格内容解析次数。"""
        calls["cell"] += 1
        return parse_cell(*args, **kwargs)

    monkeypatch.setattr(table_module, "parse_html_tables", grid)
    monkeypatch.setattr(table_module, "_html_cell_spans", cell)
    html = "<table><tr><td>中文名称</td><td>VALUE</td></tr></table>"
    renderer = _RecordingRenderer(_middle([_table(10, (40, 60, 350, 200), html)]))
    block = renderer.middle_json.pages[0].blocks[0].content[0]
    tables = []
    for width, size in [(300, 8.5), (100, 7), (300, 8.5), (300, 8.5)]:
        built = renderer._html_tables(html, page_idx=0, block=block, available_width=width, spatial=SpatialTableOptions(size))
        built[0].wrap(width, 1e9)
        tables.append(built[0])
    assert calls == {"grid": 1, "cell": 2}
    assert tables[0]._colWidths == tables[2]._colWidths
    first = tables[0]._cellvalues[0][0][0]
    last = tables[-1]._cellvalues[0][0][0]
    assert first is not last
    assert first.frags is not last.frags
    assert first.frags[0] is not last.frags[0]


def test_winning_table_region_is_not_fitted_again(monkeypatch):
    """原框足够高时一次试排即直接用于最终绘制，不再重建最佳候选。"""
    fitted = []
    original = SpatialTableContent.fit

    def fit(self, width, height):
        """记录每个实际区域的试排调用。"""
        fitted.append((width, height))
        return original(self, width, height)

    monkeypatch.setattr(SpatialTableContent, "fit", fit)
    html = "<table>" + "<tr><td>Long descriptive label 中文</td><td>12345</td></tr>" * 8 + "</table>"
    renderer = _RecordingRenderer(_middle([_table(10, (40, 60, 350, 110), html)]))
    payload = renderer.render()
    assert len(fitted) == len(set(fitted))
    assert PdfReader(BytesIO(payload)).pages[0].extract_text().count("12345") == 8


def test_cached_table_widths_follow_style_changes():
    """复用已解析表格时，更新字体或行高必须使旧样式下的测量失效。"""
    html = "<table><tr><td>MMMMMMMM</td><td>i</td></tr></table>"
    renderer = _RecordingRenderer(_middle([_table(10, (40, 60, 350, 200), html)]))
    block = renderer.middle_json.pages[0].blocks[0].content[0]
    before = renderer._html_tables(html, page_idx=0, block=block, available_width=180, spatial=SpatialTableOptions())[0]
    renderer.styles.table_cell.fontName = "Courier"
    after = renderer._html_tables(html, page_idx=0, block=block, available_width=180, spatial=SpatialTableOptions())[0]
    fresh = _RecordingRenderer(renderer.middle_json)
    fresh.styles.table_cell.fontName = "Courier"
    expected = fresh._html_tables(html, page_idx=0, block=block, available_width=180, spatial=SpatialTableOptions())[0]
    assert before._colWidths != after._colWidths
    assert after._colWidths == expected._colWidths
