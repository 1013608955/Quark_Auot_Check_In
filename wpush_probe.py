"""探测第二轮：定位 WPush 500「服务异常」的确切触发字符。
假设：非 BMP（4 字节）emoji 触发服务端异常，BMP（3 字节）emoji 正常。
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
            print(f"[{name}]  HTTP {r.status} -> {mask(raw)[:200]}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        print(f"[{name}]  HTTP {e.code} -> {mask(raw)[:200]}")
    except Exception as e:
        print(f"[{name}]  异常 {e}")


if not KEY:
    print("未配置 WPUSH_KEY")
    raise SystemExit(1)

print("=" * 60)

# --- BMP（3字节）emoji：预期应正常 ---
send("A-BMP emoji ✅ U+2705", {"apikey": KEY, "title": "probeA", "content": "签到 ✅ 成功"})
send("B-BMP emoji ❌ U+274C", {"apikey": KEY, "title": "probeB", "content": "失败 ❌ 了"})

# --- 非 BMP（4字节）emoji：预期触发 500 ---
send("C-非BMP 🔍 U+1F50D", {"apikey": KEY, "title": "probeC", "content": "查询 🔍 中"})
send("D-非BMP 📊 U+1F4CA", {"apikey": KEY, "title": "probeD", "content": "统计 📊 数据"})
send("E-非BMP 📱 U+1F4F1", {"apikey": KEY, "title": "probeE", "content": "手机 📱 端"})

# --- 其他可能因素 ---
send("F-仅换行", {"apikey": KEY, "title": "probeF", "content": "第一行\n第二行"})
send("G-竖线", {"apikey": KEY, "title": "probeG", "content": "a | b | c"})
send("H-Markdown星号", {"apikey": KEY, "title": "probeH", "content": "**粗体** 内容"})

print("=" * 60)
print("探测结束")
