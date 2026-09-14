"""收集一次 PDF 导出的结构化诊断，同时保留底层日志。"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

from loguru import logger

from ....result import Diagnostic


_diagnostics: ContextVar[list[Diagnostic] | None] = ContextVar("pdf_diagnostics", default=None)
_DEBUG_DIAGNOSTIC_CODES = frozenset({"pdf_title_layout_expanded", "pdf_layout_scaled"})


@contextmanager
def collect_pdf_diagnostics() -> Iterator[list[Diagnostic]]:
    """隔离并发或重入调用的诊断，退出时恢复外层收集器。"""
    items: list[Diagnostic] = []
    token = _diagnostics.set(items)
    try:
        yield items
    finally:
        _diagnostics.reset(token)


def report_pdf_diagnostic(code: str, message: str, page_index: int | None = None) -> None:
    """PDF 渲染诊断统一使用 DEBUG 日志，结构化诊断保持完整。"""
    logger.debug("{}: {}", code, message)
    items = _diagnostics.get()
    if items is not None:
        diagnostic = Diagnostic(code, message, page_index)
        if diagnostic not in items:
            items.append(diagnostic)
