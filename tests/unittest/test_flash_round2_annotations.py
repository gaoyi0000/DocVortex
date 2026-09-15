"""第二轮真实原件断言：段落语义边界、可见字符和容器成员同时验收。"""

from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

from test_flash_manual_annotations import _model
from tools.review_flash_annotations import visible

MANIFEST = json.loads((Path(__file__).parents[2] / "tests/fixtures/flash_round2_annotations.json").read_text(encoding="utf-8"))


def _starting(name: str, page: int, prefix: str) -> dict:
    """按可见文字起点定位，禁止使用修复后不稳定的块编号。"""
    matches = [block for block in _model(name)[page - 1] if visible(block.get("content")).startswith(prefix)]
    assert len(matches) == 1, (name, page, prefix)
    return matches[0]


@pytest.mark.parametrize(
    "name,page,prefixes",
    [
        ("nougat", 7, ["We present our results", "Both Nougat small and base"]),
        ("nougat", 9, ["Utility", "Nearly every dataset", "Generation Speed"]),
        ("nougat", 9, ["Future work", "The primary challenge"]),
        ("frames_v1", 1, ["Recent advancements", "To bridge this gap"]),
        ("frames_v2", 1, ["To bridge this gap", "Our work addresses"]),
        ("nash_review", 1, ["Non-alcoholic fatty liver disease", "NAFLD can be broadly"]),
        ("nash_review", 1, ["advances. Resolution", "Among individuals", "The development of a therapy"]),
    ],
)
def test_explicit_paragraph_boundaries(name: str, page: int, prefixes: list[str]) -> None:
    """明确的新段各自成为 text，段首提示不单独形成嵌套标题。"""
    matches = [_starting(name, page, prefix) for prefix in prefixes]
    assert all(block["type"] == "text" for block in matches)
    assert len({id(block) for block in matches}) == len(prefixes)
    for block in matches:
        assert sum(prefix in visible(block["content"]) for prefix in prefixes) == 1


def test_runin_paragraph_prompts_keep_bold() -> None:
    """段落拆分不丢失原有段首粗体。"""
    for prefix in ["Utility", "Generation Speed", "Future work"]:
        block = _starting("nougat", 9, prefix)
        assert any(prefix in visible(span) and "bold" in span.get("styles", []) for span in block["content"])


@pytest.mark.parametrize(
    "document,case",
    [(d, c) for d in MANIFEST["documents"] for c in d["cases"] if c["operation"] == "title"],
    ids=[c["id"] for d in MANIFEST["documents"] for c in d["cases"] if c["operation"] == "title"],
)
def test_independent_recurrent_headings(document: dict, case: dict) -> None:
    """全文重复样式的一至两行独立标题应整体识别，不能仅靠字重数值。"""
    expected = visible(case["anchors"][0]["content"])
    matches = [block for block in _model(document["name"])[case["page"] - 1] if visible(block["content"]) == expected]
    assert len(matches) == 1
    block = matches[0]
    assert block["type"] == "paragraph_title"
    assert visible(block["content"]) == expected


def test_nougat_numbered_url_footnotes_are_not_fraction_neighbors() -> None:
    """短正文尾行和 URL 脚注不构成分式，三个编号链接都归入脚注。"""
    page = _model("nougat")[4]
    for url in ["https://github.com/phfaist/pylatexenc", "https://mupdf.com/", "https://github.com/taleinat/fuzzysearch"]:
        found = [b for b in page if url in visible(b["content"])]
        assert len(found) == 1 and found[0]["type"] == "page_footnote"


def test_mmlu_native_form_owns_last_options_and_caption_binds() -> None:
    """图中最后一行选项进入图，图题前不再残留假正文屏障。"""
    page = _model("mmlu_redux")[1]
    found = [b for b in page if "A. Clark" in visible(b["content"])]
    assert len(found) == 1 and found[0]["type"] == "image"
    assert "D. Ebbinghaus" in visible(found[0]["content"])
    assert found[0]["bbox"][3] >= 0.546
    caption = _starting("mmlu_redux", 2, "Figure 1:")
    assert caption["type"] == "caption"
    assert (
        visible(caption["content"])
        == "Figure 1: Three examples of erroneous instances from MMLU Virology, College Chemistry, and Human Aging."
    )
    assert any("as missing context" in visible(b["content"]) and b["type"] == "text" for b in page)
    assert found[0]["bbox"][3] < caption["bbox"][1]


