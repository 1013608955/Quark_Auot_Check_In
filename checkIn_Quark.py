import os
import re
import sys
import time
import json
import requests
from urllib.parse import quote, urlparse, parse_qs, unquote
from datetime import datetime
from pathlib import Path

# ===================== 配置说明 =====================
# GitHub仓库变量配置：
# 1. COOKIE_QUARK：填完整的夸克接口URL，多账号用 && 或 \n 分隔
# 2. WPUSH_KEY：填wpush.cn获取的推送Token
# 3. 可选：抓包的完整请求头（替换下方USER_AGENT/QUARK_COOKIE）
# =====================================================

# 自定义配置（替换为你抓包的真实值，提升401成功率）
USER_AGENT = "Mozilla/5.0 (Mozilla/5.0 (Linux; U; Android 15; zh-CN; 2201122C Build/AQ3A.241006.001) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/123.0.6312.80 Quark/10.1.2.973 Mobile Safari/537.36"
QUARK_COOKIE = ""  # 抓包的完整Cookie字符串（可选，填后提升成功率）

# 缓存文件路径（GitHub Action中使用临时目录）
CACHE_DIR = os.getenv("RUNNER_TEMP", "/tmp")
CACHE_FILE = os.path.join(CACHE_DIR, "quark_sign_cache.txt")

def send_wpush(title, content):
    """适配WPush官方v1接口的推送实现（优化版）"""
    wpush_key = os.getenv("WPUSH_KEY")
    if not wpush_key:
        print("❌ 未配置WPUSH_KEY仓库变量，跳过推送")
        return
    
    # 限制内容长度（避免接口截断，保留关键信息）
    max_content_len = 2000
    if len(content) > max_content_len:
        content = content[:max_content_len] + "\n\n【内容过长，已截断】"
    
    # 官方接口地址
    url = "https://api.wpush.cn/api/v1/send"
    # 请求参数（按文档要求的JSON格式）
    payload = {
        "apikey": wpush_key,
        "title": title[:50],  # 标题长度限制
        "content": content
    }
    # 请求头（必须设置为JSON类型）
    headers = {
        "Content-Type": "application/json"，
        "User-Agent": "QuarkSign/1.0"
    }
    
    try:
        # 增加超时和重试
        session = requests.Session()
        session.mount('https://', requests.adapters.HTTPAdapter(max_retries=2))
        response = session.post(
            url, 
            data=json.dumps(payload, ensure_ascii=False),  # 确保中文正常
            headers=headers, 
            timeout=15
        )
        
        # 解析响应（官方返回为JSON格式）
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
    """从完整URL中解析kps/sign/vcode参数（兼容特殊字符）"""
    try:
        url_str = url_str.strip()
        if not url_str.startswith("http"):
            raise ValueError("不是有效的URL格式")
        
        parsed_url = urlparse(url_str)
        query_params = parse_qs(parsed_url.query, keep_blank_values=True)
        
        # 提取关键参数（处理列表值，取第一个）
        kps = query_params.get('kps', [''])[0]
        sign = query_params.get('sign', [''])[0]
        vcode = query_params.get('vcode', [''])[0]
        
        # 解码URL编码的参数（处理特殊字符）
        kps = unquote(kps) if kps else ''
        sign = unquote(sign) if sign else ''
        vcode = unquote(vcode) if vcode else ''
        
        # 日志输出（脱敏）
        print(f"✅ 解析后的参数: kps={kps[:20]}... | sign={sign[:20]}... | vcode={vcode}")
        
        # 检查参数完整性
        if not all([kps, sign, vcode]):
            raise ValueError(f"URL中缺失关键参数 | kps={bool(kps)} | sign={bool(sign)} | vcode={bool(vcode)}")
        
        return f"kps={kps};sign={sign};vcode={vcode}"
    except Exception as e:
        print(f"❌ URL解析失败: {str(e)} | URL: {url_str[:80]}...")
        return ""

