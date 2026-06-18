#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETH 万亿战神 AI 量化交易引擎 - 深币 (Deepcoin) V8.0 限价刺客版
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
        self.base_url = "https://api.deepcoin.com"

        if not self.api_key or not self.secret_key or not self.passphrase:
            logger.error("🚨 缺少深币 API 密钥！")

    def _get_timestamp(self):
        return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')

    def _sign(self, timestamp: str, method: str, request_path: str, body: str = ""):
        message = str(timestamp) + str(method.upper()) + str(request_path) + str(body)
        mac = hmac.new(
            bytes(self.secret_key, encoding='utf8'),
            bytes(message, encoding='utf-8'),
            digestmod='sha256'
        )
        return base64.b64encode(mac.digest()).decode('utf-8')

    def _request(self, method: str, endpoint: str, params: dict = None):
        if params is None: params = {}
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
        url = f"{self.base_url}{request_path}"
        try:
            if method.upper() == "GET":
                resp = requests.get(url, headers=headers, timeout=10)
            else:
                resp = requests.request(method.upper(), url, data=body_str, headers=headers, timeout=10)
            return resp.json()
        except Exception as e:
            logger.error(f"网络通信层异常: {e}")
            return {"code": "-1", "msg": f"网络异常: {str(e)}"}

    def get_available_balance(self, ccy="USDT"):
        res = self._request("GET", "/deepcoin/account/balance", {"ccy": ccy})
        try:
            data = res.get("data", [])
            if data and len(data) > 0:
                details = data[0].get("details", [])
                if details: return float(details[0].get("availBal", 0))
            return 0.0
        except: return 0.0

    def get_current_price(self, symbol="ETH-USDT-SWAP"):
        res = self._request("GET", "/deepcoin/market/ticker", {"instId": symbol})
        try:
            data = res.get("data", [])
            if data and len(data) > 0: return float(data[0].get("last", 0))
            return 0.0
        except: return 0.0

    def get_position_info(self, symbol="ETH-USDT-SWAP"):
        return self._request("GET", "/deepcoin/account/positions", {"instType": "SWAP", "instId": symbol})

    # ==================== V8.0 核心重构：开仓与只减仓(ReduceOnly)融为一体 ====================
    def place_limit_order(self, symbol, side, price, amount, is_close=False):
        """
        is_close=False -> 正常开仓
        is_close=True  -> 限价止盈单 (强制 reduceOnly=true，防反向对冲)
        """
        if not is_close:
            ord_side = "buy" if side.upper() == "LONG" else "sell"
            pos_side = "long" if side.upper() == "LONG" else "short"
            params = {
                "instId": symbol,
                "tdMode": "cross",
                "side": ord_side,          
                "ordType": "limit",        
                "sz": str(int(amount)),    
                "px": str(round(price, 2)),
                "posSide": pos_side,       
                "mrgPosition": "merge"     
            }
            logger.info(f"⚔️ 发起开仓限价单: {ord_side} {amount}张 @ {price}")
        else:
            # 止盈单：方向相反，但 posSide 必须指向原来的仓位方向！
            ord_side = "sell" if side.upper() == "LONG" else "buy"
            pos_side = "long" if side.upper() == "LONG" else "short"
            params = {
                "instId": symbol,
                "tdMode": "cross",
                "side": ord_side,          
                "ordType": "limit",        
                "sz": str(int(amount)),    
                "px": str(round(price, 2)),
                "posSide": pos_side,
                "reduceOnly": "true"       # 核心防线：绝对不增新仓！
            }
            logger.info(f"🎯 发起止盈限价单: {ord_side} {amount}张 @ {price} (ReduceOnly保护)")

        return self._request("POST", "/deepcoin/trade/order", params)

    def cancel_all_open_orders(self, symbol="ETH-USDT-SWAP"):
        params = {
            "InstrumentID": symbol.replace("-SWAP", "").replace("-", ""),
            "ProductGroup": "SwapU",
            "IsCrossMargin": 1,
            "IsMergeMode": 1
        }
        return self._request("POST", "/deepcoin/trade/swap/cancel-all", params)

    def close_all_positions(self, symbol="ETH-USDT-SWAP"):
        params = {
            "productGroup": "SwapU",
            "instId": symbol
        }
        return self._request("POST", "/deepcoin/trade/batch-close-position", params)

deepcoin_client = DeepcoinClient()
