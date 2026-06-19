#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, hmac, hashlib, base64, json, logging, requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

class DeepcoinClient:
    def __init__(self):
        self.api_key = os.getenv("DEEPCOIN_API_KEY")
        self.secret_key = os.getenv("DEEPCOIN_API_SECRET")
        self.passphrase = os.getenv("DEEPCOIN_PASSPHRASE")
        self.base_url = "https://api.deepcoin.com"

    def _get_timestamp(self):
        return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')

    def _sign(self, timestamp: str, method: str, request_path: str, body: str = ""):
        message = (str(timestamp) + str(method.upper()) + str(request_path) + str(body)).encode('utf-8')
        h = hmac.new(self.secret_key.encode('utf-8'), message, hashlib.sha256)
        return base64.b64encode(h.digest()).decode('utf-8')

    def _request(self, method: str, endpoint: str, params: dict = None):
        if not endpoint.startswith("/deepcoin/"): endpoint = "/deepcoin" + (endpoint if endpoint.startswith("/") else "/" + endpoint)
        timestamp = self._get_timestamp()
        body_str = json.dumps(params, separators=(',', ':')) if params and method.upper() != "GET" else ""
        request_path = f"{endpoint}?{'&'.join([f'{k}={v}' for k, v in params.items()])}" if method.upper() == "GET" and params else endpoint
        signature = self._sign(timestamp, method, request_path, body_str)
        
        headers = {
            "Content-Type": "application/json", "DC-ACCESS-KEY": self.api_key,
            "DC-ACCESS-SIGN": signature, "DC-ACCESS-TIMESTAMP": timestamp,
            "DC-ACCESS-PASSPHRASE": self.passphrase
        }
        try:
            url = f"{self.base_url}{request_path}"
            resp = requests.request(method.upper(), url, data=body_str if body_str else None, headers=headers, timeout=10)
            return resp.json()
        except: return {"code": "-1"}

    def get_available_balance(self, ccy="USDT"):
        res = self._request("GET", "/account/balances", {"instType": "SWAP"})
        try:
            if isinstance(res, dict) and "data" in res:
                for item in res["data"]:
                    if item.get("ccy") == ccy: return float(item.get("availBal", 0))
            return 0.0
        except: return 0.0

    def get_current_price(self, symbol="ETH-USDT-SWAP"):
        """🚀 借用币安公有接口获取现价 (免鉴权、极速、防404)"""
        try:
            res = requests.get("https://fapi.binance.com/fapi/v1/ticker/price?symbol=ETHUSDT", timeout=3)
            if res.status_code == 200:
                return float(res.json()["price"])
            return 0.0
        except Exception as e:
            return 0.0

    def get_position_info(self, symbol="ETH-USDT-SWAP"):
        return self._request("GET", "/account/positions", {"instType": "SWAP", "instId": symbol})

    def place_market_order(self, symbol, side, pos_side, amount):
        params = {
            "instId": symbol, "tdMode": "cross",
            "side": side, "posSide": pos_side,
            "ordType": "market", "sz": str(int(amount)),
            "mrgPosition": "merge"
        }
        return self._request("POST", "/trade/order", params)

    def place_limit_order(self, symbol, side, pos_side, price, amount):
        params = {
            "instId": symbol, "tdMode": "cross",
            "side": side, "posSide": pos_side,
            "ordType": "limit", "sz": str(int(amount)),
            "px": str(round(price, 2)), "mrgPosition": "merge"
        }
        return self._request("POST", "/trade/order", params)

    def place_conditional_order(self, symbol, side, pos_side, trigger_price, amount):
        """🚀 升级为原生市价条件单止损，誓死保证成交"""
        params = {
            "instId": symbol, "productGroup": "Swap",
            "sz": str(int(amount)), "side": side, "posSide": pos_side,
            "isCrossMargin": "1", "orderType": "market", 
            "triggerPrice": str(round(trigger_price, 2)),
            "mrgPosition": "merge", "tdMode": "cross"
        }
        return self._request("POST", "/trade/trigger-order", params)

    def cancel_all_open_orders(self, symbol="ETH-USDT-SWAP"):
        inst_id_base = symbol.replace("-SWAP", "").replace("-", "") # 转换成 ETHUSDT
        p1 = {"InstrumentID": inst_id_base, "ProductGroup": "SwapU", "IsCrossMargin": 1, "IsMergeMode": 1}
        self._request("POST", "/trade/swap/cancel-all", p1)
        self._request("POST", "/trade/swap/cancel-trigger-all", p1)

    def close_all_positions(self, symbol="ETH-USDT-SWAP"):
        return self._request("POST", "/trade/close-position", {"instId": symbol, "mrgPosition": "merge"})

deepcoin_client = DeepcoinClient()
