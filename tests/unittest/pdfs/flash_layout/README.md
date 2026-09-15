# Flash 布局回归样本

以下截页来自用户提供的原生 PDF，保留字体、Form、绘图路径和字符坐标，用于复现几何与布局问题。截页移除了文档元数据及链接批注；完整原件的链接、跨页语义和导出另行验收。

| 文件 | 原件物理页码 | 验证内容 |
| --- | --- | --- |
| `math_display_formulas.pdf` | 数学新星第 1 页 | 混合字体正文中的三处无编号公式 |
| `bloom_form_labels.pdf` | distributed-bloom-filter 第 3、4、5 页 | Form 边缘小字、映射为空格的公式括号 |
| `journal_layout_tables.pdf` | Predicting bathymetry 第 1、2、5、6、12、13 页 | 紧排行标题、分隔线、脚注、页底公式、三线表换行表头和纵向合并单元格 |

`test_flash_pdf_layout_repairs.py` 包含这些样本的类型、成员归属、边界和逐格结构断言，以及合成反例。文件名、页码和文档内容仅用于测试定位，生产规则不引用它们。

原有 `mixed_text_layout_sample.pdf.xor` 仍由既有几何回归测试负责。

## 完整人工标注语料

`annotated/` 保存另八份完整原件（118 页），用于必须保留跨页语义的作者、页眉、脚注、引用和图形回归；详见该目录 README。
