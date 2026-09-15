# Flash 规则抽象验收（2026-09-15）

## 目标与实现

基于 `3acfed223b548c5b6476917d65ce1dd728b0c269`，将两轮修复中的内容特例及固定版式假设改为结构证据。生产代码不引用论文名称、样本路径、指定问题页或自定义变量白名单。

| 规则 | 已替换的条件 | 当前依据与保护 |
| --- | --- | --- |
| 公式 | `VarWin` / `VarEnd` 白名单 | 运算关系、函数调用和二维几何识别自定义标识符；正文残留证据由共享函数判断。中文正文不作为长变量吞入。健康原生行缺少修复专用 ink 框时，须同时具备编号和二维结构才补恢复。 |
| 图文环绕 | 左侧窄正文、最后恰好一行变宽 | 连续行区间与图注空间屏障；左右镜像采用同一判定，多行宽尾保留全部成员。几何断点独立于自然段断点。 |
| 首页弱表格 | 固定 `articleinfo + abstract` 标题组合 | 元数据字段类别、独立正文区域与摘要角色；支持同义标题、中英文及左右互换。成功恢复的 HTML 表格优先，可信内部网格和不足的元数据证据阻止撤销。 |
| 分栏 | 页面中线作为栏沟 | 复用重复文字边缘推断；为图旁短图注补充显式首行与对齐续行证据。图形、算法、标题、参考文献和块合并使用共同栏依据。 |
| 参考文献与机构 | 固定半页区域、至少三个机构 | 按实际栏序处理开始/结束事件，同页附录或独立章节终止上下文；一个或多个机构由编号、机构角色及连续排版确认。 |
| 页边图形 | 彩色、页边、无邻近编号即判图片 | 出版角色与装饰形结构，或跨页同时重复的结构签名和相对位置；数学编号、可读数学及分式证据优先。颜色不参与决定。出版页脚提前分类后仍保留其内部上下文区域。 |
| 脚注 | 短标题、宽度与字号触发整组合并 | 区域标题角色、机构内容和行内编号连续性；独立起行编号仍拆条。首页通讯带限制在实际区域内，不能向邻栏或独立条目延伸。 |

共享布局证据按分析阶段构建，文本成员改变后重新计算，不在文档之间复用可变对象。新函数和方法均有中文说明。

## 兼容边界

公共 API、ModelJson / MiddleJson 结构、块类型和 PDF renderer 不变。来源行、行框、字符索引及行内样式沿用原有链路；新增区域和图形签名只供内部使用。裁剪链和可见字符底层修复未修改。

同一自然段为了避开图注可输出多个矩形块；内部几何断点不伪装成新自然段，也不新增公开段落 ID。现有 MiddleJson 连续性处理保持原契约。

原测试要求脚注条目拆分函数完全不读取文本；本轮允许它读取通用角色证据，因此将该函数移出纯几何静态守卫。其他几何分类器仍受原守卫约束，新增机构标题和独立编号反例验证新的语义边界。

## 泛化与反例验证

最终相关全套 **1323 项通过**（189.03 秒），Ruff、格式检查和 `git diff --check` 通过。新增 `tests/unittest/test_flash_rule_generalization.py`，共 **67 项**：

- 等长和不同长度变量替换、函数调用、正文排除，以及真实 PDF 经 `PdfModel.predict` 的编号二维公式恢复。
- 左右镜像与一行、两行、多行宽尾；正文成员完整且唯一，几何拆块不设置语义段界。
- 同义标题、中英文角色、短摘要、可信网格、字段不足与非首页反例。
- 单栏、非对称双栏、三栏、通栏正文中的局部图注栏；同页参考文献转附录/后续章节。
- 一到多个机构、连续机构脚注与明确独立编号条目的区分。
- 彩色/黑色矢量公式、灰度/彩色字标、缺少出版上下文、数学编号优先，以及同位置不同结构的反例。
- 0/90/180/270 度、等比例缩放和位置平移下的栏证据及公式成员保持。
- 真实 FRAMES v1 的两处通栏段首强调及独立起行编号回归。

