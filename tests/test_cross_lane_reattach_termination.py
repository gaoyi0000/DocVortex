"""回归测试：`_reattach_cross_lane_short_tails` 必须终止。

背景：该函数的搬迁判据可互相满足（短尾行从 A 迁到 B 后，下一轮又满足"从 B 迁回 A"），
而循环没有收敛保证 ⇒ A→B→A→B 无限往复，调用方（mineru-api）单核 100% 永久卡死。
最小复现无需真实文档，见对应 issue。
"""

from __future__ import annotations

import threading
import time

from docvortex.analyzers.native.pdf.line_layout import _reattach_cross_lane_short_tails
from docvortex.analyzers.native.pdf.models import _LineItem, _TextLane

_DEADLINE_SECONDS = 5.0


def _make_line(text: str, bbox: tuple[float, float, float, float], index: int) -> _LineItem:
    return _LineItem(
        text=text,
        bbox=bbox,
        angle=0,
        source_index=index,
        effective_height=bbox[3] - bbox[1],
    )


def _oscillating_lanes() -> list[_TextLane]:
    """两条边界相同、且能互相"迁回"的 lane + 一条落在 A 中的短尾行。"""
    lane_a = _TextLane(left=0.0, right=200.0)
    lane_b = _TextLane(left=0.0, right=200.0)
    prev_a = _make_line("prev in A", (10.0, 100.0, 150.0, 110.0), 0)
    prev_b = _make_line("prev in B", (10.0, 100.0, 150.0, 110.0), 1)
    tail = _make_line("short tail", (15.0, 118.0, 140.0, 128.0), 2)
    lane_a.lines.append((prev_a, prev_a.bbox))
    lane_b.lines.append((prev_b, prev_b.bbox))
    lane_a.lines.append((tail, tail.bbox))
    return [lane_a, lane_b]


def _state(lanes: list[_TextLane]) -> tuple[tuple[str, ...], ...]:
    """状态指纹：各 lane 内的行文本序列（搬迁只改归属，不改文本）。"""
    return tuple(tuple(item[0].text for item in lane.lines) for lane in lanes)


def test_does_not_loop_when_two_lanes_match_each_other() -> None:
    """回归：判据互可满足时函数必须返回；一旦状态重复即判定为环并失败。

    检测到重复状态就立刻失败（而不是干等超时），因此失败信息能直接给出环证据。
    """
    lanes = _oscillating_lanes()
    seen: dict[tuple[tuple[str, ...], ...], int] = {}
    error: list[BaseException] = []
    done = threading.Event()

    def worker() -> None:
        try:
            _reattach_cross_lane_short_tails(lanes, 10.0)
        except BaseException as exc:  # noqa: BLE001
            error.append(exc)
        finally:
            done.set()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    deadline = time.monotonic() + _DEADLINE_SECONDS
    cycle = None
    while not done.is_set() and time.monotonic() < deadline:
        snapshot = _state(lanes)
        if snapshot in seen:
            cycle = (seen[snapshot], snapshot)
            break
        seen[snapshot] = len(seen)
        time.sleep(0.001)

    if cycle is not None:
        raise AssertionError(
            "_reattach_cross_lane_short_tails 在两个 lane 之间往复振荡"
            f"（第 #{cycle[0]} 次采样已出现过同一状态，证明存在环）"
            f"；状态={cycle[1]}"
        )
    assert done.is_set(), (
        f"_reattach_cross_lane_short_tails 未在 {_DEADLINE_SECONDS}s 内返回 —— 跨栏振荡死循环回归"
    )
    assert not error, f"函数抛出异常: {error[0]!r}"


def test_no_oscillation_with_multiple_pairs() -> None:
    """回归：多对互可满足的 lane 同时存在时，也必须终止。"""
    lanes = _oscillating_lanes() + _oscillating_lanes()
    done = threading.Event()

    def worker() -> None:
        try:
            _reattach_cross_lane_short_tails(lanes, 10.0)
        finally:
            done.set()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout=_DEADLINE_SECONDS)
    assert done.is_set(), "多对互可满足 lane 场景下未终止 —— 跨栏振荡死循环回归"


def test_legitimate_move_still_happens() -> None:
    """正常路径不得被退出性保护吞掉：该搬的短尾仍要搬到正确 lane。"""
    lane_a = _TextLane(left=0.0, right=200.0)
    lane_b = _TextLane(left=210.0, right=400.0)  # lane_width = 190
    prev_a = _make_line("A prev", (10.0, 100.0, 150.0, 110.0), 0)
    prev_b = _make_line("B prev", (215.0, 100.0, 365.0, 110.0), 1)          # 宽 150 >= 0.65*190
    tail = _make_line("tail-belongs-to-B", (215.0, 118.0, 365.0, 128.0), 2)  # 宽 150 <= 0.85*190
    lane_a.lines.append((prev_a, prev_a.bbox))
    lane_b.lines.append((prev_b, prev_b.bbox))
    lane_a.lines.append((tail, tail.bbox))

    done = threading.Event()

    def worker() -> None:
        try:
            _reattach_cross_lane_short_tails([lane_a, lane_b], 10.0)
        finally:
            done.set()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout=_DEADLINE_SECONDS)

    assert done.is_set()
    assert [item[0].text for item in lane_b.lines] == ["B prev", "tail-belongs-to-B"]
    assert [item[0].text for item in lane_a.lines] == ["A prev"]
