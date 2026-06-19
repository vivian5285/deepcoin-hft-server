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
        try:
            res = self._request("GET", "/market/ticker", {"instId": symbol})
            if isinstance(res, dict) and "data" in res and len(res["data"]) > 0:
                price = res["data"][0].get("last")
                return float(price) if price else 0.0
            return 0.0
        except: return 0.0

    def get_position_info(self, symbol="ETH-USDT-SWAP"):
        return self._request("GET", "/account/positions", {"instType": "SWAP", "instId": symbol})

    def place_market_order(self, symbol, side, amount):
        params = {
            "instId": symbol, "tdMode": "cross",
            "side": "buy" if side.upper() == "LONG" else "sell",
            "ordType": "market", "sz": str(int(amount)),
            "posSide": "long" if side.upper() == "LONG" else "short",
            "mrgPosition": "merge"
        }
        return self._request("POST", "/trade/order", params)

    def place_limit_order(self, symbol, side, price, amount, is_close=False):
        params = {
            "instId": symbol, "tdMode": "cross",
            "side": "buy" if side.upper() == "LONG" else "sell",
            "ordType": "limit", "sz": str(int(amount)),
            "px": str(round(price, 2)),
            "posSide": "long" if side.upper() == "LONG" else "short",
            "mrgPosition": "merge"
        }
        if is_close: params["reduceOnly"] = True
        return self._request("POST", "/trade/order", params)

    def place_conditional_order(self, symbol, side, trigger_price, amount):
        """🚀 补丁2：深币硬止损优化，给予 5U 穿透让步，誓死保证止损成交"""
        ord_px = trigger_price - 5.0 if side.upper() == "SELL" else trigger_price + 5.0
        params = {
            "instId": symbol, "tdMode": "cross",
            "side": "buy" if side.upper() == "LONG" else "sell",
            "ordType": "conditional", "sz": str(int(amount)),
            "triggerPx": str(round(trigger_price, 2)), 
            "ordPx": str(round(ord_px, 2)),
            "posSide": "long" if side.upper() == "LONG" else "short", 
            "reduceOnly": True
        }
        return self._request("POST", "/trade/order/algo", params)

    def cancel_all_open_orders(self, symbol="ETH-USDT-SWAP"):
        self._request("POST", "/trade/cancel-batch-orders", {"instId": symbol})
        return self._request("POST", "/trade/cancel-algo-orders", {"instId": symbol})

    def close_all_positions(self, symbol="ETH-USDT-SWAP"):
        return self._request("POST", "/trade/close-position", {"instId": symbol, "mrgPosition": "merge"})

deepcoin_client = DeepcoinClient()
