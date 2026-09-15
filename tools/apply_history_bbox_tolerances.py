"""依据诊断差异报告把按坐标冻结的 bbox 容差写入历史夹具，不重新批准基线。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

_COORD_NAMES = ("x0", "y0", "x1", "y1")


def _load(path: Path) -> object:
    """以显式 UTF-8 读取 JSON，工具产物不依赖平台区域设置。"""

    return json.loads(path.read_text(encoding="utf-8"))


def _verify_reference_matches_fixture(fixture: dict, reference: dict) -> None:
    """参考捕获必须与夹具逐页指纹一致，防止借补字段重新批准基线。"""

    by_name = {document["name"]: document for document in reference}
    for document in fixture["documents"]:
        capture = by_name[document["name"]]
        assert capture["sha256"] == document["sha256"], ("source differs", document["name"])
        assert len(capture["pages"]) == len(document["pages"]), ("page count", document["name"])
        for index, (page, expected) in enumerate(zip(capture["pages"], document["pages"], strict=True)):
            assert page["fingerprint"] == expected["fingerprint"], ("reference replay drift", document["name"], index + 1, "content")
            assert page["bbox_fingerprint"] == expected["bbox_fingerprint"], (
                "reference replay drift",
                document["name"],
                index + 1,
                "bbox",
            )


def _collect_allowances(reports: list[dict]) -> dict[tuple[str, int], dict[str, dict[str, int]]]:
    """汇总各诊断矩阵的逐块坐标最大实测刻度差；出现内容变化立即拒绝。"""

    collected: dict[tuple[str, int], dict[int, dict[str, int]]] = {}
    for report in reports:
        for document in report["documents"]:
            if document["content_changed_pages"]:
                raise SystemExit(f"content changes are regressions, not tolerance material: {document['name']}")
            for page in document["changed_pages"]:
                page_allowances = collected.setdefault((document["name"], page["page"]), {})
                for block in page["blocks"]:
                    coords = page_allowances.setdefault(block["index"], {})
                    for name in _COORD_NAMES:
                        delta = abs(block["delta_steps"].get(name, 0))
                        if delta:
                            coords[name] = max(coords.get(name, 0), delta)
    return {
        key: {str(block): coords for block, coords in sorted(blocks.items())}
        for key, blocks in collected.items()
    }


def main() -> None:
    """把冻结容差写入夹具并升级 schema；容差取最大实测刻度差，不加余量。"""
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--reference", type=Path, required=True, help="参考平台（如 macOS）的捕获 summary.json")
    parser.add_argument("--diff", type=Path, action="append", required=True, help="候选平台差异报告，可多次提供")
    parser.add_argument("--platform", required=True, help="容差生效的平台标识（sys.platform 值，如 linux）")
    parser.add_argument("--reason", required=True, help="例外原因，说明字体回退等归因")
    parser.add_argument("--source", required=True, help="诊断来源，如 PR 与差异产物名称")
    args = parser.parse_args()

    fixture = _load(args.fixture)
    reference = _load(args.reference)
    reports = [_load(path) for path in args.diff]
    _verify_reference_matches_fixture(fixture, reference)
    allowances = _collect_allowances(reports)
    assert allowances, "no bbox differences found in the provided diff reports"

    capture_by_name = {document["name"]: document for document in reference}
    applied = []
    for document in fixture["documents"]:
        for page in document["pages"]:
            page_allowances = allowances.get((document["name"], page["page_index"] + 1))
            if page_allowances is None:
                page.pop("bbox_tolerance", None)
                continue
            capture_page = capture_by_name[document["name"]]["pages"][page["page_index"]]
            page["bbox_tolerance"] = {
                "platforms": [args.platform],
                "reason": args.reason,
                "source": args.source,
                "reference_blocks": [block["bbox"] for block in capture_page["blocks"]],
                "allowances": page_allowances,
            }
            applied.append((document["name"], page["page_index"] + 1, page_allowances))
    fixture["schema_version"] = 2
    fixture["bbox_tolerance_policy"] = "未配置坐标容差为零；容差按 0.001 输出网格的整数刻度差冻结，取诊断矩阵最大实测值"
    args.fixture.write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"pages_with_tolerance": len(applied), "platform": args.platform}, ensure_ascii=False))
    for name, page_number, page_allowances in applied:
        print(name, f"page {page_number}", json.dumps(page_allowances, ensure_ascii=False))


if __name__ == "__main__":
    main()