def get_env():
    """获取并解析环境变量中的夸克参数（增强容错）"""
    # 检查COOKIE_QUARK是否存在
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
    
    # 分割多账号（支持 \n 或 && 分隔）
    raw_list = re.split(r'\n|\&\&', cookie_raw)
    cookie_list = []
    
    for idx, item in enumerate(raw_list, 1):
        item = item.strip()
        if not item:
            print(f"⚠️  第{idx}个账号配置为空，跳过")
            continue
        
        if item.startswith("http"):
            # 从URL解析参数
            parsed_cookie = parse_cookie_from_url(item)
            if parsed_cookie:
                cookie_list.append(parsed_cookie)
            else:
                print(f"⚠️  第{idx}个账号URL解析失败，跳过")
        else:
            # 已是参数字符串，验证关键参数
            if all(key in item for key in ["kps=", "sign=", "vcode="]):
                cookie_list.append(item.strip())
            else:
                print(f"⚠️  第{idx}个账号参数不完整，跳过 | 内容: {item[:50]}...")
    
    # 检查解析结果
    if not cookie_list:
        err_msg = "❌ COOKIE_QUARK解析后无有效账号，请检查URL格式"
        print(err_msg)
        send_wpush("夸克自动签到", err_msg)
        sys.exit(0)
    
    print(f"✅ 成功解析{len(cookie_list)}个有效账号")
    return cookie_list

def read_sign_cache(user_index):
    """读取指定账号的签到缓存（增强容错）"""
    try:
        if not os.path.exists(CACHE_FILE):
            return False
        
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f.readlines() if line.strip()]
        
        today = datetime.now().strftime("%Y-%m-%d")
        for line in lines:
            try:
                idx, sign_date, sign_status = line.split("|", 2)  # 只分割前两个|
                if idx == str(user_index) and sign_date == today and sign_status == "success":
                    return True
            except ValueError:
                continue  # 跳过格式错误的缓存行
        return False
    except Exception as e:
        print(f"❌ 读取缓存失败: {str(e)} | 缓存文件: {CACHE_FILE}")
        return False

def write_sign_cache(user_index, sign_success):
    """写入签到缓存（确保目录存在）"""
    try:
        # 确保缓存目录存在
        Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)
        
        today = datetime.now().strftime("%Y-%m-%d")
        # 先读取现有缓存
        existing = []
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                existing = [line.strip() for line in f.readlines() if line.strip()]
        
        # 过滤当前账号的旧记录
        new_lines = []
        for line in existing:
            try:
                idx = line.split("|", 1)[0]
                if idx != str(user_index):
                    new_lines.append(line)
            except ValueError:
                continue
        
        # 仅当签到成功时添加新记录
        if sign_success:
            new_lines.append(f"{user_index}|{today}|success")
        
        # 写入缓存文件（去重+排序）
        new_lines = sorted(list(set(new_lines)))  # 去重
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines) + "\n")
        
        print(f"📝 账号{user_index}缓存已更新: {'签到成功' if sign_success else '签到失败，清除缓存'}")
    except Exception as e:
        print(f"❌ 写入缓存失败: {str(e)} | 缓存文件: {CACHE_FILE}")

