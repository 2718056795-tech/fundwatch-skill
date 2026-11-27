# FundWatch Skill v0.2.0

面向 Muse / OpenMinis / 其他 AI Agent 的独立基金实时估值工具，无第三方基金平台会员，无付费 API Key，无作者后端依赖。Python 3.10+，标准库。

## Quick start

```bash
git clone https://github.com/2718056795-tech/fundwatch-skill.git
cd fundwatch-skill
python3 fundwatch.py 011609 --require-current
python3 fundwatch.py 011609 --require-live  # 仅交易时段
python3 fundwatch.py 011609 --watch 30
python3 -m unittest discover -s tests -v
```

**开放式基金盘中没有正式实时净值。** 通过原始行情实时查询估值，区分 provider_estimate、etf_proxy、index_proxy、official_nav；绝不把旧行情冒充实时。数据可能延迟、限流、变更或停止提供。退出码2代表未通过当前/实时数据时效验收。--watch 需要持续运行环境；也可由 Agent 调度器调用单次查询。

## 数据源

天天基金新版估值、新浪基金估值；腾讯、新浪、东方财富证券行情；东方财富正式净值双源。实时证券报价必须带实际行情时间戳。收盘估值必须在同日15:00以后。内置011609/011608目标ETF 588080、跟踪指数000688，0.95为模型假设，非真实当前仓位。其他基金可直接查询平台估值；代理模型需核实映射并通过 --models 提供。暂未实现主动基金自动持仓穿透或QDII跨市场模型。

## Agent 使用

参见 [SKILL.md](SKILL.md)、[数据源及技术参考](SOURCES.md)、[模型示例](models.example.json)、[持仓示例](portfolio.example.json)。持仓和历史日志仅保存在私有文件，切勿提交到公开仓库。禁止自动交易。

## 验收状态

2026-11-27：开发环境 DNS/网络限制导致直接原始行情请求失败，实盘端到端未验收。提供离线测试及真实行情验收指令，不将测试夹具冒充实时数据。上游行情遵守使用条款。MIT License。
