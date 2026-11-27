# 数据源与实现参考

本项目独立编写，直接请求公开行情源；不调用下列 GitHub 作者的私有服务、CLI、MCP 或 Supabase。没有付费 API Key 要求不等于永久免费、可无限调用或授权商业使用。遵守上游条款，遇限流降低频率，遇认证要求停止。

## 原始行情
- 天天基金新版 FundValuationLast: FCODES / FIELDS; 直接估值（并非每只基金都覆盖）。
- 新浪基金 FdFundService.getEstimateNetworthPic: 两种估值曲线，growthrate 是比例，需要乘100转换为百分比。
- 东方财富 pingzhongdata 与 FundMNHisNetList: 正式历史净值，日期校验。
- 腾讯 qt.gtimg.cn: 国内证券实时行情，价格/昨收/行情时间。
- 新浪 hq.sinajs.cn: 国内证券行情，日期+时间。
- 东方财富 push2.eastmoney.com/api/qt/stock/get: f43/f60 价格、昨收，f86 时间戳；不接受无时间戳的报价。
- 证券行情可能延迟；严格读取源时间戳，盘中最大年龄默认90秒。

## GitHub 参考（技术路线与公开接口）
- https://github.com/hzm0321/real-time-fund/blob/main/app/api/fund.js : 新版天天基金和新浪双估值源、正式净值。
- https://github.com/Ye-Yu-Mo/FundVal-Live/blob/main/backend/api/sources/eastmoney.py : 历史净值多数据源。
- https://github.com/Ye-Yu-Mo/FundVal-Live/blob/main/backend/api/sources/penetration_engine.py : 证券行情穿透估值思路。
- https://github.com/x2rr/funds : 基金持仓和估值功能参考。
- https://github.com/hkwuks/WealthAgent : ETF/指数分类估值策略参考。

011609 的目标 ETF 588080、跟踪指数 000688；0.95 是明确的近似权重，不是当前基金仓位实测值。ETF 市场价格可能存在折溢价，不等于基金份额净值。新增基金需要验证映射。无已验证持仓/指数映射时不盲目推算。

## 验收状态
2026-11-27：当前开发网络对原始行情地址出现 DNS/访问失败，未完成实盘端到端验收。仓库包含离线测试和真实接口验收命令；成功通过离线测试不代表真实行情接口可用。
