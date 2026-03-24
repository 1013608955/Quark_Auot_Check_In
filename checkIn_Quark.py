import os
import re
import sys
import json
import requests
from urllib.parse import urlparse, parse_qs, unquote
from datetime import datetime
from zoneinfo import ZoneInfo  # Python 3.9+ 内置时区支持

# ===================== 配置说明 =====================
# GitHub仓库变量配置：
# 1. COOKIE_QUARK：填完整的夸克接口URL，多账号用 && 或 \n 分隔
# 2. WPUSH_KEY：填wpush.cn获取的推送Token
# =====================================================

USER_AGENT = "Mozilla/5.0 (Linux; Android 13; SM-G9980 Build/TP1A.220624.014; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/114.0.5735.130 Mobile Safari/537.36 Quark/10.1.2.973"

CACHE_FILE = os.path.join(os.getcwd(), ".last_success_date")
BEIJING_TZ = ZoneInfo('Asia/Shanghai')

# 全局共享 Session（连接复用，减少 TLS 握手开销）
_http = requests.Session()
_http.mount('https://', requests.adapters.HTTPAdapter(max_retries=3))
_http.headers.update({
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
})

def send_wpush(title, content):
    """适配WPush官方v1接口的推送实现"""
    wpush_key = os.getenv("WPUSH_KEY")
    if not wpush_key:
        print("❌ 未配置WPUSH_KEY仓库变量，跳过推送")
        return

    max_content_len = 2000
    if len(content) > max_content_len:
        content = content[:max_content_len] + "\n\n【内容过长，已截断】"

    url = "https://api.wpush.cn/api/v1/send"
    payload = {
        "apikey": wpush_key,
        "title": title[:50],
        "content": content
    }

    try:
        resp = _http.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json", "User-Agent": "QuarkSign/1.0"},
            timeout=15
        )
        # 清理响应中的非JSON前缀字符（如BOM、$等）
        text = resp.text
        json_start = text.find('{')
        if json_start > 0:
            text = text[json_start:]
        result = json.loads(text)
        if result.get("code") == 0:
            print("✅ WPush推送成功")
        else:
            print(f"❌ WPush推送失败: {result.get('msg', '未知错误')} | 响应码: {result.get('code')}")
    except json.JSONDecodeError:
        print(f"❌ WPush推送响应非JSON格式: {resp.text[:100]}...")
    except requests.exceptions.Timeout:
        print("❌ WPush推送超时，请检查网络")
    except Exception as e:
        print(f"❌ WPush推送异常: {str(e)}")
        
def parse_cookie_string(cookie_str):
    """将 cookie 字符串解析为 dict，支持 URL 格式和 kps=;sign=;vcode= 格式"""
    cookie_str = cookie_str.strip()
    if cookie_str.startswith("http"):
        return parse_cookie_from_url(cookie_str)
    if all(key in cookie_str for key in ["kps=", "sign=", "vcode="]):
        user_data = {}
        for item in cookie_str.split(";"):
            item = item.strip()
            if "=" in item:
                key, value = item.split("=", 1)
                user_data[key.strip()] = value.strip()
        return user_data
    return None


def parse_cookie_from_url(url_str):
    """从完整URL中解析kps/sign/vcode参数"""
    try:
        url_str = url_str.strip()
        if not url_str.startswith("http"):
            raise ValueError("不是有效的URL格式")

        parsed_url = urlparse(url_str)
        query_params = parse_qs(parsed_url.query, keep_blank_values=True)

        kps = unquote(query_params.get('kps', [''])[0]).replace(" ", "+")
        sign = unquote(query_params.get('sign', [''])[0]).replace(" ", "+")
        vcode = unquote(query_params.get('vcode', [''])[0])

        if not all([kps, sign, vcode]):
            raise ValueError(f"URL中缺失关键参数 | kps={bool(kps)} | sign={bool(sign)} | vcode={bool(vcode)}")

        return {"kps": kps, "sign": sign, "vcode": vcode}
    except Exception as e:
        print(f"❌ URL解析失败: {str(e)} | URL: {url_str[:80]}...")
        return None

