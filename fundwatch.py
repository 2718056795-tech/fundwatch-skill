#!/usr/bin/env python3
"""FundWatch 0.2: independent, read-only CN fund valuation. Python 3.10+."""
from __future__ import annotations
import argparse
import concurrent.futures as cf
import datetime as dt
import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

VERSION = "0.2.0"
CN = dt.timezone(dt.timedelta(hours=8))
CODE = re.compile(r"[0-9]{6}")
SYMBOL = re.compile(r"(sh|sz)[0-9]{6}")
TIANTIAN = "https://fundcomapi.tiantianfunds.com/mm/newCore/FundValuationLast"
SINA_FUND = "https://stock.finance.sina.com.cn/fundInfo/api/openapi.php/FdFundService.getEstimateNetworthPic"
EM_NAV = "https://fund.eastmoney.com/pingzhongdata/"
EM_MOBILE_NAV = "https://fundmobapi.eastmoney.com/FundMNewApi/FundMNHisNetList"
EM_QUOTE = "https://push2.eastmoney.com/api/qt/stock/get"
TENCENT = "https://qt.gtimg.cn/q="
SINA_QUOTE = "https://hq.sinajs.cn/list="
# Explicit mapping; weight is benchmark assumption, NOT verified current holding.
DEFAULT_MODELS = {
    "011609": {"name": "易方达上证科创50ETF联接C", "etf": "sh588080", "index": "sh000688", "weight": 0.95},
    "011608": {"name": "易方达上证科创50ETF联接A", "etf": "sh588080", "index": "sh000688", "weight": 0.95},
}
CURRENT = {"live_estimate", "lunch_estimate", "close_estimate", "official_today"}


def now_cn():
    return dt.datetime.now(CN)


def num(x):
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (ValueError, TypeError, OverflowError):
        return None


def positive(x):
    n = num(x)
    return n if n is not None and n > 0 else None


