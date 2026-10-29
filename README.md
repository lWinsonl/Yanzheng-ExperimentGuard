# 研证 · 实验设计教练

面向科研训练的实验设计审查原型。学生写研究主张、计划和执行情况，也可在浏览器本地读取 PDF、DOCX、CSV、文本与代码材料。系统检查有限的计划与执行矛盾、数据泄漏风险和比较条件，并提供修改后复查。

[在线演示](https://yanzheng-experiment-guard.winsongoh14.chatgpt.site/) · [工作流程与能力边界](./docs/experiment-guard-workflow.md)

## 本地运行

需要 Node.js 20.19+。在仓库根目录执行：

```bash
npm ci
npm run build
```

随后用静态服务器服务仓库根目录，打开 `index.html`。上传解析在浏览器本地完成；不会向服务器发送文件。当前规则引擎不支持通读整篇论文、扫描件 OCR 或自动填写实验条件。

## 来源与许可

材料卡片与代码块使用 [Beautiful UI](https://github.com/slev12397/beautiful-ui) 的 MIT 许可组件，许可文本见 [BEAUTIFUL_UI_LICENSE.txt](./BEAUTIFUL_UI_LICENSE.txt)。