def get_env():
    """获取并解析环境变量中的夸克参数"""
    if "COOKIE_QUARK" not in os.environ:
        err_msg = "❌ 未添加COOKIE_QUARK仓库变量"
        print(err_msg)
        send_wpush("夸克自动签到", err_msg)
        sys.exit(0)

    cookie_raw = os.environ.get("COOKIE_QUARK", "").strip()
    if not cookie_raw:
        err_msg = "❌ COOKIE_QUARK变量值为空"
        print(err_msg)
        send_wpush("夸克自动签到", err_msg)
        sys.exit(0)

    raw_list = re.split(r'\n|\&\&', cookie_raw)
    cookie_list = []

    for idx, item in enumerate(raw_list, 1):
        item = item.strip()
        if not item:
            print(f"⚠️  第{idx}个账号配置为空，跳过")
            continue

        parsed = parse_cookie_string(item)
        if parsed and isinstance(parsed, dict):
            cookie_list.append(parsed)
        else:
            print(f"⚠️  第{idx}个账号解析失败，跳过 | 内容: {item[:50]}...")

    if not cookie_list:
        err_msg = "❌ COOKIE_QUARK解析后无有效账号，请检查URL格式"
        print(err_msg)
        send_wpush("夸克自动签到", err_msg)
        sys.exit(0)

    print(f"✅ 成功解析{len(cookie_list)}个有效账号")
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

    @staticmethod
    def convert_bytes(b):
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
        """统一请求封装（使用全局 Session 复用连接）"""
        headers = {
            "Referer": "https://drive-m.quark.cn/",
            "Connection": "keep-alive",
        }

        try:
            if method.lower() == "get":
                resp = _http.get(url, params=params, headers=headers, timeout=20)
            elif method.lower() == "post":
                resp = _http.post(url, params=params, json=json, headers=headers, timeout=20)
            else:
                raise ValueError(f"不支持的请求方法: {method}")

            print(f"🔍 {self.user_name} 请求状态码: {resp.status_code} | URL: {url[:80]}")

            resp.raise_for_status()
            try:
                result = resp.json()
            except json.JSONDecodeError:
                print(f"❌ {self.user_name} 响应非JSON格式: {resp.text[:100]}...")
                return {}

            if not isinstance(result, dict):
                print(f"❌ {self.user_name} 响应不是字典类型: {type(result)}")
                return {}

            if result.get("code") != 0 and not result.get("data"):
                err_msg = result.get("message", result.get("msg", "未知错误"))
                print(f"{self.user_name} 接口返回错误: {err_msg} | 响应码: {result.get('code')}")
                return {}

            data = result.get("data", {})
            if not isinstance(data, dict):
                print(f"❌ {self.user_name} data字段非字典类型: {type(data)} | 内容: {str(data)[:100]}...")
                return {}
            return data
        except requests.exceptions.HTTPError as e:
            print(f"{self.user_name} HTTP错误: {str(e)} | 状态码: {resp.status_code if 'resp' in locals() else '未知'}")
            return {}
        except requests.exceptions.RequestException as e:
            print(f"{self.user_name} 请求异常: {str(e)}")
            return {}
        except ValueError as e:
            print(f"{self.user_name} 响应解析异常: {str(e)} | 响应内容: {resp.text[:100] if 'resp' in locals() else '无'}")
            return {}

    def _api_params(self):
        """构建夸克 API 公共参数"""
        return {
            "pr": "ucpro",
            "fr": "android",
            "kps": self.param.get("kps"),
            "sign": self.param.get("sign"),
            "vcode": self.param.get("vcode"),
        }

    def get_growth_info(self):
        """获取用户成长/签到基础信息"""
        url = "https://drive-m.quark.cn/1/clouddrive/capacity/growth/info"
        data = self._request("get", url, params=self._api_params())
        return data if isinstance(data, dict) else {}

    def get_growth_sign(self):
        """执行签到操作"""
        url = "https://drive-m.quark.cn/1/clouddrive/capacity/growth/sign"
        result = self._request("post", url, params=self._api_params(), json={"sign_cyclic": True})
        return result if isinstance(result, dict) else {}

    def query_balance(self):
        """查询抽奖余额"""
        url = "https://coral2.quark.cn/currency/v1/query_balance"
        params = {
            "moduleCode": "1f3563d38896438db994f118d4ff53cb",
            "kps": self.param.get("kps")
        }
        result = self._request("get", url, params=params)
        if isinstance(result, dict):
            return result.get("balance", "0")
        else:
            print(f"⚠️ {self.user_name} 抽奖余额查询返回非字典类型: {type(result)}")
            return "查询失败"

    def do_sign(self):
        """执行完整签到流程（全链路类型校验）"""
        log = [f"\n📱 {self.user_name}"]
        
        growth_info = self.get_growth_info()
        # 空字典直接判定为失败
        if not growth_info:
            log.append("❌ 获取签到基础信息失败（Cookie可能已失效/参数错误/接口返回异常）")
            return "\n".join(log), False
        
        # 所有get调用前先确保是字典
        total_cap = self.convert_bytes(growth_info.get("total_capacity", 0))
        cap_composition = growth_info.get("cap_composition", {}) or {}
        if not isinstance(cap_composition, dict):
            cap_composition = {}
        sign_reward = cap_composition.get("sign_reward", 0)
        sign_reward_str = self.convert_bytes(sign_reward)
        is_88vip = "88VIP用户" if growth_info.get("88VIP") else "普通用户"
        
        log.append(f"🔍 {is_88vip} | 总容量: {total_cap} | 签到累计: {sign_reward_str}")
        
        cap_sign = growth_info.get("cap_sign", {}) or {}
        if not isinstance(cap_sign, dict):
            cap_sign = {}
        
        if cap_sign.get("sign_daily"):
            daily_reward = self.convert_bytes(cap_sign.get("sign_daily_reward", 0))
            progress = f"{cap_sign.get('sign_progress', 0)}/{cap_sign.get('sign_target', 0)}"
            log.append(f"✅ 接口验证今日已签到 | 获得: {daily_reward} | 连签进度: {progress}")
            # 查询抽奖余额
            balance = self.query_balance()
            log.append(f"🎁 抽奖余额: {balance}")
            return "\n".join(log), True
        else:
            sign_result = self.get_growth_sign()
            if sign_result:
                reward = self.convert_bytes(sign_result.get("sign_daily_reward", 0))
                progress = f"{cap_sign.get('sign_progress', 0)+1}/{cap_sign.get('sign_target', 0)}"
                log.append(f"✅ 签到成功 | 获得: {reward} | 连签进度: {progress}")
                # 修复：重新获取最新的容量信息，确保显示签到后的当前值
                updated_info = self.get_growth_info()
                if updated_info:
                    updated_total_cap = self.convert_bytes(updated_info.get("total_capacity", 0))
                    updated_cap_composition = updated_info.get("cap_composition", {}) or {}
                    updated_sign_reward = self.convert_bytes(updated_cap_composition.get("sign_reward", 0))
                    # 替换第二行中的总容量和签到累计为最新值（不新增行）
                    log[1] = f"🔍 {is_88vip} | 总容量: {updated_total_cap} | 签到累计: {updated_sign_reward}"
                # 查询抽奖余额
                balance = self.query_balance()
                log.append(f"🎁 抽奖余额: {balance}")
                return "\n".join(log), True
            else:
                log.append(f"❌ 签到失败 | 原因: 接口返回异常（请检查Cookie有效性/重新抓包）")
                return "\n".join(log), False

