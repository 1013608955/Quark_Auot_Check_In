import os
import re
import sys
import json
import requests
from urllib.parse import quote, urlparse, parse_qs, unquote
from datetime import datetime
from pathlib import Path

# ===================== 配置说明 =====================
# GitHub仓库变量配置：
# 1. COOKIE_QUARK：填完整的夸克接口URL，多账号用 && 或 \n 分隔
# 2. WPUSH_KEY：填wpush.cn获取的推送Token
# 3. 可选：替换下方抓包的真实User-Agent/完整Cookie（提升401成功率）
# =====================================================

# 自定义配置（替换为你抓包的真实值）
USER_AGENT = "Mozilla/5.0 (Linux; Android 13; SM-G9980 Build/TP1A.220624.014; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/114.0.5735.130 Mobile Safari/537.36 Quark/10.1.2.973"
QUARK_COOKIE = ""  # 抓包的完整Cookie字符串（可选，填后提升成功率）

# 缓存文件路径（GitHub Action中使用临时目录）
CACHE_DIR = os.getenv("RUNNER_TEMP", "/tmp")
CACHE_FILE = os.path.join(CACHE_DIR, "quark_sign_cache.txt")

def send_wpush(title, content):
    """适配WPush官方v1接口的推送实现"""
    wpush_key = os.getenv("WPUSH_KEY")
    if not wpush_key:
        print("❌ 未配置WPUSH_KEY仓库变量，跳过推送")
        return
    
    # 限制内容长度（避免接口截断）
    max_content_len = 2000
    if len(content) > max_content_len:
        content = content[:max_content_len] + "\n\n【内容过长，已截断】"
    
    # 官方接口地址
    url = "https://api.wpush.cn/api/v1/send"
    # 请求参数（JSON格式）
    payload = {
        "apikey": wpush_key,
        "title": title[:50],
        "content": content
    }
    # 请求头
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
            print("✅ WPush推送成功")
        else:
            print(f"❌ WPush推送失败: {result.get('msg', '未知错误')} | 响应码: {result.get('code')}")
    except json.JSONDecodeError:
        print(f"❌ WPush推送响应非JSON格式: {response.text[:100]}...")
    except requests.exceptions.Timeout:
        print("❌ WPush推送超时，请检查网络")
    except Exception as e:
        print(f"❌ WPush推送异常: {str(e)}")
        
def parse_cookie_from_url(url_str):
    """从完整URL中解析kps/sign/vcode参数"""
    try:
        url_str = url_str.strip()
        if not url_str.startswith("http"):
            raise ValueError("不是有效的URL格式")
        
        parsed_url = urlparse(url_str)
        query_params = parse_qs(parsed_url.query, keep_blank_values=True)
        
        kps = query_params.get('kps', [''])[0]
        sign = query_params.get('sign', [''])[0]
        vcode = query_params.get('vcode', [''])[0]
        
        kps = unquote(kps) if kps else ''
        sign = unquote(sign) if sign else ''
        vcode = unquote(vcode) if vcode else ''
        
        print(f"✅ 解析后的参数: kps={kps[:20]}... | sign={sign[:20]}... | vcode={vcode}")
        
        if not all([kps, sign, vcode]):
            raise ValueError(f"URL中缺失关键参数 | kps={bool(kps)} | sign={bool(sign)} | vcode={bool(vcode)}")
        
        return f"kps={kps};sign={sign};vcode={vcode}"
    except Exception as e:
        print(f"❌ URL解析失败: {str(e)} | URL: {url_str[:80]}...")
        return ""

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
        
        if item.startswith("http"):
            parsed_cookie = parse_cookie_from_url(item)
            if parsed_cookie:
                cookie_list.append(parsed_cookie)
            else:
                print(f"⚠️  第{idx}个账号URL解析失败，跳过")
        else:
            if all(key in item for key in ["kps=", "sign=", "vcode="]):
                cookie_list.append(item.strip())
            else:
                print(f"⚠️  第{idx}个账号参数不完整，跳过 | 内容: {item[:50]}...")
    
    if not cookie_list:
        err_msg = "❌ COOKIE_QUARK解析后无有效账号，请检查URL格式"
        print(err_msg)
        send_wpush("夸克自动签到", err_msg)
        sys.exit(0)
    
    print(f"✅ 成功解析{len(cookie_list)}个有效账号")
    return cookie_list

def read_sign_cache(user_index):
    """读取指定账号的签到缓存"""
    try:
        if not os.path.exists(CACHE_FILE):
            return False
        
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f.readlines() if line.strip()]
        
        today = datetime.now().strftime("%Y-%m-%d")
        for line in lines:
            try:
                idx, sign_date, sign_status = line.split("|", 2)
                if idx == str(user_index) and sign_date == today and sign_status == "success":
                    return True
            except ValueError:
                continue
        return False
    except Exception as e:
        print(f"❌ 读取缓存失败: {str(e)} | 缓存文件: {CACHE_FILE}")
        return False

