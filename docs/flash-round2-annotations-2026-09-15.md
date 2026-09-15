# Flash 第二轮人工标注修复验收（2026-09-15）

## 结果

- 基于 `main@b56d294` 实施，开发分支为 `codex/flash-native-round2`；修复及本报告一并提交至本地 `main`，未推送。
- 本轮 **6 份完整 PDF、98 页、31 组标注均修复通过**。两项可选修复均实现，无保守保留项。
- 第一轮 **8 份、118 页、87 组标注**已重放；3 组旧“整块合并”范围按原页真实段界细化，原始块内容、区域与编号保留。
- **1125 项**相关解析、真实样本、字符可见性、公式、原生表格及可视化测试通过；另 **131 项**原始字符样式测试通过，总计 **1256 项**。
- 历史 **19 份、168 页**中，166 页语义和几何指纹完全不变；仅批准财报 2 页变化。
- 公共 `parse → MiddleJson → HTML / 图片资产包` 重跑 6 份原件，98 页、78 项资产，解析诊断为空。HTML 图片路径全部可解析。

## 实现及边界

1. **可见字符视图**：Flash 的原生页提取入口使用与图形相同的累积 Form 裁剪和坐标变换。完全裁剪、无绘制模式与零透明度字符被排除；部分裁剪字符仍保留字符索引、来源与原点，布局框采用可见范围。原始字符 API 的默认行为不变。白色或小字号本身不是删除条件。
2. **段落**：句末可越过实际缩小的上标引用；同栏稳定左缘、重复首行缩进、短尾剩余宽度和下一词宽度共同确认换段。保留粗体提示，显式段界传递到后续合并。公式、条目、参考文献和 caption 保留原有连续性约束。
3. **图形与算法**：Form 成员证据可补全图缘选项行；已确认代码成员对图片形成边界。跨栏实际文字行不能仅因外接矩形相交而合并。caption 续行逐步恢复，不能通过邻栏的通栏尾行认领正文。
4. **脚注**：先恢复同一物理行的碎片，再按横线及实际栏范围分组；分数线要求上下内容相对居中。机构标题及其宽行按一组保留，普通编号脚注继续使用已有分组规则。
5. **标题**：将字重 0 视为未知，结合跨页重复字体、独立间隔、正文后继和多行整体识别。段内粗体继续归入 text。
6. **首页弱表格**：仅在原生表格恢复失败、首页 article info / abstract 分区及历史字段证据同时成立时恢复文本。真实表格保持原生表格恢复流程。

生产规则未引入文件名、页码或论文正文特例，不新增公共类型或 OCR/VLM 路径。新函数和方法均有中文注释。

## 逐项验收

原始指纹、物理页码、文字锚点及区域见 `tests/fixtures/flash_round2_annotations.json`；下表与 `flash_round2_review_decisions.json` 一致。

