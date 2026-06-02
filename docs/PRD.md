# 产品需求文档 (PRD)

> **版本**：v1.1.0
> **最后更新**：2026-06

## 1. 项目概述

### 项目名称
AI 小说管理系统

### 项目类型
**桌面应用**（Tauri 2 包装）+ 前后端分离架构

### 项目简介
本项目是一个**本地运行**的小说管理工具，通过 Tauri 桌面壳子将 React 前端和 FastAPI 后端打包为单一可执行文件。用户可以管理 AI 模型配置、上传小说文件、自动解析章节目录，并在原生窗口中阅读。

### 核心功能
- **AI 模型配置管理**：管理 Anthropic / OpenAI 兼容的多种 AI 模型连接
- **小说上传与管理**：TXT 格式小说上传、浏览、搜索、删除
- **章节智能解析**：通过自定义正则规则自动提取章节目录
- **章节阅读**：原生窗口流畅阅读体验
- **本地数据存储**：SQLite 数据库 + 本地文件系统

### 目标用户
- **个人用户**：管理自己的小说库（**非 SaaS，单机使用**）
- **AI 爱好者**：需要用不同 AI 模型处理文本的用户
- **网文读者**：希望系统化管理大量小说文件的用户

### 设计原则
- 🎯 **本地优先**：所有数据存储在本地，无云端依赖
- 🚀 **一键使用**：双击 exe 即可启动（仍需 Python 后端）
- 🎨 **现代化 UI**：深色主题，响应式设计
- ⚡ **轻量高效**：Tauri 打包后仅 8MB（对比 Electron 100MB+）

---

## 2. 用户故事

### 2.1 AI 模型配置

作为用户，我希望：
- ➕ 添加不同提供商的 AI 模型（Anthropic / OpenAI / 自定义）
- 🔍 测试模型连接是否正常
- ✏️ 编辑或删除已保存的模型
- ✅ 启用/禁用特定模型（临时切换）
- 📊 查看所有已配置的模型列表

### 2.2 小说管理

作为用户，我希望：
- 📤 通过拖拽或点击上传 TXT 小说
- 📋 在列表中浏览所有已上传的小说
- 🔍 按标题或作者搜索小说
- 🗑️ 删除不需要的小说
- 📑 查看每本小说的章节列表

### 2.3 章节解析

作为用户，我希望：
- 🎯 设置自定义正则规则解析章节
- 👀 解析前预览结果
- 💾 一键保存解析结果
- 📖 阅读时支持章节间跳转

---

## 3. 功能规格

### 3.1 AI 模型配置（v1.0）

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | ✅ | 配置名称 |
| provider | enum | ✅ | anthropic / openai / custom |
| model_url | string | ✅ | API 端点 URL |
| api_key | string | ✅ | 认证密钥 |
| model_name | string | ✅ | 模型标识 |
| enabled | bool | ❌ | 默认 true |

### 3.2 小说管理（v1.0）

**支持格式**：仅 `.txt`
**最大文件**：50MB（`MAX_UPLOAD_SIZE` 可配置）
**存储位置**：`backend/data/novels/{id}_{filename}`

每本小说记录：
- 标题（自动从文件名提取）
- 作者（默认"未知作者"）
- 文件大小、上传时间
- 解析状态（pending / parsed / failed）

### 3.3 章节解析（v1.0）

**默认正则规则**（按优先级）：
1. `第.+?章` - 通用中文章节
2. `第\d+章` - 纯数字章节
3. `^第[一二三四五六七八九十百千零\d]+章.*` - 中文数字章节

**支持自定义**：用户在 UI 中输入任何合法正则表达式

### 3.4 桌面集成（v1.1 - Tauri）

- 窗口大小：1280×800（默认）
- 最小尺寸：1024×700
- 标题：AI 小说管理系统
- 图标：自设计深色主题图标
- 单实例运行（默认）

---

## 4. 非功能性需求

### 4.1 性能
- 前端首屏 < 2 秒
- 小说上传速度：本地文件几乎瞬时
- 章节解析速度：10MB 小说 < 5 秒

