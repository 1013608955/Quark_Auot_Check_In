import os
import re
import sys
import time
import requests
from urllib.parse import quote, urlparse, parse_qs, unquote
from datetime import datetime

# ===================== 配置说明 =====================
# GitHub仓库变量配置：
# 1. COOKIE_QUARK：填完整的夸克接口URL，多账号用 && 或 \n 分隔
# 2. WPUSH_KEY：填wpush.cn获取的推送Token
# =====================================================

# 缓存文件路径（GitHub Action中使用临时目录）
CACHE_FILE = os.path.join(os.getenv("RUNNER_TEMP", "/tmp"), "quark_sign_cache.txt")

def send_wpush(title, content):
    """WPush推送实现"""
    wpush_key = os.getenv("WPUSH_KEY")
    if not wpush_key:
        print("❌ 未配置WPUSH_KEY仓库变量，跳过推送")
        return
    
    title_encoded = quote(title, encoding='utf-8')
    content_encoded = quote(content, encoding='utf-8')
    url = f"https://wpush.cn/send?token={wpush_key}&title={title_encoded}&content={content_encoded}"
    
    try:
        response = requests.get(url, timeout=10)
        result = response.json()
        if result.get("code") == 200:
            print("✅ WPush推送成功")
        else:
            print(f"❌ WPush推送失败: {result.get('msg', '未知错误')}")
    except Exception as e:
        print(f"❌ WPush推送异常: {str(e)}")

def parse_cookie_from_url(url_str):
    """从完整URL中解析kps/sign/vcode参数"""
    try:
        url_str = url_str.strip()
        parsed_url = urlparse(url_str)
        query_params = parse_qs(parsed_url.query)
        
        kps = query_params.get('kps', [''])[0]
        sign = query_params.get('sign', [''])[0]
        vcode = query_params.get('vcode', [''])[0]
        
        kps = unquote(kps) if kps else ''
        sign = unquote(sign) if sign else ''
        vcode = unquote(vcode) if vcode else ''
        
        if not all([kps, sign, vcode]):
            raise ValueError("URL中缺失kps/sign/vcode关键参数")
        
        return f"kps={kps};sign={sign};vcode={vcode}"
    except Exception as e:
        print(f"❌ URL解析失败: {str(e)} | URL: {url_str[:50]}...")
        return ""

def get_env():
    """获取并解析环境变量中的夸克参数"""
    if "COOKIE_QUARK" not in os.environ:
        err_msg = "❌ 未添加COOKIE_QUARK仓库变量"
        print(err_msg)
        send_wpush("夸克自动签到", err_msg)
        sys.exit(0)
    
    cookie_raw = os.environ.get("COOKIE_QUARK")
    raw_list = re.split(r'\n|&&', cookie_raw)
    cookie_list = []
    
    for item in raw_list:
        item = item.strip()
        if not item:
            continue
        
        if item.startswith("http"):
            parsed_cookie = parse_cookie_from_url(item)
            if parsed_cookie:
                cookie_list.append(parsed_cookie)
        else:
            if all(key in item for key in ["kps=", "sign=", "vcode="]):
                cookie_list.append(item.strip())
    
    if not cookie_list:
        err_msg = "❌ COOKIE_QUARK解析后无有效账号，请检查URL格式"
        print(err_msg)
        send_wpush("夸克自动签到", err_msg)
        sys.exit(0)
    
    return cookie_list

def read_sign_cache(user_index):
    """读取指定账号的签到缓存（仅当实际签到成功时有效）"""
    try:
        if not os.path.exists(CACHE_FILE):
            return False
        
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        today = datetime.now().strftime("%Y-%m-%d")
        for line in lines:
            if line.strip():
                idx, sign_date, sign_status = line.strip().split("|")
                if idx == str(user_index) and sign_date == today and sign_status == "success":
                    return True
        return False
    except Exception as e:
        print(f"❌ 读取缓存失败: {str(e)}")
        return False

