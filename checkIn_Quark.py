import os
import re
import sys
import requests
from urllib.parse import quote

# ===================== 配置项说明 =====================
# 1. 环境变量 COOKIE_QUARK：夸克Cookie，多账号用 && 或 \n 分隔
#    格式示例：kps=xxx;sign=xxx;vcode=xxx&&kps=yyy;sign=yyy;vcode=yyy
# 2. 环境变量 WPUSH_KEY：WPush的推送Token（从wpush.cn获取）
# =====================================================

def send_wpush(title, content):
    """
    WPush推送实现
    :param title: 推送标题
    :param content: 推送内容
    """
    # 获取WPush Token
    wpush_key = os.getenv("WPUSH_KEY")
    if not wpush_key:
        print("❌ 未配置WPUSH_KEY环境变量，跳过推送")
        return
    
    # WPush推送接口
    url = f"https://wpush.cn/send?token={wpush_key}&title={quote(title)}&content={quote(content)}"
    
    try:
        response = requests.get(url, timeout=10)
        result = response.json()
        if result.get("code") == 200:
            print("✅ WPush推送成功")
        else:
            print(f"❌ WPush推送失败: {result.get('msg', '未知错误')}")
    except Exception as e:
        print(f"❌ WPush推送异常: {str(e)}")

def get_env():
    """
    获取并解析环境变量中的夸克Cookie
    :return: 解析后的Cookie列表（每个元素是单个账号的Cookie字符串）
    """
    # 检查COOKIE_QUARK是否存在
    if "COOKIE_QUARK" not in os.environ:
        err_msg = "❌ 未添加COOKIE_QUARK环境变量"
        print(err_msg)
        send_wpush("夸克自动签到", err_msg)
        sys.exit(0)
    
    # 读取并分割多账号Cookie（支持 \n 或 && 分隔）
    cookie_raw = os.environ.get("COOKIE_QUARK")
    cookie_list = re.split(r'\n|&&', cookie_raw)
    
    # 过滤空值和无效项
    cookie_list = [cookie.strip() for cookie in cookie_list if cookie.strip()]
    
    if not cookie_list:
        err_msg = "❌ COOKIE_QUARK格式错误，无有效账号"
        print(err_msg)
        send_wpush("夸克自动签到", err_msg)
        sys.exit(0)
    
    return cookie_list

class Quark:
    """
    夸克网盘签到类，封装签到、查询等核心功能
    """
    def __init__(self, user_data, user_index):
        """
        初始化
        :param user_data: 解析后的用户Cookie字典
        :param user_index: 用户序号（用于日志区分）
        """
        self.param = user_data
        self.user_index = user_index
        self.user_name = f"第{user_index}个账号"
        
        # 检查必要参数
        self._check_required_params()

    def _check_required_params(self):
        """检查必要参数是否齐全，缺失则抛出异常"""
        required = ["kps", "sign", "vcode"]
        missing = [p for p in required if p not in self.param or not self.param[p]]
        if missing:
            raise ValueError(f"{self.user_name} 缺失必要参数: {','.join(missing)}")

    def convert_bytes(self, b):
        """
        字节单位转换（B -> KB/MB/GB/TB）
        :param b: 原始字节数
        :return: 格式化后的带单位字符串
        """
        if not isinstance(b, (int, float)) or b < 0:
            return "0.00 B"
        
        units = ("B", "KB", "MB", "GB", "TB", "PB")
        i = 0
        while b >= 1024 and i < len(units) - 1:
            b /= 1024
            i += 1
        return f"{b:.2f} {units[i]}"

    def _request(self, method, url, params=None, json=None):
        """
        统一请求封装，处理通用异常
        :param method: 请求方法（get/post）
        :param url: 请求地址
        :param params: URL参数
        :param json: POST JSON数据
        :return: 接口返回的data字段，失败返回False
        """
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; SM-G9980 Build/TP1A.220624.014; wv) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*"
        }
        
        try:
            if method.lower() == "get":
                resp = requests.get(url, params=params, headers=headers, timeout=15)
            elif method.lower() == "post":
                resp = requests.post(url, params=params, json=json, headers=headers, timeout=15)
            else:
                raise ValueError(f"不支持的请求方法: {method}")
            
            resp.raise_for_status()  # 抛出HTTP状态码异常
            result = resp.json()
            
            # 检查接口返回状态
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
        """
        执行完整签到流程
        :return: 签到结果日志字符串
        """
        log = [f"\n📱 {self.user_name}"]
        
        # 1. 获取基础信息
        growth_info = self.get_growth_info()
        if not growth_info:
            log.append("❌ 获取签到基础信息失败")
            return "\n".join(log)
        
        # 2. 解析基础信息
        total_cap = self.convert_bytes(growth_info.get("total_capacity", 0))
        sign_reward = growth_info.get("cap_composition", {}).get("sign_reward", 0)
        sign_reward_str = self.convert_bytes(sign_reward)
        is_88vip = "88VIP用户" if growth_info.get("88VIP") else "普通用户"
        
        log.append(f"🔍 {is_88vip} | 总容量: {total_cap} | 签到累计: {sign_reward_str}")
        
        # 3. 检查签到状态/执行签到
        cap_sign = growth_info.get("cap_sign", {})
        if cap_sign.get("sign_daily"):
            # 已签到
            daily_reward = self.convert_bytes(cap_sign.get("sign_daily_reward", 0))
            progress = f"{cap_sign.get('sign_progress', 0)}/{cap_sign.get('sign_target', 0)}"
            log.append(f"✅ 今日已签到 | 获得: {daily_reward} | 连签进度: {progress}")
        else:
            # 执行签到
            sign_result = self.get_growth_sign()
            if sign_result:
                reward = self.convert_bytes(sign_result.get("sign_daily_reward", 0))
                progress = f"{cap_sign.get('sign_progress', 0)+1}/{cap_sign.get('sign_target', 0)}"
                log.append(f"✅ 签到成功 | 获得: {reward} | 连签进度: {progress}")
            else:
                log.append(f"❌ 签到失败 | 原因: 接口返回异常")
        
        # 4. 查询抽奖余额（可选）
        balance = self.queryBalance()
        log.append(f"🎁 抽奖余额: {balance}")
        
        return "\n".join(log)

def main():
    """主执行函数"""
    print("---------- 夸克网盘自动签到开始 ----------")
    final_msg = ["夸克网盘签到结果汇总:"]
    
    # 1. 获取并解析Cookie
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
                    # 处理值中包含=的情况（只分割第一个=）
                    key, value = item.split("=", 1)
                    user_data[key] = value
            
            # 初始化夸克签到类并执行签到
            quark = Quark(user_data, idx)
            sign_log = quark.do_sign()
            final_msg.append(sign_log)
            print(sign_log)
        
        except Exception as e:
            err_log = f"\n📱 第{idx}个账号 | ❌ 处理失败: {str(e)}"
            final_msg.append(err_log)
            print(err_log)
    
    # 3. 推送结果到WPush
    final_content = "\n".join(final_msg)
    send_wpush("夸克网盘自动签到", final_content)
    
    print("\n---------- 夸克网盘自动签到结束 ----------")
    return final_content

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        error_msg = f"❌ 脚本执行异常: {str(e)}"
        print(error_msg)
        send_wpush("夸克签到脚本异常", error_msg)
        sys.exit(1)
