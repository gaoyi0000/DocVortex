"""验证标题利用空白扩大、保持正文层次且不覆盖相邻内容。"""

from copy import deepcopy

import pytest

from docvortex.schema import MiddleJson
from docvortex.document.pdf import PDFDocument
from test_pdf_original_layout import _middle, _png_uri, _text
from test_pdf_title_font_plan import _render, _sizes


def _block(text, rect, *, title=False, index=0, **kwargs):
    """用 point 坐标定义合成页面，避免归一化数值遮蔽间距边界。"""
    x0, y0, x1, y1 = rect
    if title:
        kwargs.update(type="paragraph_title", level=2)
    return _text(text, index=index, bbox=(x0 / 400, y0 / 600, x1 / 400, y1 / 600), **kwargs)


def _image(rect, index):
    """构造真实区域图，使标题扩展必须遵守视觉内容的占用范围。"""
    x0, y0, x1, y1 = rect
    bbox = (x0 / 400, y0 / 600, x1 / 400, y1 / 600)
    return {
        "type": "image",
        "index": index,
        "bbox": bbox,
        "content": [
            {"type": "image_body", "index": index, "bbox": bbox, "content": "", "image_base64": _png_uri()},
        ],
    }


def _one_page(blocks):
    """构造单页严格文档，所有测量和绘制仍经过公开入口。"""
    blocks = deepcopy(blocks)
    for index, block in enumerate(blocks):
        block["index"] = index
        if block["type"] == "image":
            block["content"][0]["index"] = index
    return _middle([{"page_idx": 0, "blocks": blocks}])


def _title(plans, index=0):
    """读取当前标题的实际字号及安全绘制范围。"""
    return plans["paragraph_title:level=2"].titles[index]


def _clear(record, obstacles):
    """逐项核对页面边界、原左边缘及与其它原框至少 2 pt 的间距。"""
    x0, y0, x1, y1 = record["draw_bbox_pt"]
    assert x0 == pytest.approx(record["original_bbox_pt"][0], abs=0.001)
    assert 0 <= x0 < x1 <= 400 and -0.001 <= y0 < y1 <= 600.001
    for bx0, by0, bx1, by1 in obstacles:
        assert x1 + 2 <= bx0 + 0.001 or bx1 + 2 <= x0 + 0.001 or y1 + 2 <= by0 + 0.001 or by1 + 2 <= y0 + 0.001


def test_original_frame_stays_when_it_already_fits():
    """原框足够时不移动或扩大，标题字号依旧比实际正文大 2 pt。"""
    rect = (40, 40, 300, 70)
    artifact, plans = _render(_one_page([_block("TITLE", rect, title=True), _block("BODY", (40, 100, 300, 180), index=1)]))
    record = _title(plans)
    assert record["draw_bbox_pt"] == pytest.approx(rect)
    assert not record["expanded"]
    assert _sizes(artifact.content)["TITLE"] == pytest.approx(_sizes(artifact.content)["BODY"] + 2, abs=0.01)


@pytest.mark.parametrize("kind,level,increment", [("paragraph_title", 6, 2), ("doc_title", 1, 4)])
def test_body_reference_overrides_old_style_caps_and_handles_no_chapters(kind, level, increment):
    """末级标题可以超过旧样式上限，无章节标题时主标题使用正文加 4 pt。"""
    artifact, _ = _render(
        _one_page(
            [
                _text("TITLE", type=kind, level=level, bbox=(0.1, 0.1, 0.9, 0.2)),
                _block("BODY", (40, 150, 300, 250), index=1),
            ]
        )
    )
    sizes = _sizes(artifact.content)
    assert sizes["TITLE"] == pytest.approx(sizes["BODY"] + increment, abs=0.01)


def test_only_upward_space_is_used_without_moving_body():
    """下方紧邻正文时向上借空白，正文仍使用原位置和字号。"""
    obstacles = [(40, 20, 300, 60), (40, 107, 300, 180)]
    artifact, plans = _render(
        _one_page(
            [
                _block("PREVIOUS", obstacles[0], index=1),
                _block("TITLE", (40, 100, 140, 105), title=True),
                _block("BODY", obstacles[1], index=2),
            ]
        )
    )
    record = _title(plans)
    assert record["draw_bbox_pt"][1] < 100 and record["draw_bbox_pt"][3] <= 105.001
    assert record["final_font_size"] == 12.5
    assert _sizes(artifact.content)["BODY"] == 10.5
    _clear(record, obstacles)


