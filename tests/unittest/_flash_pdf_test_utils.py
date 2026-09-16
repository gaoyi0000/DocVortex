from __future__ import annotations

import hashlib
import json
import math
from contextlib import contextmanager
from unittest.mock import patch
from typing import Any

from docvortex.analyzers.native.pdf import (
    models,
    pipeline,
)


_IGNORED_FINGERPRINT_KEYS = {
    "bbox",
    "lines",
    "image_path",
    "image_url",
    "img_path",
    "_layout_tree",
    # 临时段界证据由公共页面连续性测试验收，不属于可见内容或版面指纹。
    "_reference_start",
    "_paragraph_boundary",
}

_BBOX_GRID = 1000
_BBOX_COORD_NAMES = ("x0", "y0", "x1", "y1")


@contextmanager
def formula_detection_evidence():
    """语义金标检查清空前的检测证据；同时断言真实输出边界已将公式内容清空。

    仅供检测、编号归属和几何金标使用。公开解析及 renderer 测试不得使用此辅助器。
    """
    normalize = pipeline._normalize_output_block

    def capture(block, page_size):
        """保留最终检测证据供旧金标比较，避免图片化掩盖公式识别退化。"""
        output = normalize(block, page_size)
        if output is not None and output["type"] == "equation":
            assert output["content"] == ""
            output["content"] = pipeline._sanitize_pdf_control_text(block["content"], preserve_newlines=True)
        return output

    with patch.object(pipeline, "_normalize_output_block", capture):
        yield


def _sha256_bytes(value: bytes) -> str:
    """返回测试载荷的稳定 SHA256。"""

    return hashlib.sha256(value).hexdigest()


def _canonical_value(value: Any) -> Any:
    """移除允许变化的几何与大载荷，保留语义标签、层级和可见内容。"""

    if isinstance(value, dict):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if key not in _IGNORED_FINGERPRINT_KEYS
        }
    if isinstance(value, list):
        return [_canonical_value(item) for item in value]
    if isinstance(value, str) and len(value) > 2048:
        return {"sha256": _sha256_bytes(value.encode("utf-8", errors="replace")), "length": len(value)}
    return value


def _visible_text(value: Any) -> str:
    """递归提取指纹计算使用的可见文本。"""

    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_visible_text(item) for item in value)
    if isinstance(value, dict):
        return _visible_text(value.get("content", ""))
    return ""


