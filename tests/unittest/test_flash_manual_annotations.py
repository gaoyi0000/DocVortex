"""用完整原件验证人工标注，定位依赖物理页和区域而不是修复后的块序号。"""

from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re

import pytest
from bs4 import BeautifulSoup

from docvortex.analyzers.native import PdfModel
from docvortex.document.pdf import PDFDocument
from docvortex.postprocess.pages import model_json_to_pages
from docvortex.schema import ModelJson
from tools.review_flash_annotations import check_case, contains, visible

ROOT = Path(__file__).parents[2]
MANIFEST = json.loads((ROOT / "tests/fixtures/flash_manual_annotations.json").read_text(encoding="utf-8"))
DOCUMENTS = {document["name"]: document for document in MANIFEST["documents"]}


@lru_cache(maxsize=None)
def _model(name: str) -> list[list[dict]]:
    """每份完整原件仅解析一次，保留页眉、字体及参考文献所需的跨页上下文。"""
    document = DOCUMENTS[name]
    source = ROOT / document["path"]
    assert hashlib.sha256(source.read_bytes()).hexdigest() == document["sha256"]
    with PDFDocument(str(source)) as pdf:
        assert pdf.page_count == document["page_count"]
        return PdfModel().predict(pdf)


@pytest.mark.parametrize(
    "name,case",
    [
        (name, case)
        for name, document in DOCUMENTS.items()
        for case in document["cases"]
        if case["anchors"]
        and case["operation"] in {"merge", "caption", "title", "table", "equation", "code", "logo", "footnote"}
    ],
    ids=[
        case["id"]
        for document in DOCUMENTS.values()
        for case in document["cases"]
        if case["anchors"]
        and case["operation"] in {"merge", "caption", "title", "table", "equation", "code", "logo", "footnote"}
    ],
)
def test_annotation_members_have_expected_owner(name: str, case: dict) -> None:
    """逐项检查所标原始成员的类型和完整归属，不能只靠总块数通过。"""
    result = check_case(case, _model(name)[case["page"] - 1])
    assert result["status"] == "geometry_pass", result


@pytest.mark.parametrize(
    "name,page,allowed,required",
    [
        ("nougat", 3, [0.12, 0.075, 0.885, 0.39], [0.13, 0.09, 0.87, 0.373]),
        ("mmlu_redux", 2, [0.49, 0.33, 0.835, 0.56], [0.51, 0.35, 0.815, 0.535]),
        ("mmlu_redux", 5, [0.165, 0.08, 0.835, 0.39], [0.18, 0.10, 0.82, 0.36]),
        ("nash_review", 3, [0.065, 0.065, 0.94, 0.745], [0.09, 0.09, 0.915, 0.733]),
        ("nash_review", 5, [0.065, 0.345, 0.94, 0.815], [0.09, 0.37, 0.92, 0.80]),
        ("nash_review", 8, [0.075, 0.16, 0.94, 0.81], [0.10, 0.18, 0.90, 0.80]),
        ("k2_treap", 5, [0.08, 0.56, 0.93, 0.91], [0.11, 0.58, 0.90, 0.90]),
        ("k2_treap", 6, [0.065, 0.63, 0.94, 0.91], [0.10, 0.65, 0.89, 0.90]),
        ("k2_treap", 8, [0.065, 0.065, 0.94, 0.325], [0.10, 0.08, 0.89, 0.315]),
        ("k2_treap", 13, [0.09, 0.065, 0.93, 0.697], [0.107, 0.08, 0.897, 0.69]),
    ],
)
def test_whole_figure_covers_ink_and_excludes_body(name: str, page: int, allowed: list, required: list) -> None:
    """同时限制最小覆盖和最大范围，不能靠扩大整页图片来满足成员归属。"""
    blocks = _model(name)[page - 1]
    images = [block for block in blocks if block["type"] == "image" and contains(block["bbox"], required)]
    assert len(images) == 1
    assert contains(allowed, images[0]["bbox"])
    assert not any(
        block["type"] in {"text", "paragraph_title", "equation", "code", "header"}
        and contains(images[0]["bbox"], block["bbox"], 0.001)
        for block in blocks
    )


@pytest.mark.parametrize(
    "name,page,prefix",
    [
        ("nougat", 5, "Figure 4:"),
        ("nougat", 6, "Figure 5:"),
        ("nougat", 8, "Figure 6:"),
        ("nougat", 13, "Table A.1:"),
        ("frames_v1", 8, "Figure 4:"),
        ("frames_v2", 5, "Figure 2:"),
        ("fornax", 8, "Fig. 7."),
        ("k2_treap", 11, "Fig. 11."),
        ("k2_treap", 12, "Fig. 12."),
        ("k2_treap", 13, "Fig. 13."),
        ("k2_treap", 14, "Fig. 14."),
    ],
)
def test_caption_survives_final_visual_grouping(name: str, page: int, prefix: str) -> None:
    """caption 在最终严格协议中仍有正确父容器，不能在后处理阶段退回普通正文。"""
    model = _model(name)
    pages = model_json_to_pages(
        ModelJson(
            pages=model,
            page_index_map=[],
            metadata={"file_suffix": "pdf", "producer": {"name": "docvortex", "version": "test"}},
        )
    )
    pending = [block.model_dump(mode="json") for block in pages[page - 1].blocks]
    found = []
    while pending:
        block = pending.pop()
        if visible(block.get("content")).startswith(prefix) and block["type"].endswith("_caption"):
            found.append(block)
        if isinstance(block.get("content"), list):
            pending.extend(item for item in block["content"] if isinstance(item, dict) and "bbox" in item)
    assert len(found) == 1