def test_only_rightward_space_keeps_title_on_one_line():
    """上下均受阻时利用同栏右侧空白，保留原顶边且不挤压前后正文。"""
    obstacles = [(40, 20, 300, 100), (40, 121, 300, 180)]
    artifact, plans = _render(
        _one_page(
            [
                _block("PREVIOUS", obstacles[0], index=1),
                _block("LONG HEADING", (40, 102, 68, 119), title=True),
                _block("BODY", obstacles[1], index=2),
            ]
        )
    )
    record = _title(plans)
    assert record["draw_bbox_pt"][1] == pytest.approx(102)
    assert record["draw_bbox_pt"][2] > 68
    assert record["final_font_size"] == 12.5
    assert "LONG HEADING" in _sizes(artifact.content)
    _clear(record, obstacles)


def test_long_title_can_wrap_inside_expanded_column():
    """长标题可以在安全栏宽内多行排版，而非被压回很矮的原框。"""
    body = (40, 220, 300, 300)
    _, plans = _render(
        _one_page(
            [
                _block(
                    "A longer heading with several words repeated across multiple lines " * 3, (40, 80, 130, 85), title=True
                ),
                _block("BODY", body, index=1),
            ]
        )
    )
    record = _title(plans)
    assert record["final_font_size"] == 12.5
    assert record["draw_bbox_pt"][3] - record["draw_bbox_pt"][1] > 20
    _clear(record, [body])


def test_consecutive_titles_share_gap_without_double_claiming_it():
    """相邻标题以间隙中线分配空间，扩展后仍保持原顺序和安全间距。"""
    _, plans = _render(
        _one_page(
            [
                _block("FIRST", (40, 100, 130, 105), title=True),
                _block("SECOND", (40, 125, 180, 130), title=True, index=1),
                _block("BODY", (40, 160, 300, 250), index=2),
            ]
        )
    )
    first, second = plans["paragraph_title:level=2"].titles
    assert first["final_font_size"] == second["final_font_size"] == 12.5
    assert first["draw_bbox_pt"][3] <= 114.001
    assert second["draw_bbox_pt"][1] >= 115.999
    _clear(first, [second["draw_bbox_pt"], (40, 160, 300, 250)])
    _clear(second, [first["draw_bbox_pt"], (40, 160, 300, 250)])


def test_two_columns_and_nearby_image_bound_right_expansion():
    """右栏图像即使旁边有留白，也不能被左栏标题的扩展侵入。"""
    obstacles = [(40, 100, 180, 180), (220, 30, 380, 180)]
    _, plans = _render(
        _one_page(
            [
                _block("LEFT TITLE", (40, 50, 90, 55), title=True),
                _block("BODY", obstacles[0], index=1),
                _image(obstacles[1], 2),
            ]
        )
    )
    record = _title(plans)
    assert record["draw_bbox_pt"][2] <= 180.001
    assert record["final_font_size"] == 12.5
    _clear(record, obstacles)


def test_existing_spanning_title_preserves_its_span():
    """原本跨栏的标题保留原跨度，以下方跨栏正文确定安全右边界。"""
    obstacles = [(40, 20, 170, 60), (220, 20, 360, 60), (40, 130, 360, 210)]
    _, plans = _render(
        _one_page(
            [
                _block("LEFT", obstacles[0], index=1),
                _block("RIGHT", obstacles[1], index=2),
                _block("SPANNING HEADING", (40, 80, 330, 85), title=True),
                _block("WIDE BODY", obstacles[2], index=3),
            ]
        )
    )
    record = _title(plans)
    assert 330 <= record["draw_bbox_pt"][2] <= 360
    assert record["final_font_size"] == 12.5
    _clear(record, obstacles)


def test_unknown_column_does_not_borrow_the_whole_page_width():
    """只有另一栏正文时用全篇正文字号兜底，但不据此猜测标题所在栏的宽度。"""
    _, plans = _render(
        _one_page(
            [
                _block("SMALL", (40, 100, 90, 105), title=True),
                _block("OTHER COLUMN", (220, 150, 360, 230), index=1),
            ]
        )
    )
    record = _title(plans)
    assert record["draw_bbox_pt"][2] == 90
    assert record["final_font_size"] == 12.5


def test_title_at_page_edge_stays_inside_page_and_clear_of_images():
    """页面顶部的标题只能向下借空白，不能越出页面或侵入右侧图片。"""
    obstacles = [(40, 40, 170, 100), (200, 0, 390, 50)]
    _, plans = _render(
        _one_page(
            [
                _block("EDGE", (40, 0, 130, 5), title=True),
                _block("BODY", obstacles[0], index=1),
                _image(obstacles[1], 2),
            ]
        )
    )
    record = _title(plans)
    assert record["draw_bbox_pt"][1] == 0 and record["final_font_size"] == 12.5
    _clear(record, obstacles)


