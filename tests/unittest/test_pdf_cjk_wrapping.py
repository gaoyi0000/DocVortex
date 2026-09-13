"""验证中英混排按中文字符断行，避免表注因空格分词产生大段留白。"""

from copy import deepcopy
from io import BytesIO

import pytest
from pypdf import PdfReader

from docvortex.document.pdf import PDFDocument
from docvortex.render import PdfLayout, render_pdf
from docvortex.render._internal.pdf.formula import FormulaRenderer
from docvortex.render._internal.pdf.inline import PdfAnchorRegistry, PdfInlineContext, build_pdf_paragraph
from docvortex.render._internal.pdf.styles import build_pdf_styles
from docvortex.schema import HyperlinkSpan, TextSpan
from test_pdf_original_layout import _middle, _text

NOTE = "注:异常值采用 1. 5倍四分位距（1. 5 IQR）原则确定。所有特征数据均分布在1. 5 IQR范围内，未发现异常值，因此数据可直接用于模型训练。"
WIDTH = 232.0554


def _paragraph(spans, *, style=None, block_type="table_footnote", preserve_newlines=False, anchor=None):
    """通过生产入口解析富文本，保留真实字体度量与链接注册。"""
    return build_pdf_paragraph(
        spans,
        style or build_pdf_styles().footnote,
        context=PdfInlineContext(FormulaRenderer(), PdfAnchorRegistry([anchor] if anchor else [])),
        page_idx=2,
        block_index=12,
        block_type=block_type,
        max_width=WIDTH,
        preserve_newlines=preserve_newlines,
        anchor=anchor,
    )


def _lines(paragraph, width=WIDTH):
    """读取测量得到的实际行内容，而非只检查断行模式开关。"""
    paragraph.wrap(width, 1000)
    return ["".join(fragment.text for fragment in line.words) for line in paragraph.blPara.lines]


def test_real_chinese_footnote_uses_remaining_line_width():
    """真实表注的 IQR 回到可容纳的首行，前两行不再因中文分词留下大段空白。"""
    paragraph = _paragraph([TextSpan(type="text", content=NOTE)])
    lines = _lines(paragraph)
    assert "IQR）原则确定" in lines[0]
    assert len(lines) == 3
    assert "".join(lines) == NOTE
    assert all(0 <= line.extraSpace < 8.5 for line in paragraph.blPara.lines[:-1])


def test_font_and_link_boundaries_do_not_move_chinese_phrases():
    """粗体与超链接边界不会令中文整段搬行，链接标注只生成一次。"""
    prefix, suffix = NOTE.split("IQR", 1)
    paragraph = _paragraph(
        [
            TextSpan(type="text", content=prefix),
            HyperlinkSpan(type="hyperlink", url="https://example.org/iqr", content=[TextSpan(type="text", content="IQR")]),
            TextSpan(type="text", content=suffix, styles=["bold"]),
        ],
        anchor="note",
    )
    assert "IQR" in _lines(paragraph)[0]
    assert "".join(_lines(paragraph)) == NOTE
    output = BytesIO()
    from reportlab.pdfgen.canvas import Canvas

    canvas = Canvas(output)
    paragraph.drawOn(canvas, 40, 600)
    canvas.save()
    annotations = PdfReader(BytesIO(output.getvalue())).pages[0]["/Annots"]
    assert len(annotations) == 1
    assert annotations[0].get_object()["/A"]["/URI"] == "https://example.org/iqr"


def test_table_text_preserves_explicit_breaks_and_wraps_chinese():
    """表格保留显式换行，同时中文仍能在字符边界使用剩余行宽。"""
    paragraph = _paragraph([TextSpan(type="text", content=NOTE + "\n下一行")], block_type="table_body", preserve_newlines=True)
    lines = _lines(paragraph)
    assert "IQR" in lines[0]
    assert lines[-1] == "下一行"


@pytest.mark.parametrize("kind", ["code_body", "algorithm_body"])
def test_literal_blocks_keep_existing_wrap_mode(kind):
    """含中文的代码和算法字面块不启用新的自然语言断行规则。"""
    paragraph = _paragraph([TextSpan(type="text", content=NOTE)], block_type=kind, preserve_newlines=True)
    assert paragraph.style.wordWrap is None


def test_cjk_style_is_local_and_english_remains_unchanged():
    """中英文段落共用输入样式时互不污染，纯英文保留原有空格分词。"""
    style = build_pdf_styles().footnote
    chinese = _paragraph([TextSpan(type="text", content=NOTE)], style=style)
    english = _paragraph([TextSpan(type="text", content="English words use the existing line breaking rules.")], style=style)
    assert chinese.style.wordWrap == "CJK"
    assert english.style is style and style.wordWrap is None


@pytest.mark.parametrize("layout", [PdfLayout.ORIGINAL, PdfLayout.REFLOW])
def test_public_pdf_paths_preserve_all_mixed_text(layout):
    """两条公开 PDF 路径输出完整混排文字，原布局首个 IQR 实际位于首行且输入不变。"""
    middle = _middle([{"page_idx": 0, "blocks": [_text(NOTE, bbox=(0.1, 0.1, 0.68, 0.25))]}])
    before = deepcopy(middle.to_dict())
    payload = render_pdf(middle, layout=layout)
    with PDFDocument(payload) as document:
        chars = document.get_page_chars_with_geometry(0).chars
        actual = "".join(char["char"] for char in chars)
        assert "".join(actual.split()) == "".join(NOTE.split())
        if layout == PdfLayout.ORIGINAL:
            first_i = next(char for char in chars if char["char"] == "I")
            assert first_i["bbox"][1] == pytest.approx(chars[0]["bbox"][1], abs=3)
    assert middle.to_dict() == before
