# AI 小说创作 + 加料 + 图像生成 系统

> **当前版本**：v0.3.x（2026-06）

基于 **Tauri + React + FastAPI** 的本地 AI 创作桌面应用。覆盖小说管理、
AI 创作（Planner/Writer/Critic 三 Agent）、知识图谱、加料工坊、图像生成。

## 功能特性

- 🤖 AI 模型配置（Anthropic / OpenAI / 国产厂商兼容）
- 📚 小说管理：上传 TXT、章节解析、阅读
- ✍️ **AI 小说创作**：引导式问答建项 → 三 Agent 单候选流水线 → 知识图谱记忆
- 🧠 **知识图谱**：人物 / 事件 / 地点 / 剧情线索 / 出场记录（多表物理隔离）
- 🔧 **加料工坊**：总结 → 识别 → 改写三步流水线，支持回滚历史版本
- 🎨 **图像生成**：文生图 / 图生图，多模型（MiniMax / DashScope）
- 📤 章节导出：TXT / Markdown，保留中文文件名
- 💾 SQLite 本地存储，TaskRegistry 长任务可恢复
- 🖥️ Tauri 桌面应用（双 exe：Web 壳 + Python 后端）
- ⌨️ 键盘快捷键：Ctrl+Enter 触发生成，Esc 取消

## 项目结构

```
d:\AI\new\                          ← 根目录
├── .gitignore                       ← Git 忽略规则
├── README.md                        ← 本文件
│
├── backend/                         ← 🐍 Python (FastAPI) 后端
│   ├── main.py                      # API 入口
│   ├── config.py                    # 配置（含路径/CORS）
│   ├── database.py                  # SQLite 操作
│   ├── schemas.py                   # Pydantic 模型
│   ├── conftest.py                  # pytest 配置
│   ├── smoke_test.py                # 烟雾测试
│   ├── pyproject.toml               # Python 依赖（uv）
│   ├── uv.lock                      # 依赖锁文件
│   ├── .python-version              # Python 版本
│   ├── .gitignore
│   │
│   ├── routers/                     # API 路由
│   │   ├── __init__.py
│   │   ├── models.py                # AI 模型配置接口
│   │   └── novels.py                # 小说管理接口
│   │
│   ├── services/                    # 业务逻辑
│   │   ├── __init__.py
│   │   ├── ai_service.py
│   │   ├── file_service.py
│   │   ├── model_service.py
│   │   └── novel_service.py
│   │
│   ├── tests/                       # 测试
│   │   ├── __init__.py
│   │   ├── test_api.py
│   │   ├── test_parsers.py
│   │   └── test_e2e.py              # E2E 测试（含前端）
│   │
│   └── data/                        # 运行时数据（gitignored）
│       ├── models.db                # SQLite 数据库
│       └── novels/                  # 上传的小说文件
│
├── frontend/                        # ⚛️  React + Vite 前端
│   ├── index.html
│   ├── package.json
│   ├── package-lock.json
│   ├── vite.config.js               # Vite 配置
│   │
│   └── src/
│       ├── main.jsx
│       ├── App.jsx
│       ├── App.css
│       ├── ThemeContext.jsx
│       ├── api/client.js            # API 客户端（已加 Tauri 检测）
│       ├── components/
│       │   ├── ModelConfigPanel.jsx
│       │   ├── NovelPanel.jsx
│       │   ├── NovelReader.jsx
│       │   ├── ErrorBoundary.jsx
│       │   ├── Modal/ConfirmDialog.jsx
│       │   └── Toast/ToastProvider.jsx
│       ├── hooks/useApi.js
│       └── utils/regex.js
│
├── src-tauri/                       # 🦀 Tauri (Rust) 桌面壳子
│   ├── Cargo.toml
│   ├── Cargo.lock
│   ├── tauri.conf.json              # Tauri 应用配置
│   ├── build.rs
│   ├── .gitignore
│   │
│   ├── src/
│   │   ├── main.rs                  # 入口
│   │   └── lib.rs                   # 启动逻辑
│   │
│   ├── capabilities/default.json    # 权限配置
│   └── icons/                       # 16 个图标（含源图）
│
├── scripts/                         # 📜 启动/构建脚本
│   ├── start-app.bat                # 一键启动（日常使用）
│   ├── build.bat                    # 一键重新构建
│   └── dev.bat                      # 一键开发模式
│
└── docs/                            # 📖 项目文档
    ├── PRD.md                       # 产品需求
    └── 技术架构文档.md
```