def test_insufficient_space_only_shrinks_the_constrained_title():
    """安全区域只有 4 pt 高时单独缩小当前标题，另一页的同级标题仍达到目标字号。"""
    obstacles = [(40, 20, 300, 100), (40, 108, 300, 180)]
    middle = _middle(
        [
            {
                "page_idx": 0,
                "blocks": [
                    _block("PREVIOUS", obstacles[0]),
                    _block("TINY", (40, 102, 170, 106), title=True, index=1),
                    _block("BODY0", obstacles[1], index=2),
                ],
            },
            {
                "page_idx": 1,
                "blocks": [_block("ROOMY", (40, 40, 300, 70), title=True), _block("BODY1", (40, 100, 300, 180), index=1)],
            },
        ]
    )
    artifact, plans = _render(middle)
    plan = plans["paragraph_title:level=2"]
    assert plan.target_font_size == 12.5 and plan.exception_count == 1
    assert plan.titles[0]["final_font_size"] < 6 and plan.titles[1]["final_font_size"] == 12.5
    assert plan.titles[0]["reasons"] == ["insufficient_space"]
    assert _sizes(artifact.content)["BODY0"] == _sizes(artifact.content)["BODY1"] == 10.5
    assert any(d.code == "pdf_layout_small_text" for d in artifact.diagnostics)
    _clear(plan.titles[0], obstacles)


def test_existing_geometry_conflict_does_not_expand_occupied_area():
    """输入已重叠时报告冲突，标题仍留在自身原框内，不扩大原有重叠范围。"""
    original = (40, 80, 180, 90)
    artifact, plans = _render(
        _one_page(
            [
                _block("CONFLICT", original, title=True),
                _block("BODY", (40, 85, 300, 180), index=1),
            ]
        )
    )
    record = _title(plans)
    assert record["geometry_conflict"] and not record["expanded"]
    x0, y0, x1, y1 = record["draw_bbox_pt"]
    assert x0 >= 40 and y0 >= 80 and x1 <= 180 and y1 <= 90.001
    assert any(d.code == "pdf_title_geometry_conflict" for d in artifact.diagnostics)


def test_fallback_uses_only_exported_body_fonts():
    """没有同栏正文时只参考已导出页面，单独导出标题页时回退到默认正文样式。"""
    middle = _middle(
        [
            {"page_idx": 0, "blocks": [_block("SMALL BODY", (40, 50, 300, 62.2))]},
            {"page_idx": 1, "blocks": [_block("TITLE", (40, 60, 300, 65), title=True)]},
        ]
    )
    _, full = _render(middle)
    _, selected = _render(middle.model_copy(update={"pages": [middle.pages[1]]}))
    assert full["paragraph_title:level=2"].target_font_size == 9.7
    assert selected["paragraph_title:level=2"].target_font_size == 12.5


@pytest.mark.parametrize("formula", ["x^2", r"\frac{\sum_{i=1}^n x_i}{y}"])
@pytest.mark.parametrize("narrow", [False, True])
def test_expanded_rich_title_keeps_formula_links_and_anchor_once(formula, narrow):
    """扩大标题时保留富文本、上下标和公式，链接与锚点只输出一次。"""
    data = _one_page(
        [
            _block("unused", (40, 80, 100, 85), title=True, anchor="head"),
            _block("BODY", (220, 180, 360, 240) if narrow else (40, 180, 300, 240), index=1),
        ]
    ).to_dict()
    data["pages"][0]["blocks"][0]["content"] = [
        {"type": "text", "content": "RICH "},
        {"type": "text", "content": "BOLD ", "styles": ["bold"]},
        {"type": "text", "content": "SUPER ", "styles": ["superscript"]},
        {"type": "equation_inline", "content": formula},
        {"type": "hyperlink", "url": "#head", "content": [{"type": "text", "content": "JUMP"}]},
    ]
    artifact, plans = _render(MiddleJson.from_dict(data))
    assert _title(plans)["expanded"] and _title(plans)["final_font_size"] == 12.5
    sizes = _sizes(artifact.content)
    assert any("RICH" in text for text in sizes) and any("JUMP" in text for text in sizes)
    assert not any(d.code == "pdf_duplicate_anchor" for d in artifact.diagnostics)
    with PDFDocument(artifact.content) as document:
        rect = _title(plans)["draw_bbox_pt"]
        ink = [
            char["tight_bbox"]
            for char in document.get_page_chars_with_geometry(0).chars
            if char["char"].strip() and (char["bbox"][0] < 150 if narrow else char["bbox"][1] < 160) and char["tight_bbox"]
        ]
        ink.extend(path.bbox for path in document.get_page_path_infos(0))
        assert ink
        assert all(
            box[0] >= rect[0] - 0.5 and box[1] >= rect[1] - 0.5 and box[2] <= rect[2] + 0.5 and box[3] <= rect[3] + 0.5
            for box in ink
        )