def _page_fingerprint(page: list[dict[str, Any]]) -> str:
    """计算忽略输出 bbox 后的逐页语义指纹。"""

    payload = json.dumps(_canonical_value(page), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha256_bytes(payload.encode("utf-8"))


def _page_bbox_fingerprint(page: list[dict[str, Any]]) -> str:
    """计算类型、文本顺序和公开 bbox 共同组成的逐页指纹。"""

    payload = [
        {
            "type": block.get("type"),
            "bbox": block.get("bbox"),
            "text_sha256": _sha256_bytes(_visible_text(block.get("content")).encode("utf-8", errors="replace")),
        }
        for block in page
    ]
    return _sha256_bytes(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"))


def _bbox_grid_steps(bbox: Any) -> list[int]:
    """按 0.001 输出量化网格取整数刻度，避免浮点表示差造成边界误判。"""

    values = list(bbox) if isinstance(bbox, (list, tuple)) else None
    assert values is not None and len(values) == 4, ("bbox must hold four coordinates", bbox)
    assert all(isinstance(value, (int, float)) and math.isfinite(value) for value in values), ("bbox must be finite", bbox)
    return [round(float(value) * _BBOX_GRID) for value in values]


def _assert_page_bboxes_within(
    page: list[dict[str, Any]],
    reference_bboxes: list[list[float]],
    allowances: dict[str, dict[str, int]],
    context: tuple[Any, ...],
) -> None:
    """逐块比较 bbox 的整数刻度差；未配置坐标的容差为零，超差即失败。

    allowances 的块索引与坐标名为 JSON 字符串键，例如 {"3": {"y0": 2}}。
    """

    assert len(page) == len(reference_bboxes), (*context, "block count", len(page), len(reference_bboxes))
    for index, (block, reference) in enumerate(zip(page, reference_bboxes, strict=True)):
        actual_steps = _bbox_grid_steps(block.get("bbox"))
        reference_steps = _bbox_grid_steps(reference)
        allowed = allowances.get(str(index), {})
        for name, actual, expected in zip(_BBOX_COORD_NAMES, actual_steps, reference_steps, strict=True):
            delta = actual - expected
            limit = int(allowed.get(name, 0))
            assert abs(delta) <= limit, (
                *context,
                "block",
                index,
                name,
                "expected",
                expected,
                "actual",
                actual,
                "delta",
                delta,
                "allowed",
                limit,
            )


def _assert_history_page(page: list[dict[str, Any]], expected: dict[str, Any], context: tuple[Any, ...], platform: str) -> None:
    """内容指纹始终精确校验；仅平台命中冻结容差的页面用整数刻度比较替代 bbox 指纹。"""

    assert _page_fingerprint(page) == expected["fingerprint"], (*context, "content")
    tolerance = expected.get("bbox_tolerance")
    if tolerance is not None and platform in tolerance["platforms"]:
        _assert_page_bboxes_within(page, tolerance["reference_blocks"], tolerance["allowances"], context)
    else:
        assert _page_bbox_fingerprint(page) == expected["bbox_fingerprint"], (*context, "bbox")


def _geometry_summary_mismatch(
    file_name: str,
    expected_document: dict[str, Any],
    actual_document: dict[str, Any],
) -> dict[str, Any] | None:
    """比较版本化几何摘要，并返回缺失或数值漂移的结构化诊断。"""

    expected_summary = expected_document.get("expected_geometry_summary")
    actual_summary = actual_document.get("geometry_summary")
    if not isinstance(expected_summary, dict):
        return {
            "file": file_name,
            "reason": "geometry_summary_expectation_missing",
        }
    if actual_summary != expected_summary:
        return {
            "file": file_name,
            "reason": "geometry_summary_mismatch",
            "expected": expected_summary,
            "actual": actual_summary,
        }
    return None


def _text_line(
    text: str,
    bbox: tuple[float, float, float, float],
    source_index: int,
    *,
    angle: int = 0,
    visual_row_id: int | None = None,
    run_index: int = 0,
    split_from_row: bool = False,
    effective_height: float | None = None,
    font_signature: tuple[str, int] | None = None,
    font_coverage: float = 0.0,
    dominant_font_weight: float | None = None,
    median_glyph_width: float | None = None,
    leading_emphasis_width: float | None = None,
    leading_typography_width: float | None = None,
    paragraph_formula_context: bool = False,
    preserve_split_boundary: bool = False,
    semantic_type: str | None = None,
    ink_bbox: tuple[float, float, float, float] | None = None,
) -> models._LineItem:
    """构造栏带、排版恢复与图形标签测试使用的原生文本行。"""

    return models._LineItem(
        text=text,
        bbox=bbox,
        ink_bbox=ink_bbox,
        angle=angle,
        source_index=source_index,
        visual_row_id=visual_row_id,
        run_index=run_index,
        effective_height=effective_height or (bbox[3] - bbox[1]),
        font_signature=font_signature,
        font_coverage=font_coverage,
        dominant_font_weight=dominant_font_weight,
        median_glyph_width=median_glyph_width,
        leading_emphasis_width=leading_emphasis_width,
        leading_typography_width=leading_typography_width,
        paragraph_formula_context=paragraph_formula_context,
        split_from_row=split_from_row,
        preserve_split_boundary=preserve_split_boundary,
        semantic_type=semantic_type,
    )


def _prepared_text_page(
    *lines: models._LineItem,
    page_size: tuple[float, float] = (100.0, 100.0),
) -> models._PreparedPage:
    """构造跨页边缘类型测试使用的无容器轻量页面。"""

    return models._PreparedPage(
        page_size=page_size,
        remaining_lines=list(lines),
        table_bboxes=[],
        drawing_lines=[],
        fixed_blocks=[],
    )
