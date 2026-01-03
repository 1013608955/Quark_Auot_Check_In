import os
import re
import sys
import json
import time
import logging
import requests
from urllib.parse import quote, urlparse, parse_qs, unquote
from datetime import datetime, timedelta
from pathlib import Path

# ===================== 全局配置（集中管理，方便维护） =====================
CONFIG = {
    # 基础配置
    "USER_AGENT": "Mozilla/5.0 (Linux; Android 13; SM-G9980 Build/TP1A.220624.014; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/114.0.5735.130 Mobile Safari/537.36 Quark/10.1.2.973",
    "QUARK_COOKIE": "",  # 可选Cookie（抓包获取）
    "CACHE_FILE": os.path.join(os.getcwd(), ".last_success_date"),
    # 时区配置（兼容pytz安装失败）
    "TIMEZONE": "Asia/Shanghai",
    # 接口URL（集中管理，方便更新）
    "API_URLS": {
        "growth_info": "https://drive-m.quark.cn/1/clouddrive/capacity/growth/info",
        "growth_sign": "https://drive-m.quark.cn/1/clouddrive/capacity/growth/sign",
        "query_balance": "https://coral2.quark.cn/currency/v1/queryBalance"
    },
    # 网络配置
    "REQUESTS": {
        "TIMEOUT": 20,
        "MAX_RETRIES": 3,
        "VERIFY_SSL": False
    },
    # 推送配置
    "WPUSH": {
        "MAX_CONTENT_LEN": 2000,
        "API_URL": "https://api.wpush.cn/api/v1/send"
    },
    # 其他配置
    "DEBUG": os.getenv("DEBUG", "false").lower() == "true",
    "ENV": os.getenv("ENV", "prod").lower()  # 运行环境：prod/test
}

# ===================== 日志初始化（规范化） =====================
logging.basicConfig(
    level=logging.DEBUG if CONFIG["DEBUG"] or CONFIG["ENV"] == "test" else logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# ===================== 时区兼容（兜底方案） =====================
try:
    import pytz
    BEIJING_TZ = pytz.timezone(CONFIG["TIMEZONE"])
except ImportError:
    logger.warning("pytz未安装，使用手动时区补偿（UTC+8）")
    class SimpleBeijingTZ:
        @staticmethod
        def localize(dt):
            return dt + timedelta(hours=8)
        
        @staticmethod
        def normalize(dt):
            return dt
    BEIJING_TZ = SimpleBeijingTZ()

# ===================== 工具函数 =====================
def mask_sensitive_str(s: str) -> str:
    """敏感字符串脱敏（仅保留前8后4）"""
    if not s or len(s) <= 12:
        return s
    return f"{s[:8]}...{s[-4:]}"

def send_wpush(title, content):
    """适配WPush官方v1接口的推送实现（容错增强）"""
    wpush_key = os.getenv("WPUSH_KEY")
    if not wpush_key:
        logger.warning("未配置WPUSH_KEY仓库变量，跳过推送")
        return
    
    # 测试环境跳过推送
    if CONFIG["ENV"] == "test":
        logger.info(f"测试环境，跳过WPush推送 | 标题：{title}")
        return
    
    # 限制内容长度
    if len(content) > CONFIG["WPUSH"]["MAX_CONTENT_LEN"]:
        content = content[:CONFIG["WPUSH"]["MAX_CONTENT_LEN"]] + "\n\n【内容过长，已截断】"
    
    payload = {
        "apikey": wpush_key,
        "title": title[:50],
        "content": content
    }
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "QuarkSign/1.0"
    }
    
    try:
        session = requests.Session()
        session.mount('https://', requests.adapters.HTTPAdapter(max_retries=2))
        response = session.post(
            CONFIG["WPUSH"]["API_URL"],
            data=json.dumps(payload, ensure_ascii=False),
            headers=headers,
            timeout=15,
            verify=CONFIG["REQUESTS"]["VERIFY_SSL"]
        )
        
        result = response.json()
        if result.get("code") == 0:
            logger.info("WPush推送成功")
        else:
            logger.error(f"WPush推送失败: {result.get('msg', '未知错误')} | 响应码: {result.get('code')}")
    except json.JSONDecodeError:
        logger.error(f"WPush推送响应非JSON格式: {response.text[:100]}...")
    except requests.exceptions.Timeout:
        logger.error("WPush推送超时，请检查网络")
    except Exception as e:
        logger.error(f"WPush推送异常: {str(e)}", exc_info=CONFIG["DEBUG"])