| 标注 ID | 物理页 | 结果与证据 |
| --- | --- | --- |
| nougat-05-r2-01 | 5 | 修复通过：8、9、10 的 URL 均归入 page_footnote；真实分式反例保持。 |
| nougat-07-r2-02 | 7 | 修复通过：在 Both Nougat small and base 前独立成段。 |
| nougat-09-r2-03 | 9 | 修复通过：Utility、Nearly every dataset、Generation Speed 分为三个 text，段首粗体保留。 |
| nougat-09-r2-04 | 9 | 修复通过：Future work 与 The primary challenge 分为两段，段首强调保留。 |
| nougat-17-r2-05 | 17 | 修复通过：裁剪隐藏的 IP、1/1、日期和浏览器标题不进入 Flash；可见页码 17 保留。 |
| mmlu_redux-02-r2-01 | 2 | 修复通过：完整 Form 吸收最后选项行，图片下边界包含 A. Clark 至 D. Ebbinghaus。 |
| mmlu_redux-02-r2-02 | 2 | 修复通过：三行 Figure 1 caption 完整绑定图片，Human Aging. 不再归入邻栏正文。 |
| frames_v1-01-r2-01 | 1 | 修复通过：在 To bridge this gap 前分为两段。 |
| frames_v1-08-r2-02 | 8 | 修复通过：算法 1～12 行完整且仅属于 code_body；图片起点低于代码底部。 |
| frames_v2-01-r2-01 | 1 | 修复通过：重复首行缩进支持页底 Our work addresses 单行新段；已实现可选拆分。 |
| nash_review-01-r2-01 | 1 | 修复通过：NAFLD can be broadly 前分为两段，句末上标引用不再阻断换段。 |
| nash_review-01-r2-02 | 1 | 修复通过：续段、Among individuals、The development of a therapy 分为三段。 |
| nash_review-11-r2-03 | 11 | 修复通过：Affiliations 与四个机构恢复为一个 page_footnote，按实际行序连接。 |
| nash_review-04-r2-04 | 4 | 修复通过：重复未知字重样式和独立排版支持整个标题；多行标题完整归入 paragraph_title。 |
| nash_review-06-r2-05 | 6 | 修复通过：重复未知字重样式和独立排版支持整个标题；多行标题完整归入 paragraph_title。 |
| nash_review-06-r2-06 | 6 | 修复通过：重复未知字重样式和独立排版支持整个标题；多行标题完整归入 paragraph_title。 |
| nash_review-07-r2-07 | 7 | 修复通过：重复未知字重样式和独立排版支持整个标题；多行标题完整归入 paragraph_title。 |
| nash_review-07-r2-08 | 7 | 修复通过：重复未知字重样式和独立排版支持整个标题；多行标题完整归入 paragraph_title。 |
| nash_review-09-r2-09 | 9 | 修复通过：重复未知字重样式和独立排版支持整个标题；多行标题完整归入 paragraph_title。 |
| nash_review-09-r2-10 | 9 | 修复通过：重复未知字重样式和独立排版支持整个标题；多行标题完整归入 paragraph_title。 |
| nash_review-10-r2-11 | 10 | 修复通过：重复未知字重样式和独立排版支持整个标题；多行标题完整归入 paragraph_title。 |
| nash_review-10-r2-12 | 10 | 修复通过：重复未知字重样式和独立排版支持整个标题；多行标题完整归入 paragraph_title。 |
| nash_review-12-r2-13 | 12 | 修复通过：重复未知字重样式和独立排版支持整个标题；多行标题完整归入 paragraph_title。 |
| nash_review-12-r2-14 | 12 | 修复通过：重复未知字重样式和独立排版支持整个标题；多行标题完整归入 paragraph_title。 |
| nash_review-12-r2-15 | 12 | 修复通过：重复未知字重样式和独立排版支持整个标题；多行标题完整归入 paragraph_title。 |
| nash_review-12-r2-16 | 12 | 修复通过：重复未知字重样式和独立排版支持整个标题；多行标题完整归入 paragraph_title。 |
| nash_review-12-r2-17 | 12 | 修复通过：重复未知字重样式和独立排版支持整个标题；多行标题完整归入 paragraph_title。 |
| nash_review-12-r2-18 | 12 | 修复通过：重复未知字重样式和独立排版支持整个标题；多行标题完整归入 paragraph_title。 |
| k2_treap-01-r2-01 | 1 | 修复通过：article info 与 abstract 恢复两片文本区域；小标题为 paragraph_title，历史、关键词、摘要、版权为 text。 |
| k2_treap-10-r2-02 | 10 | 修复通过：同行碎片及 our research. 归入一个完整脚注，右栏正文保持独立。 |
| mmlu_redux-02-r2-03 | 2 | 修复通过：原块 6 的窄栏上部接回 4、5，下方 documentation… 通栏尾行独立。 |

## MMLU 图旁正文补充调整

新增一组标注，锚点来自第二轮首次验收的源码快照，原块编号为 4、5、6。生产规则依据图注邻接、实际行宽变化和同栏未结束的续文恢复分块。前后检查文字集合完全一致，只有 MMLU 第 2 页变化；其余 7 份人工样本及历史 168 页没有新增变化。MiddleJson 与 HTML 已同步重导出。

