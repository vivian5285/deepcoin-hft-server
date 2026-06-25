#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, hmac, hashlib, base64, json, logging, requests, time
from datetime import datetime, timezone
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, '.env'))
logger = logging.getLogger(__name__)

class DeepcoinClient:
    def __init__(self):
        self.api_key = os.getenv("DEEPCOIN_API_KEY", "")
        self.secret_key = os.getenv("DEEPCOIN_API_SECRET", "")
        self.passphrase = os.getenv("DEEPCOIN_PASSPHRASE", "")
        self.base_url = "https://api.deepcoin.com"

    def _get_timestamp(self):
        return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')

    def _sign(self, timestamp: str, method: str, request_path: str, body: str = ""):
        message = (str(timestamp) + str(method.upper()) + str(request_path) + str(body)).encode('utf-8')
        h = hmac.new(self.secret_key.encode('utf-8'), message, hashlib.sha256)
        return base64.b64encode(h.digest()).decode('utf-8')

    def _request(self, method: str, endpoint: str, params: dict = None):
        if not self.api_key or not self.secret_key:
            return None
        if not endpoint.startswith("/deepcoin/"): 
            endpoint = "/deepcoin" + (endpoint if endpoint.startswith("/") else "/" + endpoint)
            
        timestamp = self._get_timestamp()
        body_str = json.dumps(params, separators=(',', ':')) if params and method.upper() != "GET" else ""
        request_path = f"{endpoint}?{'&'.join([f'{k}={v}' for k, v in params.items()])}" if method.upper() == "GET" and params else endpoint
        signature = self._sign(timestamp, method, request_path, body_str)
        
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
            return resp.json()
        except Exception as e: 
            logger.error(f"Deepcoin 请求失败 {endpoint}: {e}")
            return None

    def get_available_balance(self, ccy="USDT"):
        res = self._request("GET", "/account/balances", {"instType": "SWAP"})
        if isinstance(res, dict) and "data" in res:
            for item in res["data"]:
                if item.get("ccy") == ccy: 
                    eq = float(item.get("eq", 0))
                    return eq if eq > 0 else float(item.get("availBal", 0)) 
        return 0.0

    def get_current_price(self, symbol="ETH-USDT-SWAP"):
        try:
            binance_symbol = symbol.split("-")[0] + "USDT" 
            res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={binance_symbol}", timeout=5)
            return float(res.json().get("price", 0.0))
        except: return 0.0

    def get_position_info(self, symbol="ETH-USDT-SWAP"):
        return self._request("GET", "/account/positions", {"instType": "SWAP", "instId": symbol})

    # 🚀 极其关键：支持 reduce_only 护甲
    def place_market_order(self, symbol, side, pos_side, qty, reduce_only=False):
        params = {
            "instId": symbol, "tdMode": "cross", "side": side, "posSide": pos_side,
            "ordType": "market", "sz": str(int(qty)), "mrgPosition": "merge"
        }
        if reduce_only: params["reduceOnly"] = True #
        return self._request("POST", "/trade/order", params)

    def place_limit_order(self, symbol, side, pos_side, px, qty, reduce_only=False):
        params = {
            "instId": symbol, "tdMode": "cross", "side": side, "posSide": pos_side,
            "ordType": "limit", "sz": str(int(qty)), "px": str(px), "mrgPosition": "merge"
        }
        if reduce_only: params["reduceOnly"] = True #[cite: 16]
        return self._request("POST", "/trade/order", params)

    # 🚀 极其关键：双轨绝杀撤单（同步猎杀 Algo 条件单和普通限价单）
    def cancel_all_open_orders(self, symbol="ETH-USDT-SWAP"):
        try:
            self._request("POST", "/trade/cancel-batch-orders", {"instId": symbol})
            self._request("POST", "/trade/cancel-algos", {"instId": symbol})
            time.sleep(0.3)
            # 逐点猎杀普通限价单
            pending = self._request("GET", "/trade/orders-pending", {"instType": "SWAP", "instId": symbol})
            if pending and 'data' in pending:
                for ord in pending['data']:
                    if ord.get("ordId"): self._request("POST", "/trade/cancel-order", {"instId": symbol, "ordId": ord.get("ordId")})
            # 逐点猎杀条件止损单[cite: 16]
            pending_algos = self._request("GET", "/trade/orders-algo-pending", {"instType": "SWAP", "instId": symbol})
            if pending_algos and 'data' in pending_algos:
                for algo in pending_algos['data']:
                    if algo.get("algoId"): self._request("POST", "/trade/cancel-algos", {"instId": symbol, "algoId": algo.get("algoId")})
        except Exception as e: logger.error(f"撤单异常: {e}")

deepcoin_client = DeepcoinClient()
