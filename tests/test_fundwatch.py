import datetime as dt
import json
import unittest
import fundwatch as f

def t(h,m,s=0):
    return dt.datetime(2026,11,27,h,m,s,tzinfo=f.CN)

class FreshnessTests(unittest.TestCase):
    def test_stale_1342_after_close(self):
        self.assertEqual(f.freshness(t(13,42).isoformat(),t(18,48)), "stale")
    def test_1459_not_close(self):
        self.assertEqual(f.freshness(t(14,59,59).isoformat(),t(18,48)), "stale")
    def test_close(self):
        self.assertEqual(f.freshness(t(15,0,3).isoformat(),t(18,48)), "close_estimate")
    def test_live(self):
        self.assertEqual(f.freshness(t(14,1).isoformat(),t(14,2)), "live_estimate")
    def test_expired(self):
        self.assertEqual(f.freshness(t(14,0).isoformat(),t(14,2)), "stale")
    def test_date_only_not_live(self):
        self.assertEqual(f.freshness("2026-11-27",t(14,2)), "unavailable")
    def test_future(self):
        self.assertEqual(f.freshness(t(14,5).isoformat(),t(14,2)), "stale")
    def test_weekend(self):
        now=t(14,2)+dt.timedelta(days=1)
        self.assertEqual(f.freshness(now.isoformat(),now), "stale")

class ParserTests(unittest.TestCase):
    def test_tencent(self):
        fields=[""]*33
        fields[3]="1346.25";fields[4]="1169.99";fields[30]="20261127150003"
        q=f.parse_tencent('v_sh000688="'+ "~".join(fields)+'";')[0]
        self.assertAlmostEqual(q["rate_pct"],15.064,places=2)
        self.assertEqual(q["asof"],t(15,0,3).isoformat())
    def test_sina_quote(self):
        fields=[""]*33
        fields[2]="1";fields[3]="1.1";fields[30]="2026-11-27";fields[31]="15:00:00"
        q=f.parse_sina_quote('var hq_str_sh588080="'+",".join(fields)+'";')[0]
        self.assertAlmostEqual(q["rate_pct"],10)
    def test_eastmoney(self):
        raw=json.dumps({"data":{"f57":"588080","f43":1.1,"f60":1,"f86":int(t(15,0).timestamp())}})
        self.assertAlmostEqual(f.parse_em_quote(raw,"sh588080")[0]["rate_pct"],10)
    def test_sina_growth_units(self):
        data={"result":{"data":{"networth":[{"pre_date":"2026-11-27","min_time":"15:00","growthrate":0.1,"pre_nav":1.1}]}}}
        self.assertAlmostEqual(f.parse_sina_fund("fundwatch("+json.dumps(data)+");")[0]["rate_pct"],10)
    def test_missing_not_zero(self):
        self.assertIsNone(f.num(None))
        self.assertIsNone(f.num(float("nan")))
        self.assertEqual(f.parse_tencent(""),[])
    def test_jsonp_not_eval(self):
        with self.assertRaises(ValueError):
            f.payload("evil();")

class ModelsTests(unittest.TestCase):
    def setUp(self):
        self.nav={"date":"2026-11-26","nav":1}
        self.spec=f.DEFAULT_MODELS["011609"]
        self.q=f.quote("tencent_quote","sh000688",t(15,0,3),110,100)
    def test_index_fallback(self):
        r,_=f.model_estimate(self.spec,[self.q],self.nav,t(18,48),90)
        self.assertEqual(r["kind"],"index_proxy")
        self.assertAlmostEqual(r["rate_pct"],9.5)
        self.assertAlmostEqual(r["nav"],1.095)
    def test_etf_priority(self):
        etf=f.quote("tencent_quote","sh588080",t(15,0,3),1.12,1)
        r,_=f.model_estimate(self.spec,[self.q,etf],self.nav,t(18,48),90)
        self.assertEqual(r["kind"],"etf_proxy")
        self.assertAlmostEqual(r["rate_pct"],11.4)
    def test_stale_etf_falls_back(self):
        etf=f.quote("tencent_quote","sh588080",t(13,42),1.12,1)
        r,_=f.model_estimate(self.spec,[self.q,etf],self.nav,t(18,48),90)
        self.assertEqual(r["kind"],"index_proxy")
    def test_disagreement_rejects(self):
        other=f.quote("sina_quote","sh000688",t(15,0,3),120,100)
        r,err=f.model_estimate(self.spec,[self.q,other],self.nav,t(18,48),90)
        self.assertIsNone(r)
        self.assertIn("disagree",err)
    def test_old_baseline(self):
        r,_=f.model_estimate(self.spec,[self.q],{"date":"2026-11-25","nav":1},t(18,48),90)
        self.assertIsNone(r)
    def test_all_network_errors(self):
        def request(*args):
            raise OSError("offline fixture")
        r=f.query(["011609"],f.DEFAULT_MODELS,{},request=request,clock=lambda:t(18,48))
        self.assertEqual(r["funds"][0]["status"],"unavailable")
        self.assertIsNone(r["funds"][0]["nav"])
    def test_end_to_end_fallback(self):
        def request(url,*args):
            if "FundMNHisNetList" in url:
                return json.dumps({"Datas":[{"FSRQ":"2026-11-26","DWJZ":"1.0"}]})
            if "qt.gtimg.cn" in url:
                fields=[""]*33
                fields[3]="110";fields[4]="100";fields[30]="20261127150003"
                return 'v_sh000688="'+ "~".join(fields)+'";'
            raise OSError("offline fixture")
        out=f.query(["011609"],f.DEFAULT_MODELS,{"011609":{"shares":1000,"cost_total":900}},request=request,clock=lambda:t(18,48))
        r=out["funds"][0]
        self.assertEqual(r["status"],"close_estimate")
        self.assertEqual(r["kind"],"index_proxy")
        self.assertAlmostEqual(r["position"]["day_pnl"],95)
    def test_pnl(self):
        self.assertEqual(f.position_values({"shares":1000,"cost_total":900},1.1,1)["day_pnl"],100)

if __name__=="__main__":
    unittest.main()
