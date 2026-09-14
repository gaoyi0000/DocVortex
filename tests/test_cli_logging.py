"""验证 CLI 全局 loguru 日志等级参数的解析与过滤行为。"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Iterator

from click.testing import CliRunner
from loguru import logger
import pytest

from docvortex import cli


@pytest.fixture
def isolated_logger() -> Iterator[None]:
    """隔离 loguru 全局 sink，避免 CLI 日志测试影响其他用例。"""
    logger.remove()
    yield
    logger.remove()
    logger.add(sys.stderr)


class _DummyPDFDocument:
    """替身 PDF 文档，避免日志参数测试依赖真实 PDF 解析。"""

    def __enter__(self) -> "_DummyPDFDocument":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        return False

    def classify(self) -> str:
        return "txt"


def _invoke_classify(runner: CliRunner, source: Path, *arguments: str):
    """调用 classify 子命令并返回执行结果，供日志参数断言复用。"""
    return runner.invoke(cli.main, [*arguments, "classify", str(source)])


def test_cli_log_level_defaults_to_info(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """未显式配置时，根命令默认传入 info 日志等级。"""
    source = tmp_path / "source.pdf"
    source.write_bytes(b"dummy")
    levels = []
    monkeypatch.setattr(cli, "_configure_log_level", levels.append)
    monkeypatch.setattr("docvortex.document.pdf.PDFDocument", lambda _: _DummyPDFDocument())

    result = _invoke_classify(CliRunner(), source)

    assert result.exit_code == 0, result.output
    assert levels == ["info"]


def test_cli_log_level_accepts_root_option_and_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """根命令参数生效，且显式参数优先于环境变量。"""
    source = tmp_path / "source.pdf"
    source.write_bytes(b"dummy")
    levels = []
    monkeypatch.setattr(cli, "_configure_log_level", levels.append)
    monkeypatch.setattr("docvortex.document.pdf.PDFDocument", lambda _: _DummyPDFDocument())
    monkeypatch.setenv("DOCVORTEX_LOG_LEVEL", "warning")
    runner = CliRunner()

    environment_result = _invoke_classify(runner, source)
    explicit_result = _invoke_classify(runner, source, "--log-level", "debug")

    assert environment_result.exit_code == 0, environment_result.output
    assert explicit_result.exit_code == 0, explicit_result.output
    assert levels == ["warning", "debug"]


def test_cli_rejects_invalid_log_level(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """非法日志等级在进入业务命令前被 Click 拒绝。"""
    source = tmp_path / "source.pdf"
    source.write_bytes(b"dummy")
    levels = []
    monkeypatch.setattr(cli, "_configure_log_level", levels.append)
    monkeypatch.setenv("DOCVORTEX_LOG_LEVEL", "verbose")

    result = _invoke_classify(CliRunner(), source)

    assert result.exit_code != 0
    assert "Invalid value" in result.output
    assert levels == []


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        ("info", ("debug hidden", False, "warning shown", True)),
        ("debug", ("debug shown", True, "warning shown", True)),
        ("error", ("warning hidden", False, "error shown", True)),
    ],
)
def test_configure_log_level_filters_loguru_output(
    isolated_logger, capsys: pytest.CaptureFixture[str], level: str, expected: tuple[str, bool, str, bool]
) -> None:
    """全局日志等级按 loguru 阈值过滤标准错误输出。"""
    cli._configure_log_level(level)
    logger.debug("debug hidden" if level == "info" else "debug shown")
    logger.warning("warning hidden" if level == "error" else "warning shown")
    logger.error("error shown")

    stderr = capsys.readouterr().err
    debug_message, debug_expected, warning_message, warning_expected = expected
    assert (debug_message in stderr) is debug_expected
    assert (warning_message in stderr) is warning_expected
    assert "error shown" in stderr


def test_importing_cli_preserves_host_loguru_sink() -> None:
    """导入 CLI 模块不重建宿主应用已配置的 loguru sink。"""
    messages: list[str] = []
    handler_id = logger.add(messages.append, level="DEBUG", format="{message}")
    try:
        importlib.reload(cli)
        logger.debug("host sink remains")
    finally:
        logger.remove(handler_id)

    assert "host sink remains\n" in messages
