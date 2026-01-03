import os
import re
import sys
import json
import requests
from urllib.parse import quote, urlparse, parse_qs, unquote
from datetime import datetime
import time
import logging

# ===================== 配置说明 =====================
# GitHub仓库变量配置：
# 1. COOKIE_QUARK：填完整的夸克接口URL，多账号用 && 或 \n 分隔
# 2. WPUSH_KEY：填wpush.cn获取的推送Token
# =====================================================

# 自定义配置
USER_AGENT = "Mozilla/5.0 (Linux; Android 13; SM-G9980 Build/TP1A.220624.014; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/114.0.5735.130 Mobile Safari/537.36 Quark/10.1.2.973"
QUARK_COOKIE = ""  # 抓包的完整Cookie字符串（可选，填后提升成功率）

# 配置日志级别
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("quark_sign.log")
    ]
)
logger = logging.getLogger("QuarkSign")

def send_wpush(title, content):
    """适配WPush官方v1接口的推送实现"""
    wpush_key = os.getenv("WPUSH_KEY")
    if not wpush_key:
        logger.info("❌ 未配置WPUSH_KEY仓库变量，跳过推送")
        return
    
    # 限制内容长度
    max_content_len = 2000
    if len(content) > max_content_len:
        content = content[:max_content_len] + "\n\n【内容过长，已截断】"
    
    # 官方接口地址
    url = "https://api.wpush.cn/api/v1/send"
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
            url, 
            data=json.dumps(payload, ensure_ascii=False),
            headers=headers, 
            timeout=15
        )
        
        result = response.json()
        if result.get("code") == 0:
            logger.info("✅ WPush推送成功")
        else:
            logger.error(f"❌ WPush推送失败: {result.get('msg', '未知错误')} | 响应码: {result.get('code')}")
    except json.JSONDecodeError:
        logger.error(f"❌ WPush推送响应非JSON格式: {response.text[:100]}...")
    except requests.exceptions.Timeout:
        logger.error("❌ WPush推送超时，请检查网络")
    except Exception as e:
        logger.error(f"❌ WPush推送异常: {str(e)}")

def parse_cookie_from_url(url_str):
    """从完整URL中解析kps/sign/vcode参数（已修复空格处理）"""
    try:
        url_str = url_str.strip()
        if not url_str.startswith("http"):
            raise ValueError("不是有效的URL格式")
        
        parsed_url = urlparse(url_str)
        query_params = parse_qs(parsed_url.query, keep_blank_values=True)
        
        kps = query_params.get('kps', [''])[0]
        sign = query_params.get('sign', [''])[0]
        vcode = query_params.get('vcode', [''])[0]
        
        # 仅保留unquote处理，移除错误的replace(" ", "+")
        kps = unquote(kps) if kps else ''
        sign = unquote(sign) if sign else ''
        vcode = unquote(vcode) if vcode else ''
        
        logger.info(f"✅ 解析后的参数: kps={kps} | sign={sign} | vcode={vcode}")
        
        if not all([kps, sign, vcode]):
            raise ValueError(f"URL中缺失关键参数 | kps={bool(kps)} | sign={bool(sign)} | vcode={bool(vcode)}")
        
        return f"kps={kps};sign={sign};vcode={vcode}"
    except Exception as e:
        logger.error(f"❌ URL解析失败: {str(e)} | URL: {url_str[:80]}...")
        return ""