def write_sign_cache(user_index, sign_success):
    """写入签到缓存（仅当实际签到成功时记录）"""
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        # 先读取现有缓存，过滤掉当前账号的旧记录
        existing = []
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                existing = f.readlines()
        
        # 过滤当前账号的旧记录
        new_lines = []
        for line in existing:
            if line.strip() and not line.strip().startswith(f"{user_index}|"):
                new_lines.append(line)
        
        # 仅当签到成功时添加新记录
        if sign_success:
            new_lines.append(f"{user_index}|{today}|success\n")
        
        # 写入缓存文件
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        
        print(f"📝 账号{user_index}缓存已更新: {'签到成功' if sign_success else '签到失败，清除缓存'}")
    except Exception as e:
        print(f"❌ 写入缓存失败: {str(e)}")

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
        missing = [p for p in required if p not in self.param or not self.param[p]]
        if missing:
            raise ValueError(f"{self.user_name} 缺失必要参数: {','.join(missing)}")

    def convert_bytes(self, b):
        """字节单位转换"""
        if not isinstance(b, (int, float)) or b < 0:
            return "0.00 B"
        
        units = ("B", "KB", "MB", "GB", "TB", "PB")
        i = 0
        while b >= 1024 and i < len(units) - 1:
            b /= 1024
            i += 1
        return f"{b:.2f} {units[i]}"

    def _request(self, method, url, params=None, json=None):
        """统一请求封装"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; SM-G9980 Build/TP1A.220624.014; wv) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://drive-m.quark.cn/",
            "Connection": "keep-alive"
        }
        
        try:
            session = requests.Session()
            session.mount('https://', requests.adapters.HTTPAdapter(max_retries=3))
            
            if method.lower() == "get":
                resp = session.get(url, params=params, headers=headers, timeout=20)
            elif method.lower() == "post":
                resp = session.post(url, params=params, json=json, headers=headers, timeout=20)
            else:
                raise ValueError(f"不支持的请求方法: {method}")
            
            resp.raise_for_status()
            result = resp.json()
            
            if result.get("code") != 0 and not result.get("data"):
                print(f"{self.user_name} 接口返回错误: {result.get('message', '未知错误')}")
                return False
            return result.get("data", {})
        except requests.exceptions.RequestException as e:
            print(f"{self.user_name} 请求异常: {str(e)}")
            return False
        except ValueError as e:
            print(f"{self.user_name} 响应解析异常: {str(e)}")
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
            log.append("❌ 获取签到基础信息失败（Cookie可能已失效）")
            write_sign_cache(self.user_index, False)  # 清除缓存
            return "\n".join(log), False
        
        # 3. 解析基础信息
        total_cap = self.convert_bytes(growth_info.get("total_capacity", 0))
        sign_reward = growth_info.get("cap_composition", {}).get("sign_reward", 0)
        sign_reward_str = self.convert_bytes(sign_reward)
        is_88vip = "88VIP用户" if growth_info.get("88VIP") else "普通用户"
        
        log.append(f"🔍 {is_88vip} | 总容量: {total_cap} | 签到累计: {sign_reward_str}")
        
        # 4. 检查真实签到状态/执行签到
        cap_sign = growth_info.get("cap_sign", {})
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
                log.append(f"❌ 签到失败 | 原因: 接口返回异常（请检查Cookie有效性）")
                sign_success = False
        
        # 5. 查询抽奖余额
        balance = self.queryBalance()
        log.append(f"🎁 抽奖余额: {balance}")
        
        # 6. 根据实际签到结果更新缓存
        write_sign_cache(self.user_index, sign_success)
        
        return "\n".join(log), sign_success

def main():
    """主执行函数"""
    print("---------- 夸克网盘自动签到开始 ----------")
    final_msg = ["夸克网盘签到结果汇总:"]
    overall_success = True
    
    # 1. 获取并解析Cookie/URL
    cookie_list = get_env()
    final_msg.append(f"📊 检测到有效账号数: {len(cookie_list)}")
    
    # 2. 遍历每个账号执行签到
    for idx, cookie_str in enumerate(cookie_list, 1):
        try:
            # 解析单个账号的Cookie字符串为字典
            user_data = {}
            for item in cookie_str.split(";"):
                item = item.strip()
                if "=" in item:
                    key, value = item.split("=", 1)
                    user_data[key] = value
            
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
    
    # 3. 推送结果到WPush
    final_content = "\n".join(final_msg)
    send_wpush("夸克网盘自动签到" + ("（部分账号失败）" if not overall_success else ""), final_content)
    
    print("\n---------- 夸克网盘自动签到结束 ----------")
    return final_content

if __name__ == "__main__":
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    try:
        main()
    except Exception as e:
        error_msg = f"❌ 脚本执行异常: {str(e)}"
        print(error_msg)
        send_wpush("夸克签到脚本异常", error_msg)
        sys.exit(1)