def parse_cookie_from_url(url_str):
    """从完整URL中解析kps/sign/vcode参数（脱敏输出）"""
    try:
        url_str = url_str.strip()
        if not url_str.startswith("http"):
            raise ValueError("不是有效的URL格式")
        
        parsed_url = urlparse(url_str)
        query_params = parse_qs(parsed_url.query, keep_blank_values=True)
        
        kps = query_params.get('kps', [''])[0]
        sign = query_params.get('sign', [''])[0]
        vcode = query_params.get('vcode', [''])[0]
        
        kps = unquote(kps).replace(" ", "+") if kps else ''
        sign = unquote(sign).replace(" ", "+") if sign else ''
        vcode = unquote(vcode) if vcode else ''
        
        # 脱敏输出
        logger.info(
            f"解析后的参数: kps={mask_sensitive_str(kps)} | "
            f"sign={mask_sensitive_str(sign)} | vcode={mask_sensitive_str(vcode)}"
        )
        
        if not all([kps, sign, vcode]):
            raise ValueError(
                f"URL中缺失关键参数 | kps={bool(kps)} | "
                f"sign={bool(sign)} | vcode={bool(vcode)}"
            )
        
        return f"kps={kps};sign={sign};vcode={vcode}"
    except Exception as e:
        logger.error(f"URL解析失败: {str(e)} | URL: {url_str[:80]}...")
        return ""

def get_env():
    """获取并解析环境变量中的夸克参数"""
    if "COOKIE_QUARK" not in os.environ:
        err_msg = "未添加COOKIE_QUARK仓库变量"
        logger.error(err_msg)
        send_wpush("夸克自动签到", f"❌ {err_msg}")
        sys.exit(0)
    
    cookie_raw = os.environ.get("COOKIE_QUARK", "").strip()
    if not cookie_raw:
        err_msg = "COOKIE_QUARK变量值为空"
        logger.error(err_msg)
        send_wpush("夸克自动签到", f"❌ {err_msg}")
        sys.exit(0)
    
    raw_list = re.split(r'\n|\&\&', cookie_raw)
    cookie_list = []
    
    for idx, item in enumerate(raw_list, 1):
        item = item.strip()
        if not item:
            logger.warning(f"第{idx}个账号配置为空，跳过")
            continue
        
        if item.startswith("http"):
            parsed_cookie = parse_cookie_from_url(item)
            if parsed_cookie:
                cookie_list.append(parsed_cookie)
            else:
                logger.warning(f"第{idx}个账号URL解析失败，跳过")
        else:
            if all(key in item for key in ["kps=", "sign=", "vcode="]):
                cookie_list.append(item.strip())
            else:
                logger.warning(f"第{idx}个账号参数不完整，跳过 | 内容: {item[:50]}...")
    
    if not cookie_list:
        err_msg = "COOKIE_QUARK解析后无有效账号，请检查URL格式"
        logger.error(err_msg)
        send_wpush("夸克自动签到", f"❌ {err_msg}")
        sys.exit(0)
    
    logger.info(f"成功解析{len(cookie_list)}个有效账号")
    return cookie_list

