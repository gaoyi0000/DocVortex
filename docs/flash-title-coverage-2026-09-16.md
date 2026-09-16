# 栏首与近满栏小标题补充验收

已修复 dual_caption P8 块1（Altered Protein Metabolism）和 P11 块10（Cyproheptadine and Other Antiserotonergic Drugs）。两者均输出为 `paragraph_title`，最终 HTML 均为一个 h2。

## 原因与通用修复

- P8 标题为栏内第一行，原规则因没有上一行而直接跳过。现在允许缺少上方正文，但要求位置与全页正文区顶部相符；页眉不参与上方正文判定，字体、字重、下方留白及真实后继正文等条件仍保留。
- P11 标题约占局部正文宽度 95%，被 90% 固定比例上限排除。现在使用标题是否落在实际栏左右边界内判断，右边允许半个正文行高的几何误差；越栏标题不能通过。
- 没有增加文件名、页码、块号、原句或字体名称条件。新增 24 个合成正反例，独立改变栏宽、字号和位置，覆盖栏首、长标题、越栏与侧栏中部情形；新增两处原件断言。

## 验收

**1506 项测试通过**（230.72 秒），其中针对性检查 123 项通过。Ruff、格式和差异检查通过。

两份原件 41 页仅上述两个块改变类型，全部文字和块框保持不变。第一轮 8 份／118 页与历史 19 份／168 页相对本次冻结基线均零差异；第二轮 6 份／98 页包含在第一轮完整文档中，不累计覆盖量。未更新旧基线。

完整解析、MiddleJson、HTML 和资产包重放通过；两个导出共 34 个资产，无缺失图片或解析诊断。原页与前后标框已审阅，浏览器确认两个 h2。

- 两页对比：`output/pdf/flash-title-coverage/final/changes.html`
- 完整画廊：`output/pdf/flash-title-coverage/final/index.html`
- 导出：`output/pdf/flash-title-coverage/exports/`
- 裁决：`tests/fixtures/flash_title_coverage_review_decisions.json`
- 测试日志：`output/pdf/flash-title-coverage/tests.log`

修改前未提交代码和输出已冻结于 `output/pdf/flash-title-coverage/baseline-code/` 与 `baseline/`，源码指纹与上一轮验收记录核对一致。本轮仍在 `codex/flash-spatial-layout-round3`；未提交、推送或运行远端 CI。