def write_sign_cache(user_index, sign_success):
    """写入签到缓存（确保目录存在）"""
    try:
        Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)
        
        today = datetime.now().strftime("%Y-%m-%d")
        existing = []
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                existing = [line.strip() for line in f.readlines() if line.strip()]
        
        new_lines = []
        for line in existing:
            try:
                idx = line.split("|", 1)[0]
                if idx != str(user_index):
                    new_lines.append(line)
            except ValueError:
                continue
        
        if sign_success:
            new_lines.append(f"{user_index}|{today}|success")
        
        new_lines = sorted(list(set(new_lines)))
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines) + "\n")
        
        print(f"📝 账号{user_index}缓存已更新: {'签到成功' if sign_success else '签到失败，清除缓存'}")
    except Exception as e:
        print(f"❌ 写入缓存失败: {str(e)} | 缓存文件: {CACHE_FILE}")

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

    def _request(self, method, url, params=None, json=None):
        """统一请求封装（补充关键请求头）"""
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
        
        try:
            session = requests.Session()
            session.mount('https://', requests.adapters.HTTPAdapter(max_retries=3))
            
            if method.lower() == "get":
                resp = session.get(
                    url, 
                    params=params, 
                    headers=headers, 
                    timeout=20,
                    verify=False
                )
            elif method.lower() == "post":
                resp = session.post(
                    url, 
                    params=params, 
                    json=json, 
                    headers=headers, 
                    timeout=20,
                    verify=False
                )
            else:
                raise ValueError(f"不支持的请求方法: {method}")
            
            print(f"🔍 {self.user_name} 请求状态码: {resp.status_code} | URL: {url[:80]}")
            
            resp.raise_for_status()
            result = resp.json()
            
            if result.get("code") != 0 and not result.get("data"):
                err_msg = result.get("message", result.get("msg", "未知错误"))
                print(f"{self.user_name} 接口返回错误: {err_msg} | 响应码: {result.get('code')}")
                return False
            return result.get("data", {})
        except requests.exceptions.HTTPError as e:
            print(f"{self.user_name} HTTP错误: {str(e)} | 状态码: {resp.status_code if 'resp' in locals() else '未知'}")
            return False
        except requests.exceptions.RequestException as e:
            print(f"{self.user_name} 请求异常: {str(e)}")
            return False
        except ValueError as e:
            print(f"{self.user_name} 响应解析异常: {str(e)} | 响应内容: {resp.text[:100] if 'resp' in locals() else '无'}")
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
        """执行完整签到流程"""
        log = [f"\n📱 {self.user_name}"]
        sign_success = False
        
        if read_sign_cache(self.user_index):
            log.append("✅ 缓存显示今日已成功签到，跳过执行（如需重新签到请清除缓存）")
            return "\n".join(log), True
        
        growth_info = self.get_growth_info()
        if not growth_info:
            log.append("❌ 获取签到基础信息失败（Cookie可能已失效/参数错误）")
            write_sign_cache(self.user_index, False)
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
            sign_success = True
        else:
            sign_result = self.get_growth_sign()
            if sign_result:
                reward = self.convert_bytes(sign_result.get("sign_daily_reward", 0))
                progress = f"{cap_sign.get('sign_progress', 0)+1}/{cap_sign.get('sign_target', 0)}"
                log.append(f"✅ 签到成功 | 获得: {reward} | 连签进度: {progress}")
                sign_success = True
            else:
                log.append(f"❌ 签到失败 | 原因: 接口返回异常（请检查Cookie有效性/重新抓包）")
                sign_success = False
        
        balance = self.queryBalance()
        log.append(f"🎁 抽奖余额: {balance}")
        
        write_sign_cache(self.user_index, sign_success)
        
        return "\n".join(log), sign_success

def main():
    """主执行函数（输出状态给Workflow）"""
    print("="*50)
    print("---------- 夸克网盘自动签到开始 ----------")
    print(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*50)
    
    final_msg = [f"夸克网盘签到结果汇总（{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}）:"]
    overall_success = True
    
    cookie_list = get_env()
    final_msg.append(f"📊 检测到有效账号数: {len(cookie_list)}")
    
    for idx, cookie_str in enumerate(cookie_list, 1):
        print(f"\n{'='*30} 处理第{idx}个账号 {'='*30}")
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
    
    # 关键：输出签到成功状态给GitHub Workflow
    print(f"::set-output name=overall_success::{str(overall_success).lower()}")
    
    print("\n" + "="*50)
    print("---------- 夸克网盘自动签到结束 ----------")
    print("="*50)
    return final_content

if __name__ == "__main__":
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    os.environ.setdefault('REQUESTS_CA_BUNDLE', '')
    
    try:
        main()
    except Exception as e:
        error_msg = f"❌ 脚本执行异常: {str(e)}"
        print(error_msg)
        send_wpush("夸克签到脚本异常", error_msg)
        # 异常时标记为签到失败
        print(f"::set-output name=overall_success::false")
        sys.exit(1)
