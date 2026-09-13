"""通过真实解析验证 Flash 公式图片化，独立于检测证据金标辅助器。"""

from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from pypdf import PdfReader

from docvortex import parse, render_artifact
from docvortex.schema import EquationBlock, PageInfo


@pytest.fixture(scope="module")
def equations():
    """解析 demo1 第三页，保留实际公式图片与源页几何用于多格式导出。"""
    result = parse(Path(__file__).parents[2] / "demo/pdfs/demo1.pdf", page_range="3", keep_model_json=True)
    raw = [block for page in result.model_json.pages for block in page if block["type"] == "equation"]
    assert len(raw) == 2 and all(block["content"] == "" for block in raw)
    blocks = [block for page in result.middle_json.pages for block in page.blocks if isinstance(block, EquationBlock)]
    assert len(blocks) == 2 and all(block.content == "" for block in blocks)
    assert all(block.image_path or block.image_base64 for block in blocks)
    middle = result.middle_json.model_copy(update={"pages": [PageInfo(page_idx=2, blocks=blocks)]})
    return middle, result.assets


@pytest.mark.parametrize("target", ["pdf", "markdown", "html", "docx", "epub", "latex"])
def test_flash_display_equations_use_images_in_every_renderer(equations, target) -> None:
    """空公式内容通过每种 renderer 的现有回退输出真实图片，输入保持不变。"""
    middle, assets = equations
    before = middle.to_json()
    artifact = render_artifact(middle, target, assets=assets)
    assert middle.to_json() == before
    if target == "pdf":
        assert len(PdfReader(BytesIO(artifact.content)).pages[0].images) == 2
    elif target in {"docx", "epub"}:
        with ZipFile(BytesIO(artifact.content)) as archive:
            assert (
                sum(
                    name.lower().endswith((".png", ".jpg", ".jpeg")) and not name.startswith("docProps/")
                    for name in archive.namelist()
                )
                == 2
            )
    else:
        marker = {"markdown": "![", "html": "<img", "latex": r"\includegraphics"}[target]
        assert artifact.content.decode().count(marker) == 2
