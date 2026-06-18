#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETH 万亿战神 AI 量化交易引擎 - 深币 (Deepcoin) 私有核心通信客户端
架构基底: V7.1 终极修复版 (已切换至 openapi 真实网关)
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

# 加载环境变数
load_dotenv()
logger = logging.getLogger(__name__)

class DeepcoinClient:
    def __init__(self):
        self.api_key = os.getenv("DEEPCOIN_API_KEY")
        self.secret_key = os.getenv("DEEPCOIN_API_SECRET")
        self.passphrase = os.getenv("DEEPCOIN_PASSPHRASE")  # 深币专属的三重加密机制
        
        # 👑 核心修复：更换为深币真正的 API 访问入口
        self.base_url = "https://openapi.deepcoin.com"

        if not self.api_key or not self.secret_key or not self.passphrase:
            logger.error("🚨 缺少深币 API 密钥！请检查 .env 文件中的 DEEPCOIN_API_KEY, SECRET 和 PASSPHRASE")

    def _get_timestamp(self):
        """生成符合 Deepcoin/OKX 标准的 ISO8601 时间戳"""
        return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')

    def _sign(self, timestamp: str, method: str, request_path: str, body: str = ""):
        """Deepcoin 核心 HMAC-SHA256 签名算法"""
        message = str(timestamp) + str(method.upper()) + str(request_path) + str(body)
        mac = hmac.new(
            bytes(self.secret_key, encoding='utf8'),
            bytes(message, encoding='utf-8'),
            digestmod='sha256'
        )
        d = mac.digest()
        return base64.b64encode(d).decode('utf-8')

    def _request(self, method: str, endpoint: str, params: dict = None):
        """底层加密通信网关"""
        if params is None:
            params = {}

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

        # 生成签名
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

    # ==========================================
    # 核心资金与盘口信息接口 (资产雷达)
    # ==========================================

    def get_available_balance(self, ccy="USDT"):
        """获取可用保证金余额"""
        res = self._request("GET", "/deepcoin/account/balance", {"ccy": ccy})
        try:
            data = res.get("data", [])
            if data and len(data) > 0:
                details = data[0].get("details", [])
                if details:
                    return float(details[0].get("availBal", 0))
            return 0.0
        except:
            return 0.0

    def get_current_price(self, symbol="ETH-USDT-SWAP"):
        """获取极速盘口现价"""
        res = self._request("GET", "/deepcoin/market/ticker", {"instId": symbol})
        try:
            data = res.get("data", [])
            if data and len(data) > 0:
                return float(data[0].get("last", 0))
            return 0.0
        except:
            return 0.0

    def get_position_info(self, symbol="ETH-USDT-SWAP"):
        """获取持仓明细"""
        return self._request("GET", "/deepcoin/account/positions", {"instType": "SWAP", "instId": symbol})

    # ==========================================
    # 核心执行端指令 (包含限价挂单防线)
    # ==========================================

    def place_limit_order(self, symbol, side, price, amount, leverage=20, is_close=False):
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
            logger.info(f"⚔️ 发起深币开仓限价单: {ord_side} {amount}张 @ {price}")
        else:
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
                "reduceOnly": "true"       # 核心防线
            }
            logger.info(f"🎯 发起深币止盈限价单: {ord_side} {amount}张 @ {price} (ReduceOnly保护)")

        return self._request("POST", "/deepcoin/trade/order", params)

    def cancel_all_open_orders(self, symbol="ETH-USDT-SWAP"):
        """一键撤销所有未成交挂单 (防悬空)"""
        params = {
            "InstrumentID": symbol.replace("-SWAP", "").replace("-", ""),
            "ProductGroup": "SwapU",
            "IsCrossMargin": 1,
            "IsMergeMode": 1
        }
        return self._request("POST", "/deepcoin/trade/swap/cancel-all", params)

    def close_all_positions(self, symbol="ETH-USDT-SWAP"):
        """一键终极全平 (官方批量平仓接口，秒级焦土清算)"""
        params = {
            "productGroup": "SwapU",
            "instId": symbol
        }
        return self._request("POST", "/deepcoin/trade/batch-close-position", params)

    def close_position_partial(self, symbol="ETH-USDT-SWAP", action="LONG", close_ratio=0.5):
        """精确切割：市价平掉指定比例仓位"""
        pos_res = self.get_position_info(symbol)
        try:
            data = pos_res.get("data", [])
            current_sz = 0
            for p in data:
                if p.get("posSide", "").lower() == action.lower():
                    current_sz = float(p.get("pos", 0))
                    break
            
            if current_sz <= 0:
                return {"code": "0", "msg": "当前无仓位可平"}

            close_sz = int(current_sz * close_ratio)
            if close_sz <= 0:
                close_sz = 1
            
            ord_side = "sell" if action.upper() == "LONG" else "buy"
            pos_side = action.lower()

            params = {
                "instId": symbol,
                "tdMode": "cross",
                "side": ord_side,
                "ordType": "market",
                "sz": str(close_sz),
                "posSide": pos_side,
                "mrgPosition": "merge"
            }
            return self._request("POST", "/deepcoin/trade/order", params)
            
        except Exception as e:
            logger.error(f"部分平仓切割失败: {e}")
            return {"code": "-1", "msg": str(e)}

deepcoin_client = DeepcoinClient()
