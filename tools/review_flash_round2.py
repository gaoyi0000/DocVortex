"""用公共 parse 接口重放指定原件清单，保存可检查的 HTML、MiddleJson 和图片资产包。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time

from loguru import logger

from docvortex import parse

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    """保留完整文档上下文并校验源指纹；只输出证据，不自动批准测试基线。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "output/pdf/flash-round2/exports")
    parser.add_argument("--manifest", type=Path, default=ROOT / "tests/fixtures/flash_round2_annotations.json")
    args = parser.parse_args()
    logger.remove()
    manifest = json.loads(args.manifest.read_text())
    summary = []
    source_hash = hashlib.sha256()
    for source in sorted((ROOT / "src").rglob("*.py")):
        source_hash.update(str(source.relative_to(ROOT)).encode())
        source_hash.update(source.read_bytes())
    for document in manifest["documents"]:
        source = ROOT / document["path"]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == document["sha256"]
        folder = args.output / document["name"]
        folder.mkdir(parents=True, exist_ok=True)
        start = time.monotonic()
        result = parse(source, keep_model_json=True)
        result.export(folder / "document.html", output_format="html", overwrite=True)
        from bs4 import BeautifulSoup

        html = BeautifulSoup((folder / "document.html").read_text(), "html.parser")
        missing_images = [
            image["src"]
            for image in html.find_all("img", src=True)
            if not image["src"].startswith(("data:", "http:", "https:")) and not (folder / image["src"]).is_file()
        ]
        assert not missing_images, (document["name"], missing_images)
        result.save_bundle(folder / "document.zip", overwrite=True)
        (folder / "middle.json").write_text(json.dumps(result.to_dict(), ensure_ascii=False), encoding="utf-8")
        item = {
            "name": document["name"],
            "sha256": document["sha256"],
            "code_sha256": source_hash.hexdigest(),
            "pages": len(result.middle_json.pages),
            "assets": len(result.assets),
            "seconds": round(time.monotonic() - start, 2),
            "diagnostics": [str(diagnostic) for diagnostic in result.diagnostics],
            "missing_images": missing_images,
        }
        summary.append(item)
        print(item, flush=True)
    (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