class Quark:
    """夸克网盘签到类（优化请求头）"""
    def __init__(self, user_data, user_index):
        self.param = user_data
        self.user_index = user_index
        self.user_name = f"第{user_index}个账号"
        self._check_required_params()

    def _check_required_params(self):
        """检查必要参数（更严谨）"""
        required = ["kps", "sign", "vcode"]
        missing = []
        for p in required:
            val = self.param.get(p, "").strip()
            if not val:
                missing.append(p)
        
        if missing:
            raise ValueError(f"{self.user_name} 缺失必要参数: {','.join(missing)}")

    def convert_bytes(self, b):
        """字节单位转换（增强容错）"""
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
        # 基础请求头（替换为抓包的真实值）
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://drive-m.quark.cn/",
            "Connection": "keep-alive",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept-Encoding": "gzip, deflate, br"
        }
        
        # 添加完整Cookie（可选，填后提升成功率）
        if QUARK_COOKIE:
            headers["Cookie"] = QUARK_COOKIE
        
        try:
            # 配置重试和超时
            session = requests.Session()
            session.mount('https://', requests.adapters.HTTPAdapter(max_retries=3))
            session.mount('http://', requests.adapters.HTTPAdapter(max_retries=3))
            
            # 执行请求
            if method.lower() == "get":
                resp = session.get(
                    url, 
                    params=params, 
                    headers=headers, 
                    timeout=20,
                    verify=False  # 忽略SSL验证（解决部分环境证书问题）
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
            
            # 打印响应状态（便于排查401）
            print(f"🔍 {self.user_name} 请求状态码: {resp.status_code} | URL: {url[:80]}")
            
            resp.raise_for_status()
            result = resp.json()
            
            # 检查接口返回状态
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
        """执行完整签到流程（验证实际签到状态）"""
        log = [f"\n📱 {self.user_name}"]
        sign_success = False  # 标记实际签到是否成功
        
        # 1. 先检查缓存（仅当缓存显示已成功签到时跳过）
        if read_sign_cache(self.user_index):
            log.append("✅ 缓存显示今日已成功签到，跳过执行（如需重新签到请清除缓存）")
            return "\n".join(log), True
        
        # 2. 获取基础信息（验证真实状态）
        growth_info = self.get_growth_info()
        if not growth_info:
            log.append("❌ 获取签到基础信息失败（Cookie可能已失效/参数错误）")
            write_sign_cache(self.user_index, False)  # 清除缓存
            return "\n".join(log), False
        
        # 3. 解析基础信息（兜底处理）
        total_cap = self.convert_bytes(growth_info.get("total_capacity", 0))
        cap_composition = growth_info.get("cap_composition", {}) or {}
        sign_reward = cap_composition.get("sign_reward", 0)
        sign_reward_str = self.convert_bytes(sign_reward)
        is_88vip = "88VIP用户" if growth_info.get("88VIP") else "普通用户"
        
        log.append(f"🔍 {is_88vip} | 总容量: {total_cap} | 签到累计: {sign_reward_str}")
        
        # 4. 检查真实签到状态/执行签到（兜底cap_sign不存在的情况）
        cap_sign = growth_info.get("cap_sign", {}) or {}
        if cap_sign.get("sign_daily"):
            # 接口明确返回已签到（真实状态）
            daily_reward = self.convert_bytes(cap_sign.get("sign_daily_reward", 0))
            progress = f"{cap_sign.get('sign_progress', 0)}/{cap_sign.get('sign_target', 0)}"
            log.append(f"✅ 接口验证今日已签到 | 获得: {daily_reward} | 连签进度: {progress}")
            sign_success = True
        else:
            # 执行签到并验证结果
            sign_result = self.get_growth_sign()
            if sign_result:
                reward = self.convert_bytes(sign_result.get("sign_daily_reward", 0))
                progress = f"{cap_sign.get('sign_progress', 0)+1}/{cap_sign.get('sign_target', 0)}"
                log.append(f"✅ 签到成功 | 获得: {reward} | 连签进度: {progress}")
                sign_success = True
            else:
                log.append(f"❌ 签到失败 | 原因: 接口返回异常（请检查Cookie有效性/重新抓包）")
                sign_success = False
        
        # 5. 查询抽奖余额
        balance = self.queryBalance()
        log.append(f"🎁 抽奖余额: {balance}")
        
        # 6. 根据实际签到结果更新缓存
        write_sign_cache(self.user_index, sign_success)
        
        return "\n".join(log), sign_success

def main():
    """主执行函数（优化日志）"""
    print("="*50)
    print("---------- 夸克网盘自动签到开始 ----------")
    print(f"执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*50)
    
    final_msg = [f"夸克网盘签到结果汇总（{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}）:"]
    overall_success = True
    
    # 1. 获取并解析Cookie/URL
    cookie_list = get_env()
    final_msg.append(f"📊 检测到有效账号数: {len(cookie_list)}")
    
    # 2. 遍历每个账号执行签到
    for idx, cookie_str in enumerate(cookie_list, 1):
        print(f"\n{'='*30} 处理第{idx}个账号 {'='*30}")
        try:
            # 解析单个账号的Cookie字符串为字典（兼容值含=的情况）
            user_data = {}
            for item in cookie_str.split(";"):
                item = item.strip()
                if "=" in item:
                    key, value = item.split("=", 1)  # 只分割第一个=
                    user_data[key.strip()] = value.strip()
            
            # 初始化夸克签到类并执行签到
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
    
    # 3. 推送结果到WPush
    final_content = "\n".join(final_msg)
    send_wpush(
        "夸克网盘自动签到" + ("（部分账号失败）" if not overall_success else ""),
        final_content
    )
    
    print("\n" + "="*50)
    print("---------- 夸克网盘自动签到结束 ----------")
    print("="*50)
    return final_content

if __name__ == "__main__":
    # 设置编码和SSL环境（解决GitHub Action中文乱码/证书问题）
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    os.environ.setdefault('REQUESTS_CA_BUNDLE', '')
    
    try:
        main()
    except Exception as e:
        error_msg = f"❌ 脚本执行异常: {str(e)}"
        print(error_msg)
        send_wpush("夸克签到脚本异常", error_msg)
        sys.exit(1)
