"""覆盖历史 bbox 冻结容差比较助手的全部裁决路径。"""

from __future__ import annotations

import pytest

from _flash_pdf_test_utils import (
    _assert_history_page,
    _assert_page_bboxes_within,
    _bbox_grid_steps,
    _page_bbox_fingerprint,
    _page_fingerprint,
)


def _block(bbox: tuple[float, float, float, float], content: str = "sample") -> dict:
    """构造与历史断言路径一致的公开输出块。"""

    return {"type": "text", "bbox": list(bbox), "content": content}


def test_exact_match_passes_without_allowance() -> None:
    """无任何放宽时，与参考完全一致的 bbox 通过。"""

    page = [_block((0.1, 0.2, 0.3, 0.4)), _block((0.5, 0.6, 0.7, 0.8))]
    _assert_page_bboxes_within(page, [(0.1, 0.2, 0.3, 0.4), (0.5, 0.6, 0.7, 0.8)], {}, ("doc", 1))


def test_delta_at_allowed_boundary_passes() -> None:
    """刻度差恰好等于允许值时通过，不因边界值失败。"""

    page = [_block((0.1, 0.2, 0.302, 0.4))]
    _assert_page_bboxes_within(page, [(0.1, 0.2, 0.3, 0.4)], {"0": {"x1": 2}}, ("doc", 1))
    page = [_block((0.1, 0.199, 0.3, 0.4))]
    _assert_page_bboxes_within(page, [(0.1, 0.2, 0.3, 0.4)], {"0": {"y0": 1}}, ("doc", 1))


def test_delta_one_step_beyond_allowance_fails() -> None:
    """超出允许值一刻度即失败，报告块索引、坐标、双方值与差值。"""

    page = [_block((0.1, 0.2, 0.303, 0.4))]
    with pytest.raises(AssertionError, match=r"'block', 0, 'x1'.*'delta', 3, 'allowed', 2"):
        _assert_page_bboxes_within(page, [(0.1, 0.2, 0.3, 0.4)], {"0": {"x1": 2}}, ("doc", 1))


def test_unconfigured_coordinate_change_fails() -> None:
    """未配置容差的坐标出现一刻度变化即失败。"""

    page = [_block((0.1, 0.2, 0.3, 0.401))]
    with pytest.raises(AssertionError, match=r"'block', 0, 'y1'"):
        _assert_page_bboxes_within(page, [(0.1, 0.2, 0.3, 0.4)], {"0": {"x1": 2}}, ("doc", 1))


def test_block_count_mismatch_fails() -> None:
    """块数与参考不符时失败，不允许部分比较。"""

    page = [_block((0.1, 0.2, 0.3, 0.4)), _block((0.5, 0.6, 0.7, 0.8))]
    with pytest.raises(AssertionError, match="block count"):
        _assert_page_bboxes_within(page, [(0.1, 0.2, 0.3, 0.4)], {}, ("doc", 1))


@pytest.mark.parametrize("bbox", [(0.1, 0.2, 0.3), (0.1, 0.2, 0.3, float("nan")), None])
def test_illegal_bbox_shape_or_value_fails(bbox) -> None:
    """坐标数量不是四或包含非有限值时失败。"""

    page = [{"type": "text", "bbox": bbox, "content": "sample"}]
    with pytest.raises(AssertionError):
        _assert_page_bboxes_within(page, [(0.1, 0.2, 0.3, 0.4)], {}, ("doc", 1))


def test_grid_steps_ignore_float_representation_noise() -> None:
    """量化网格整数刻度不受 0.001 浮点表示差影响。"""

    assert _bbox_grid_steps((0.117, 0.2, 0.3, 0.4)) == _bbox_grid_steps((0.117 + 1e-12, 0.2, 0.3, 0.4))
    assert _bbox_grid_steps((0.117, 0.2, 0.3, 0.4)) == [117, 200, 300, 400]


def test_history_page_assertion_rejects_content_or_order_change() -> None:
    """内容或顺序变化始终按内容指纹失败，不进入容差路径。"""

    reference_page = [_block((0.1, 0.2, 0.3, 0.4), "first"), _block((0.5, 0.6, 0.7, 0.8), "second")]
    expected = {
        "fingerprint": _page_fingerprint(reference_page),
        "bbox_fingerprint": _page_bbox_fingerprint(reference_page),
        "bbox_tolerance": {"platforms": ["linux"], "reference_blocks": [(0.1, 0.2, 0.3, 0.4), (0.5, 0.6, 0.7, 0.8)], "allowances": {}},
    }
    reordered = [reference_page[1], reference_page[0]]
    with pytest.raises(AssertionError, match="content"):
        _assert_history_page(reordered, expected, ("doc", 1), "linux")


def test_history_page_assertion_branches_on_platform() -> None:
    """容差仅在配置命中的平台生效，其余平台维持精确 bbox 指纹。"""

    reference_page = [_block((0.1, 0.2, 0.3, 0.4))]
    expected = {
        "fingerprint": _page_fingerprint(reference_page),
        "bbox_fingerprint": _page_bbox_fingerprint(reference_page),
        "bbox_tolerance": {"platforms": ["linux"], "reference_blocks": [(0.1, 0.2, 0.3, 0.4)], "allowances": {"0": {"x1": 2}}},
    }
    shifted = [_block((0.1, 0.2, 0.302, 0.4))]
    _assert_history_page(shifted, expected, ("doc", 1), "linux")
    with pytest.raises(AssertionError, match="bbox"):
        _assert_history_page(shifted, expected, ("doc", 1), "darwin")
    _assert_history_page(reference_page, expected, ("doc", 1), "darwin")