def get_env():
    """获取并解析环境变量中的夸克参数"""
    if "COOKIE_QUARK" not in os.environ:
        err_msg = "❌ 未添加COOKIE_QUARK仓库变量"
        logger.error(err_msg)
        send_wpush("夸克自动签到", err_msg)
        sys.exit(0)
    
    cookie_raw = os.environ.get("COOKIE_QUARK", "").strip()
    if not cookie_raw:
        err_msg = "❌ COOKIE_QUARK变量值为空"
        logger.error(err_msg)
        send_wpush("夸克自动签到", err_msg)
        sys.exit(0)
    
    # 清理无效字符并分割
    raw_list = [item for item in re.split(r'\n|\s*&&\s*', cookie_raw) if item.strip()]
    cookie_list = []
    
    for idx, item in enumerate(raw_list, 1):
        item = item.strip()
        if not item:
            logger.warning(f"⚠️  第{idx}个账号配置为空，跳过")
            continue
        
        if item.startswith("http"):
            parsed_cookie = parse_cookie_from_url(item)
            if parsed_cookie:
                cookie_list.append(parsed_cookie)
            else:
                logger.warning(f"⚠️  第{idx}个账号URL解析失败，跳过")
        else:
            if all(key in item for key in ["kps=", "sign=", "vcode="]):
                cookie_list.append(item.strip())
            else:
                logger.warning(f"⚠️  第{idx}个账号参数不完整，跳过 | 内容: {item[:50]}...")
    
    if not cookie_list:
        err_msg = "❌ COOKIE_QUARK解析后无有效账号，请检查URL格式"
        logger.error(err_msg)
        send_wpush("夸克自动签到", err_msg)
        sys.exit(0)
    
    logger.info(f"✅ 成功解析{len(cookie_list)}个有效账号")
    return cookie_list

class Quark:
    """夸克网盘签到类"""
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

    def _request(self, method, url, params=None, json=None, retries=3):
        """统一请求封装（已移除verify=False）"""
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://drive-m.quark.cn/",
            "Connection": "keep-alive",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept-Encoding": "gzip, deflate, br"
        }
        
        if QUARK_COOKIE:
            headers["Cookie"] = QUARK_COOKIE
        
        for attempt in range(retries):
            try:
                session = requests.Session()
                session.mount('https://', requests.adapters.HTTPAdapter(max_retries=3))
                
                if method.lower() == "get":
                    resp = session.get(
                        url, 
                        params=params, 
                        headers=headers, 
                        timeout=20
                    )
                elif method.lower() == "post":
                    resp = session.post(
                        url, 
                        params=params, 
                        json=json, 
                        headers=headers, 
                        timeout=20
                    )
                else:
                    raise ValueError(f"不支持的请求方法: {method}")
                
                logger.info(f"🔍 {self.user_name} 请求状态码: {resp.status_code} | URL: {url[:80]}")
                
                resp.raise_for_status()
                result = resp.json()
                
                if result.get("code") != 0 and not result.get("data"):
                    err_msg = result.get("message", result.get("msg", "未知错误"))
                    logger.error(f"{self.user_name} 接口返回错误: {err_msg} | 响应码: {result.get('code')}")
                    return False
                return result.get("data", {})
            except requests.exceptions.HTTPError as e:
                if attempt < retries - 1:
                    wait_time = 2 ** attempt  # 指数退避
                    logger.warning(f"{self.user_name} HTTP错误: {str(e)} | 状态码: {resp.status_code if 'resp' in locals() else '未知'}, 重试中 (尝试 {attempt+1}/{retries})")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"{self.user_name} HTTP错误: {str(e)} | 状态码: {resp.status_code if 'resp' in locals() else '未知'}")
                    return False
            except requests.exceptions.RequestException as e:
                if attempt < retries - 1:
                    wait_time = 2 ** attempt
                    logger.warning(f"{self.user_name} 请求异常: {str(e)}, 重试中 (尝试 {attempt+1}/{retries})")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"{self.user_name} 请求异常: {str(e)}")
                    return False
            except ValueError as e:
                logger.error(f"{self.user_name} 响应解析异常: {str(e)} | 响应内容: {resp.text[:100] if 'resp' in locals() else '无'}")
                return False
        return False

    def get_growth_info(self):
        """获取用户成长/签到基础信息"""
        url = "https://drive-m.quark.cn/1/clouddrive/capacity/growth/info"
        params = {
            "pr": "ucpro",
            "fr": "android",
            "kps": self.param.get("kps"),
            "sign": self.param.get("sign"),
            "vcode": self.param.get("vcode")
        }
        return self._request("get", url, params=params)

    def get_growth_sign(self):
        """执行签到操作"""
        url = "https://drive-m.quark.cn/1/clouddrive/capacity/growth/sign"
        params = {
            "pr": "ucpro",
            "fr": "android",
            "kps": self.param.get("kps"),
            "sign": self.param.get("sign"),
            "vcode": self.param.get("vcode")
        }
        data = {"sign_cyclic": True}
        return self._request("post", url, params=params, json=data)

    def queryBalance(self):
        """查询抽奖余额"""
        url = "https://coral2.quark.cn/currency/v1/queryBalance"
        params = {
            "moduleCode": "1f3563d38896438db994f118d4ff53cb",
            "kps": self.param.get("kps")
        }
        result = self._request("get", url, params=params)
        return result.get("balance", "0") if result else "查询失败"

    def do_sign(self):
        """执行完整签到流程（无需缓存检查）"""
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
            return "\n".join(log), True
        else:
            sign_result = self.get_growth_sign()
            if sign_result:
                reward = self.convert_bytes(sign_result.get("sign_daily_reward", 0))
                progress = f"{cap_sign.get('sign_progress', 0)+1}/{cap_sign.get('sign_target', 0)}"
                log.append(f"✅ 签到成功 | 获得: {reward} | 连签进度: {progress}")
                return "\n".join(log), True
            else:
                log.append(f"❌ 签到失败 | 原因: 接口返回异常（请检查Cookie有效性/重新抓包）")
                return "\n".join(log), False
        
        balance = self.queryBalance()
        log.append(f"🎁 抽奖余额: {balance}")
        return "\n".join(log), True