def write_success_date():
    """写入成功签到的日期（北京时间）"""
    try:
        # 获取当前北京时间的日期
        beijing_now = datetime.now(BEIJING_TZ)
        current_date = beijing_now.strftime('%Y-%m-%d')
        # 写入缓存文件
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            f.write(current_date)
        print(f"✅ 已写入成功签到日期: {current_date} 到 {CACHE_FILE}")
    except Exception as e:
        print(f"❌ 写入签到日期失败: {str(e)}")

def main():
    """主执行函数（输出状态给Workflow）"""
    now = datetime.now(BEIJING_TZ)
    time_str = now.strftime('%Y-%m-%d %H:%M:%S')

    print("="*50)
    print("---------- 夸克网盘自动签到开始 ----------")
    print(f"执行时间: {time_str} (北京时间)")
    print("="*50)

    final_msg = [f"夸克网盘签到结果汇总（{time_str} 北京时间）:"]
    overall_success = True
    
    cookie_list = get_env()
    final_msg.append(f"📊 检测到有效账号数: {len(cookie_list)}")
    
    for idx, cookie_str in enumerate(cookie_list, 1):
        print(f"\n{'='*30} 处理第{idx}个账号 {'='*30}")
        try:
            quark = Quark(cookie_str, idx)
            sign_log, sign_success = quark.do_sign()
            final_msg.append(sign_log)
            print(sign_log)
            
            if not sign_success:
                overall_success = False
        except Exception as e:
            err_log = f"\n📱 第{idx}个账号 | ❌ 处理失败: {str(e)}"
            final_msg.append(err_log)
            print(err_log)
            overall_success = False
        print(f"{'='*70}")
    
    final_content = "\n".join(final_msg)
    send_wpush(
        "夸克网盘自动签到" + ("（部分账号失败）" if not overall_success else ""),
        final_content
    )
    
    # 核心修改：仅当所有账号签到成功时，写入缓存文件
    if overall_success:
        print(f"\n✅ 所有账号签到成功，准备写入缓存文件")
        write_success_date()
    else:
        print(f"\n❌ 部分/全部账号签到失败，不写入缓存文件")
    # 输出状态到环境变量（确保Workflow能识别）
    github_output = os.getenv('GITHUB_OUTPUT')
    if github_output:
        with open(github_output, 'a', encoding='utf-8') as f:
            f.write(f"overall_success={str(overall_success).lower()}\n")
    print(f"📤 签到状态输出: overall_success={str(overall_success).lower()}")
    
    print("\n" + "="*50)
    print("---------- 夸克网盘自动签到结束 ----------")
    print("="*50)
    return final_content

if __name__ == "__main__":
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    
    try:
        main()
    except Exception as e:
        error_msg = f"❌ 脚本执行异常: {str(e)}"
        print(error_msg)
        send_wpush("夸克签到脚本异常", error_msg)
        github_output = os.getenv('GITHUB_OUTPUT')
        if github_output:
            with open(github_output, 'a', encoding='utf-8') as f:
                f.write("overall_success=false\n")
        print("📤 签到状态输出: overall_success=false")
        sys.exit(1)
