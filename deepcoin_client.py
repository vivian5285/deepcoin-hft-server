#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETH 万亿战神 AI 量化交易引擎 - 深币 (Deepcoin) 核心通信客户端
架构基底: V8.5 智慧驱动版 (完美适配 DC- 鉴权协议，包含条件止损指令)
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
            logger.error("🚨 缺少深币 API 密钥！")

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
        body_str = json.dumps(params, separators=(',', ':')) if params and method.upper() != "GET" else ""
        request_path = f"{endpoint}?{'&'.join([f'{k}={v}' for k, v in params.items()])}" if method.upper() == "GET" and params else endpoint

        signature = self._sign(timestamp, method, request_path, body_str)
        
        # 已验证成功的 DC- 协议标准
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
            if isinstance(res, dict) and "data" in res:
                for item in res["data"]:
                    if item.get("ccy") == ccy:
                        return float(item.get("availBal", 0))
            return 0.0
        except: return 0.0

    def get_current_price(self, symbol="ETH-USDT-SWAP"):
        """精准盘口读取（容错版）"""
        try:
            res = self._request("GET", "/market/ticker", {"instId": symbol})
            if isinstance(res, dict) and "data" in res and len(res["data"]) > 0:
                price = res["data"][0].get("last")
                return float(price) if price else 0.0
            return 0.0
        except: return 0.0

    def get_position_info(self, symbol="ETH-USDT-SWAP"):
        """获取真实持仓"""
        return self._request("GET", "/account/positions", {"instType": "SWAP", "instId": symbol})

    def place_limit_order(self, symbol, side, price, amount, is_close=False):
        """标准限价单（用于建仓和限价止盈）"""
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

    def place_conditional_order(self, symbol, side, trigger_price, amount):
        """计划委托条件单（用于限价止损）"""
        params = {
            "instId": symbol,
            "tdMode": "cross",
            "side": "buy" if side.upper() == "LONG" else "sell",
            "ordType": "conditional",
            "sz": str(int(amount)),
            "triggerPx": str(round(trigger_price, 2)),
            "ordPx": str(round(trigger_price, 2)), # 触发后以该价格挂单
            "posSide": "long" if side.upper() == "LONG" else "short",
            "reduceOnly": True
        }
        return self._request("POST", "/trade/order/algo", params)

    def cancel_all_open_orders(self, symbol="ETH-USDT-SWAP"):
        """一键撤销所有挂单（包含普通单和条件单）"""
        # 深币撤销所有未成交
        res1 = self._request("POST", "/trade/cancel-batch-orders", {"instId": symbol})
        # 撤销所有计划委托(止盈止损)
        res2 = self._request("POST", "/trade/cancel-algo-orders", {"instId": symbol})
        return res1

    def close_all_positions(self, symbol="ETH-USDT-SWAP"):
        """市价一键全平"""
        params = {"instId": symbol, "mrgPosition": "merge"}
        return self._request("POST", "/trade/close-position", params)

deepcoin_client = DeepcoinClient()
