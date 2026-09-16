# Flash 原生 PDF 空间布局：第三轮修复与验收

## 范围与证据

基于 `a8511caa6615fcf479a2b861061b4633ae1eef5f`，开发分支为 `codex/flash-spatial-layout-round3`。两份原件共 41 页、25 个重点页、36 组人工标注。源文件和原始块锚点保存在 `tests/fixtures/flash_round3_annotations.json`，断言不依赖修复后的块编号。

- `journal_dual_caption.pdf`：20 页；SHA256 `ae9ee7db89a1ff23f9be8ecdb4ae70596ad1e3eec78c1d370f562a4aad3aa5ec`。
- `quantum_appendix_layout.pdf`：21 页；SHA256 `6f393579aacfb8119f92790e565d539856e21d901f683147d242daefd6d094bb`。
- 原页／修改前／修改后画廊：`output/pdf/flash-round3/final/index.html`。
- 公共接口导出：`output/pdf/flash-round3/final-exports/`，每份文档包含 HTML、MiddleJson、图片资产及 ZIP。
- 修改前代码的完整源码指纹为 `e5ddd06fdb910bfcb83e316e42c36b58bfb8d51baac2682f68d919be183434c6`，已与独立的只读基准 checkout 核对。

## 实现

1. **参考文献和局部分栏**：使用连续编号的稳定左缘确定参考区域的横向和纵向范围，支持无 References 标题、齐平或悬挂续行。局部标题限定区域起点；只有具有独立留白的章节标题才能终止区域。作者年代式条目的年份不充当编号。混合栏页上方正文独立排序，避免上标的微小高度差让右栏先读。
2. **标题和段落**：限制正文原型对满栏连续行的提升及标题邻行传播；多行未知字重标题增加居中对齐证据。首页独立标题带和出版日期带支持文档标题及编号机构识别。同行碎片依据同栏、基线、后继整行支持恢复；段内数学前缀按成员而非外接框认领。
3. **公式**：在原有检测结束后补齐独立数学带及右侧／右下编号，只扩充不完整区域。完整公式沿用原有结果。短标记必须有包围结构，百分数及全角百分数不能作为编号；正文短句、栏沟及表格为屏障。保留既有行内数学回退成员，不因其已被正文认领而删除。
4. **表注与图例**：以表内规则行的结束位置分离外框包住的表注，表格恢复和投影共用收缩后的表体范围。从紧邻图片的独立图编号恢复破碎说明，完整图注不再次扩展。图例先恢复药名—符号物理行，再按分类和重复栏左缘组织阅读顺序，统一归属图片的图注释。
5. **公共转换**：临时参考条目起点及段界证据传入页面合并阶段；新编号和已确认段界禁止续接，跨栏／跨页参考续项可保留 `continues_prev`。临时字段在 PageInfo 对象化前移除，不新增公共参数或块类型。

生产规则没有新增文件名、页码、块号、论文原句或特定字体名称判断。新增函数均有中文说明。

## 回归裁决

没有通过更新旧基线消除失败。下列候选变化均通过规则收紧解决，审阅过程的失败图像仍保留在输出目录：

| 回归证据 | 裁决与处理 |
| --- | --- |
| `current-history/demo2/page-03-after.png`：短正文 `is given by` 被吸入公式 | 扩展短正文屏障，并把数学带恢复放在既有检测之后，完整公式不重建。 |
| `current-history/caibao1/page-02-after.png`：并列图片的图注归属和顺序改变 | 图注恢复入口限定为独立编号及其尚未归组的说明带；已有完整图注沿用原流程。 |
| 作者年代式参考文献被按年份重新分条；参考上下文侵入附录 | 编号模式与传统悬挂条目分组分开，仅对可靠编号区域提前保护；保留附录终止及脚注排除规则。 |
| `refined2-history/中文论文4/page-02-after.png`：正文中的行内数学内容缺失 | 区分原先用于正文恢复的已认领成员和新公式补全成员，保留前者；增加全角百分数反例。 |
| `frames_v1/v2` 附录数字列表吸入下方图说明 | 作者年代式跨页状态不激活数字参考模式；普通编号仍作为传统分组边界，保留原基线并增加四页反例。 |
| `fix.pdf` 参考条目内部的斜体行被当成区域终点 | 终点必须具有独立留白；真实样本同时检查条目数、条目完整性和无假标题，不能只数编号。 |

