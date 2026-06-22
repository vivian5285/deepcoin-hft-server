#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import logging, requests, time, os, hmac, hashlib, base64, json
from datetime import datetime, timezone
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, '.env'))
logger = logging.getLogger(__name__)

class DeepcoinClient:
    def __init__(self):
        self.api_key = os.getenv("DEEPCOIN_API_KEY", "")
        self.secret_key = os.getenv("DEEPCOIN_API_SECRET", "")
        self.passphrase = os.getenv("DEEPCOIN_PASSPHRASE", "")
        self.base_url = "https://api.deepcoin.com"

    def _get_timestamp(self):
        return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')

    def _sign(self, timestamp: str, method: str, request_path: str, body: str = ""):
        message = (str(timestamp) + str(method.upper()) + str(request_path) + str(body)).encode('utf-8')
        h = hmac.new(self.secret_key.encode('utf-8'), message, hashlib.sha256)
        return base64.b64encode(h.digest()).decode('utf-8')

    def _request(self, method: str, endpoint: str, params: dict = None):
        if not self.api_key or not self.secret_key:
            logger.error("⚠️ Deepcoin API 密钥未配置！")
            return None

        if not endpoint.startswith("/deepcoin/"): 
            endpoint = "/deepcoin" + (endpoint if endpoint.startswith("/") else "/" + endpoint)

        timestamp = self._get_timestamp()
        body_str = json.dumps(params, separators=(',', ':')) if params and method.upper() != "GET" else ""
        request_path = endpoint
        if method.upper() == "GET" and params:
            request_path += "?" + "&".join([f"{k}={v}" for k, v in params.items()])

        signature = self._sign(timestamp, method, request_path, body_str)

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
            if str(res_json.get("code", "")) != "0":
                logger.warning(f"Deepcoin API 返回: {res_json}")
            return res_json
        except Exception as e:
            logger.error(f"Deepcoin 请求失败 {endpoint}: {e}")
            return None

    # ==================== 精简可靠的撤单逻辑 ====================
    def cancel_all_open_orders(self, symbol="ETH-USDT-SWAP"):
        logger.info(f"🧹 开始清理 {symbol} 普通挂单...")
        try:
            pending = self._request("GET", "/trade/orders-pending", {"instType": "SWAP", "instId": symbol})
            if pending and isinstance(pending, dict) and pending.get('data'):
                for order in pending['data']:
                    ord_id = order.get("ordId")
                    if ord_id:
                        self._request("POST", "/trade/cancel-order", {"instId": symbol, "ordId": ord_id})
                        time.sleep(0.2)
            logger.info(f"✅ {symbol} 普通挂单清理完成")
        except Exception as e:
            logger.error(f"撤单异常: {e}")

    def get_available_balance(self, ccy="USDT"):
        res = self._request("GET", "/account/balances", {"instType": "SWAP"})
        if isinstance(res, dict) and "data" in res:
            for item in res["data"]:
                if item.get("ccy") == ccy:
                    equity = float(item.get("equity", 0))
                    return equity if equity > 0 else float(item.get("availBal", 0))
        return 0.0

    def get_current_price(self, symbol="ETH-USDT-SWAP"):
        try:
            binance_symbol = symbol.split("-")[0] + "USDT"
            url = f"https://api.binance.com/api/v3/ticker/price?symbol={binance_symbol}"
            res = requests.get(url, timeout=5)
            return float(res.json().get("price", 0.0))
        except:
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

deepcoin_client = DeepcoinClient()