### 4.2 兼容性
- **操作系统**：Windows 10/11（macOS/Linux 待适配）
- **浏览器内核**：WebView2（Win10+ 自带）
- **Python**：3.10+
- **Node.js**：18+
- **Rust**：1.77+

### 4.3 安全
- API Key 仅本地存储，不上传任何云端
- CORS 严格限制允许的源
- Tauri capabilities 最小权限原则

### 4.4 隐私
- 所有用户数据（小说、模型配置）保存在本地
- 不收集任何遥测数据
- 离线可用

---

## 5. 技术选型

### 5.1 技术栈

| 层 | 技术 | 版本 | 作用 |
|----|------|------|------|
| **桌面壳** | Tauri | 2.11 | 原生窗口、WebView 渲染 |
| **前端框架** | React | 18 | UI 组件 |
| **构建工具** | Vite | 5 | 快速 HMR、生产打包 |
| **后端框架** | FastAPI | latest | 异步 API |
| **数据库** | SQLite | - | 本地持久化 |
| **DB 驱动** | aiosqlite | latest | 异步 SQLite |
| **包管理-前端** | npm | - | Node 依赖 |
| **包管理-后端** | uv | latest | Python 依赖 |
| **包管理-Rust** | cargo | 1.77+ | Rust 依赖 |

### 5.2 系统依赖

```
backend/pyproject.toml:
  - fastapi
  - uvicorn[standard]
  - aiosqlite
  - httpx
  - pydantic
  - python-multipart

frontend/package.json:
  - react, react-dom
  - vite
  - @vitejs/plugin-react

src-tauri/Cargo.toml:
  - tauri 2
  - serde, serde_json
```

---

## 6. 项目结构

```
d:\AI\new\
├── backend/                # FastAPI 后端
│   ├── routers/            # API 路由
│   ├── services/           # 业务服务
│   ├── tests/              # 单元/E2E 测试
│   ├── data/               # 运行时数据 (gitignored)
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   └── pyproject.toml
│
├── frontend/               # React + Vite 前端
│   ├── src/
│   │   ├── api/client.js
│   │   ├── components/
│   │   │   ├── ModelConfigPanel.jsx
│   │   │   ├── NovelPanel.jsx
│   │   │   ├── NovelReader.jsx
│   │   │   ├── ErrorBoundary.jsx
│   │   │   ├── Modal/ConfirmDialog.jsx
│   │   │   └── Toast/ToastProvider.jsx
│   │   ├── hooks/useApi.js
│   │   └── utils/regex.js
│   └── vite.config.js
│
├── src-tauri/              # Tauri 桌面壳
│   ├── src/main.rs
│   ├── src/lib.rs
│   ├── tauri.conf.json
│   ├── capabilities/default.json
│   └── icons/              # 16 个尺寸
│
├── scripts/                # 启动/构建脚本
│   ├── start-app.bat
│   ├── build.bat
│   └── dev.bat
│
└── docs/                   # 项目文档
    ├── PRD.md (本文件)
    └── 技术架构文档.md
```

---

## 7. 数据模型

### 7.1 model_configs（AI 模型配置）
```sql
CREATE TABLE model_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    provider TEXT NOT NULL,           -- anthropic / openai / custom
    model_url TEXT NOT NULL,
    api_key TEXT NOT NULL,
    model_name TEXT NOT NULL,
    enabled INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 7.2 novels（小说）
```sql
CREATE TABLE novels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    author TEXT DEFAULT '未知作者',
    filename TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_size INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',    -- pending / parsed / failed
    parse_rule TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 7.3 chapters（章节）
```sql
CREATE TABLE chapters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    novel_id INTEGER NOT NULL,
    chapter_number INTEGER NOT NULL,
    title TEXT NOT NULL,
    content TEXT,
    start_position INTEGER DEFAULT 0,
    end_position INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (novel_id) REFERENCES novels(id) ON DELETE CASCADE
);
```

