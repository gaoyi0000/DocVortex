# Flash PDF 等价性基准

## PDF 导出性能与等价性

`pdf_render.py` 只测量已物化 MiddleJson 到 PDF artifact 的导出，不包含 Bundle 读取、PDF 解析、视觉检查和写盘。
每个输入及 ORIGINAL/REFLOW 组合使用独立进程，首次调用单列，随后默认计时五次取中位数。

```bash
python tests/benchmarks/pdf_render.py --source /path/to/bundle --source fixture:rich --backend python --output output/pdf/performance/baseline
python tests/benchmarks/pdf_render.py --source /path/to/bundle --source fixture:rich --backend accel --output output/pdf/performance/accel --baseline output/pdf/performance/baseline
```

`--source` 可重复指定 Bundle；不指定时使用含中英混排、矢量公式、链接和重复图片的合成语料。
`--backend python` 在独立测试进程中禁用扩展导入，`accel` 则要求真实加载原生函数，均不修改 ReportLab 全局配置。
`--runs 0` 只运行首次导出与等价性检查。`--profile` 额外保存 cProfile，剖析不参与耗时和内存测量。
RSS 每 50 ms 采样，包含解释器和已加载输入，不是文档增量；非常短的峰值可能未被采到。

报告冻结输入/素材摘要、依赖版本、Git 状态、实际加速后端、PDF 字节、诊断、逐页像素/文字/链接和页面尺寸。
同后端基线要求字节一致；跨后端仍严格比较视觉与诊断。输出目录不能覆盖，输入集合不一致或结果不等价时报错。
首次调用包含惰性渲染模块加载，但不包含解释器启动及 Bundle 读取。性能测量期间不要并行运行测试或其它重负载任务。

## Flash 原生分析

在仓库根目录执行，默认覆盖版本化的 19 份布局语料和 12 份原生表格文档：

```bash
python tests/benchmarks/flash_pdf.py --output output/flash_pdf_refactor/baseline
python tests/benchmarks/flash_pdf.py --output output/flash_pdf_refactor/candidate --baseline output/flash_pdf_refactor/baseline
```

每份文档在独立子进程中预热一次、计时五次，报告中位耗时与进程峰值 RSS。耗时包含 PDFDocument 打开、原生分析和关闭，不包含后处理、输出序列化、OCR 或渲染。RSS 在输出后处理和额外剖析之前采集；它包含解释器和已导入模块，不是文档的增量内存。

每份文档保存完整 `model_list` 和通过统一后处理入口生成的 `middle_json`。仅调用 DocVortex 原生流程，版本字符串固定，比较不移除任何输出字段。`report.json` 包含源码版本、依赖版本、文件指纹与历史清单差异；历史清单不会被改写。`comparison.json` 分别报告完整输出是否相等、耗时比例和 RSS 比例，输出不等价时命令失败。

使用 `--runs 0` 跳过预热和重复计时，只进行功能比较。`--path` 可重复指定固定子集；基线和候选必须使用同一份语料集合。`--profile` 额外生成逐函数调用次数、自身耗时与累计耗时，可定位提取、几何校准、页面准备、页面组装和样式物化阶段；剖析耗时不参与性能比较。性能测量期间避免同时执行测试、构建或其它 CPU 密集任务。

已有报告目录不能覆盖。先在原始版本建立基线，然后在候选版本使用新的输出目录；不可通过更新基线掩盖输出变化。超过 5% 的持续耗时或 RSS 回退应独立复测并定位。
