# AI Model Settings

AI 模型连接配置管理平台，支持 Anthropic API 和 OpenAI API 兼容模型的配置、测试和保存。

## 功能特性

- 支持 Anthropic API 兼容模型配置
- 支持 OpenAI API 兼容模型配置
- 连接测试功能（带动画反馈）
- SQLite 数据库持久化存储
- 现代化的深色主题界面

## 项目结构

```
d:\AI\new\
├── backend/                 # FastAPI 后端
│   ├── main.py             # API 接口
│   ├── database.py        # 数据库操作
│   ├── schemas.py         # 数据模型
│   └── pyproject.toml     # Python 依赖
├── frontend/               # React 前端
│   ├── src/
│   │   ├── App.jsx        # 主组件
│   │   └── App.css       # 样式
│   └── package.json      # Node 依赖
└── README.md
```

## 快速开始

### 后端

```bash
cd backend
pip install -e .
python main.py
```

后端服务运行在 http://localhost:8008

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端开发服务器运行在 http://localhost:5173

## API 接口

| 接口 | 方法 | 功能 |
|------|------|------|
| `/api/models` | GET | 获取所有模型配置 |
| `/api/models/{provider}` | GET | 获取指定 provider 配置 |
| `/api/models` | POST | 保存/更新模型配置 |
| `/api/models/{provider}` | DELETE | 删除模型配置 |
| `/api/models/test` | POST | 测试连接 |

## 技术栈

- **后端**: FastAPI, SQLite, httpx
- **前端**: React, Vite