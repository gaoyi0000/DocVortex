"""验证 PDF 日志分级不改变结构化诊断及其去重行为。"""

from __future__ import annotations

import pytest
from loguru import logger

from docvortex.render._internal.pdf.diagnostics import collect_pdf_diagnostics, report_pdf_diagnostic
from docvortex.result import Diagnostic


@pytest.mark.parametrize(
    "code,level",
    [
        ("pdf_title_layout_expanded", "DEBUG"),
        ("pdf_layout_scaled", "DEBUG"),
        ("pdf_layout_small_text", "WARNING"),
        ("pdf_title_geometry_conflict", "WARNING"),
        ("pdf_image_unavailable", "WARNING"),
        ("pdf_formula_fallback", "WARNING"),
        ("unknown_diagnostic", "WARNING"),
    ],
)
def test_log_level_preserves_structured_diagnostics(code: str, level: str) -> None:
    """按真实日志级别捕获输出，重复诊断仍只在结构化列表保存一次。"""
    records: list[str] = []
    warnings: list[str] = []
    debug_sink = logger.add(records.append, level="DEBUG", format="{level.name}|{message}")
    warning_sink = logger.add(warnings.append, level="WARNING", format="{level.name}|{message}")
    try:
        with collect_pdf_diagnostics() as items:
            report_pdf_diagnostic(code, "example", 4)
            report_pdf_diagnostic(code, "example", 4)
        assert items == [Diagnostic(code, "example", 4)]
        assert [str(message).strip() for message in records] == [f"{level}|{code}: example"] * 2
        assert len(warnings) == (2 if level == "WARNING" else 0)
    finally:
        logger.remove(debug_sink)
        logger.remove(warning_sink)
