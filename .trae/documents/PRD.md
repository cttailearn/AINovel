# 产品需求文档 (PRD)

## 1. 项目概述

### 项目名称
前后端分离的 React 前端应用

### 项目类型
单页应用 (SPA)，作为后端服务的 Web 前端界面

### 核心功能
- 提供与后端服务交互的用户界面
- 通过配置文件管理后端连接地址
- 支持开发环境和生产环境切换

### 目标用户
- 后端服务使用者
- 需要通过 Web 界面操作后端 API 的用户

---

## 2. 用户需求

### 功能需求
1. **后端连接配置**
   - 通过 config.json 文件配置后端服务地址
   - 默认连接地址：127.0.0.1:8008
   - 支持自定义端口配置

2. **开发环境支持**
   - 使用 `npm run dev` 启动开发服务器
   - 支持热重载 (HMR)
   - 自动代理后端请求

3. **生产环境支持**
   - 使用 `npm run build` 打包成静态文件
   - 生成的静态文件可部署到任何静态服务器

4. **项目结构要求**
   - 放置在 frontend 目录
   - 使用 npm 管理依赖

---

## 3. 技术选型

### 框架选择
- **构建工具**: Vite
- **前端框架**: React 18
- **语言**: JavaScript / JSX
- **包管理工具**: npm

### 项目依赖
- react
- react-dom
- vite
- @vitejs/plugin-react

---

## 4. 目录结构

```
frontend/
├── config.json          # 后端配置
├── index.html           # 入口 HTML
├── package.json         # npm 配置
├── vite.config.js       # Vite 配置
├── public/              # 静态资源
└── src/                 # 源代码
    ├── main.jsx         # React 入口
    ├── App.jsx          # 根组件
    ├── App.css          # 样式
    ├── config.js        # 配置读取工具
    └── components/      # 组件目录
```

---

## 5. 配置说明

### config.json 结构
```json
{
  "backend": {
    "host": "127.0.0.1",
    "port": 8008
  }
}
```

### 配置读取
- 前端应用启动时读取 config.json
- 构建时通过 Vite 配置注入环境变量
- 提供统一的 API 请求基础路径

---

## 6. 验收标准

1. ✅ frontend 目录存在且结构完整
2. ✅ package.json 包含正确的 scripts 配置
3. ✅ config.json 存在且包含后端配置
4. ✅ `npm run dev` 能正常启动开发服务器
5. ✅ `npm run build` 能生成静态文件到 dist 目录
6. ✅ 前端能正确读取并使用 config.json 中的配置
7. ✅ 开发环境下能成功连接后端 127.0.0.1:8008