## 目录必要性对照

| 场景 | backend/ | frontend/ | src-tauri/ | scripts/ | docs/ |
|------|:---:|:---:|:---:|:---:|:---:|
| **跑现有 exe** | ✅ | ❌ | ❌ | ✅ | ❌ |
| **修改后端** | ✅ | - | - | ✅ | - |
| **修改前端** | ✅ | ✅ | ✅ | ✅ | - |
| **修改 Tauri 配置** | ✅ | - | ✅ | ✅ | - |
| **修改文档** | - | - | - | - | ✅ |

> 简而言之：**frontend/ 和 src-tauri/ 是"开发原料"**，运行现有 exe 只需要：
> `backend/` + `src-tauri/target/release/ai-novel-desktop.exe` + `scripts/start-app.bat`

## 快速使用（已有 exe）

### 日常使用
双击 [`scripts\start-app.bat`](file:///d:/AI/new/scripts/start-app.bat)：
- 自动启动 FastAPI 后端
- 自动打开桌面应用窗口

### 关闭应用
- 关闭桌面窗口即停止前端
- 后端进程保留（任务管理器结束 `python.exe` 即可）

## 开发指南

### 开发模式（热更新）
双击 [`scripts\dev.bat`](file:///d:/AI/new/scripts/dev.bat)：
- 启动后端（8008 端口）
- 启动 Vite 开发服务器
- 启动 Tauri 开发窗口（带热更新）
- 修改 `frontend/src/` 下的文件会自动刷新
- 修改 `src-tauri/` 下的 Rust 代码需要重新编译

### 重新构建
双击 [`scripts\build.bat`](file:///d:/AI/new/scripts/build.bat)：
- 构建前端：`npm run build`
- 构建 Tauri：`cargo build --release`
- 产物：`src-tauri/target/release/ai-novel-desktop.exe`

### 单独运行某个部分
```bash
# 仅后端
cd backend
uv run main.py

# 仅前端开发服务器
cd frontend
npm run dev
# 访问 http://localhost:5173
```

## 环境要求

| 工具 | 版本 | 用途 |
|------|------|------|
| Node.js | ≥ 18 | 前端构建 |
| Python | ≥ 3.10 | FastAPI 后端 |
| uv | 最新版 | Python 包管理 |
| Rust | ≥ 1.77 | Tauri 编译 |
| MSVC | 2022 | Rust 编译 |
| WebView2 | 系统自带 | Tauri 运行时 |

## API 接口

后端运行在 `http://127.0.0.1:8008`，前端调用 `/api/*` 路径。

主要接口：
- `GET/POST /api/models` - AI 模型配置
- `GET/POST/DELETE /api/novels` - 小说管理
- `POST /api/novels/{id}/parse` - 章节解析

完整文档：查看 [`docs/PRD.md`](file:///d:/AI/new/docs/PRD.md)

## 技术栈

- **桌面壳子**: Tauri 2.11 (Rust)
- **前端**: React 18 + Vite 5
- **后端**: FastAPI + SQLite (aiosqlite)
- **打包**: cargo + tauri-cli

## 常见问题

### Q: 启动后报错「无法连接 127.0.0.1:8008」？
A: 后端没启动。检查 `scripts\start-app.bat` 是否正常运行，或手动 `cd backend && uv run main.py`。

### Q: 修改了前端代码没生效？
A: Tauri 嵌入的是构建后的文件，需要重新构建：`scripts\build.bat`。

### Q: Tauri 编译很慢？
A: 首次 5~10 分钟（下载 + 编译 434 个依赖）。后续增量编译 1~2 分钟。

### Q: 国内 cargo 拉不动依赖？
A: 已在 `~/.cargo/config.toml` 配置 `rsproxy.cn` 镜像。脚本内已自动设置 `CARGO_HTTP_CHECK_REVOKE=false`。

### Q: 怎么完全分发给朋友用？
A: 当前 Tauri exe 仍依赖 Python 后端。要做到"双击即用"：
1. 用 PyInstaller 把 backend 打成 exe
2. 配置 Tauri sidecar 自动启动后端 exe
3. 重新构建 Tauri
4. 产物：`ai-novel-desktop.exe` + `ai-novel-backend.exe`

## 迭代历史

- **v1.1.0** - Tauri 桌面化 + 项目结构整理（当前）
- **v1.0.0** - AI 模型配置 + 小说管理（Web 版）