# ===================== 夸克签到类 =====================
class Quark:
    """夸克网盘签到类（重试增强）"""
    def __init__(self, user_data, user_index):
        self.param = user_data
        self.user_index = user_index
        self.user_name = f"第{user_index}个账号"
        self._check_required_params()

    def _check_required_params(self):
        """检查必要参数"""
        required = ["kps", "sign", "vcode"]
        missing = []
        for p in required:
            val = self.param.get(p, "").strip()
            if not val:
                missing.append(p)
        
        if missing:
            raise ValueError(f"{self.user_name} 缺失必要参数: {','.join(missing)}")

    def convert_bytes(self, b):
        """字节单位转换"""
        try:
            b = float(b)
            if b < 0:
                return "0.00 B"
        except (ValueError, TypeError):
            return "0.00 B"
        
        units = ("B", "KB", "MB", "GB", "TB", "PB")
        i = 0
        while b >= 1024 and i < len(units) - 1:
            b /= 1024
            i += 1
        return f"{b:.2f} {units[i]}"

    def _request(self, method, url, params=None, json=None):
        """统一请求封装（补充关键请求头）"""
        headers = {
            "User-Agent": CONFIG["USER_AGENT"],
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://drive-m.quark.cn/",
            "Connection": "keep-alive",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept-Encoding": "gzip, deflate, br"
        }
        
        if CONFIG["QUARK_COOKIE"]:
            headers["Cookie"] = CONFIG["QUARK_COOKIE"]
        
        try:
            session = requests.Session()
            session.mount('https://', requests.adapters.HTTPAdapter(max_retries=CONFIG["REQUESTS"]["MAX_RETRIES"]))
            
            if method.lower() == "get":
                resp = session.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=CONFIG["REQUESTS"]["TIMEOUT"],
                    verify=CONFIG["REQUESTS"]["VERIFY_SSL"]
                )
            elif method.lower() == "post":
                resp = session.post(
                    url,
                    params=params,
                    json=json,
                    headers=headers,
                    timeout=CONFIG["REQUESTS"]["TIMEOUT"],
                    verify=CONFIG["REQUESTS"]["VERIFY_SSL"]
                )
            else:
                raise ValueError(f"不支持的请求方法: {method}")
            
            logger.info(f"{self.user_name} 请求状态码: {resp.status_code} | URL: {url[:80]}")
            
            resp.raise_for_status()
            result = resp.json()
            
            if result.get("code") != 0 and not result.get("data"):
                err_msg = result.get("message", result.get("msg", "未知错误"))
                logger.error(f"{self.user_name} 接口返回错误: {err_msg} | 响应码: {result.get('code')}")
                return False
            return result.get("data", {})
        except requests.exceptions.HTTPError as e:
            logger.error(
                f"{self.user_name} HTTP错误: {str(e)} | "
                f"状态码: {resp.status_code if 'resp' in locals() else '未知'}"
            )
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"{self.user_name} 请求异常: {str(e)}")
            return False
        except ValueError as e:
            logger.error(
                f"{self.user_name} 响应解析异常: {str(e)} | "
                f"响应内容: {resp.text[:100] if 'resp' in locals() else '无'}"
            )
            return False

    def get_growth_info(self):
        """获取用户成长/签到基础信息"""
        params = {
            "pr": "ucpro",
            "fr": "android",
            "kps": self.param.get("kps"),
            "sign": self.param.get("sign"),
            "vcode": self.param.get("vcode")
        }
        return self._request("get", CONFIG["API_URLS"]["growth_info"], params=params)

    def get_growth_sign(self):
        """执行签到操作（新增重试机制）"""
        params = {
            "pr": "ucpro",
            "fr": "android",
            "kps": self.param.get("kps"),
            "sign": self.param.get("sign"),
            "vcode": self.param.get("vcode")
        }
        data = {"sign_cyclic": True}
        
        # 重试逻辑
        for retry in range(CONFIG["REQUESTS"]["MAX_RETRIES"]):
            result = self._request("post", CONFIG["API_URLS"]["growth_sign"], params=params, json=data)
            if result:
                return result
            logger.warning(f"{self.user_name} 签到第{retry+1}次失败，2秒后重试...")
            time.sleep(2)
        
        logger.error(f"{self.user_name} 签到重试{CONFIG['REQUESTS']['MAX_RETRIES']}次后仍失败")
        return False

    def queryBalance(self):
        """查询抽奖余额"""
        params = {
            "moduleCode": "1f3563d38896438db994f118d4ff53cb",
            "kps": self.param.get("kps")
        }
        result = self._request("get", CONFIG["API_URLS"]["query_balance"], params=params)
        return result.get("balance", "0") if result else "查询失败"

    def do_sign(self):
        """执行完整签到流程"""
        log = [f"\n📱 {self.user_name}"]
        
        growth_info = self.get_growth_info()
        if not growth_info:
            log.append("❌ 获取签到基础信息失败（Cookie可能已失效/参数错误）")
            return "\n".join(log), False
        
        total_cap = self.convert_bytes(growth_info.get("total_capacity", 0))
        cap_composition = growth_info.get("cap_composition", {}) or {}
        sign_reward = cap_composition.get("sign_reward", 0)
        sign_reward_str = self.convert_bytes(sign_reward)
        is_88vip = "88VIP用户" if growth_info.get("88VIP") else "普通用户"
        
        log.append(f"🔍 {is_88vip} | 总容量: {total_cap} | 签到累计: {sign_reward_str}")
        
        cap_sign = growth_info.get("cap_sign", {}) or {}
        if cap_sign.get("sign_daily"):
            daily_reward = self.convert_bytes(cap_sign.get("sign_daily_reward", 0))
            progress = f"{cap_sign.get('sign_progress', 0)}/{cap_sign.get('sign_target', 0)}"
            log.append(f"✅ 接口验证今日已签到 | 获得: {daily_reward} | 连签进度: {progress}")
            # 查询抽奖余额
            balance = self.queryBalance()
            log.append(f"🎁 抽奖余额: {balance}")
            return "\n".join(log), True
        else:
            sign_result = self.get_growth_sign()
            if sign_result:
                reward = self.convert_bytes(sign_result.get("sign_daily_reward", 0))
                progress = f"{cap_sign.get('sign_progress', 0)+1}/{cap_sign.get('sign_target', 0)}"
                log.append(f"✅ 签到成功 | 获得: {reward} | 连签进度: {progress}")
                # 查询抽奖余额
                balance = self.queryBalance()
                log.append(f"🎁 抽奖余额: {balance}")
                return "\n".join(log), True
            else:
                log.append(f"❌ 签到失败 | 原因: 接口返回异常（请检查Cookie有效性/重新抓包）")
                return "\n".join(log), False