def stamp(s):
    s = str(s).strip()
    if len(s) <= 10:
        return None
    try:
        d = dt.datetime.fromisoformat(s)
        return d.astimezone(CN) if d.tzinfo else d.replace(tzinfo=CN)
    except ValueError:
        pass
    for fmt in ("%Y%m%d%H%M%S", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
        try:
            return dt.datetime.strptime(s, fmt).replace(tzinfo=CN)
        except ValueError:
            pass
    return None


def date(s):
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def epoch(s, divisor=1):
    n = num(s)
    if n is None or n <= 0:
        return None
    try:
        return dt.datetime.fromtimestamp(n/divisor, CN)
    except (OSError, ValueError, OverflowError):
        return None


def url(base, **params):
    return base + "?" + urllib.parse.urlencode(params)


def get(u, timeout=6, referer=None):
    headers = {"User-Agent": "Mozilla/5.0 FundWatch/0.2", "Accept": "*/*", "Cache-Control": "no-cache"}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(u, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read(16_000_001)
        enc = r.headers.get_content_charset()
    if len(raw) > 16_000_000:
        raise ValueError("response too large")
    for codec in (enc, "utf-8-sig", "gb18030"):
        if codec:
            try:
                return raw.decode(codec)
            except (UnicodeError, LookupError):
                pass
    raise ValueError("unknown charset")


def payload(s):
    s = s.strip().lstrip("\ufeff")
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        m = re.fullmatch(r"[\w.$]+\s*\(\s*(.*)\s*\)\s*;?", s, re.S)
        if not m:
            raise ValueError("not JSON or JSONP")
        return json.loads(m[1])


def market_phase(now):
    if now.weekday() >= 5:
        return "weekend"
    t = now.time()
    if t < dt.time(9,30):
        return "pre_open"
    if t <= dt.time(11,30):
        return "morning"
    if t < dt.time(13):
        return "lunch"
    if t < dt.time(15):
        return "afternoon"
    return "after_close"


def freshness(asof, now, max_age=90):
    t = stamp(asof)
    if not t:
        return "unavailable"
    if t.date() != now.date() or (t-now).total_seconds() > 30:
        return "stale"
    p = market_phase(now)
    clock = t.time()
    if p in ("morning", "afternoon"):
        start = dt.time(9,30) if p == "morning" else dt.time(13)
        if clock >= start and (now-t).total_seconds() <= max_age:
            return "live_estimate"
    elif p == "lunch" and dt.time(11,30) <= clock <= dt.time(11,35):
        return "lunch_estimate"
    elif p == "after_close" and dt.time(15) <= clock <= dt.time(15,30):
        return "close_estimate"
    return "stale"


def record(source, t, rate=None, nav=None, kind="provider_estimate", **extra):
    return {"source": source, "asof": t.isoformat() if isinstance(t, dt.datetime) else t,
            "rate_pct": num(rate), "nav": positive(nav), "kind": kind, **extra}


def parse_tiantian(raw, codes):
    obj = payload(raw)
    if obj.get("success") is not True or not isinstance(obj.get("data"), list):
        raise ValueError("Tiantian refused or invalid schema")
    result = {}
    for r in obj["data"]:
        c = str(r.get("FCODE"))
        if c not in codes:
            continue
        d = date(r.get("PDATE"))
        nav = positive(r.get("NAV"))
        result[c] = {"name": r.get("SHORTNAME") or c,
                     "estimate": record("tiantian", stamp(r.get("GZTIME")), r.get("GSZZL"), r.get("GSZ")),
                     "official": [{"date": d.isoformat(), "nav": nav, "rate_pct": None, "source": "tiantian_nav"}] if d and nav else []}
    return result


def parse_sina_fund(raw):
    points = payload(raw)["result"]["data"]["networth"]
    result = []
    for suffix in ("", "2"):
        candidates = []
        for p in points:
            t = stamp(str(p.get("pre_date", "")) + " " + str(p.get("min_time", "")))
            rate = num(p.get("growthrate" + suffix))
            nav = positive(p.get("pre_nav" + suffix))
            if t and (rate is not None or nav is not None):
                candidates.append(record("sina_fund" + (suffix or "1"), t, rate*100 if rate is not None else None, nav))
        if candidates:
            result.append(max(candidates, key=lambda x:x["asof"]))
    return result


def parse_nav(raw):
    m = re.search(r"\bData_netWorthTrend\s*=\s*", raw)
    if not m:
        raise ValueError("missing NAV history")
    rows, _ = json.JSONDecoder().raw_decode(raw[m.end():].lstrip())
    result = []
    for p in rows:
        t = epoch(p.get("x"), 1000)
        v = positive(p.get("y"))
        if t and v:
            result.append({"date":t.date().isoformat(), "nav":v, "rate_pct":num(p.get("equityReturn")), "source":"eastmoney_nav"})
    return sorted(result, key=lambda x:x["date"])[-3:]


def parse_mobile_nav(raw):
    result = []
    for p in payload(raw).get("Datas") or []:
        d, v = date(p.get("FSRQ")), positive(p.get("DWJZ"))
        if d and v:
            result.append({"date":d.isoformat(), "nav":v, "rate_pct":num(p.get("JZZZL")), "source":"eastmoney_mobile_nav"})
    if not result:
        raise ValueError("no mobile NAV data")
    return result


def quote(source, symbol, t, price, previous):
    price, previous = positive(price), positive(previous)
    if not (t and price and previous):
        return None
    return record(source, t, (price/previous-1)*100, kind="market_quote",
                  symbol=symbol, price=price, previous_close=previous)


def parse_tencent(raw):
    result = []
    for sym, body in re.findall(r'v_((?:sh|sz)[0-9]{6})\s*=\s*"([^"]*)"', raw):
        f = body.split("~")
        if len(f) > 30:
            q = quote("tencent_quote", sym, stamp(f[30]), f[3], f[4])
            if q:
                result.append(q)
    return result


def parse_sina_quote(raw):
    result = []
    for sym, body in re.findall(r'hq_str_((?:sh|sz)[0-9]{6})\s*=\s*"([^"]*)"', raw):
        f = body.split(",")
        if len(f) > 31:
            q = quote("sina_quote", sym, stamp(f[30]+" "+f[31]), f[3], f[2])
            if q:
                result.append(q)
    return result


def parse_em_quote(raw, sym):
    d = payload(raw).get("data")
    if not isinstance(d, dict) or str(d.get("f57")) != sym[2:]:
        raise ValueError("invalid Eastmoney quote")
    # fltt=2 asks for decimal prices. Ratio works also if both have same scale.
    q = quote("eastmoney_quote", sym, epoch(d.get("f86")), d.get("f43"), d.get("f60"))
    return [q] if q else []


def valid_code(c):
    if not isinstance(c, str) or not CODE.fullmatch(c):
        raise ValueError("invalid six-digit fund code")
    return c


def previous_weekday(d):
    d -= dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def model_spec(spec):
    if not isinstance(spec, dict):
        raise ValueError("model must be an object")
    w = num(spec.get("weight"))
    if w is None or not 0 < w <= 1:
        raise ValueError("weight must be in (0,1]")
    for k in ("etf", "index"):
        if spec.get(k) and not SYMBOL.fullmatch(spec[k]):
            raise ValueError("invalid domestic ETF/index symbol")
    if not (spec.get("etf") or spec.get("index")):
        raise ValueError("ETF or index required")
    return {**spec, "weight":w}


def status(r, now, max_age):
    if r.get("rate_pct") is None and r.get("nav") is None:
        return "unavailable"
    return freshness(r.get("asof"), now, max_age)


def best_quote(quotes, sym, now, age):
    valid = [q for q in quotes if q["symbol"] == sym and status(q,now,age) in CURRENT]
    if not valid:
        return None, None
    valid.sort(key=lambda q:q["asof"], reverse=True)
    # Reject conflicting fresh prices, not merely pick convenient result.
    fresh_rates = [q["rate_pct"] for q in valid]
    if max(fresh_rates)-min(fresh_rates) > 0.5:
        return None, "fresh quote providers disagree by >0.5 percentage points for "+sym
    return valid[0], None


def model_estimate(spec, quotes, nav, now, age):
    if not nav or date(nav["date"]) != previous_weekday(now.date()):
        return None, "proxy requires previous weekday official NAV (holiday gaps not inferred)"
    errors = []
    for kind in ("etf","index"):
        sym = spec.get(kind)
        if not sym:
            continue
        q, err = best_quote(quotes,sym,now,age)
        if err:
            errors.append(err)
        if q:
            rate = q["rate_pct"]*spec["weight"]
            return record(q["source"], q["asof"], rate, nav["nav"]*(1+rate/100),
                          "etf_proxy" if kind=="etf" else "index_proxy",
                          symbol=sym, weight=spec["weight"], raw_market_rate_pct=q["rate_pct"],
                          raw_market_price=q["price"], previous_close=q["previous_close"],
                          assumption="weight is a configured proxy; remaining allocation assumed flat; not ETF iNAV"), "; ".join(errors) or None
    return None, "; ".join(errors) or "no fresh ETF/index quote"


def position_values(p, nav, base):
    shares = num(p.get("shares"))
    cost = num(p.get("cost_total"))
    if shares is None or shares < 0 or (cost is not None and cost < 0):
        raise ValueError("invalid shares or cost_total")
    mv = shares*nav if nav is not None else None
    return {"shares":shares, "market_value":round(mv,2) if mv is not None else None,
            "day_pnl":round(shares*(nav-base),2) if nav is not None and base is not None else None,
            "holding_pnl":round(mv-cost,2) if mv is not None and cost is not None else None}


def query(codes, models, positions, timeout=6, max_age=90, request=get, clock=now_cn):
    codes = list(dict.fromkeys(valid_code(c) for c in codes))
    if not codes:
        raise ValueError("at least one fund code required")
    errors = {c:[] for c in codes}
    navs = {c:[] for c in codes}
    estimates = {c:[] for c in codes}
    names = {}
    quotes = []
    symbols = sorted({s for c in codes if c in models for s in (models[c].get("etf"),models[c].get("index")) if s})
    jobs = []
    with cf.ThreadPoolExecutor(max_workers=8) as pool:
        def submit(kind, ids, u, parser, referer=None):
            jobs.append((kind, ids, pool.submit(lambda: parser(request(u, timeout, referer)))))
        for i in range(0,len(codes),50):
            chunk=codes[i:i+50]
            submit("tiantian",chunk,url(TIANTIAN,FCODES=",".join(chunk),FIELDS="FCODE,SHORTNAME,GSZZL,GZTIME,GSZ,NAV,PDATE"),lambda s, cc=set(chunk):parse_tiantian(s,cc))
        for c in codes:
            submit("sina_fund",[c],url(SINA_FUND,symbol=c,callback="fundwatch"),parse_sina_fund)
            submit("nav",[c],EM_NAV+c+".js",parse_nav)
            submit("mobile_nav",[c],url(EM_MOBILE_NAV,FCODE=c,pageIndex=1,pageSize=3,plat="Wap",product="EFund",version="2.0.0",deviceid="Wap"),parse_mobile_nav)
        for i in range(0,len(symbols),30):
            syms=symbols[i:i+30]
            ids=[c for c in codes if c in models and any(s in syms for s in (models[c].get("etf"),models[c].get("index")))]
            submit("quote",ids,TENCENT+",".join(syms),parse_tencent)
            submit("quote",ids,SINA_QUOTE+",".join(syms),parse_sina_quote,"https://finance.sina.com.cn/")
        for sym in symbols:
            ids=[c for c in codes if c in models and sym in (models[c].get("etf"),models[c].get("index"))]
            secid=("1." if sym.startswith("sh") else "0.")+sym[2:]
            submit("quote",ids,url(EM_QUOTE,secid=secid,fields="f43,f57,f60,f86",fltt=2),lambda s, sy=sym:parse_em_quote(s,sy))
        for kind,ids,future in jobs:
            try:
                result=future.result()
                if kind=="tiantian":
                    for c, r in result.items():
                        names[c]=r["name"]; navs[c]+=r["official"]; estimates[c].append(r["estimate"])
                elif kind=="sina_fund":
                    estimates[ids[0]]+=result
                elif kind in ("nav","mobile_nav"):
                    navs[ids[0]]+=result
                else:
                    quotes+=result
            except (OSError,ValueError,TypeError,KeyError,AttributeError) as e:
                for c in ids:
                    errors[c].append(kind+": "+type(e).__name__+": "+str(e)[:240])
    now=clock()
    rows=[]
    for c in codes:
        spec=models.get(c)
        all_nav=[n for n in navs[c] if date(n["date"]) and date(n["date"])<=now.date()]
        by_day={}
        for n in all_nav:
            old=by_day.get(n["date"])
            if old is None or (old["rate_pct"] is None and n["rate_pct"] is not None):
                by_day[n["date"]]=n
        ns=sorted(by_day.values(),key=lambda n:n["date"])
        n=ns[-1] if ns else None
        base=None
        warnings=[]
        candidates=estimates[c][:]
        if spec:
            m,err=model_estimate(spec,quotes,n,now,max_age)
            if m:
                candidates.append(m)
            if err:
                warnings.append(err)
        for r in candidates:
            r["status"]=status(r,now,max_age)
        # Valid provider first, then ETF, then index; freshest within each type.
        live=[r for r in candidates if r["status"] in CURRENT]
        live.sort(key=lambda r:r["asof"] or "",reverse=True)
        live.sort(key=lambda r:{"provider_estimate":0,"etf_proxy":1,"index_proxy":2}.get(r["kind"],3))
        chosen=None
        if n and n["date"]==now.date().isoformat():
            chosen=record(n["source"],n["date"],n["rate_pct"],n["nav"],"official_nav")
            chosen["status"]="official_today"
            if len(ns)>1 and date(ns[-2]["date"])==previous_weekday(now.date()) and n["rate_pct"] is not None and abs((n["nav"]/ns[-2]["nav"]-1)*100-n["rate_pct"])<=0.1:
                base=ns[-2]["nav"]
        elif live:
            chosen=dict(live[0])
            if n and date(n["date"])==previous_weekday(now.date()) and chosen["rate_pct"] is not None:
                implied=n["nav"]*(1+chosen["rate_pct"]/100)
                if chosen["nav"] is None:
                    chosen["nav"]=implied
                if abs(chosen["nav"]-implied)<=max(0.001,n["nav"]*0.001):
                    base=n["nav"]
                else:
                    warnings.append("estimate and NAV baseline inconsistent; day P&L withheld")
            if chosen["kind"]!="provider_estimate":
                warnings.append("market-price/benchmark proxy, not actual intraday fund NAV")
            rates=[r["rate_pct"] for r in live if r["rate_pct"] is not None]
            if rates and max(rates)-min(rates)>0.5:
                warnings.append("current valuation candidates differ by >0.5 percentage points")
        elif n:
            chosen=record(n["source"],n["date"],None,n["nav"],"official_nav")
            chosen["status"]="latest_official_only"
            warnings.append("NO current intraday estimate; official NAV is historical")
        else:
            chosen=record(None,None)
            chosen["status"]="unavailable"
        if base is None:
            warnings.append("daily P&L withheld: prior official NAV or return not verified")
        row={"code":c,"name":names.get(c) or (spec or {}).get("name") or c,
             **chosen,"baseline_nav":base,"official_nav":n,"candidates":candidates,
             "market_quotes":[{**q,"status":status(q,now,max_age)} for q in quotes if spec and q["symbol"] in (spec.get("etf"),spec.get("index"))],
             "warnings":warnings,"errors":errors[c]}
        if c in positions:
            row["position"]=position_values(positions[c],chosen["nav"],base)
        rows.append(row)
    held=[r["position"] for r in rows if "position" in r]
    summary={"position_count":len(held)}
    for k in ("market_value","day_pnl","holding_pnl"):
        values=[p[k] for p in held if p[k] is not None]
        summary[k]=round(sum(values),2) if values else None
        summary[k+"_known_count"]=len(values)
        summary[k+"_complete"]=bool(held) and len(values)==len(held)
    return {"version":VERSION,"queried_at":now.isoformat(),"market_phase_cn":market_phase(now),
            "exchange_calendar_verified":False,"funds":rows,"portfolio":summary}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("codes",nargs="*")
    p.add_argument("--models",type=Path,help="private JSON code-to-ETF/index/weight mappings")
    p.add_argument("--portfolio",type=Path,help="private JSON with positions list: code, shares, cost_total")
    p.add_argument("--watch",type=int,help="poll every N seconds (minimum 30)")
    p.add_argument("--timeout",type=float,default=6)
    p.add_argument("--max-age",type=int,default=90)
    p.add_argument("--require-current",action="store_true")
    p.add_argument("--require-live",action="store_true")
    p.add_argument("--history",type=Path,help="append private JSONL snapshots")
    p.add_argument("--compare",action="store_true",help="compatibility flag; all sources already compared")
    p.add_argument("--version",action="version",version=VERSION)
    a=p.parse_args(argv)
    if not 0<a.timeout<=30 or not 30<=a.max_age<=300 or (a.watch is not None and a.watch<30):
        p.error("timeout 0..30, max-age 30..300, watch >=30")
    if a.watch and (a.require_current or a.require_live):
        p.error("require flags are for one-shot mode")
    try:
        models={k:model_spec(v) for k,v in DEFAULT_MODELS.items()}
        if a.models:
            models.update({valid_code(k):model_spec(v) for k,v in json.loads(a.models.read_text(encoding="utf-8")).items()})
        positions={}
        if a.portfolio:
            for pos in json.loads(a.portfolio.read_text(encoding="utf-8"))["positions"]:
                c=valid_code(pos["code"])
                if c in positions:
                    raise ValueError("duplicate position; aggregate shares first")
                positions[c]=pos
        codes=list(dict.fromkeys(a.codes+list(positions)))
        if not codes:
            p.error("provide fund code(s) or portfolio")
        while True:
            start=time.monotonic()
            out=query(codes,models,positions,a.timeout,a.max_age)
            line=json.dumps(out,ensure_ascii=False,allow_nan=False)
            if a.history:
                a.history.parent.mkdir(parents=True,exist_ok=True)
                with a.history.open("a",encoding="utf-8") as f:
                    f.write(line+"\n")
            print(line if a.watch else json.dumps(out,ensure_ascii=False,allow_nan=False,indent=2),flush=True)
            if not a.watch:
                if a.require_live:
                    return 2 if any(r["status"]!="live_estimate" for r in out["funds"]) else 0
                if a.require_current:
                    return 2 if any(r["status"] not in CURRENT for r in out["funds"]) else 0
                return 0
            time.sleep(max(0,a.watch-(time.monotonic()-start)))
    except KeyboardInterrupt:
        return 0
    except (OSError,ValueError,KeyError,TypeError) as e:
        print(json.dumps({"error":str(e)},ensure_ascii=False),file=sys.stderr)
        return 1


if __name__=="__main__":
    raise SystemExit(main())
