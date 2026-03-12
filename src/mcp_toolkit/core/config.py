import os
from pathlib import Path

############################
# 大模型配置
############################
DOUBAO_API_KEY = os.getenv("DOUBAO_API_KEY", "")
DOUBAO_MODEL_NAME = os.getenv("DOUBAO_MODEL_NAME", "")
DOUBAO_BASE_URL = os.getenv("DOUBAO_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")

############################
# 金融相关配置
############################
ALPHAVANTAGE_API_KEY = os.getenv("ALPHAVANTAGE_API_KEY", "")
ALPHAVANTAGE_BASE_URL = os.getenv(
    "ALPHAVANTAGE_API_URL",
    f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol=IBM&apikey={ALPHAVANTAGE_API_KEY}",
)

############################
# 数据库配置
############################
SQLITE_DB_PATH = os.getenv(
    "SQLITE_DB_PATH",
    r"",
)

############################
# 高德地图 Web 服务 API 配置
############################
AMAP_API_KEY = os.getenv("AMAP_API_KEY", "")
AMAP_BASE_URL = os.getenv("AMAP_BASE_URL", "https://restapi.amap.com/v3")
# 高德 API 请求超时（秒）
AMAP_TIMEOUT = int(os.getenv("AMAP_TIMEOUT", "30"))
# 逆地理编码默认搜索半径（米）
AMAP_DEFAULT_RADIUS = int(os.getenv("AMAP_DEFAULT_RADIUS", "1000"))
# 周边搜索最大半径（米）
AMAP_MAX_SEARCH_RADIUS = int(os.getenv("AMAP_MAX_SEARCH_RADIUS", "50000"))
# POI 搜索默认每页条数
AMAP_DEFAULT_PAGE_SIZE = int(os.getenv("AMAP_DEFAULT_PAGE_SIZE", "20"))
# POI 搜索最大每页条数
AMAP_MAX_PAGE_SIZE = int(os.getenv("AMAP_MAX_PAGE_SIZE", "50"))

############################
# 搜索引擎配置
############################
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GOOGLE_SEARCH_ENGINE_ID = os.getenv("GOOGLE_SEARCH_ENGINE_ID", "")
GOOGLE_SEARCH_BASE_URL = os.getenv(
    "GOOGLE_SEARCH_BASE_URL",
    f"https://www.googleapis.com/customsearch/v1?key={GOOGLE_API_KEY}&cx={GOOGLE_SEARCH_ENGINE_ID}&q=",
)

############################
# 文件系统配置
############################
# 沙箱根目录：所有文件操作被限制在此路径内
FILESYSTEM_ROOT = os.getenv("FILESYSTEM_ROOT", r"")
# 允许访问的路径列表（逗号分隔）
ACCESS_PATH_LIST = os.getenv("ACCESS_PATH_LIST", "")

############################
# 邮件相关配置（QQ Mail）
############################
QQ_MAIL_SMTP_SERVER       = os.getenv("QQ_MAIL_SMTP_SERVER",       "smtp.qq.com")
QQ_MAIL_SMTP_PORT         = int(os.getenv("QQ_MAIL_SMTP_PORT",     "465"))
QQ_MAIL_SMTP_USER         = os.getenv("QQ_MAIL_SMTP_USER",         "")
QQ_MAIL_SMTP_PASSWORD_KEY = os.getenv("QQ_MAIL_SMTP_PASSWORD_KEY", "")

QQ_MAIL_IMAP_SERVER = os.getenv("QQ_MAIL_IMAP_SERVER", "imap.qq.com")
QQ_MAIL_IMAP_PORT   = int(os.getenv("QQ_MAIL_IMAP_PORT", "993"))

############################
# 网络请求通用配置
############################
USER_AGENT = os.getenv("USER_AGENT", "Mozilla/5.0 (compatible; MCPToolkit/1.0)")
# 默认 HTTP 超时（秒）
TIMEOUT_S = int(os.getenv("TIMEOUT_S", "30"))
# 网页正文最大字符数
MAX_TEXT_CHARS = int(os.getenv("MAX_TEXT_CHARS", str(8_000)))
# Web 搜索专用超时（秒），默认 3 分钟
WEB_SEARCH_TIMEOUT = int(os.getenv("WEB_SEARCH_TIMEOUT", str(3 * 60)))

############################
# SerpAPI 配置（Web 搜索）
############################
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")

############################
# Shell / Python 执行配置
############################
# shell_exec 单条命令最长执行时间（秒）
SHELL_EXEC_TIMEOUT = int(os.getenv("SHELL_EXEC_TIMEOUT", "30"))
# python_exec 代码片段最长执行时间（秒）
PYTHON_EXEC_TIMEOUT = int(os.getenv("PYTHON_EXEC_TIMEOUT", "30"))
# shell_env_get 允许读取的环境变量白名单（逗号分隔），空字符串表示不限制
SHELL_ENV_WHITELIST = [
    k.strip()
    for k in os.getenv("SHELL_ENV_WHITELIST", "").split(",")
    if k.strip()
]

############################
# 日志配置
############################
# 项目根日志目录
LOG_DIR = Path(os.getenv("LOG_DIR", str(Path(__file__).resolve().parents[3] / "log")))
# 默认日志文件名
LOG_FILENAME = os.getenv("LOG_FILENAME", "mcp_toolkit.log")
# 单个日志文件最大体积（字节），默认 10 MB
LOG_MAX_BYTES = int(os.getenv("LOG_MAX_BYTES", str(10 * 1024 * 1024)))
# 日志轮转最多保留的旧文件数量
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "5"))
# 控制台日志级别（DEBUG / INFO / WARNING / ERROR）
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
# 日志格式
LOG_FORMAT = os.getenv(
    "LOG_FORMAT",
    "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
# 时间格式
LOG_DATE_FORMAT = os.getenv("LOG_DATE_FORMAT", "%Y-%m-%d %H:%M:%S")

############################
# Session 配置
############################
# 会话最大空闲时长（秒），超时后可由外部清理器关闭，0 表示不限制
SESSION_MAX_IDLE_SECONDS = int(os.getenv("SESSION_MAX_IDLE_SECONDS", "0"))
# 同时允许的最大会话数量，0 表示不限制
SESSION_MAX_COUNT = int(os.getenv("SESSION_MAX_COUNT", "0"))