def test_table_description_rows_are_complete() -> None:
    """两版长描述表均保留表头和五种推理类型，逐格恢复不只扩大表框。"""
    for name in ("frames_v1", "frames_v2"):
        tables = [block for block in _model(name)[3] if block["type"] == "table"]
        assert len(tables) == 1
        soup = BeautifulSoup(tables[0]["content"], "html.parser")
        rows = soup.find_all("tr")
        assert len(rows) == 6
        assert [row.find_all(["td", "th"])[0].get_text(" ", strip=True) for row in rows][-2:] == [
            "Temporal Reasoning",
            "Post-Processing",
        ]
        assert "Roman numerals" in rows[-1].get_text(" ", strip=True)


def test_repeated_bold_prompts_form_five_paragraphs() -> None:
    """紧排行距中的五个粗体引导段单独成段，粗体仍由行内样式表达。"""
    paragraphs = [block for block in _model("mmlu_redux")[6] if block["type"] == "text" and 0.41 < block["bbox"][1] < 0.58]
    assert len(paragraphs) == 5
    assert all(
        any("bold" in span.get("styles", []) for span in block["content"] if isinstance(span, dict)) for block in paragraphs
    )


def test_reference_entries_do_not_merge_or_turn_into_equations() -> None:
    """参考条目边界、年份及 DOI 普通尾行不会被误合并或公式化。"""
    page = _model("frames_v2")[8]
    references = [block for block in page if block["type"] == "text" and block["bbox"][0] > 0.5 and block["bbox"][1] > 0.27]
    google = [block for block in references if visible(block["content"]).startswith("Google.")]
    assert len(google) == 2
    assert "2024a" in visible(google[0]["content"]) and "2024b" not in visible(google[0]["content"])
    assert "2024b" in visible(google[1]["content"])
    assert not any(block["type"] == "equation" for block in page)
    final = _model("connexin")[4]
    assert sum(bool(re.match(r"^2[12][.] ", visible(block["content"]))) for block in final if block["type"] == "text") == 2
    assert not any(block["type"] == "equation" for block in final)


def test_page_footnote_does_not_capture_neighboring_column() -> None:
    """短脚注线只认领同栏文字；同高度的右栏正文仍保持正文身份。"""
    page = _model("fornax")[5]
    notes = [block for block in page if block["type"] == "page_footnote"]
    assert notes and all(block["bbox"][2] < 0.5 for block in notes)
    assert "and x − z planes" not in " ".join(visible(block["content"]) for block in notes)
    body = " ".join(visible(block["content"]) for block in page if block["type"] == "text" and block["bbox"][0] > 0.5)
    assert "and x − z planes" in body


def test_numbered_discussion_items_keep_separate_members() -> None:
    """两个编号论点各自包含续行，第二项的解释不能留在第一项或另成一块。"""
    page = _model("fornax")[10]
    first = [block for block in page if block["type"] == "text" and visible(block["content"]).startswith("1. Two")]
    second = [block for block in page if block["type"] == "text" and visible(block["content"]).startswith("2. ")]
    assert len(first) == len(second) == 1
    assert "2. " not in visible(first[0]["content"])
    assert "This is illustrated" in visible(second[0]["content"])


@pytest.mark.parametrize(
    "page,top,bottom,count",
    [
        (9, 0.18, 0.395, 1),
        (10, 0.07, 0.49, 2),
        (11, 0.07, 0.29, 1),
        (12, 0.29, 0.515, 1),
        (13, 0.07, 0.697, 1),
        (14, 0.07, 0.28, 1),
    ],
)
def test_vector_chart_labels_stay_in_the_figure(page: int, top: float, bottom: float, count: int) -> None:
    """图例、坐标文字和子图标题不能残留为正文、页眉或伪代码。"""
    blocks = _model("k2_treap")[page - 1]
    assert sum(block["type"] == "image" for block in blocks) == count
    assert not [
        block
        for block in blocks
        if top < block["bbox"][1] < bottom and block["type"] in {"text", "header", "paragraph_title", "code", "equation"}
    ]


