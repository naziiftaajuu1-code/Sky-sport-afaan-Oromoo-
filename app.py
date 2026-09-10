import os, time, json, asyncio, logging, hashlib, hmac, html, re
from datetime import datetime, timezone
from urllib.parse import parse_qsl
from xml.etree import ElementTree as ET

import aiohttp
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import uvicorn

logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO"))
log=logging.getLogger("sky-sport")

BOT_TOKEN=os.environ["BOT_TOKEN"]
WEB_APP_URL=os.getenv("WEB_APP_URL","https://t.me/sky_sport_afaan_oromoo_bot/sky_sporti")
FEED_URL=os.getenv("FEED_URL","https://sky-sporti-afaan-oromoo.blogspot.com/feeds/posts/default?alt=rss&max-results=20")
PUBLIC_BASE_URL=os.getenv("PUBLIC_BASE_URL","").rstrip("/")
ADMIN_SECRET=os.getenv("ADMIN_SECRET","")
POLL_SECONDS=int(os.getenv("POLL_SECONDS","3600"))
HTTP_TIMEOUT=int(os.getenv("HTTP_TIMEOUT","20"))
MAX_POSTS=int(os.getenv("MAX_POSTS","20"))
DB_FILE=os.getenv("DB_FILE","sky_sport_state.json")

app=FastAPI(title="Sky Sport Afaan Oromoo Telegram Backend", version="14.0")

state={"subscribers":[], "seen":[]}
lock=asyncio.Lock()

def load_state():
    global state
    try:
        with open(DB_FILE,"r",encoding="utf-8") as f:
            x=json.load(f)
            if isinstance(x,dict):
                state.update(x)
    except FileNotFoundError:
        pass
    except Exception:
        log.exception("state load failed")

def save_state():
    tmp=DB_FILE+".tmp"
    with open(tmp,"w",encoding="utf-8") as f:
        json.dump(state,f,ensure_ascii=False)
    os.replace(tmp,DB_FILE)

async def tg(method, payload=None, timeout=20):
    url=f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    for attempt in range(4):
        try:
            timeout_obj=aiohttp.ClientTimeout(total=timeout)
            async with aiohttp.ClientSession(timeout=timeout_obj) as s:
                async with s.post(url,json=payload or {}) as r:
                    data=await r.json(content_type=None)
                    if r.status == 429:
                        retry=int(data.get("parameters",{}).get("retry_after",2))
                        await asyncio.sleep(min(retry,30))
                        continue
                    if r.status >= 500:
                        await asyncio.sleep(2**attempt)
                        continue
                    return data
        except (aiohttp.ClientError, asyncio.TimeoutError):
            if attempt==3: raise
            await asyncio.sleep(2**attempt)
    return {"ok":False}

def validate_init_data(init_data:str):
    if not init_data: return None
    pairs=dict(parse_qsl(init_data,keep_blank_values=True))
    received=pairs.pop("hash",None)
    if not received: return None
    data_check="\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret=hmac.new(b"WebAppData",BOT_TOKEN.encode(),hashlib.sha256).digest()
    calc=hmac.new(secret,data_check.encode(),hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc,received): return None
    try:
        auth=int(pairs.get("auth_date","0"))
        if abs(time.time()-auth)>86400: return None
    except Exception: return None
    user=json.loads(pairs.get("user","{}"))
    return user if user.get("id") else None

async def fetch_feed():
    timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
    async with aiohttp.ClientSession(timeout=timeout,headers={"User-Agent":"SkySportBot/14"}) as s:
        async with s.get(FEED_URL) as r:
            r.raise_for_status()
            return await r.text()

def parse_feed(xml):
    root=ET.fromstring(xml)
    items=[]
    for item in root.findall(".//item")[:MAX_POSTS]:
        def txt(tag):
            x=item.find(tag)
            return (x.text or "").strip() if x is not None else ""
        title=txt("title"); link=txt("link"); guid=txt("guid") or link
        desc=re.sub("<[^>]+>"," ",txt("description"))
        desc=re.sub(r"\s+"," ",desc).strip()
        pub=txt("pubDate")
        if title and link:
            items.append({"id":guid,"title":title,"link":link,"description":desc[:500],"published":pub})
    return items