# ===================== 缓存操作 =====================
def write_success_date():
    """写入成功签到的日期（北京时间）"""
    try:
        # 处理时区兼容
        if isinstance(BEIJING_TZ, pytz.BaseTzInfo):
            beijing_now = datetime.now(BEIJING_TZ)
        else:
            beijing_now = BEIJING_TZ.localize(datetime.now())
        
        current_date = beijing_now.strftime('%Y-%m-%d')
        
        # 测试环境不写入真实缓存
        if CONFIG["ENV"] == "test":
            logger.info(f"测试环境，模拟写入缓存日期: {current_date}")
            return
        
        # 写入缓存文件
        with open(CONFIG["CACHE_FILE"], 'w', encoding='utf-8') as f:
            f.write(current_date)
        logger.info(f"已写入成功签到日期: {current_date} 到 {CONFIG['CACHE_FILE']}")
    except Exception as e:
        logger.error(f"写入签到日期失败: {str(e)}", exc_info=CONFIG["DEBUG"])

# ===================== 主函数 =====================
def main():
    """主执行函数"""
    logger.info("="*50)
    logger.info("---------- 夸克网盘自动签到开始 ----------")
    
    # 输出执行时间（北京时间）
    if isinstance(BEIJING_TZ, pytz.BaseTzInfo):
        exec_time = datetime.now(BEIJING_TZ).strftime('%Y-%m-%d %H:%M:%S')
    else:
        exec_time = BEIJING_TZ.localize(datetime.now()).strftime('%Y-%m-%d %H:%M:%S')
    logger.info(f"执行时间: {exec_time} (北京时间) | 运行环境: {CONFIG['ENV']}")
    logger.info("="*50)
    
    final_msg = [f"夸克网盘签到结果汇总（{exec_time} 北京时间）:"]
    overall_success = True
    success_count = 0  # 成功账号数
    fail_count = 0     # 失败账号数
    
    cookie_list = get_env()
    final_msg.append(f"📊 检测到有效账号数: {len(cookie_list)}")
    
    for idx, cookie_str in enumerate(cookie_list, 1):
        logger.info(f"\n{'='*30} 处理第{idx}个账号 {'='*30}")
        try:
            user_data = {}
            for item in cookie_str.split(";"):
                item = item.strip()
                if "=" in item:
                    key, value = item.split("=", 1)
                    user_data[key.strip()] = value.strip()
            
            quark = Quark(user_data, idx)
            sign_log, sign_success = quark.do_sign()
            final_msg.append(sign_log)
            logger.info(sign_log)
            
            # 统计成功/失败数
            if sign_success:
                success_count += 1
            else:
                fail_count += 1
                overall_success = False
        except Exception as e:
            err_log = f"\n📱 第{idx}个账号 | ❌ 处理失败: {str(e)}"
            final_msg.append(err_log)
            logger.error(err_log, exc_info=CONFIG["DEBUG"])
            fail_count += 1
            overall_success = False
        logger.info(f"{'='*70}")
    
    # 补充统计信息
    final_msg.insert(1, f"📊 签到统计：成功{success_count}个 | 失败{fail_count}个")
    
    # 推送结果
    final_content = "\n".join(final_msg)
    send_wpush(
        "夸克网盘自动签到" + ("（部分账号失败）" if not overall_success else ""),
        final_content
    )
    
    # 仅生产环境+全部成功时写入缓存
    if overall_success and CONFIG["ENV"] == "prod":
        logger.info("\n所有账号签到成功，准备写入缓存文件")
        write_success_date()
    else:
        logger.info("\n部分/全部账号签到失败，不写入缓存文件")
    
    # 输出状态到环境变量
    github_output = os.getenv('GITHUB_OUTPUT')
    if github_output:
        with open(github_output, 'a', encoding='utf-8') as f:
            f.write(f"overall_success={str(overall_success).lower()}\n")
    logger.info(f"签到状态输出: overall_success={str(overall_success).lower()}")
    
    logger.info("\n" + "="*50)
    logger.info("---------- 夸克网盘自动签到结束 ----------")
    logger.info("="*50)
    return final_content

# ===================== 入口 =====================
if __name__ == "__main__":
    # 统一编码设置
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    os.environ.setdefault('REQUESTS_CA_BUNDLE', '')
    
    try:
        main()
    except Exception as e:
        error_msg = f"脚本执行异常: {str(e)}"
        logger.error(error_msg, exc_info=CONFIG["DEBUG"])
        send_wpush("夸克签到脚本异常", f"❌ {error_msg}")
        
        # 输出失败状态
        github_output = os.getenv('GITHUB_OUTPUT')
        if github_output:
            with open(github_output, 'a', encoding='utf-8') as f:
                f.write("overall_success=false\n")
        logger.info("签到状态输出: overall_success=false")
        sys.exit(1)
