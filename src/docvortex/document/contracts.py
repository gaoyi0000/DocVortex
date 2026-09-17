"""HTML Flash 解析使用的来源上下文契约。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class HtmlSourceContext:
    """保存相对链接解析及 HTML 解码所需的来源上下文。

    fetch_remote_images 默认关闭，远程图片仅记录 URL；开启后解析阶段会对受限
    HTTP(S) 图片发起网络请求并内嵌，不可信输入的 SSRF 风险由调用者承担。
    """

    source_uri: str | None = None
    local_resource_root: Path | None = None
    transport_encoding: str | None = None
    fetch_remote_images: bool = False


__all__ = ["HtmlSourceContext"]
