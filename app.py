from fastapi import FastAPI, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from jinja2 import Template
from datetime import datetime
import uvicorn, threading, queue, time, random, os

app = FastAPI()

# 密碼設定（上雲後你可改這裡）
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "eggadmin")

orders = []
orders_lock = threading.Lock()
job_q = queue.Queue()
is_worker_running = threading.Event()
stop_event = threading.Event()

INDEX_HTML = Template("""
<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<title>點餐</title>
<h2>雞蛋糕點餐 🍰</h2>
<form method="post" action="/order">
  <label>口味：</label>
  <select name="sku">
    <option value="classic">原味</option>
    <option value="choco">巧克力</option>
  </select><br><br>
  <label>數量：</label>
  <input type="number" name="qty" min="1" value="1" required><br><br>
  <button type="submit">送出</button>
</form>
<p style="margin-top:1rem"><a href="/admin">管理頁</a></p>
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
    #{{o["id"]}} | {{o["sku"]}} x {{o["qty"]}} | {{o["ts"]}} | 狀態：<b>{{o["status"]}}</b>
    {% if o.get("progress") is not none %}
      ｜ 進度：{{o["progress"]}}%
    {% endif %}
  </li>
{% endfor %}
</ol>
<p><a href="/">回點餐頁</a></p>
""")

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
    return RedirectResponse(url="/admin?pw=" + ADMIN_PASSWORD, status_code=303)

@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    pw = request.query_params.get("pw")
    if pw != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="請輸入正確密碼：在網址加上 ?pw=你的密碼")
    with orders_lock:
        snapshot = list(orders)
    return ADMIN_HTML.render(orders=snapshot, is_running=is_worker_running.is_set())

@app.get("/api/orders")
def api_orders():
    with orders_lock:
        return JSONResponse(list(orders))

@app.on_event("shutdown")
def on_shutdown(): stop_event.set()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
