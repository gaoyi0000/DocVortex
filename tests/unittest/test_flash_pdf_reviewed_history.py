"""锁定 cefa1208 重放并逐页审阅后的历史输出；旧几何清单的陈旧条目不整体覆盖。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from _flash_pdf_test_utils import _page_bbox_fingerprint, _page_fingerprint, formula_detection_evidence
from test_flash_pdf_char_geometry import _read_pdf_fixture
from docvortex.analyzers.native.pdf.pipeline import _analyze_native_document
from docvortex.document.pdf import PDFDocument

ROOT = Path(__file__).parents[2]
MANIFEST = json.loads((ROOT / "tests/fixtures/flash_reviewed_history.json").read_text())


@pytest.mark.parametrize("document", MANIFEST["documents"], ids=lambda document: document["name"])
def test_reviewed_historical_pages_keep_content_order_types_and_bounds(document: dict) -> None:
    """覆盖 19 份 168 页的逐页类型、内容、阅读顺序和边界，公式文本使用既有检测证据辅助器。"""
    payload = _read_pdf_fixture(ROOT / document["path"])
    assert hashlib.sha256(payload).hexdigest() == document["sha256"]
    with PDFDocument(payload) as pdf, formula_detection_evidence():
        pages = _analyze_native_document(pdf)
    assert len(pages) == len(document["pages"])
    for index, (page, expected) in enumerate(zip(pages, document["pages"], strict=True)):
        assert _page_fingerprint(page) == expected["fingerprint"], (document["name"], index + 1, "content")
        assert _page_bbox_fingerprint(page) == expected["bbox_fingerprint"], (document["name"], index + 1, "bbox")
