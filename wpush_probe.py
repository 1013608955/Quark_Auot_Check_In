"""临时探测脚本：用真实 API Key 对比多种参数组合，定位 WPush 500「服务异常」的触发条件。
仅用于排查，定位后会删除。
"""
import os
import urllib.parse
import urllib.request
import urllib.error

KEY = os.environ.get("WPUSH_KEY", "")
URL = "https://api.wpush.cn/api/v1/send"


def mask(t):
    if not t:
        return ""
    if KEY and KEY in t:
        t = t.replace(KEY, "***")
    return t


def send(name, data):
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        URL, data=body, headers={"User-Agent": "QuarkSign/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            raw = r.read().decode("utf-8", "replace")
            print(f"[{name}]  HTTP {r.status} -> {mask(raw)[:300]}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        print(f"[{name}]  HTTP {e.code} -> {mask(raw)[:300]}")
    except Exception as e:
        print(f"[{name}]  异常 {e}")


if not KEY:
    print("未配置 WPUSH_KEY，无法探测")
    raise SystemExit(1)

print(f"API Key 前缀: {KEY[:6]}... 长度: {len(KEY)}")
print(f"Key 是否以 WPUSH_ 开头: {KEY.startswith('WPUSH_')}")
print("=" * 60)

realistic = (
    "夸克网盘签到结果汇总（2026-09-09 08:00:00 北京时间）:\n"
    "\u0001 检测到有效账号数: 2\n\n"
    "第1个账号\n"
    "\U0001f50d 普通用户 | 总容量: 1.50 TB | 签到累计: 20.00 GB\n"
    "✅ 签到成功 | 获得: 200.00 MB | 连签进度: 5/7"
)

send("1-仅标题(无content)", {"apikey": KEY, "title": "probe1-minimal"})
send("2-ASCII短内容", {"apikey": KEY, "title": "probe2", "content": "hello world"})
send("3-真实内容(中文/emoji/多行)", {"apikey": KEY, "title": "probe3", "content": realistic})
send("4-显式channel=wechat", {"apikey": KEY, "title": "probe4", "content": "hello", "channel": "wechat"})
send("5-长内容2000字", {"apikey": KEY, "title": "probe5", "content": "测" * 2000})
send("6-带url参数", {"apikey": KEY, "title": "probe6", "content": "hello", "url": "https://example.com"})

print("=" * 60)
print("探测结束")
