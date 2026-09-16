# Flash 标题与段落成员补充修复验收

## 结果

本轮完成 9 组补充标注：fix P10 的附录 E 是完整的双行 `paragraph_title`；dual_caption P5、P10、P12、P15 指定的 7 处小字号粗体标题全部提升，P15 的双行标题保持一个块；dual_caption P10 的 `Prescribing` 完整、唯一地归于下一段，上一段止于 `day.`，两段行框和块框不再共享该行。

同一规则还自然恢复了 9 个同类标题。两份原件共有 12 个变化页，均对照原文、修改前及修改后标框逐页接受。生产规则不使用文件名、页码、块号、论文原句或特定字体名称。

- 逐页画廊：`output/pdf/flash-round3-followup/final/index.html`
- 两份完整导出：`output/pdf/flash-round3-followup/exports/`（HTML、MiddleJson、图片、资产包）
- 逐项裁决：`tests/fixtures/flash_round3_followup_review_decisions.json`

## 实现与成因

多行标题使用后继正文重复左右缘作为额外的局部居中参照。同一物理行的字体碎片先按基线聚合，首行和列表缩进不决定栏中心；保留原有未知字重和跨页重复排版要求。

小字号标题单独使用相对字号、可靠字重、上下独立留白、后继正文和容器排除证据。已确认的标题行组通过内部 `title_band_id` 传递给语义行连接，避免分类后重新拆开。该字段不进入公共协议。

段首恢复只对具有共同物理行身份、同字体、同栏和后继整行支持的连续文字放宽空格距离。空间合并复用统一成员合并函数，完整传递 `_text_lines`、内容和几何元数据，解决旧实现只合并内容及框、随后又从不完整成员重建内容造成的漏词。

## 回归与裁决

- **1480 项测试通过**，耗时 206.37 秒；包含新增的 35 项标题、成员守恒、数值列保护及真实样本检查。针对性检查单独运行 **200 项通过**。
- 历史 **19 份／168 页**相对本次冻结基线零变化。
- 第一轮 **8 份／118 页**相对本次冻结基线零变化；第二轮 **6 份／98 页**包含其中，不累计为额外独立覆盖量。
- 首个候选曾把 nougat P17 小表格的标签和百分数列连入一组，造成两条比较记录合并。对照原页后拒绝此变化，通过排除数值列的宽空格放宽修复，并增加合成与原件反例；未更新旧基线。
- 最终两份 41 页原件的非空白文本差异仅为恢复 `Prescribing`，未删除其他字符。另以源成员集合、唯一归属、行框和公共段落边界断言验证，避免仅比较旧输出遗漏已有缺字。
- 公共 `parse → MiddleJson → HTML／资产包` 全链路通过，34 个资产均可解析，缺失图片和解析诊断为空。浏览器确认附录 E 和小标题的标题层级、完整双行标题，以及独立的 `Prescribing` 段落。
- 21 个修改或新增 Python 文件通过 Ruff、格式检查，`git diff --check` 通过。

## 冻结与重放

冻结的是上一轮未提交源码及其输出，而非仅 Git HEAD。源码指纹 `1533f54963374b15a3cb18ff581f594a1a75fdc9eea47e88ee44cbddbf6988f8` 已与 `baseline-code/src` 逐文件核对；原输出保存在 `output/pdf/flash-round3-followup/baseline/`。本轮最终源码指纹为 `d9a40dab073789eafc52b25fd2fc5771ae0ccc930b44222735eac7c4310f774c`，画廊、历史重放和公共导出记录一致。

```sh
PY=/Users/myhloli/projects/20240809magic_pdf/Magic-PDF/.venv1/bin/python
PYTHONPATH=src "$PY" tools/review_flash_round3.py --baseline output/pdf/flash-round3-followup/baseline/final --output output/pdf/flash-round3-followup/final
PYTHONPATH=src "$PY" tools/review_flash_annotations.py --output output/pdf/flash-round3-followup/final-manual
PYTHONPATH=src "$PY" tools/review_flash_regression.py --output output/pdf/flash-round3-followup/final-history --compare-to output/pdf/flash-round3-followup/baseline/accepted-history
PYTHONPATH=src "$PY" tools/review_flash_round2.py --manifest tests/fixtures/flash_round3_annotations.json --output output/pdf/flash-round3-followup/exports
PYTHONPATH=src "$PY" -m pytest tests/unittest/test_flash_pdf_*.py tests/unittest/test_flash_rule_generalization.py tests/unittest/test_flash_manual_annotations.py tests/unittest/test_flash_round2_annotations.py tests/unittest/test_flash_round3_annotations.py tests/unittest/test_flash_spatial_evidence.py tests/unittest/test_pdf_document.py tests/unittest/test_pdf_object_clipping.py tests/unittest/test_pdf_text_dedup.py tests/unittest/test_native_pdf_table*.py tests/unittest/test_pdf_visualization.py tests/unittest/test_pdf_text_styles.py tests/unittest/test_postprocess_paragraphs.py -q
```

仍位于 `codex/flash-spatial-layout-round3`，未提交或推送；结果为指定本地 macOS／Python／PDFium 运行时的验收，未运行远端 CI。本轮没有新增公共参数或输出类型。

## 后续栏首及长标题补充

P8 与 P11 的剩余两处标题已修复，详见 [栏首与近满栏小标题验收](flash-title-coverage-2026-09-16.md)。