async def notify_new_posts():
    xml=await fetch_feed()
    posts=parse_feed(xml)
    async with lock:
        seen=set(state["seen"])
        new=[p for p in reversed(posts) if p["id"] not in seen]
        # First run: mark existing posts without broadcasting.
        if not seen:
            state["seen"]=[p["id"] for p in posts][:200]
            save_state()
            return {"new":0,"subscribers":len(state["subscribers"]),"bootstrap":True}
        state["seen"]=(list(dict.fromkeys(state["seen"]+[p["id"] for p in posts])))[:200]
        subs=list(dict.fromkeys(state["subscribers"]))
        save_state()
    sent=0; removed=[]
    for p in new:
        msg=f"⚽ <b>SKY SPORTS AFAAN OROMOO</b>\n\n<b>{html.escape(p['title'])}</b>"
        if p["description"]: msg+=f"\n\n{html.escape(p['description'][:400])}"
        msg+=f"\n\n🔗 <a href=\"{html.escape(p['link'],quote=True)}\">Oduu guutuu dubbisi</a>"
        for chat_id in subs:
            try:
                res=await tg("sendMessage",{"chat_id":chat_id,"text":msg,"parse_mode":"HTML","disable_web_page_preview":False})
                if res.get("ok"): sent+=1
                elif res.get("error_code")==403: removed.append(chat_id)
            except Exception:
                log.exception("send failed chat=%s",chat_id)
    if removed:
        async with lock:
            state["subscribers"]=[x for x in state["subscribers"] if x not in removed]
            save_state()
    return {"new":len(new),"sent":sent,"removed":len(removed)}

async def poll_loop():
    await asyncio.sleep(10)
    while True:
        try:
            await notify_new_posts()
        except Exception:
            log.exception("hourly feed check failed")
        await asyncio.sleep(max(POLL_SECONDS,300))

@app.on_event("startup")
async def startup():
    load_state()
    asyncio.create_task(poll_loop())

@app.get("/")
async def root():
    return {"ok":True,"service":"sky-sport-telegram","version":"14.0"}

@app.get("/health")
async def health():
    return {"ok":True,"subscribers":len(state["subscribers"]),"seen":len(state["seen"])}

@app.post("/telegram/webhook")
async def webhook(request:Request):
    update=await request.json()
    msg=update.get("message") or update.get("edited_message")
    if msg:
        chat=msg.get("chat",{})
        chat_id=chat.get("id")
        text=(msg.get("text") or "").strip()
        if chat_id and text.startswith("/start"):
            async with lock:
                if chat_id not in state["subscribers"]:
                    state["subscribers"].append(chat_id)
                    state["subscribers"]=state["subscribers"][-10000:]
                    save_state()
            await tg("sendMessage",{"chat_id":chat_id,
                "text":"⚽ <b>SKY SPORTS AFAAN OROMOO</b>\\n\\nOduu taphaa, xinxala, transfer fi seenaa kubbaa miilaa Afaan Oromootiin.\\n\\n👇 App keenya bani:",
                "parse_mode":"HTML",
                "reply_markup":{"inline_keyboard":[[{"text":"🚀 OPEN SKY SPORT","web_app":{"url":WEB_APP_URL}}]]}})
        elif chat_id and text.startswith("/stop"):
            async with lock:
                state["subscribers"]=[x for x in state["subscribers"] if x!=chat_id]
                save_state()
            await tg("sendMessage",{"chat_id":chat_id,"text":"Beeksisa haaraa irraa baateetta. /start jechuun deebitee galuu dandeessa."})
    return {"ok":True}

@app.post("/miniapp/register")
async def miniapp_register(request:Request):
    body=await request.json()
    user=validate_init_data(body.get("initData",""))
    if not user: raise HTTPException(401,"Invalid Telegram initData")
    cid=int(user["id"])
    async with lock:
        if cid not in state["subscribers"]:
            state["subscribers"].append(cid)
            state["subscribers"]=state["subscribers"][-10000:]
            save_state()
    return {"ok":True,"user_id":cid}

@app.post("/admin/check")
async def admin_check(request:Request):
    if not ADMIN_SECRET or request.headers.get("x-admin-secret")!=ADMIN_SECRET:
        raise HTTPException(403,"Forbidden")
    return await notify_new_posts()

if __name__=="__main__":
    uvicorn.run(app,host="0.0.0.0",port=int(os.getenv("PORT","10000")))
