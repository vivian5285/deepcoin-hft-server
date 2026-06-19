#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, hmac, hashlib, base64, json, logging, requests, time
from datetime import datetime, timezone
from urllib.parse import urlencode
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, '.env'))
logger = logging.getLogger(__name__)

class DeepcoinClient:
    def __init__(self):
        # 兼容各种环境变量命名
        self.api_key = os.getenv("DEEPCOIN_API_KEY", os.getenv("API_KEY", ""))
        self.secret_key = os.getenv("DEEPCOIN_API_SECRET", os.getenv("DEEPCOIN_SECRET_KEY", os.getenv("SECRET_KEY", "")))
        self.passphrase = os.getenv("DEEPCOIN_PASSPHRASE", os.getenv("PASSPHRASE", os.getenv("API_PASSPHRASE", "")))
        self.base_url = "https://api.deepcoin.com"

    def _get_timestamp(self):
        # 👑 V7 核心：ISO8601 UTC 时间戳
        return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')

    def _sign(self, timestamp: str, method: str, request_path: str, body: str = ""):
        message = (str(timestamp) + str(method.upper()) + str(request_path) + str(body)).encode('utf-8')
        h = hmac.new(self.secret_key.encode('utf-8'), message, hashlib.sha256)
        return base64.b64encode(h.digest()).decode('utf-8')

    def _request(self, method: str, endpoint: str, params: dict = None):
        if not self.api_key or not self.secret_key:
            logger.error("⚠️ Deepcoin API 密钥未配置！")
            return None

        # 确保加上 /deepcoin 前缀
        if not endpoint.startswith("/deepcoin/"): 
            endpoint = "/deepcoin" + (endpoint if endpoint.startswith("/") else "/" + endpoint)
            
        timestamp = self._get_timestamp()
        
        # 👑 V7 核心：GET 请求参数必须拼接在 URL 后面参与签名，POST body 必须转 JSON
        body_str = json.dumps(params, separators=(',', ':')) if params and method.upper() != "GET" else ""
        request_path = f"{endpoint}?{'&'.join([f'{k}={v}' for k, v in params.items()])}" if method.upper() == "GET" and params else endpoint
        
        signature = self._sign(timestamp, method, request_path, body_str)
        
        # 👑 V7 核心：全新的 DC-ACCESS 请求头
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
            res_json = resp.json()
            if str(res_json.get("code")) != "0":
                logger.warning(f"Deepcoin API 业务异常: {res_json}")
            return res_json
        except Exception as e: 
            logger.error(f"Deepcoin 请求失败 {endpoint}: {e} | 返回: {resp.text if 'resp' in locals() else 'N/A'}")
            return None

    def get_available_balance(self, ccy="USDT"):
        # 👑 V7 核心：接口变更为 /account/balances，字段名为 availBal
        res = self._request("GET", "/account/balances", {"instType": "SWAP"})
        if isinstance(res, dict) and "data" in res:
            for item in res["data"]:
                if item.get("ccy") == ccy: 
                    return float(item.get("availBal", 0)) 
        return 0.0

    def get_current_price(self, symbol="ETH-USDT-SWAP"):
        # 👑 V7 核心：接口变更为 /market/ticker
        res = self._request("GET", "/market/ticker", {"instId": symbol})
        if isinstance(res, dict) and "data" in res and len(res["data"]) > 0:
            price = res["data"][0].get("last")
            return float(price) if price else 0.0
        return 0.0

    def get_position_info(self, symbol="ETH-USDT-SWAP"):
        return self._request("GET", "/account/positions", {"instType": "SWAP", "instId": symbol})

    def place_market_order(self, symbol, side, pos_side, qty):
        params = {
            "instId": symbol, "tdMode": "cross",
            "side": side, "posSide": pos_side,
            "ordType": "market", "sz": str(int(qty)),
            "mrgPosition": "merge"
        }
        return self._request("POST", "/trade/order", params)

    def place_limit_order(self, symbol, side, pos_side, px, qty):
        params = {
            "instId": symbol, "tdMode": "cross",
            "side": side, "posSide": pos_side,
            "ordType": "limit", "sz": str(int(qty)),
            "px": str(px), "mrgPosition": "merge"
        }
        return self._request("POST", "/trade/order", params)

    def place_conditional_order(self, symbol, side, pos_side, trigger_px, qty):
        params = {
            "instId": symbol, "tdMode": "cross",
            "side": side, "posSide": pos_side,
            "ordType": "conditional", "sz": str(int(qty)),
            "triggerPx": str(trigger_px), "ordPx": str(trigger_px),
            "reduceOnly": True
        }
        return self._request("POST", "/trade/order/algo", params)

    def cancel_all_open_orders(self, symbol="ETH-USDT-SWAP"):
        try:
            # 👑 融合版：保留我们设计的 0.5 秒双重轰炸防线，使用 V7 最新接口
            self._request("POST", "/trade/cancel-batch-orders", {"instId": symbol})
            self._request("POST", "/trade/cancel-algo-orders", {"instId": symbol})
            time.sleep(0.5)
            self._request("POST", "/trade/cancel-batch-orders", {"instId": symbol})
            self._request("POST", "/trade/cancel-algo-orders", {"instId": symbol})
            logger.info("🧹 双重撤单轰炸完成，盘口已物理级清空！")
        except Exception as e:
            logger.error(f"撤单异常: {e}")

    def close_all_positions(self, symbol="ETH-USDT-SWAP"):
        return self._request("POST", "/trade/close-position", {"instId": symbol, "mrgPosition": "merge"})

deepcoin_client = DeepcoinClient()
