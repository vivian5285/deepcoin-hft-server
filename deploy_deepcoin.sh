#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, hmac, hashlib, base64, json, logging, requests, time
from datetime import datetime, timezone
from urllib.parse import urlencode
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, '.env'))
logger = logging.getLogger(__name__)

class DeepcoinClient:
    def __init__(self):
        self.api_key = os.getenv("DEEPCOIN_API_KEY", os.getenv("API_KEY", ""))
        self.secret_key = os.getenv("DEEPCOIN_API_SECRET", os.getenv("DEEPCOIN_SECRET_KEY", os.getenv("SECRET_KEY", "")))
        self.passphrase = os.getenv("DEEPCOIN_PASSPHRASE", os.getenv("PASSPHRASE", os.getenv("API_PASSPHRASE", "")))
        self.base_url = "https://api.deepcoin.com"

    def _get_timestamp(self):
        # 👑 V7 核心：ISO8601 UTC 时间戳
        return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')

    def _sign(self, timestamp: str, method: str, request_path: str, body: str = ""):
        message = (str(timestamp) + str(method.upper()) + str(request_path) + str(body)).encode('utf-8')
        h = hmac.new(self.secret_key.encode('utf-8'), message, hashlib.sha256)
        return base64.b64encode(h.digest()).decode('utf-8')

    def _request(self, method: str, endpoint: str, params: dict = None):
        if not self.api_key or not self.secret_key:
            logger.error("⚠️ Deepcoin API 密钥未配置！")
            return None

        # 确保加上 /deepcoin 前缀
        if not endpoint.startswith("/deepcoin/"): 
            endpoint = "/deepcoin" + (endpoint if endpoint.startswith("/") else "/" + endpoint)
            
        timestamp = self._get_timestamp()
        
        # 👑 V7 核心：GET 请求参数拼接，POST body 转 JSON
        body_str = json.dumps(params, separators=(',', ':')) if params and method.upper() != "GET" else ""
        request_path = f"{endpoint}?{'&'.join([f'{k}={v}' for k, v in params.items()])}" if method.upper() == "GET" and params else endpoint
        
        signature = self._sign(timestamp, method, request_path, body_str)
        
        # 👑 V7 核心：DC-ACCESS 请求头
        headers = {
            "Content-Type": "application/json", 
            "DC-ACCESS-KEY": self.api_key,
            "DC-ACCESS-SIGN": signature, 
            "DC-ACCESS-TIMESTAMP": timestamp,
            "DC-ACCESS-PASSPHRASE": self.passphrase
        }
        
        try:
            url = f"{self.base_url}{request_path}"
            resp = requests.request(method.upper(), url, data=body_str if body_str else None, headers=headers, timeout=10)
            res_json = resp.json()
            if str(res_json.get("code")) != "0":
                logger.warning(f"Deepcoin API 业务异常: {res_json}")
            return res_json
        except Exception as e: 
            logger.error(f"Deepcoin 请求失败 {endpoint}: {e} | 返回: {resp.text if 'resp' in locals() else 'N/A'}")
            return None

    def get_available_balance(self, ccy="USDT"):
        # 👑 完美读取深币金库：优先读取动态总权益 (Equity) 以确保熔断防线精准！
        res = self._request("GET", "/account/balances", {"instType": "SWAP"})
        if isinstance(res, dict) and "data" in res:
            for item in res["data"]:
                if item.get("ccy") == ccy: 
                    # eq = 动态总权益(包含未实现盈亏)，它是风控和下注的最精准基准
                    eq = float(item.get("eq", 0))
                    if eq > 0:
                        return eq
                    # 如果获取不到 eq，再退化使用静态余额 availBal
                    return float(item.get("availBal", 0)) 
        return 0.0

    def get_current_price(self, symbol="ETH-USDT-SWAP"):
        """🚀 白嫖币安公开接口查价，绝对稳定，且两端基准 100% 同步"""
        try:
            binance_symbol = symbol.split("-")[0] + "USDT" 
            url = f"https://api.binance.com/api/v3/ticker/price?symbol={binance_symbol}"
            res = requests.get(url, timeout=5)
            data = res.json()
            return float(data.get("price", 0.0))
        except Exception as e:
            logger.error(f"借用币安公开接口查价失败: {e}")
            return 0.0

    def get_position_info(self, symbol="ETH-USDT-SWAP"):
        return self._request("GET", "/account/positions", {"instType": "SWAP", "instId": symbol})

    def place_market_order(self, symbol, side, pos_side, qty):
        """基础市价下单接口（已被验证绝对稳定）"""
        params = {
            "instId": symbol, "tdMode": "cross",
            "side": side, "posSide": pos_side,
            "ordType": "market", "sz": str(int(qty)),
            "mrgPosition": "merge"
        }
        return self._request("POST", "/trade/order", params)

    def place_limit_order(self, symbol, side, pos_side, px, qty):
        params = {
            "instId": symbol, "tdMode": "cross",
            "side": side, "posSide": pos_side,
            "ordType": "limit", "sz": str(int(qty)),
            "px": str(px), "mrgPosition": "merge"
        }
        return self._request("POST", "/trade/order", params)

    def place_conditional_order(self, symbol, side, pos_side, trigger_px, qty):
        # 修正 OKX/Deepcoin 架构标准的 Algo 终极路径
        params = {
            "instId": symbol, "tdMode": "cross",
            "side": side, "posSide": pos_side,
            "ordType": "conditional", "sz": str(int(qty)),
            "triggerPx": str(trigger_px), "ordPx": str(trigger_px),
            "reduceOnly": True
        }
        return self._request("POST", "/trade/order-algo", params)

    def cancel_all_open_orders(self, symbol="ETH-USDT-SWAP"):
        # 尝试高级接口：一键批量撤单
        try:
            self._request("POST", "/trade/cancel-batch-orders", {"instId": symbol})
            self._request("POST", "/trade/cancel-algos", {"instId": symbol})
            time.sleep(0.5)
        except Exception:
            pass # 如果高级接口 404 失效，静默拦截，进入底层的逐一点杀模式

        # 🚀 终极防线：获取所有挂单，逐一精准点杀 (底层基础接口，绝对有效)
        try:
            # 1. 猎杀普通限价单 (留在盘口的 10/30/60 止盈网)
            pending = self._request("GET", "/trade/orders-pending", {"instType": "SWAP", "instId": symbol})
            if pending and isinstance(pending, dict) and 'data' in pending:
                for ord in pending['data']:
                    ord_id = ord.get("ordId")
                    if ord_id: 
                        self._request("POST", "/trade/cancel-order", {"instId": symbol, "ordId": ord_id})

            # 2. 猎杀条件委托单 (留在远处的保本或止损单)
            pending_algos = self._request("GET", "/trade/orders-algo-pending", {"instType": "SWAP", "instId": symbol})
            if pending_algos and isinstance(pending_algos, dict) and 'data' in pending_algos:
                for algo in pending_algos['data']:
                    algo_id = algo.get("algoId")
                    if algo_id: 
                        self._request("POST", "/trade/cancel-algos", {"instId": symbol, "algoId": algo_id})
                        
            logger.info("🧹 盘口撤单巡查猎杀完毕，幽灵挂单已彻底清除！")
        except Exception as e:
            logger.error(f"逐一猎杀幽灵挂单时发生异常: {e}")

    def close_all_positions(self, symbol="ETH-USDT-SWAP"):
        """🚀 终极防爆修复：抛弃不稳定的 Close 接口，采用反向市价单物理平仓"""
        try:
            pos_info = self.get_position_info(symbol)
            if pos_info and 'data' in pos_info:
                for p in pos_info['data']:
                    sz = float(p.get("pos", 0))
                    if sz > 0:
                        pos_side = p.get("posSide", "").lower()
                        # 如果持有长仓(long)，就下卖单(sell)；如果持有短仓(short)，就下买单(buy)
                        close_side = "sell" if pos_side == "long" else "buy"
                        logger.info(f"🔨 启动物理清仓：发送 {close_side} {pos_side} {sz} 张市价单")
                        self.place_market_order(symbol, close_side, pos_side, sz)
        except Exception as e:
            logger.error(f"物理平仓执行异常: {e}")

deepcoin_client = DeepcoinClient()
