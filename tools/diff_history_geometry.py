"""比较两份历史几何捕获的逐块 bbox，报告坐标刻度差与内容指纹差异，不修改任何基线。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

_COORD_NAMES = ("x0", "y0", "x1", "y1")
_GRID = 1000


def _read_summary(directory: Path) -> dict[str, dict]:
    """按文档名索引捕获 summary，缺失即视为捕获不完整。"""
    documents = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    return {document["name"]: document for document in documents}


def _steps(bbox: list[float]) -> list[int]:
    """按 0.001 输出量化网格取整数刻度，避免浮点表示差造成边界误判。"""
    return [round(value * _GRID) for value in bbox]


def _coordinate_points(delta_steps: dict[str, int], page_size: list[float]) -> dict[str, float]:
    """把刻度差换算为 PDF point，横向用页宽、纵向用页高。"""
    return {
        name: round(delta_steps[name] / _GRID * page_size[0 if name.startswith("x") else 1], 3)
        for name in _COORD_NAMES
    }


def compare_document(reference: dict, candidate: dict) -> dict:
    """逐页比较内容指纹与整数刻度 bbox；内容差异与几何差异分开归因。"""
    assert reference["sha256"] == candidate["sha256"], ("source differs", reference["name"])
    pages = []
    max_steps = 0
    content_changed = 0
    for index, (ref_page, cand_page) in enumerate(zip(reference["pages"], candidate["pages"], strict=True)):
        ref_blocks, cand_blocks = ref_page["blocks"], cand_page["blocks"]
        page_content_changed = ref_page["fingerprint"] != cand_page["fingerprint"] or len(ref_blocks) != len(cand_blocks)
        content_changed += page_content_changed
        entries = []
        if not page_content_changed:
            for block_index, (ref_block, cand_block) in enumerate(zip(ref_blocks, cand_blocks, strict=True)):
                delta = {
                    name: cand - ref
                    for name, ref, cand in zip(_COORD_NAMES, _steps(ref_block["bbox"]), _steps(cand_block["bbox"]), strict=True)
                }
                if any(delta.values()):
                    max_steps = max(max_steps, max(abs(value) for value in delta.values()))
                    entries.append(
                        {
                            "index": block_index,
                            "type": cand_block.get("type"),
                            "text": cand_block.get("text"),
                            "ref_bbox": ref_block["bbox"],
                            "cand_bbox": cand_block["bbox"],
                            "delta_steps": delta,
                            "delta_points": _coordinate_points(delta, ref_page["page_size"]),
                        }
                    )
        if page_content_changed or entries:
            pages.append({"page": index + 1, "content_changed": page_content_changed, "blocks": entries})
    return {
        "name": reference["name"],
        "max_abs_steps": max_steps,
        "content_changed_pages": content_changed,
        "changed_pages": pages,
    }


def main() -> None:
    """输出参考/候选的逐块差异报告；仅内容指纹变化视为回归并以非零码退出。"""
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    reference, candidate = _read_summary(args.reference), _read_summary(args.candidate)
    assert reference.keys() == candidate.keys(), "captured document sets differ"
    report = {
        "reference_environment": next(iter(reference.values()))["environment"],
        "candidate_environment": next(iter(candidate.values()))["environment"],
        "documents": [compare_document(reference[name], candidate[name]) for name in sorted(reference)],
    }
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    total_content = sum(document["content_changed_pages"] for document in report["documents"])
    affected = [document["name"] for document in report["documents"] if document["changed_pages"]]
    maximum = max((document["max_abs_steps"] for document in report["documents"]), default=0)
    print(
        json.dumps(
            {"max_abs_steps": maximum, "documents_with_diff": affected, "content_changed_pages": total_content},
            ensure_ascii=False,
        )
    )
    for document in report["documents"]:
        for page in document["changed_pages"]:
            print(document["name"], f"page {page['page']}", "content-changed" if page["content_changed"] else "", flush=True)
    raise SystemExit(1 if total_content else 0)


if __name__ == "__main__":
    main()
