# 产品需求文档 (PRD)

## 1. 项目概述

### 项目名称
AI 小说管理系统

### 项目类型
前后端分离的 Web 应用

### 核心功能
- **AI 模型配置管理**：管理多种 AI 模型的连接配置（已完成）
- **小说上传与管理**：上传、浏览、删除小说（新增）
- **章节解析**：通过自定义规则自动解析章节目录（新增）

### 目标用户
- 需要管理小说库的用户
- 需要使用 AI 模型处理文本的用户

---

## 2. 用户需求

### 2.1 已完成功能 - AI 模型配置

1. **后端连接配置**
   - 通过配置文件管理后端服务地址
   - 默认连接地址：127.0.0.1:8008

2. **模型配置管理**
   - 添加、编辑、删除模型配置
   - 支持多种提供商（Anthropic、OpenAI、Custom）
   - 测试模型连接状态
   - 启用/禁用模型

### 2.2 新增功能 - 小说管理

#### 功能需求

1. **小说上传**
   - 支持上传 TXT 格式的小说文件
   - 显示上传进度
   - 上传成功后自动解析章节目录
   - 每个小说记录：文件名、作者、标题、状态、上传时间

2. **小说浏览**
   - 列表展示所有已上传的小说
   - 显示小说基本信息（标题、作者、章节数、状态）
   - 支持删除小说
   - 支持按标题或作者搜索
   - 点击小说查看详情和章节列表

3. **章节解析**
   - 设置解析规则：使用正则表达式匹配章节标题
   - 默认规则：`第.+?章`、`第\\d+章`、`^第[一二三四五六七八九十百千零\\d]+章`
   - 支持自定义正则规则
   - 解析后自动生成章节目录
   - 显示解析结果预览

4. **章节查看**
   - 展示小说的所有章节
   - 点击章节查看内容
   - 显示章节标题和内容

---

## 3. 技术选型

### 框架选择
- **后端**：FastAPI + uvicorn + aiosqlite
- **前端**：React 18 + Vite
- **语言**：Python / JavaScript / JSX

### 项目依赖

#### 后端依赖
- fastapi
- uvicorn
- aiosqlite
- httpx
- pydantic
- python-multipart

#### 前端依赖
- react
- react-dom
- vite
- @vitejs/plugin-react

---

## 4. 目录结构

```
backend/
├── main.py              # FastAPI 入口
├── database.py          # 数据库操作
├── schemas.py           # 数据模型
├── models.db            # SQLite 数据库
└── novels/              # 小说文件存储目录

frontend/
├── config.json          # 后端配置
├── index.html           # 入口 HTML
├── package.json         # npm 配置
├── vite.config.js       # Vite 配置
└── src/                 # 源代码
    ├── main.jsx         # React 入口
    ├── App.jsx          # 根组件
    ├── App.css          # 样式
    ├── config.js        # 配置读取
    └── components/      # 组件目录
        ├── ModelConfig.jsx    # 模型配置组件
        ├── NovelList.jsx     # 小说列表
        ├── NovelUpload.jsx   # 小说上传
        ├── NovelDetail.jsx  # 小说详情
        └── ChapterView.jsx   # 章节查看
```

---

## 5. 数据库设计

### 5.1 model_configs 表（已存在）

```sql
CREATE TABLE model_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    provider TEXT NOT NULL,
    model_url TEXT NOT NULL,
    api_key TEXT NOT NULL,
    model_name TEXT NOT NULL,
    enabled INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 5.2 novels 表（新增）

```sql
CREATE TABLE novels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    author TEXT DEFAULT '未知作者',
    filename TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_size INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',
    parse_rule TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 5.3 chapters 表（新增）

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

## 6. API 设计

### 6.1 小说管理 API

#### 上传小说
```
POST /api/novels/upload
Content-Type: multipart/form-data

file: (binary)

Response:
{
    "id": 1,
    "title": "小说标题",
    "author": "作者名",
    "filename": "xxx.txt",
    "status": "pending",
    "message": "上传成功"
}
```

#### 获取小说列表
```
GET /api/novels

Response:
{
    "novels": [
        {
            "id": 1,
            "title": "小说标题",
            "author": "作者名",
            "chapter_count": 0,
            "status": "pending",
            "created_at": "2024-01-01T00:00:00"
        }
    ]
}
```

#### 获取单个小说详情
```
GET /api/novels/{id}

Response:
{
    "id": 1,
    "title": "小说标题",
    "author": "作者名",
    "filename": "xxx.txt",
    "status": "parsed",
    "chapter_count": 100,
    "chapters": [...]
}
```

#### 删除小说
```
DELETE /api/novels/{id}

Response:
{
    "message": "小说已删除"
}
```

### 6.2 章节解析 API

#### 设置解析规则
```
PUT /api/novels/{id}/parse-rule
Content-Type: application/json

{
    "rule": "^第[一二三四五六七八九十百千零\\d]+章.*"
}

Response:
{
    "message": "规则已更新"
}
```

#### 执行解析
```
POST /api/novels/{id}/parse
Content-Type: application/json

{
    "rule": "^第[一二三四五六七八九十百千零\\d]+章.*"
}

Response:
{
    "success": true,
    "chapters_found": 100,
    "chapters": [
        {
            "id": 1,
            "chapter_number": 1,
            "title": "第一章 xxx"
        }
    ]
}
```

#### 获取章节内容
```
GET /api/novels/{novel_id}/chapters/{chapter_id}

Response:
{
    "id": 1,
    "chapter_number": 1,
    "title": "第一章 xxx",
    "content": "章节内容..."
}
```

---

## 7. 前端界面设计

### 7.1 导航结构
- 顶部导航栏包含两个主要标签：
  - **模型配置**：现有的 AI 模型配置界面
  - **小说管理**：新的小说管理界面

### 7.2 小说上传界面
- 拖拽上传区域
- 点击选择文件
- 上传进度条
- 上传成功后自动跳转至小说详情

### 7.3 小说浏览界面
- 搜索栏（按标题/作者搜索）
- 小说卡片列表
- 每个卡片显示：标题、作者、章节数、状态、操作按钮

### 7.4 小说详情界面
- 小说信息展示
- 解析规则设置区域
- 章节列表
- 解析按钮

### 7.5 章节查看
- 章节标题
- 章节内容（支持滚动）

---

## 8. 验收标准

### 已完成功能
1. ✅ 模型配置界面完整可用
2. ✅ 主题切换功能正常
3. ✅ 后端连接状态显示

### 新增功能
1. ✅ 小说上传功能正常
2. ✅ 小说列表展示正常
3. ✅ 小说详情显示正常
4. ✅ 删除小说功能正常
5. ✅ 章节解析规则设置正常
6. ✅ 章节解析执行正常
7. ✅ 章节内容查看正常
8. ✅ 响应式布局正常

---

## 9. 迭代历史

### v1.0.0（当前版本）
- AI 模型配置管理
- 小说上传与浏览
- 章节解析功能