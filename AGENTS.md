# MikuDanceStudio

MikuMikuDance v9.32 的行为级移植（C++ / Win32 / DirectX 9），准备开源。

## 提交规范（强制）

- **禁止**在 commit message 中添加 `Co-Authored-By: Claude`（或任何 AI 署名/尾注）。
  历史上的此类尾注已于 2026-09 全部移除；未来的提交同样不得添加。

## 代码检索工具

- **Serena**：`.serena/project.yml`（clangd/cpp）。MCP 以项目目录为 cwd 启动即可。
- **CodeGraph**：索引在 `.codegraph/`（数据库不入库）。新克隆先 `codegraph init .`，改动后 `codegraph sync .`。
- **Graphify**：`graphify-out/graph.json` 与 `GRAPH_REPORT.md` 入库。仅用本地 AST 更新，不调用 LLM：
  `graphify extract . --code-only && graphify cluster-only . --no-label --no-viz`。
