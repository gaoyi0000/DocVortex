from __future__ import annotations

import base64
from io import BytesIO

from PIL import Image

from docvortex.foundation._svg_raster import is_svg_image_part, looks_like_svg_payload, serialize_svg_image

_VECTOR_LOGO_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="118" height="30" viewBox="0 0 118 30">'
    b'<rect width="118" height="30" fill="#006633"/><circle cx="15" cy="15" r="8" fill="#ffffff"/></svg>'
)


def _decode(data_uri: str) -> Image.Image:
    """把光栅化产物解码为 PIL 图片以便检查尺寸与透明通道。"""
    return Image.open(BytesIO(base64.b64decode(data_uri.split(",", 1)[1])))


def test_svg_rasterizes_to_transparent_png_and_upscales_small_long_edge() -> None:
    """验证 SVG 光栅化为透明 PNG，小尺寸固有像素放大到最小可视长边。"""
    data_uri = serialize_svg_image(_VECTOR_LOGO_SVG)

    assert data_uri is not None and data_uri.startswith("data:image/png;base64,")
    with _decode(data_uri) as image:
        assert image.format == "PNG"
        assert image.mode == "RGBA"
        assert image.size == (512, 131)


def test_svg_size_hint_controls_render_pixels_with_aspect_preserved() -> None:
    """验证显式帧尺寸提示决定渲染像素，纵横比不一致时按原比例 letterbox。"""
    data_uri = serialize_svg_image(_VECTOR_LOGO_SVG, size_hint=(565, 141))

    with _decode(data_uri) as image:
        assert image.size == (555, 141)


def test_svg_oversized_intrinsic_is_clamped_to_raster_budget() -> None:
    """验证超大固有尺寸按单边与总像素预算等比收缩。"""
    svg = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="20000" height="100">'
        b'<rect width="20000" height="100" fill="red"/></svg>'
    )

    with _decode(serialize_svg_image(svg)) as image:  # type: ignore[arg-type]
        assert image.size == (8192, 41)


def test_content_free_svg_degrades_to_none() -> None:
    """验证无视觉内容或仅含脚本的 SVG 光栅化为全透明时返回 None。"""
    assert serialize_svg_image(b'<svg xmlns="http://www.w3.org/2000/svg"/>') is None
    assert (
        serialize_svg_image(b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>') is None
    )


def test_svg_with_dtd_or_invalid_markup_is_rejected() -> None:
    """验证 DTD 实体注入与损坏标记在解析阶段即被拒绝。"""
    dtd = (
        b'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
        b'<svg xmlns="http://www.w3.org/2000/svg"/>'
    )
    assert serialize_svg_image(dtd) is None
    assert serialize_svg_image(b"<svg><unclosed>") is None


def test_svg_part_detection_by_declared_type_suffix_and_payload() -> None:
    """验证部件级 SVG 判定覆盖声明类型、后缀与载荷嗅探三种来源。"""
    assert is_svg_image_part("media/image1.svg", "")
    assert is_svg_image_part(None, "image/svg+xml")
    assert is_svg_image_part("media/image1.svg", "text/xml")
    assert not is_svg_image_part("media/image1.png", "image/png")
    assert not is_svg_image_part(None, None)
    assert looks_like_svg_payload(b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"/>')
    assert looks_like_svg_payload(b"<svg width='10'/>")
    assert not looks_like_svg_payload(b"\x89PNG\r\n\x1a\n")
    assert not looks_like_svg_payload(b"GIF89a")