def test_mmlu_wrapped_body_merges_above_independent_wide_tail() -> None:
    """图旁原块 4、5、6 的窄行连续成段，恢复通栏的尾行独立且不混入 caption。"""
    body = _starting("mmlu_redux", 2, "We identify numerous errors")
    tail = _starting("mmlu_redux", 2, "documentation, it is difficult")
    caption = _starting("mmlu_redux", 2, "Figure 1:")
    assert body["type"] == tail["type"] == "text"
    assert visible(body["content"]).endswith(
        "as missing context. These errors appear randomly, and due to the lack of comprehensive"
    )
    assert "as C in MMLU)" in visible(body["content"])
    assert body["bbox"][2] < caption["bbox"][0]
    assert len(tail["lines"]) == 1
    assert tail["bbox"][1] >= caption["bbox"][3]
    assert "Human Aging." not in visible(body["content"]) + visible(tail["content"])


def test_confirmed_algorithm_is_complete_and_excluded_from_figure() -> None:
    """算法全部十二行只属于代码，图形边界不能侵入其末四行。"""
    page = _model("frames_v1")[7]
    code = [b for b in page if b["type"] == "code"]
    images = [b for b in page if b["type"] == "image"]
    assert len(code) == len(images) == 1
    assert re.findall(r"^\s*(\d+):", visible(code[0]["content"]), re.MULTILINE) == list(map(str, range(1, 13)))
    assert images[0]["bbox"][1] >= code[0]["bbox"][3]
    assert "return R" not in visible(images[0]["content"])


def test_full_width_affiliation_footnote_keeps_visual_row_order() -> None:
    """通栏机构脚注恢复三条实际行，不按上标拆出来的片段交错排列。"""
    page = _model("nash_review")[10]
    notes = [b for b in page if b["type"] == "page_footnote"]
    assert len(notes) == 1
    text = re.sub(r"\s+", "", visible(notes[0]["content"]))
    assert text.startswith("Affiliations1DepartmentofHepatology")
    assert "Germany;2BerlinInstituteofHealth,Berlin,Germany;3NAFLDResearchCenter" in text
    assert "UnitedStates;4DivisionofLiverDiseases" in text
    assert text.endswith("NewYork,NY,UnitedStates")
    assert not any(b["type"] == "text" and b["bbox"][1] > 0.82 for b in page)


def test_inline_footnote_fragment_is_reunited_with_its_own_note() -> None:
    """上标附近的同行续文与下一行属于同一脚注，右栏正文不被认领。"""
    page = _model("k2_treap")[9]
    found = [b for b in page if "which allow us to use it for" in visible(b["content"])]
    assert len(found) == 1 and found[0]["type"] == "page_footnote"
    assert "The dataset belongs to" in visible(found[0]["content"])
    assert visible(found[0]["content"]).endswith("our research.")
    assert found[0]["bbox"][2] < 0.5


def test_article_info_and_abstract_are_independent_text_regions() -> None:
    """弱表中的元数据与摘要恢复独立文本分区，不能把真正单元格表当作同类候选。"""
    page = _model("k2_treap")[0]
    assert not any(b["type"] == "table" and 0.3 < b["bbox"][1] < 0.6 for b in page)
    for text in ["articleinfo", "abstract"]:
        found = [b for b in page if re.sub(r"\s+", "", visible(b["content"])).casefold() == text]
        assert len(found) == 1 and found[0]["type"] == "paragraph_title"
    assert _starting("k2_treap", 1, "Efficient processing")["type"] == "text"


def test_clipped_browser_footer_is_not_visible_text() -> None:
    """嵌套 Form 外的浏览器页脚不参与任何分类，可见论文页码仍保留。"""
    page = _model("nougat")[16]
    assert not any(
        value in visible(b["content"]) for b in page for value in ["3.86.159.32", "10/03/2023, 17:22", "latex-ocr-demo"]
    )
    assert not any(visible(b["content"]).strip() == "1/1" for b in page)
    assert any(b["type"] == "page_number" and visible(b["content"]) == "17" for b in page)