两个临时字段 `_reference_start`、`_paragraph_boundary` 不进入旧可见内容指纹；只排除这两个明确字段，没有放宽类型、内容、顺序或 bbox 校验。其行为由公共页面转换测试单独断言，包括跨页数字开头续项、新编号不续接、图例归属和私有字段清理。

## 重放

使用用户指定的 `.venv1`，在仓库根目录执行：

```sh
PY=/Users/myhloli/projects/20240809magic_pdf/Magic-PDF/.venv1/bin/python
PYTHONPATH=src "$PY" tools/review_flash_round3.py
PYTHONPATH=src "$PY" tools/review_flash_round2.py --manifest tests/fixtures/flash_round3_annotations.json --output output/pdf/flash-round3/final-exports
PYTHONPATH=src "$PY" tools/review_flash_regression.py --output output/pdf/flash-round3/accepted-history --compare-to output/pdf/flash-round3/baseline-history
PYTHONPATH=src "$PY" tools/review_flash_annotations.py --output output/pdf/flash-round3/accepted-manual
PYTHONPATH=src "$PY" -m pytest tests/unittest/test_flash_pdf_*.py tests/unittest/test_flash_rule_generalization.py tests/unittest/test_flash_manual_annotations.py tests/unittest/test_flash_round2_annotations.py tests/unittest/test_flash_round3_annotations.py tests/unittest/test_flash_spatial_evidence.py tests/unittest/test_pdf_document.py tests/unittest/test_pdf_object_clipping.py tests/unittest/test_pdf_text_dedup.py tests/unittest/test_native_pdf_table*.py tests/unittest/test_pdf_visualization.py tests/unittest/test_pdf_text_styles.py tests/unittest/test_postprocess_paragraphs.py -q
```

逐项裁决和最终运行结果见 `tests/fixtures/flash_round3_review_decisions.json`。公式继续使用现有图片资产路径；本轮不处理原 PDF 的错误字符映射或引入数学内容识别。

## 最终验收结果

- **1445 项测试通过**，耗时 198.50 秒；日志：`output/pdf/flash-round3/accepted-tests.log`。19 个修改／新增 Python 文件通过 Ruff 和格式检查，`git diff --check` 通过。
- 两份新文档 **41 页**全部重放，**36 组标注**通过针对性结构测试及视觉审阅；画廊覆盖 **25 个标注页与 2 个额外变化页**。额外变化为第一份 P12 短尾接回同段、fix P7 附录标题与正文分离。
- 历史 **19 份／168 页**可见内容、类型、顺序和块框指纹均与修改前一致。
- 第一轮 **8 份／118 页**中 114 页一致，4 页变化逐项接受，见下表。第二轮 **6 份／98 页**是上述完整文档的子集，已全部覆盖；不将重叠页累加为独立覆盖量。
- `parse → MiddleJson → HTML／资产包` 已完成，两份导出共 34 个资产，缺失图片和解析诊断均为空。浏览器检查了正文标题、图例分组阅读顺序及图片加载。公式仍使用原生裁图，不改变数学内容识别方式。
- 对原生正文、图注、表格及公式检测内容进行非空白字符守恒核对；仅第一份 P5、P17 和 fix P20 共四处行末连字符随正常断词连接被移除，无其他非空白字符丢失或新增。
- 未修改原有测试金标。以下四页是完整重放产生的自然改善，已保存旧／新指纹和逐项接受理由；拒绝的候选变化通过收紧规则恢复原基线。

| 文档／页 | 接受理由 |
| --- | --- |
| fornax P1 | 独立双行主标题由 `paragraph_title` 恢复为 `doc_title`，作者和机构顺序保持。 |
| mmlu_redux P13 | 独立加粗的 Checklist 由正文恢复为段落标题。 |
| k2_treap P3 | 保留行内区间右括号对应的原生映射字符，避免与后继正文粘连；不做字符替换。 |
| k2_treap P9 | 保留行内矩阵维数右括号对应的原生映射字符；块框和阅读顺序不变。 |

既有语料变化页与恢复旧基线的页面对比：`output/pdf/flash-round3/manual-visuals/index.html`。全部裁决（包括源码、原件及页面指纹）保存在 `tests/fixtures/flash_round3_review_decisions.json`。

本次结果为指定 macOS／Python／PDFium 运行时的本地验收；未执行远端 CI，未提交或推送。原 PDF 的字符映射错误仍沿用原有处理，本轮没有引入 OCR／VLM。

## 后续补充验收

用户新增的标题与段落成员问题已在补充轮完成，见 [补充修复验收](flash-spatial-layout-followup-2026-09-16.md)。本报告保留第一轮实现时的验证记录。
