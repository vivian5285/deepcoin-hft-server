#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETH 万亿战神 AI 量化交易引擎 - 深币 (Deepcoin) 核心通信客户端
架构基底: V7.7 最终胜利版 (已完美适配 DC- 鉴权协议与 100U 余额读取)
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
        # 补全路径
        if not endpoint.startswith("/deepcoin/"):
            endpoint = "/deepcoin" + (endpoint if endpoint.startswith("/") else "/" + endpoint)
            
        timestamp = self._get_timestamp()
        body_str = json.dumps(params, separators=(',', ':')) if params and method.upper() != "GET" else ""
        request_path = f"{endpoint}?{'&'.join([f'{k}={v}' for k, v in params.items()])}" if method.upper() == "GET" and params else endpoint

        signature = self._sign(timestamp, method, request_path, body_str)
        
        # 使用验证成功的 DC- Header 协议
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
            logger.error(f"网关通信故障: {e}")
            return {"code": "-1"}

    def get_available_balance(self, ccy="USDT"):
        """精准读取余额"""
        res = self._request("GET", "/account/balances", {"instType": "SWAP"})
        try:
            # 这里的解析逻辑已经验证成功
            for item in res.get("data", []):
                if item.get("ccy") == ccy:
                    return float(item.get("availBal", 0))
            return 0.0
        except: return 0.0

    def get_current_price(self, symbol="ETH-USDT-SWAP"):
        """获取盘口价格"""
        res = self._request("GET", "/market/ticker", {"instId": symbol})
        try:
            return float(res["data"][0]["last"])
        except: return 0.0

    def place_limit_order(self, symbol, side, price, amount, is_close=False):
        """标准下单"""
        params = {
            "instId": symbol,
            "tdMode": "cross",
            "side": "buy" if side.upper() == "LONG" else "sell",
            "ordType": "limit",
            "sz": str(int(amount)),
            "px": str(round(price, 2)),
            "posSide": "long" if side.upper() == "LONG" else "short",
            "mrgPosition": "merge"
        }
        if is_close: params["reduceOnly"] = True
        return self._request("POST", "/trade/order", params)

deepcoin_client = DeepcoinClient()
