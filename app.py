from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from jinja2 import Template
from datetime import datetime
import uvicorn, threading, queue, time, random, os, sys

app = FastAPI()

# ─────────────────────────────────────────────
# 密碼設定（Render 必須設 ADMIN_PASSWORD；本機可設 DEBUG=1）
# ─────────────────────────────────────────────
DEBUG = os.getenv("DEBUG", "0") == "1"
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

if not ADMIN_PASSWORD:
    if DEBUG:
        ADMIN_PASSWORD = "DUAN1223"
        print("[DEBUG] 使用預設管理密碼：DUAN1223")
    else:
        print("❌ ERROR: ADMIN_PASSWORD 未設定（請到 Render → Environment 新增）", file=sys.stderr)
        raise SystemExit(1)

# ─────────────────────────────────────────────
# 訂單與背景工人
# ─────────────────────────────────────────────
orders = []
orders_lock = threading.Lock()
job_q = queue.Queue()
is_worker_running = threading.Event()
stop_event = threading.Event()

# ─────────────────────────────────────────────
# HTML 模板
# ─────────────────────────────────────────────
INDEX_HTML = Template("""
<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<title>雞蛋糕點餐 🍰</title>
<h2>雞蛋糕點餐 🍰</h2>
<form method="post" action="/order">
  <label>口味：</label>
  <select name="sku">
    <option value="classic">原味</option>
    <option value="choco">巧克力</option>
  </select><br><br>
  <label>數量：</label>
  <input type="number" name="qty" min="1" value="1" required><br><br>
  <button type="submit">送出訂單</button>
</form>
<p style="margin-top:1rem"><a href="/admin">（店員）管理頁</a></p>
""")

THANKS_HTML = Template("""
<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<title>已收到訂單</title>
<h2>感謝下單！</h2>
{% if o %}
<p>訂單編號：<b>#{{o["id"]}}</b> ｜ 口味：{{o["sku"]}} ｜ 數量：{{o["qty"]}}</p>
{% else %}
<p>找不到這筆訂單。</p>
{% endif %}
<p>您可以稍後再回到本頁查看，或至櫃檯詢問進度。</p>
<p><a href="/">回到點餐頁</a></p>
""")

ADMIN_HTML = Template("""
<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="3">
<title>管理</title>
<h2>目前訂單</h2>
<p>背景工人：<b>{{ '製作中' if is_running else '待命' }}</b></p>
<ol>
{% for o in orders %}
  <li>
    #{{o["id"]}} | {{o["sku"]}} x {{o["qty"]}} | {{o["ts"]}} |
    狀態：<b>{{o["status"]}}</b>
    {% if o.get("progress") is not none %}
      ｜ 進度：{{o["progress"]}}%
    {% endif %}
  </li>
{% endfor %}
</ol>
<p><a href="/">回點餐頁</a></p>
""")

# ─────────────────────────────────────────────
# 工具
# ─────────────────────────────────────────────
def _now(): return datetime.now().strftime("%H:%M:%S")

def _find(oid: int):
    with orders_lock:
        return next((o for o in orders if o["id"] == oid), None)

def _set(oid: int, **fields):
    with orders_lock:
        o = next((x for x in orders if x["id"] == oid), None)
        if o:
            o.update(fields)
            o["ts"] = _now()

# 模擬製作流程（把你的機器流程接進來即可）
def run_one_batch(order: dict):
    total_steps = random.randint(5, 8)
    for i in range(total_steps):
        time.sleep(1)
        prog = int((i + 1) / total_steps * 100)
        _set(order["id"], progress=prog)
    _set(order["id"], status="done", progress=100)

def worker():
    while not stop_event.is_set():
        try:
            oid = job_q.get(timeout=0.3)
        except queue.Empty:
            is_worker_running.clear()
            continue
        is_worker_running.set()
        _set(oid, status="processing", progress=0)
        od = _find(oid)
        try:
            if od: run_one_batch(od)
        except Exception as e:
            _set(oid, status=f"error: {e}")
        finally:
            job_q.task_done()
    is_worker_running.clear()

threading.Thread(target=worker, daemon=True).start()

# ─────────────────────────────────────────────
# 路由
# ─────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def index():
    return INDEX_HTML.render()

@app.post("/order")
def order(sku: str = Form(...), qty: int = Form(...)):
    with orders_lock:
        oid = (orders[0]["id"] + 1) if orders else 1
        orders.insert(0, {"id": oid, "sku": sku, "qty": int(qty),
                          "ts": _now(), "status": "queued", "progress": None})
    job_q.put(oid)
    return RedirectResponse(url=f"/thanks?oid={oid}", status_code=303)

@app.get("/thanks", response_class=HTMLResponse)
def thanks(oid: int):
    o = _find(oid)
    return THANKS_HTML.render(o=o)

# 未授權時回 401 HTML（不丟例外，避免 500）
@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    pw = request.query_params.get("pw")
    if pw != ADMIN_PASSWORD:
        msg = """
        <!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
        <h3>未授權 / Unauthorized</h3>
        <p>請在網址後加上 <code>?pw=你的密碼</code> 後再嘗試。</p>
        """
        return HTMLResponse(msg, status_code=401)
    with orders_lock:
        snapshot = list(orders)
    return ADMIN_HTML.render(orders=snapshot, is_running=is_worker_running.is_set())

@app.get("/api/orders")
def api_orders():
    with orders_lock:
        return JSONResponse(list(orders))

@app.on_event("shutdown")
def on_shutdown():
    stop_event.set()

# ─────────────────────────────────────────────
# 啟動
# ─────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
