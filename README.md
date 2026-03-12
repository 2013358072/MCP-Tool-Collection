# MCP-Tool-Collection

基于 `FastMCP` 的 Windows 友好型 MCP 工具集合，提供文件系统、网络、文档、表格、幻灯片、PDF、邮件、Shell、数据库、金融、地图等能力。

## 项目简介

本项目将常见办公和系统能力封装为 MCP Tools，适合接入支持 MCP 的客户端或调试工具进行调用。

当前工具覆盖以下能力：

- 文件系统
- Web 请求与网页抓取
- DOCX 文档读写
- Excel 表格处理
- PPTX 幻灯片处理
- PDF 读取与表格抽取
- 邮件发送与读取
- Shell / Python 执行
- SQLite 数据库
- Yahoo Finance 金融数据
- 高德地图服务

## 安装

建议在虚拟环境中安装：

```bash
pip install -e .
```

如果你使用 `uv`：

```bash
uv pip install -e .
```

## 启动方式

在项目根目录执行：

```bash
python -m mcp_toolkit.main
```

当前服务默认以 `streamable-http` 方式启动，监听：

```text
http://0.0.0.0:8801
```

## 配置说明

配置文件位置：

```text
src/mcp_toolkit/core/config.py
```

推荐通过环境变量配置，不建议把真实密钥直接写入源码。

### 通用必填字段

以下字段建议在启动前明确配置：

| 字段名 | 说明 | 是否必填 |
| --- | --- | --- |
| `FILESYSTEM_ROOT` | 文件沙箱根目录。文件、文档、表格、PDF、PPT 等相对路径都会落在这里。 | 是 |
| `SQLITE_DB_PATH` | SQLite 默认数据库路径。`db_sqlite_query` 不传 `db_path` 时使用。 | 是 |

### 按能力启用时的必填字段

以下字段只在你使用对应工具能力时需要配置：

| 字段名 | 用途 | 对应工具/模块 | 是否必填 |
| --- | --- | --- | --- |
| `SERPAPI_KEY` | Web 搜索能力 | `web_search` | 使用搜索时必填 |
| `AMAP_API_KEY` | 高德地图服务 | 所有 `maps_*` 工具 | 使用地图时必填 |
| `QQ_MAIL_SMTP_USER` | QQ 邮箱用户名 | 邮件工具 | 使用邮件时必填 |
| `QQ_MAIL_SMTP_PASSWORD_KEY` | QQ 邮箱授权码 | 邮件工具 | 使用邮件时必填 |
| `DOUBAO_API_KEY` | 豆包/方舟模型密钥 | 豆包相关搜索或模型能力 | 使用对应能力时必填 |
| `DOUBAO_MODEL_NAME` | 豆包模型名 | 豆包相关搜索或模型能力 | 使用对应能力时必填 |

### 常用可选字段

| 字段名 | 说明 |
| --- | --- |
| `DOUBAO_BASE_URL` | 豆包 API 基础地址 |
| `AMAP_BASE_URL` | 高德地图 Web 服务基础地址 |
| `AMAP_TIMEOUT` | 高德请求超时秒数 |
| `TIMEOUT_S` | 通用 HTTP 请求超时 |
| `WEB_SEARCH_TIMEOUT` | Web 搜索超时 |
| `SHELL_EXEC_TIMEOUT` | Shell 命令执行超时 |
| `PYTHON_EXEC_TIMEOUT` | Python 代码执行超时 |
| `LOG_DIR` | 日志目录 |
| `LOG_FILENAME` | 日志文件名 |
| `LOG_LEVEL` | 控制台日志级别 |
| `SESSION_MAX_IDLE_SECONDS` | 会话最大空闲时间 |
| `SESSION_MAX_COUNT` | 最大会话数量 |

## 工具清单

以下工具清单基于 `tools_list.json`。

### 1. 文件系统工具

| 工具名 | 说明 |
| --- | --- |
| `fs_read_file` | 读取文件 |
| `fs_write_text` | 写入文本文件（覆盖/创建） |
| `fs_write_json` | 写入 JSON 文件 |
| `fs_list_dir` | 列出目录内容 |
| `fs_glob` | 按通配符匹配文件 |
| `fs_mkdir` | 创建目录 |
| `fs_remove` | 删除文件 |
| `fs_move` | 移动或重命名文件/目录 |
| `fs_copy` | 复制文件或目录 |
| `fs_stat` | 获取文件元信息 |
| `fs_exists` | 判断路径是否存在 |
| `fs_compute_hash` | 计算文件哈希 |
| `fs_search_text` | 搜索文件或目录中的文本 |
| `fs_zip_create` | 创建 zip 包 |
| `fs_zip_extract` | 解压 zip |

### 2. Web 工具

