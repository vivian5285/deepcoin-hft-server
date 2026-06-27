#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, hmac, hashlib, base64, json, logging, requests, time
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
            return None
        if not endpoint.startswith("/deepcoin/"):
            endpoint = "/deepcoin" + (endpoint if endpoint.startswith("/") else "/" + endpoint)
        timestamp = self._get_timestamp()
        body_str = json.dumps(params, separators=(',', ':')) if params and method.upper() != "GET" else ""
        request_path = f"{endpoint}?{'&'.join([f'{k}={v}' for k, v in params.items()])}" if method.upper() == "GET" and params else endpoint
        signature = self._sign(timestamp, method, request_path, body_str)
        headers = {
            "Content-Type": "application/json",
            "DC-ACCESS-KEY": self.api_key,
            "DC-ACCESS-SIGN": signature,
            "DC-ACCESS-TIMESTAMP": timestamp,
            "DC-ACCESS-PASSPHRASE": self.passphrase
        }
        try:
            resp = requests.request(method.upper(), f"{self.base_url}{request_path}", data=body_str if body_str else None, headers=headers, timeout=10)
            return resp.json()
        except Exception as e:
            logger.error(f"Deepcoin 请求失败 {endpoint}: {e}")
            return None

    def get_available_balance(self, ccy="USDT"):
        res = self._request("GET", "/account/balances", {"instType": "SWAP"})
        if isinstance(res, dict) and "data" in res:
            for item in res["data"]:
                if item.get("ccy") == ccy:
                    eq = float(item.get("eq", 0))
                    return eq if eq > 0 else float(item.get("availBal", 0))
        return 0.0

    def get_current_price(self, symbol="ETH-USDT-SWAP"):
        try:
            return float(requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol.split('-')[0]}USDT", timeout=5).json().get("price", 0.0))
        except:
            return 0.0

    def get_position_info(self, symbol="ETH-USDT-SWAP"):
        return self._request("GET", "/account/positions", {"instType": "SWAP", "instId": symbol})

    def place_market_order(self, symbol, side, pos_side, qty, reduce_only=False):
        params = {
            "instId": symbol, "tdMode": "cross", "side": side, "posSide": pos_side,
            "ordType": "market", "sz": str(int(qty)), "mrgPosition": "merge"
        }
        if reduce_only:
            params["reduceOnly"] = True
        return self._request("POST", "/trade/order", params)

    def place_limit_order(self, symbol, side, pos_side, px, qty, reduce_only=False):
        params = {
            "instId": symbol, "tdMode": "cross", "side": side, "posSide": pos_side,
            "ordType": "limit", "sz": str(int(qty)), "px": str(px), "mrgPosition": "merge"
        }
        if reduce_only:
            params["reduceOnly"] = True
        return self._request("POST", "/trade/order", params)

    def place_stop_market_order(self, symbol, side, pos_side, stop_price):
        params = {
            "instId": symbol, "tdMode": "cross", "side": side, "posSide": pos_side,
            "ordType": "stop_market", "stopPrice": str(stop_price), "closePosition": "true"
        }
        return self._request("POST", "/trade/order", params)

    def cancel_all_open_orders(self, symbol="ETH-USDT-SWAP"):
        try:
            base_symbol = symbol.replace("-SWAP", "").replace("-", "")

            # 第一层：一键撤销全部普通挂单
            self._safe_cancel("/trade/swap/cancel-all", {
                "InstrumentID": base_symbol,
                "ProductGroup": "SwapU",
                "IsCrossMargin": 1,
                "IsMergeMode": 1
            })

            # 第二层：一键撤销全部条件单/止损单
            self._safe_cancel("/trade/swap/cancel-trigger-all", {
                "InstrumentID": base_symbol,
                "ProductGroup": "SwapU",
                "IsCrossMargin": -1,
                "IsMergeMode": -1
            })

            time.sleep(0.4)

            # 第三层：兜底扫描清理
            pending = self._request("GET", "/trade/v2/orders-pending", {"instId": symbol, "limit": 50})
            if pending and 'data' in pending:
                for ord in pending['data']:
                    if ord.get("ordId"):
                        self._safe_cancel("/trade/cancel-order", {"instId": symbol, "ordId": ord.get("ordId")})

            trigger_pending = self._request("GET", "/trade/trigger-orders-pending", {"instType": "SWAP", "instId": symbol, "limit": 50})
            if trigger_pending and 'data' in trigger_pending:
                for t_ord in trigger_pending['data']:
                    if t_ord.get("ordId"):
                        self._safe_cancel("/trade/cancel-trigger-order", {"instId": symbol, "ordId": t_ord.get("ordId")})

        except Exception as e:
            logger.error(f"撤单巡检异常: {e}")

    def _safe_cancel(self, endpoint, params):
        res = self._request("POST", endpoint, params)
        if res and str(res.get("code", "")) != "0":
            msg = str(res.get("msg", "")).lower() + str(res.get("sMsg", "")).lower()
            if "too many" in msg or "limit" in msg or "frequent" in msg:
                time.sleep(1.5)
                self._request("POST", endpoint, params)
        return res

deepcoin_client = DeepcoinClient()
