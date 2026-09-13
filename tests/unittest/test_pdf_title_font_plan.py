"""验证只有同级标题统一字号，正文继续按各自框独立适配。"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from io import BytesIO
from math import hypot

import pytest
from pypdf import PdfReader

from docvortex import render_artifact
from docvortex.render import PdfLayout, PdfRenderOptions
from docvortex.render._internal.pdf.font_plan import collect_font_plans
from test_pdf_original_layout import _middle, _text


def _document(title_heights, body_heights=None):
    """按受控高度构造同级标题和正文，检查各自的容量约束。"""
    heights = body_heights or [80] * len(title_heights)
    return _middle(
        [
            {
                "page_idx": idx,
                "blocks": [
                    _text(f"TITLE{idx}", type="paragraph_title", level=2, bbox=(0.1, 0.1, 0.9, 0.1 + title_height / 600)),
                    _text(f"BODY{idx}", index=1, bbox=(0.1, 0.5, 0.9, 0.5 + height / 600)),
                ],
            }
            for idx, (title_height, height) in enumerate(zip(title_heights, heights, strict=True))
        ]
    )


def _render(middle, layout=PdfLayout.ORIGINAL):
    """从公开入口导出并读取内部标题统计，验证输入保持不变。"""
    before = deepcopy(middle.to_dict())
    with collect_font_plans() as plans:
        artifact = render_artifact(middle, "pdf", options=PdfRenderOptions(layout=layout))
    assert middle.to_dict() == before
    return artifact, {plan.group: plan for plan in plans}


def _sizes(payload):
    """读取实际 PDF 字号，计入 Canvas 变换而不只检查字体指令的名义字号。"""
    result = {}
    for page in PdfReader(BytesIO(payload)).pages:

        def visit(text, cm, tm, font, size):
            """保存各段文字最终绘制字号。"""
            if text.strip():
                result[text.strip()] = size * hypot(cm[0], cm[1])

        page.extract_text(visitor_text=visit)
    return result


def test_only_titles_share_size_and_body_keeps_individual_fit():
    """公共标题字号参考正文，正文较大的位置允许单独放大标题而不改变正文。"""
    artifact, plans = _render(_document([80, 12.2], [80, 12.2]))
    assert set(plans) == {"paragraph_title:level=2"}
    assert plans["paragraph_title:level=2"].target_font_size == 11.1
    sizes = _sizes(artifact.content)
    assert sizes["TITLE0"] == pytest.approx(12.5, abs=0.01)
    assert sizes["TITLE1"] == pytest.approx(11.1, abs=0.01)
    assert sizes["BODY0"] == 10.5
    assert 6 < sizes["BODY1"] < sizes["BODY0"]


@pytest.mark.parametrize("heights", [[80] * 9 + [4], [80] * 8 + [12.2], [80, 4]])
def test_tiny_title_boxes_borrow_space_without_shrinking_the_group(heights):
    """原框再矮也不压低标题目标；周围有空白时达到正文加 2 pt。"""
    artifact, plans = _render(_document(heights))
    plan = plans["paragraph_title:level=2"]
    assert plan.target_font_size == 12.5 and plan.exception_count == 0
    sizes = _sizes(artifact.content)
    assert len(sizes) == 2 * len(heights)
    assert all(sizes[f"BODY{idx}"] == 10.5 for idx in range(len(heights)))
    assert all(sizes[f"TITLE{idx}"] == pytest.approx(12.5, abs=0.01) for idx in range(len(heights)))
    assert len(PdfReader(BytesIO(artifact.content)).pages) == len(heights)
    assert any(d.code == "pdf_title_layout_expanded" for d in artifact.diagnostics)
    assert not any(d.code == "pdf_layout_font_coverage_limited" for d in artifact.diagnostics)


@pytest.mark.parametrize("kind", ["text", "ref_text", "header", "footer", "page_number", "page_footnote"])
def test_non_title_types_are_not_uniformly_scaled(kind):
    """正文及辅助文字完全恢复逐块适配，不进入任何文档级字号组。"""
    middle = _middle(
        [
            {
                "page_idx": idx,
                "blocks": [
                    _text(f"TEXT{idx}", type=kind, bbox=(0.1, 0.1, 0.9, 0.1 + height / 600)),
                ],
            }
            for idx, height in enumerate([80, 8])
        ]
    )
    artifact, plans = _render(middle)
    sizes = _sizes(artifact.content)
    assert not plans and sizes["TEXT0"] > sizes["TEXT1"]


def test_title_levels_and_index_references_are_separate():
    """不同标题级别独立选字号，目录引用不压低正文标题或重复注册锚点。"""
    middle = _middle(
        [
            {
                "page_idx": 0,
                "blocks": [
                    _text("MAIN", type="doc_title", level=1, bbox=(0.1, 0.1, 0.9, 0.2)),
                    _text("HEADING", type="paragraph_title", level=2, index=1, anchor="head", bbox=(0.1, 0.3, 0.9, 0.4)),
                    _text("LEVEL3", type="paragraph_title", level=3, index=2, bbox=(0.1, 0.5, 0.9, 0.6)),
                    {
                        "type": "index",
                        "index": 3,
                        "bbox": (0.1, 0.7, 0.9, 0.8),
                        "content": [
                            _text(
                                "REFERENCE", type="paragraph_title", level=2, index=4, anchor="head", bbox=(0.1, 0.7, 0.9, 0.71)
                            ),
                        ],
                    },
                ],
            }
        ]
    )
    artifact, plans = _render(middle)
    assert set(plans) == {"doc_title:level=1", "paragraph_title:level=2", "paragraph_title:level=3"}
    sizes = _sizes(artifact.content)
    assert sizes["MAIN"] == pytest.approx(14.5, abs=0.01)
    assert sizes["HEADING"] == pytest.approx(12.5, abs=0.01) and sizes["LEVEL3"] == pytest.approx(12.5, abs=0.01)
    assert not any(d.code == "pdf_duplicate_anchor" for d in artifact.diagnostics)
    assert len(PdfReader(BytesIO(artifact.content)).pages[0]["/Annots"]) == 1


def test_export_selection_blank_pages_and_parallel_font_plans():
    """标题统计仅考虑导出页，空白页保留，并发调用不共享字号计划。"""
    full = _document([80, 12.2])
    selected = full.model_copy(update={"pages": [full.pages[0]]})
    blank = full.pages[1].model_copy(update={"blocks": []})
    with_blank = selected.model_copy(update={"pages": [full.pages[0], blank]})
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(_render, [full, selected, with_blank]))
    assert [plans["paragraph_title:level=2"].target_font_size for _, plans in results] == [12.5, 12.5, 12.5]
    assert PdfReader(BytesIO(results[-1][0].content)).pages[1].extract_text() == ""
    _, plans = _render(full, PdfLayout.REFLOW)
    assert not plans
