#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETH 万亿战神 AI 量化交易引擎 - 深币 (Deepcoin) 核心通信客户端
架构基底: V7.2 生产环境终极修复版 (已切换至 /api/ 真实路径)
"""

import os
import time
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
        
        # 核心修复：确保使用官方推荐的 openapi 地址
        self.base_url = "https://openapi.deepcoin.com"

        if not self.api_key or not self.secret_key or not self.passphrase:
            logger.error("🚨 缺少深币 API 密钥！")

    def _get_timestamp(self):
        return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')

    def _sign(self, timestamp: str, method: str, request_path: str, body: str = ""):
        message = str(timestamp) + str(method.upper()) + str(request_path) + str(body)
        mac = hmac.new(bytes(self.secret_key, encoding='utf8'), bytes(message, encoding='utf-8'), digestmod='sha256')
        return base64.b64encode(mac.digest()).decode('utf-8')

    def _request(self, method: str, endpoint: str, params: dict = None):
        # 核心路径修复：所有 endpoint 统一指向 /api/ 开头的最新接口 [cite: 12]
        if not endpoint.startswith("/api/"):
            endpoint = endpoint.replace("/deepcoin/", "/api/")
            
        timestamp = self._get_timestamp()
        body_str = ""
        request_path = endpoint

        if method.upper() == "GET":
            if params:
                query_string = "&".join([f"{k}={v}" for k, v in params.items()])
                request_path = f"{endpoint}?{query_string}"
        else:
            if params:
                body_str = json.dumps(params, separators=(',', ':'))

        signature = self._sign(timestamp, method, request_path, body_str)
        headers = {
            "Content-Type": "application/json",
            "Deepcoin-Access-Key": self.api_key,
            "Deepcoin-Access-Sign": signature,
            "Deepcoin-Access-Timestamp": timestamp,
            "Deepcoin-Access-Passphrase": self.passphrase
        }

        try:
            url = f"{self.base_url}{request_path}"
            resp = requests.request(method.upper(), url, data=body_str if body_str else None, headers=headers, timeout=10)
            return resp.json()
        except Exception as e:
            return {"code": "-1", "msg": f"网络通信故障: {str(e)}"}

    def get_available_balance(self, ccy="USDT"):
        """获取可用余额 [cite: 12]"""
        res = self._request("GET", "/api/account/balances", {"ccy": ccy})
        try:
            # 根据最新透视数据解析，直接取 data 下的字段 [cite: 16]
            data = res.get("data", [])
            return float(data[0].get("availBal", 0)) if data else 0.0
        except: return 0.0

    def get_current_price(self, symbol="ETH-USDT-SWAP"):
        """获取实时盘口 [cite: 16]"""
        res = self._request("GET", "/api/market/ticker", {"instId": symbol})
        try:
            data = res.get("data", [])
            return float(data[0].get("last", 0)) if data else 0.0
        except: return 0.0

    def place_limit_order(self, symbol, side, price, amount, is_close=False):
        """标准下单接口 """
        ord_side = "buy" if side.upper() == "LONG" else "sell"
        params = {
            "instId": symbol,
            "tdMode": "cross",
            "side": ord_side,
            "ordType": "limit",
            "sz": str(int(amount)),
            "px": str(round(price, 2)),
            "posSide": "long" if side.upper() == "LONG" else "short",
            "mrgPosition": "merge"
        }
        if is_close: params["reduceOnly"] = "true"
        return self._request("POST", "/api/trade/order", params)

deepcoin_client = DeepcoinClient()
