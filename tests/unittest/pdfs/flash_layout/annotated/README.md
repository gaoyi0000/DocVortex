# 人工标注 Flash 原生 PDF 回归语料

这些文件为用户提供的完整原生 PDF，保留字体、路径、嵌套 Form、链接和跨页上下文。不得按文件名、页码或论文内容编写生产特例。

| 测试文件 | 原始文件 | 页数 |
| --- | --- | --- |
| nougat.pdf | 2308.13418v1.pdf | 17 |
| mmlu_redux.pdf | 2406.04127v2.pdf | 21 |
| frames_v1.pdf | 2409.12941v1.pdf | 14 |
| frames_v2.pdf | 2409.12941v2.pdf | 15 |
| nash_review.pdf | 7061196.pdf | 15 |
| connexin.pdf | 12352684 (1)-需要重打印.pdf | 5 |
| fornax.pdf | 公式密集span不规范-两个block重叠部分.pdf | 15 |
| k2_treap.pdf | 公式密集span不规范论文.pdf | 16 |

SHA-256、物理页码、原始块序号、文本与区域锚点见 `tests/fixtures/flash_manual_annotations.json`。
`test_flash_manual_annotations.py` 覆盖类型、成员归属、最大/最小图片边界、粗体、逐格表格及最终 MiddleJson；`tools/review_flash_annotations.py` 可重放完整语料。
原序号仅用于追溯；修复后的目标使用文本、类型和区域匹配。
