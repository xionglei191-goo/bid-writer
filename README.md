# 技术标生产与知识工程系统

本项目是本地Web版技术标生产系统。系统以 `02_知识库` 为知识资产中心，以 `03_生产系统/bid_writer_app` 为应用代码和可重建运行索引，以 `04_交付与报告` 为正式交付目录。

## 启动

双击 `run_server.cmd`，浏览器访问 `http://127.0.0.1:8765`。

首次安装依赖：

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" -m pip install -r backend\requirements.txt
cd frontend
npm install
npm run build
```

## 模块

- `backend/bid_writer_v2/knowledge`：扫描、去重、解析/OCR、知识拆解、重构、审核、发布和检索。
- `backend/bid_writer_v2/production`：项目、要求、目录、章节生成、证据响应、质量门禁和DOCX导出。
- `frontend/src`：React模块化工作台。
- `docs`：架构、模块边界、研发工作流和技术决策。

## 数据边界

原始资料只能从 `01_原始标书库` 读取；正式知识只从 `02_知识库/06_已发布知识库` 检索；SQLite和OCR缓存位于 `data`，可从知识文件重建；正式文件写入 `04_交付与报告`。客户资料、知识正文、数据库和真实密钥不会提交到GitHub。

## 批量管理

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" backend\scripts_v2\manage.py scan
& "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" backend\scripts_v2\manage.py queue-all
& "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" backend\scripts_v2\manage.py work --limit 20
& "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" backend\scripts_v2\manage.py metrics
```

## 测试

```powershell
$env:PYTHONPATH = "backend"
& "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" -m unittest discover -s backend\tests_v2 -v
cd frontend
npm run build
```
