#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETH 万亿战神 AI 量化交易引擎 - 深币 (Deepcoin) 核心通信客户端
架构基底: V7.6 生产环境最终协议版 (已完全对齐 DC- 协议规范)
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

        if not self.api_key or not self.secret_key or not self.passphrase:
            logger.error("🚨 密钥配置不全，请检查 .env")

    def _get_timestamp(self):
        return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')

    def _sign(self, timestamp: str, method: str, request_path: str, body: str = ""):
        """避雷版签名：绕过系统 OpenSSL 策略限制"""
        message = (str(timestamp) + str(method.upper()) + str(request_path) + str(body)).encode('utf-8')
        h = hmac.new(self.secret_key.encode('utf-8'), message, hashlib.sha256)
        return base64.b64encode(h.digest()).decode('utf-8')

    def _request(self, method: str, endpoint: str, params: dict = None):
        # 确保路径规范：/deepcoin/ 开头
        if not endpoint.startswith("/deepcoin/"):
            endpoint = "/deepcoin" + (endpoint if endpoint.startswith("/") else "/" + endpoint)
            
        timestamp = self._get_timestamp()
        body_str = json.dumps(params, separators=(',', ':')) if params and method.upper() != "GET" else ""
        request_path = f"{endpoint}?{'&'.join([f'{k}={v}' for k, v in params.items()])}" if method.upper() == "GET" and params else endpoint

        signature = self._sign(timestamp, method, request_path, body_str)
        
        # 【核心修正】：深币强制要求 DC- 前缀的 Header 协议
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
            return {"code": "-1", "msg": f"网关通信失败: {str(e)}"}

    def get_available_balance(self, ccy="USDT"):
        """获取交易账户余额"""
        res = self._request("GET", "/account/balances", {"instType": "SWAP"})
        try:
            # 兼容深币多层 JSON 结构
            return float(res["data"][0]["availBal"])
        except: return 0.0

    def get_current_price(self, symbol="ETH-USDT-SWAP"):
        """获取盘口现价"""
        res = self._request("GET", "/market/ticker", {"instId": symbol})
        try:
            return float(res["data"][0]["last"])
        except: return 0.0

    def place_limit_order(self, symbol, side, price, amount, is_close=False):
        """标准限价下单"""
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