---

## 8. API 规格

所有 API 以 `/api` 为前缀。

### 8.1 健康检查
- `GET /api/health` → `{"status": "healthy"}`

### 8.2 AI 模型
- `GET /api/models` - 列出所有配置
- `GET /api/models/enabled` - 仅启用的
- `POST /api/models` - 创建
- `PUT /api/models/{id}` - 更新
- `PATCH /api/models/{id}/toggle?enabled=1` - 启停
- `DELETE /api/models/{id}` - 删除
- `POST /api/models/test` - 测试连接

### 8.3 小说
- `GET /api/novels` - 列表
- `GET /api/novels/{id}` - 详情
- `POST /api/novels/upload` - 上传（multipart）
- `PUT /api/novels/{id}` - 更新
- `DELETE /api/novels/{id}` - 删除
- `PUT /api/novels/{id}/parse-rule` - 设置规则
- `POST /api/novels/{id}/parse` - 执行解析
- `POST /api/novels/{id}/parse-preview` - 预览解析
- `POST /api/novels/{id}/parse-fixed` - 按固定块解析
- `GET /api/novels/{id}/raw` - 原始文本
- `GET /api/novels/{novel_id}/chapters/{chapter_id}` - 章节内容

---

## 9. UI 设计

### 9.1 整体布局
```
┌────────────────────────────────────────┐
│  [Logo]  AI 小说管理系统    [主题切换]   │  ← 顶部
├────────────────────────────────────────┤
│  [模型配置]  [小说管理]                  │  ← Tab 导航
├────────────────────────────────────────┤
│                                        │
│         内容区（Tab 切换）              │
│                                        │
└────────────────────────────────────────┘
```

### 9.2 模型配置页
- 表格展示已配置模型
- 操作按钮：测试、编辑、删除、启停
- 顶部「添加模型」按钮

### 9.3 小说管理页
- 左侧：搜索框 + 小说列表
- 右侧：详情 / 阅读 / 解析规则

### 9.4 主题
- 默认深色主题（与 Tauri 启动器一致）
- 浅色主题可选
- 主题设置持久化在 localStorage

---

## 10. 验收标准

### v1.0.0（已完成 ✅）
- ✅ AI 模型 CRUD 操作
- ✅ 模型连接测试
- ✅ 小说上传、列表、删除
- ✅ 章节解析（默认规则 + 自定义规则）
- ✅ 章节内容查看
- ✅ 深色/浅色主题切换

### v1.1.0（已完成 ✅）
- ✅ Tauri 桌面化打包
- ✅ 单 exe 8MB（release 优化）
- ✅ 系统托盘图标
- ✅ 窗口尺寸持久化

### v2.0.0（待开发 🚧）
- ⏳ PyInstaller 打包后端（无需 Python 环境）
- ⏳ 跨平台支持（macOS / Linux）
- ⏳ 阅读进度同步
- ⏳ 多格式支持（EPUB、PDF）
- ⏳ AI 章节摘要

---

## 11. 风险与限制

| 风险 | 描述 | 缓解 |
|------|------|------|
| **后端依赖 Python** | 当前仍需 Python 环境 | 后续用 PyInstaller 打包 |
| **仅 Windows** | Tauri 配置仅优化 Windows | macOS/Linux 需重新构建 |
| **WebView2 依赖** | 需 Win10+ 自带运行时 | Win7 不支持 |
| **大文件性能** | 50MB+ 小说解析可能慢 | 后续支持流式解析 |
| **正则复杂度** | 用户写错正则可能卡死 | 加超时和错误提示 |

---

## 12. 迭代历史

### v1.1.0（当前）
- 🎁 Tauri 2.11 桌面化
- 🎁 项目结构整理（scripts/、docs/、data/）
- 🎁 详细 README + 启动脚本
- 🎁 Tauri 启动时检测环境

### v1.0.0
- AI 模型配置（Anthropic / OpenAI）
- 小说上传与列表管理
- 章节自动解析
- 现代化深色 UI