前后对比：`output/pdf/flash-round2/visual-review/mmlu-wrap-before-after.png`。补充回归日志：`output/pdf/flash-round2/logs/mmlu-wrap-regression.log`。

## 第一轮断言的三处细化

旧锚点保留，新增 `expected_regions` 和 `round2_review_reason`，同时检查两个自然段的正确归属。

- `frames_v2-01-02`：第一段内部仍合并，`Our work addresses…` 为第二轮明确允许的独立新段。
- `nougat-02-10`：`Decoder` 与同行正文仍合并；原页短尾句末后的 `Following Kim et al.…` 另成段。
- `fornax-04-02`：第一段公式碎片仍归入正文；`At variance with…` 有明确首行缩进，独立成段。

原页和前后标框已对照检查，没有用原始大框强行跨越新的真实段界。

## 历史基线裁决

| 样本 | 页 | 裁决 |
| --- | --- | --- |
| caibao1 | 1 | 字符“企”右侧被裁剪 0.1096pt，保留文字，仅收紧可见框；段落归一化右界 0.616 → 0.615。更新该页几何指纹。 |
| caibao1 | 5 | 删除完全被裁剪隐藏的“图表8：”；可见“图表7：”caption 和全部图内标签保持。图框不再包含隐藏文字。更新该页指纹。 |
| 其余历史页 | 166 页 | 语义和几何指纹不变，保持基线。 |
| 中文合成样本 | 3、4 | 两条普通说明句由误判 paragraph_title 恢复 text；结合原页和生成代码确认，更新类型库存，正文总数 12 → 14。此样本在 168 页历史集之外。 |

逐字符裁剪证据：`output/pdf/flash-round2/visual-review/caibao1-visible-chars.json`。原有较旧的 `flash_layout_geometry_manifest.json` 未整体刷新。

## 端到端与视觉检查

- 已查看本轮全部目标页/标题区域的最终标框，以及争议段落和历史变化页的原页、前后标框。
- MMLU 图片截图包含完整末行四个选项；三行 caption 以 `image_caption` 进入 MiddleJson，结束于 `Human Aging.`，HTML 内容一致。
- FRAMES v1 算法标题和 `code_body` 保留，正文行号 1～12 完整且只归属一次；最终图片资产不包含代码末行。
- Nougat 的 Utility、Generation Speed、Future work 在 HTML 中仍有粗体；公式截图保留完整求和上下限；不可见浏览器文字未进入 HTML，可见页码保留。
- Nash 机构脚注与 K2 同行脚注按实际阅读顺序进入最终输出；K2 首页为两个文本区域，非伪表格。
- 历史中间实验曾出现 caption 分裂、空格丢失和引用条目误拆，均修正规则后重新验证，未据此更新基线。

## 重放命令

使用 `/Users/myhloli/projects/20240809magic_pdf/Magic-PDF/.venv1/bin/python`（下列 `$PY`）。

```sh
PY=/Users/myhloli/projects/20240809magic_pdf/Magic-PDF/.venv1/bin/python
$PY tools/review_flash_annotations.py --output output/pdf/flash-round2/current
$PY tools/review_flash_regression.py --output output/pdf/flash-round2/history-current --compare-to output/pdf/flash-round2/history-before
$PY tools/review_flash_round2.py
$PY -m pytest tests/unittest/test_flash_pdf_*.py tests/unittest/test_flash_round2_annotations.py tests/unittest/test_flash_manual_annotations.py tests/unittest/test_pdf_document.py tests/unittest/test_pdf_object_clipping.py tests/unittest/test_pdf_text_dedup.py tests/unittest/test_native_pdf_table*.py tests/unittest/test_pdf_visualization.py -q
$PY -m pytest tests/unittest/test_pdf_text_styles.py -q
```

当前源码 SHA-256（排序拼接 `src/**/*.py` 路径和内容）：`ba0e69f0426fcb6f95ef2d1a726d6996111b64a51beb0ee5f5366f406220894f`。历史快照与公共导出均记录同一指纹。

可打开的结果入口：`output/pdf/flash-round2/index.html`；测试、历史重放和导出日志在 `output/pdf/flash-round2/logs/`。