def test_independent_matrix_figures_are_not_joined_across_captions() -> None:
    """同页三个矩阵和一张树图各有独立图题，不能一并扩成整页图片。"""
    page = _model("k2_treap")[2]
    assert sum(block["type"] == "image" for block in page) == 4
    captions = [visible(block["content"]) for block in page if block["type"] == "caption"]
    assert all(any(text.startswith(f"Fig. {index}.") for text in captions) for index in range(1, 5))


def test_inline_bold_titles_keep_emphasis_and_real_section_titles() -> None:
    """段首强调并入正文后保持粗体，独立节标题仍按标题输出。"""
    page = _model("nougat")[1]
    for prefix in ("Encoder", "Decoder"):
        blocks = [block for block in page if visible(block["content"]).startswith(prefix)]
        assert len(blocks) == 1 and blocks[0]["type"] == "text"
        assert any(prefix in visible(span) and "bold" in span.get("styles", []) for span in blocks[0]["content"])
    assert any(block["type"] == "paragraph_title" and visible(block["content"]) == "3 Model" for block in page)
    page = _model("nougat")[3]
    assert not any(
        block["type"] == "paragraph_title" and visible(block["content"]) in {"arXiv", "PMC", "IDL"} for block in page
    )


def test_reference_tail_is_not_a_repeated_header() -> None:
    """同一位置的不同卷页编号仍归属于各自参考条目。"""
    for page_index, number, year in ((13, 97, "2013;190"), (14, 138, "2015;63")):
        page = _model("nash_review")[page_index]
        entry = next(block for block in page if block["type"] == "text" and visible(block["content"]).startswith(f"[{number}]"))
        assert year in visible(entry["content"])
        assert not any(block["type"] == "header" and year in visible(block["content"]) for block in page)


def test_public_parse_materializes_formula_images_and_bold_html() -> None:
    """通过真实公共入口及 HTML 导出验证图片载荷与行内粗体，不使用检测金标补丁。"""
    from docvortex import parse, render_artifact
    from docvortex.schema import EquationBlock

    result = parse(ROOT / DOCUMENTS["nougat"]["path"], keep_model_json=True)
    for index in (7, 8):
        equations = [block for block in result.middle_json.pages[index].blocks if isinstance(block, EquationBlock)]
        assert len(equations) == 1
        assert equations[0].content == "" and (equations[0].image_path or equations[0].image_base64)
    html = render_artifact(result.middle_json, "html", assets=result.assets).content.decode()
    soup = BeautifulSoup(html, "html.parser")
    assert any("Encoder" in tag.get_text() for tag in soup.find_all(["strong", "b"]))
    assert len(soup.find_all("img")) >= 4


def test_front_matter_institutions_keep_numbers_order_and_email() -> None:
    """首页机构逐条归组，分离上标编号仍归入机构，日期不会进入最后一个机构。"""
    blocks = _model("fornax")[0]
    institutions = [block for block in blocks if block["type"] == "text" and 0.21 < block["bbox"][1] < 0.36]
    assert [re.match(r"^\d+", visible(block["content"])).group() for block in institutions] == list(map(str, range(1, 10)))
    assert "pierfrancesco.dicintio@cnr.it" in visible(institutions[0]["content"])
    assert "Draft" not in visible(institutions[-1]["content"])
    assert any(visible(block["content"]).startswith("Draft, August") for block in blocks)


def test_hanging_references_mix_single_and_wrapped_entries() -> None:
    """紧排参考文献依靠悬挂缩进成条，续行年份与期刊尾行不能游离。"""
    blocks = _model("fornax")[12]
    references = [block for block in blocks if block["type"] == "text" and (block["bbox"][0] > 0.5 or block["bbox"][1] > 0.44)]
    assert len(references) == 82
    assert visible(references[0]["content"]).startswith("Andrade,")
    assert visible(references[-1]["content"]).startswith("Wang,")
    for prefix, tail in (
        ("Borukhovetskaya,", "2022, MNRAS, 509, 5330"),
        ("Khalaj,", "Society, 457, 479"),
        ("Garavito-Camargo,", "Journal, 919, 109"),
    ):
        matches = [block for block in references if visible(block["content"]).startswith(prefix)]
        assert len(matches) == 1 and tail in visible(matches[0]["content"])
    assert not any(block["type"] == "equation" for block in blocks)


def test_fraction_bar_does_not_claim_denominator_or_body_as_footnote() -> None:
    """编号分式完整包含分子与分母，分数线下方正文不被误认成脚注。"""
    blocks = _model("fornax")[4]
    equations = [block for block in blocks if block["type"] == "equation"]
    assert len(equations) == 1 and contains(equations[0]["bbox"], [0.538, 0.716, 0.614, 0.744], 0.001)
    for prefix in ("The initial conditions", "We present here the results"):
        matched = [block for block in blocks if visible(block["content"]).startswith(prefix)]
        assert len(matched) == 1 and matched[0]["type"] == "text"
    assert not any(block["type"] == "page_footnote" for block in blocks)