| 工具名 | 说明 |
| --- | --- |
| `web_search` | 搜索引擎检索 |
| `web_fetch` | 抓取网页内容 |
| `web_extract` | 抽取网页结构化信息 |
| `http_request` | 发送通用 HTTP 请求 |
| `http_download` | 下载文件到本地 |
| `url_parse` | 解析 URL |
| `url_expand` | 展开短链或重定向 |
| `net_ping` | 网络连通性探测 |
| `net_whois` | WHOIS 查询 |
| `net_dns_lookup` | DNS 查询 |

### 3. 文档工具

| 工具名 | 说明 |
| --- | --- |
| `docs_read` | 读取 DOCX 文档 |
| `docs_write` | 覆盖写入 DOCX 文档 |
| `docs_append` | 追加内容到 DOCX 文档 |
| `docs_replace` | 在 DOCX 中查找替换 |
| `docs_find` | 在 DOCX 中查找关键字 |
| `docs_export_pdf` | 文档导出为 PDF |
| `docs_export_docx` | 根据结构化内容导出 DOCX |

### 4. 表格工具

| 工具名 | 说明 |
| --- | --- |
| `sheets_read_range` | 读取 Excel 指定范围 |
| `sheets_write_range` | 写入 Excel 指定范围 |
| `sheets_append_rows` | 追加多行到 Excel |
| `sheets_sort_range` | 对指定范围排序 |
| `sheets_export_xlsx` | 导出 XLSX 文件 |

### 5. 幻灯片工具

| 工具名 | 说明 |
| --- | --- |
| `slides_create_deck` | 创建 PPTX 演示文稿 |
| `slides_add_slide` | 新增幻灯片 |
| `slides_add_text` | 添加文本框 |
| `slides_add_image` | 添加图片 |
| `slides_add_table` | 添加表格 |
| `slides_add_chart` | 添加图表 |
| `slides_export_pptx` | 导出或另存为 PPTX |

### 6. PDF 工具

| 工具名 | 说明 |
| --- | --- |
| `pdf_read_text` | 读取 PDF 文本 |
| `pdf_extract_tables` | 抽取 PDF 表格 |

### 7. 邮件工具

| 工具名 | 说明 |
| --- | --- |
| `email_send` | 发送邮件 |
| `email_draft` | 创建草稿 |
| `email_reply` | 回复邮件 |
| `email_forward` | 转发邮件 |
| `email_search` | 搜索邮件 |
| `email_read` | 读取邮件 |
| `email_list_folders` | 列出邮箱文件夹 |
| `email_create_label` | 创建标签或文件夹 |

### 8. Shell 工具

| 工具名 | 说明 |
| --- | --- |
| `shell_exec` | 执行 Shell 命令 |
| `shell_which` | 查找可执行文件路径 |
| `shell_env_get` | 读取环境变量 |
| `python_exec` | 执行 Python 代码片段 |

### 9. 数据库工具

| 工具名 | 说明 |
| --- | --- |
| `db_sqlite_query` | 执行 SQLite 查询、写入或事务 |

### 10. 金融工具

| 工具名 | 说明 |
| --- | --- |
| `finance_get_ticker_info` | 获取股票/证券基础信息 |
| `finance_get_ticker_news` | 获取股票新闻 |
| `finance_search_financial_info` | 搜索雅虎财经信息 |
| `finance_get_financial_top_entities` | 获取板块头部实体 |
| `finance_get_price_history` | 获取历史价格 |
| `finance_get_option_chain` | 获取期权链 |
| `finance_get_ticker_earnings` | 获取收益/财报数据 |
| `finance_get_top_growth_companies` | 获取高增长公司 |
| `finance_get_top_performing_companies` | 获取高表现公司 |
| `finance_get_top_etfs_by_sector` | 获取板块 ETF 排名 |
| `finance_get_top_mutual_funds_by_sector` | 获取板块共同基金排名 |
| `finance_get_top_companies_by_sector` | 获取板块公司排名 |

### 11. 地图工具

| 工具名 | 说明 |
| --- | --- |
| `maps_geocode` | 地址转经纬度 |
| `maps_reverse_geocode` | 经纬度转地址 |
| `maps_search_places` | 关键词搜索地点 |
| `maps_search_nearby` | 搜索附近地点 |
| `maps_get_place_details` | 获取地点详情 |
| `maps_get_directions` | 路线规划 |
| `maps_get_distance` | 计算距离与耗时 |

## 日志

日志默认输出到：

```text
log/mcp_toolkit.log
```

当前已支持记录：

- Provider 启动/关闭日志
- 工具调用开始日志
- 工具调用成功日志
- 工具调用失败日志
- 工具调用异常日志

## 目录说明

```text
src/mcp_toolkit/
  core/         核心配置、日志、会话
  providers/    各类工具 Provider
log/            日志目录
```

## 注意事项

- 所有文件类能力默认应使用沙箱目录 `FILESYSTEM_ROOT`
- 建议不要将真实密钥、授权码直接写入源码
- 邮件、地图、搜索等外部服务能力依赖对应配置项
- 若修改了 `config.py` 或 Provider 代码，请重启 MCP 服务