def main():
    """主执行函数（输出状态给Workflow）"""
    logger.info("="*50)
    logger.info("---------- 夸克网盘自动签到开始 ----------")
    logger.info(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("="*50)
    
    final_msg = [f"夸克网盘签到结果汇总（{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}）:"]
    overall_success = True
    success_count = 0
    failure_count = 0
    
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
            
            if sign_success:
                success_count += 1
            else:
                failure_count += 1
                overall_success = False
        except Exception as e:
            err_log = f"\n📱 第{idx}个账号 | ❌ 处理失败: {str(e)}"
            final_msg.append(err_log)
            logger.error(err_log)
            failure_count += 1
            overall_success = False
        logger.info(f"{'='*70}")
    
    # 优化输出信息
    summary = f"✅ 成功: {success_count} | ❌ 失败: {failure_count} | 总账号: {len(cookie_list)}"
    final_msg.insert(1, summary)
    
    final_content = "\n".join(final_msg)
    send_wpush(
        "夸克网盘自动签到" + ("（部分账号失败）" if not overall_success else ""),
        final_content
    )
    
    # 输出状态到环境变量（确保Workflow能识别）
    github_output = os.getenv('GITHUB_OUTPUT')
    if github_output:
        with open(github_output, 'a', encoding='utf-8') as f:
            f.write(f"overall_success={str(overall_success).lower()}\n")
            f.write(f"success_count={success_count}\n")
            f.write(f"failure_count={failure_count}\n")
    logger.info(f"📤 签到状态输出: overall_success={str(overall_success).lower()}")
    
    logger.info("\n" + "="*50)
    logger.info("---------- 夸克网盘自动签到结束 ----------")
    logger.info("="*50)
    
    # 返回内容用于日志
    return overall_success  # 直接返回状态变量

if __name__ == "__main__":
    # 确保环境变量正确
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    os.environ.setdefault('REQUESTS_CA_BUNDLE', '')
    
    try:
        success = main()  # 获取布尔值
        if success:
            sys.exit(0)
        else:
            sys.exit(1)
    except Exception as e:
        error_msg = f"❌ 脚本执行异常: {str(e)}"
        logger.error(error_msg)
        send_wpush("夸克签到脚本异常", error_msg)
        logger.error("📤 签到状态输出: overall_success=false")
        sys.exit(1)
