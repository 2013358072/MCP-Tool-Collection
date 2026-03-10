import os


############################
# 大模型配置
############################
DOUBAO_API_KEY = os.getenv("DOUBAO_API_KEY","")
DOUBAO_MODEL_NAME = os.getenv("DOUBAO_MODEL_NAME","")
DOUBAO_BASE_URL = os.getenv("DOUBAO_BASE_URL","")

############################
# 金融相关配置
############################
ALPHAVANTAGE_API_KEY = os.getenv("ALPHAVANTAGE_API_KEY","")
ALPHAVANTAGE_BASE_URL = os.getenv("ALPHAVANTAGE_API_URL",f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol=IBM&apikey={ALPHAVANTAGE_API_KEY}")

############################
# 搜索引擎配置
############################
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY","")
GOOGLE_SEARCH_ENGINE_ID = os.getenv("GOOGLE_SEARCH_ENGINE_ID","")
GOOGLE_SEARCH_BASE_URL = os.getenv("GOOGLE_SEARCH_BASE_URL",f"https://www.googleapis.com/customsearch/v1?key={GOOGLE_API_KEY}&cx={GOOGLE_SEARCH_ENGINE_ID}&q=")

############################
# 文件系统配置
############################
ACCESS_PATH_LIST = os.getenv("ACCESS_PATH_LIST",[])

############################
# 邮件相关配置
############################
QQ_MAIL_SMTP_SERVER = os.getenv("QQ_MAIL_SMTP_SERVER","")
QQ_MAIL_SMTP_PORT = os.getenv("QQ_MAIL_SMTP_PORT","")
QQ_MAIL_SMTP_USER = os.getenv("QQ_MAIL_SMTP_USER","")
QQ_MAIL_SMTP_PASSWORD_KEY = os.getenv("QQ_MAIL_SMTP_PASSWORD_KEY","")