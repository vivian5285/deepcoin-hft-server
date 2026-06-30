# 深币 Deepcoin · ETH 永续 Webhook 交易系统

**当前版本：`v13.4.3-ws-radar`**

TradingView Webhook → 深币 ETH-USDT-SWAP 永续合约自动化引擎。与币安 VPS 逻辑对齐，单位按 **张** 计算，钉钉为 **紫金主题**。

---

## VPS 部署信息

| 项目 | 值 |
|------|-----|
| 目录 | `~/deepcoin-hft-server` |
| 端口 | **5004** |
| 健康检查 | `GET /health` |
| 主日志 | `logs/deepcoin_brain.log` |
| 部署脚本 | `bash deploy_deepcoin.sh` |

---

## 系统架构

```
TradingView Webhook
        ↓
    app.py（网关，异步线程）
        ↓
position_supervisor_deepcoin.py（智慧大脑）
├── TV/开仓日志持久化
├── 重启闪电接管 + TV 对账
├── TP123 比例审计 + 增量/核武补挂
├── 雷达移动保本（WS 推价 + 条件止损）
└── 哨兵循环（持仓/人工异动/定期扫描）
        ↓
deepcoin_client.py（REST 交易 + 公开 WS 行情）
dingtalk.py（紫金钉钉播报）
```

---

## 核心能力（v13.4.x）

### 1. 重启闪电接管
- 读取 `deepcoin_vps_state.json` + **TV 日志** + **开仓日志**
- 对账：实盘方向 / 入场价 / 最新 TV 信号
- TP123 **价位 + 张数** 严格审计（regime 比例，余数吸收到 TP3）
- 已齐全 → **跳过补挂**；不齐 → 增量补挂 → 仍失败 → **核武清场重挂**

### 2. 限价止盈 TP123
- 比例随档位（regime 1~4）变化，例如 3 档：`18% / 32% / 50%`
- 不多挂、少挂、漏挂：审计不通过自动修复
- 重复单（如 TP1 叠 6 张）→ 核武级撤净重挂

### 3. 雷达移动保本
- 价格达 TP1 距离的 60%（3 档默认）→ 激活雷达
- 跟踪 `best_price`，ATR × 档位倍数推升/下压条件止损
- **WebSocket** 订阅 `market-latest`（ETHUSDT），REST 查价仅 ≥30s 兜底
- 推止损时只撤条件单，**TP123 保留**

### 4. 人工异动
- 手动加/减仓、部分止盈吃单 → 智能重对齐 TP 比例
- 人工全平 → 撤单、复位账本、钉钉通知
- 方向与 TV 背离 → 核武全平

### 5. 日志与审计
| 文件 | 说明 |
|------|------|
| `logs/deepcoin_tv_journal.jsonl` | 每条 TV 信号 |
| `logs/deepcoin_open_journal.jsonl` | 开仓 / 接管记录 |
| `logs/deepcoin_brain.log` | 大脑主日志 |
| `deepcoin_vps_state.json` | 运行时状态（自动生成） |

---

## 环境变量（`.env`）

```env
DEEPCOIN_API_KEY=
DEEPCOIN_API_SECRET=
DEEPCOIN_PASSPHRASE=
WEBHOOK_SECRET=528586
DINGTALK_WEBHOOK=
DINGTALK_SECRET=
FLASK_HOST=0.0.0.0
FLASK_PORT=5004
```

---

## TradingView Webhook

**URL：** `http://你的VPS:5004/webhook`

```json
{
  "action": "LONG",
  "secret": "528586",
  "regime": 3,
  "atr": 30.0,
  "price": 1560.0,
  "tv_tp1": 1580.0,
  "tv_tp2": 1600.0,
  "tv_tp3": 1620.0,
  "reason": "可选说明"
}
```

| action | 说明 |
|--------|------|
| `LONG` / `SHORT` | 先平后开 → 挂 TP123 → 启动哨兵 |
| `CLOSE` | 换防清场 |
| `CLOSE_PROTECT` | 保护性全平 |
| `CLOSE_TP3` | TP3 吃满收网 |

---

## 本地开发

```bash
pip install -r requirements.txt
python app.py
# 或
gunicorn --bind 0.0.0.0:5004 --workers 1 --threads 10 app:app
```

---

## VPS 部署（标准流程）

```bash
cd ~/deepcoin-hft-server
git fetch origin && git reset --hard origin/main

# 版本门控
grep v13.4.3-ws-radar deepcoin_client.py position_supervisor_deepcoin.py

bash deploy_deepcoin.sh

# 验收
tail -60 logs/deepcoin_brain.log
curl -s http://127.0.0.1:5004/health
```

**部署成功日志示例：**

```
🧠 深币 VPS [v13.4.3-ws-radar/...] 军师托管版已加载
📡 深币公开 WS 启动: ETHUSDT market-latest
🔄 [系统重启点火] 检测到实盘持仓 ...
✅TP1 1张@1537.85 | ✅TP2 ... | ✅TP3 ...
```

---

## 与币安系统区别

| 项目 | 深币 | 币安 |
|------|------|------|
| 单位 | 张 | ETH |
| 端口 | 5004 | 5003 |
| 钉钉主题 | 紫金 | 黄金 |
| 止损类型 | 条件单 trigger | STOP_MARKET |
| WS 频道 | market-latest | markPrice@1s |

---

## 注意事项

1. 部署务必 `git reset --hard origin/main`，避免 VPS 残留旧代码。
2. 重启后看钉钉「闪电接管报告」，TP 应为 **3/3 比例审计全绿**。
3. 实盘前确认 `.env` 与 Deepcoin API 权限（合约读写）正确。
4. 仅同时持有一个方向仓位；新 TV 信号触发 **先平后开**。

---

*Quant AI · 深币紫金趋势大波段引擎*