水平图文环绕和首页面板继续面向原有水平方向；四方向变换用例覆盖共享栏证据和公式恢复，不表示新增了所有版式的任意旋转识别。

## 真实样本与逐页裁决

使用独立的 `3acfed2` checkout 重跑并冻结基线，而非使用历史缓存推断旧结果。

- 第一轮 8 份、118 页、87 组标注及第二轮 6 份、98 页、31 组标注重放。
- 历史 19 份、168 页逐页比较语义与几何指纹，**168 页全部不变**。
- 人工样本仅 FRAMES v1 第 4、6 页出现变化，两页可见字母数字库存一致；原始内容、类型、样式和前后标框保留供复核。
- 既有人工/历史金标未批量更新；新增两条具体变化裁决，前后差异使用 SHA-256 锁定。后续差异不匹配时仍显示待审。

| 文档 / 页 | 视觉裁决 | 原因 |
| --- | --- | --- |
| FRAMES v1 / 4 | 接受 | `Human annotation.` 和 `Dataset Statistics.` 均为与后继正文同一物理行的粗体提示；撤销独立标题并合入正文，粗体保留，表格不变。 |
| FRAMES v1 / 6 | 接受 | `(2) BM25-Retrieved Prompt` 在完整句尾后独立起行，恢复独立段；`(3)` 仍在行内，保持原段归属。 |

已检查上述页面的原文和前后标框，并检查公共导出中的 Nougat 四个公式截图（含自定义标识符与完整求和上下限）、MMLU 完整选项图及 Nash 出版图形。

## 公共入口与产物

全部 8 份人工原件通过真实 `parse → MiddleJson → HTML / 图片资产` 导出：**118 页、110 项资产、解析诊断为空、HTML 图片引用全部有效**。公共导出未使用保留公式内部检测内容的测试辅助器。原有辅助器仅用于历史语义指纹检查。

源码指纹、历史重放和公共导出指纹必须一致，最终值保存在 `output/pdf/flash-rule-generalization/verification.json`。

验收入口：

- `output/pdf/flash-rule-generalization/visual-review/index.html`：全部变化页、原页、前后标框和结构差异。
- `output/pdf/flash-rule-generalization/exports/`：8 份原件的 HTML、MiddleJson 和资产目录。
- `output/pdf/flash-rule-generalization/logs/`：全量测试、人工重放、历史重放和公共导出日志。
- `tests/fixtures/flash_rule_generalization_review_decisions.json`：精确匹配前后差异的视觉裁决。

### 重放

使用用户指定环境，在仓库根目录运行：

```sh
PY=/Users/myhloli/projects/20240809magic_pdf/Magic-PDF/.venv1/bin/python
$PY tools/review_flash_annotations.py --output output/pdf/flash-rule-generalization/current-manual
$PY tools/review_flash_regression.py --output output/pdf/flash-rule-generalization/current-history --compare-to output/pdf/flash-rule-generalization/baseline-history
$PY tools/review_flash_round2.py --manifest tests/fixtures/flash_manual_annotations.json --output output/pdf/flash-rule-generalization/exports
$PY tools/review_flash_generalization.py --decisions tests/fixtures/flash_rule_generalization_review_decisions.json
$PY -m pytest tests/unittest/test_flash_pdf_*.py tests/unittest/test_flash_rule_generalization.py tests/unittest/test_flash_manual_annotations.py tests/unittest/test_flash_round2_annotations.py tests/unittest/test_pdf_document.py tests/unittest/test_pdf_object_clipping.py tests/unittest/test_pdf_text_dedup.py tests/unittest/test_native_pdf_table*.py tests/unittest/test_pdf_visualization.py tests/unittest/test_pdf_text_styles.py -q
```

## 保守边界

规则仍是有适用条件的结构启发式，不承诺识别任意排版。角色词覆盖常见中英文术语；完全不可读的矢量对象在数学与装饰证据均不足时保留原通用分类。缺少稳定栏证据时不新增跨栏认领。没有引入 OCR、VLM、具体出版社词典或新的论文特例。
