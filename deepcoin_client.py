#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, time, hmac, hashlib, json, requests, logging, base64
from urllib.parse import urlencode
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, '.env'))
logger = logging.getLogger(__name__)

class DeepcoinClient:
    def __init__(self):
        self.api_key = os.getenv("DEEPCOIN_API_KEY", os.getenv("API_KEY", ""))
        self.secret_key = os.getenv("DEEPCOIN_API_SECRET", os.getenv("DEEPCOIN_SECRET_KEY", os.getenv("SECRET_KEY", "")))
        self.passphrase = os.getenv("DEEPCOIN_PASSPHRASE", os.getenv("PASSPHRASE", os.getenv("API_PASSPHRASE", "")))
        self.base_url = "https://api.deepcoin.com"

    def _get_server_time(self):
        return str(int(time.time() * 1000))

    def _sign(self, timestamp, method, request_path, body=""):
        message = str(timestamp) + method.upper() + request_path + str(body)
        mac = hmac.new(bytes(self.secret_key, encoding='utf8'), bytes(message, encoding='utf-8'), digestmod='sha256')
        return base64.b64encode(mac.digest()).decode('utf-8')

    def _request(self, method, endpoint, params=None):
        if not self.api_key or not self.secret_key:
            logger.error("⚠️ Deepcoin API 密钥未配置！")
            return None

        url = self.base_url + endpoint
        timestamp = self._get_server_time()
        body_str = ""
        request_path = endpoint

        if method == "GET" and params:
            # 深币要求 GET 参数按字母排序
            query_string = urlencode(sorted(params.items()))
            request_path = endpoint + "?" + query_string
            url = self.base_url + request_path
        elif method == "POST" and params:
            body_str = json.dumps(params)

        sign = self._sign(timestamp, method, request_path, body_str)

        headers = {
            "Content-Type": "application/json",
            "Deepcoin-Access-Key": self.api_key,
            "Deepcoin-Access-Sign": sign,
            "Deepcoin-Access-Timestamp": timestamp,
            "Deepcoin-Access-Passphrase": self.passphrase
        }

        try:
            if method == "GET":
                response = requests.get(url, headers=headers, timeout=10)
            else:
                response = requests.post(url, headers=headers, data=body_str, timeout=10)
            
            # 增加对非 JSON 返回的容错
            try:
                res_json = response.json()
            except ValueError:
                logger.error(f"Deepcoin 返回非 JSON 数据: {response.text}")
                return None

            if str(res_json.get("code")) != "0":
                logger.warning(f"Deepcoin API 业务异常: {res_json}")
            return res_json
        except Exception as e:
            logger.error(f"Deepcoin 请求失败 {endpoint}: {e}")
            return None

    def get_current_price(self, symbol="ETH-USDT-SWAP"):
        # 🚀 修复点：增加 instType="SWAP" 强制参数
        res = self._request("GET", "/deepcoin/market/tickers", {"instType": "SWAP"})
        if res and res.get("data"):
            for item in res["data"]:
                if item.get("instId") == symbol:
                    return float(item.get("last", 0))
        return 0.0

    def get_available_balance(self, ccy="USDT"):
        # 🚀 修复点：去掉 ccy 参数做全量查询，避免深币 GET 签名失败导致的 Expecting value 错误
        res = self._request("GET", "/deepcoin/account/balance")
        if res and res.get("data"):
            for item in res["data"]:
                if item.get("ccy") == ccy:
                    return float(item.get("availEq", 0))
        return 0.0

    def get_position_info(self, symbol="ETH-USDT-SWAP"):
        res = self._request("GET", "/deepcoin/account/positions", {"instId": symbol})
        return res

    def place_market_order(self, symbol, side, pos_side, qty):
        params = {"instId": symbol, "tdMode": "cross", "side": side, "posSide": pos_side, "ordType": "market", "sz": str(int(qty))}
        return self._request("POST", "/deepcoin/trade/order", params)

    def place_limit_order(self, symbol, side, pos_side, px, qty):
        params = {"instId": symbol, "tdMode": "cross", "side": side, "posSide": pos_side, "ordType": "limit", "px": str(px), "sz": str(int(qty))}
        return self._request("POST", "/deepcoin/trade/order", params)

    def place_conditional_order(self, symbol, side, pos_side, trigger_px, qty):
        params = {"instId": symbol, "tdMode": "cross", "side": side, "posSide": pos_side, "ordType": "conditional", "triggerPx": str(trigger_px), "ordPx": str(trigger_px), "sz": str(int(qty))}
        return self._request("POST", "/deepcoin/trade/order-algo", params)

    def cancel_all_open_orders(self, symbol="ETH-USDT-SWAP"):
        try:
            inst_id_base = symbol.replace("-SWAP", "").replace("-", "")
            p1 = {"InstrumentID": inst_id_base, "ProductGroup": "SwapU", "IsCrossMargin": 1, "IsMergeMode": 1}
            self._request("POST", "/deepcoin/trade/cancel-all", p1)
            self._request("POST", "/deepcoin/trade/cancel-algos-all", p1)
            time.sleep(0.5) 
            self._request("POST", "/deepcoin/trade/cancel-all", p1)
            self._request("POST", "/deepcoin/trade/cancel-algos-all", p1)
        except Exception as e:
            logger.error(f"批量撤单发生异常: {e}")

    def close_all_positions(self, symbol="ETH-USDT-SWAP"):
        try:
            res = self._request("POST", "/deepcoin/trade/close-position", {"instId": symbol, "mgnMode": "cross", "autoCxl": True})
            return res
        except Exception as e:
            logger.error(f"全平请求异常: {e}")
            return None

deepcoin_client = DeepcoinClient()
