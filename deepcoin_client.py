#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETH 万亿战神 - 深币驱动 V8.1 (补全仓位巡更与清场指令)
"""
import os
import hmac
import hashlib
import base64
import json
import logging
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

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
        if not endpoint.startswith("/deepcoin/"):
            endpoint = "/deepcoin" + (endpoint if endpoint.startswith("/") else "/" + endpoint)
        timestamp = self._get_timestamp()
        
        # 针对不同请求构造
        if method.upper() == "GET":
            query = f"?{'&'.join([f'{k}={v}' for k, v in params.items()])}" if params else ""
            request_path = endpoint + query
            body_str = ""
        else:
            body_str = json.dumps(params, separators=(',', ':')) if params else ""
            request_path = endpoint

        signature = self._sign(timestamp, method, request_path, body_str)
        headers = {
            "Content-Type": "application/json",
            "DC-ACCESS-KEY": self.api_key,
            "DC-ACCESS-SIGN": signature,
            "DC-ACCESS-TIMESTAMP": timestamp,
            "DC-ACCESS-PASSPHRASE": self.passphrase
        }
        try:
            resp = requests.request(method.upper(), self.base_url + request_path, data=body_str if body_str else None, headers=headers, timeout=10)
            return resp.json()
        except: return {"code": "-1"}

    # --- 新增核心驱动 ---
    def get_position_info(self, symbol):
        """巡更专用：查询当前持仓"""
        return self._request("GET", "/position/list", {"instId": symbol})

    def cancel_all_open_orders(self, symbol):
        """清场专用：撤销所有挂单"""
        return self._request("POST", "/trade/cancelBatchOrders", {"instId": symbol})

    def close_all_positions(self, symbol):
        """强平专用：一键平仓"""
        return self._request("POST", "/trade/closePosition", {"instId": symbol, "mrgPosition": "merge"})

    def get_available_balance(self, ccy="USDT"):
        res = self._request("GET", "/account/balances", {"instType": "SWAP"})
        try:
            return float(res["data"][0]["availBal"])
        except: return 0.0

    def get_current_price(self, symbol):
        res = self._request("GET", "/market/ticker", {"instId": symbol})
        try: return float(res["data"][0]["last"])
        except: return 0.0

    def place_limit_order(self, symbol, side, price, amount, is_close=False):
        params = {"instId": symbol, "tdMode": "cross", "side": "buy" if side.upper()=="LONG" else "sell", 
                  "ordType": "limit", "sz": str(int(amount)), "px": str(round(price, 2)), 
                  "posSide": "long" if side.upper()=="LONG" else "short", "mrgPosition": "merge"}
        if is_close: params["reduceOnly"] = True
        return self._request("POST", "/trade/order", params)

deepcoin_client = DeepcoinClient()
