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
        self.api_key = os.getenv("DEEPCOIN_API_KEY", "")
        self.secret_key = os.getenv("DEEPCOIN_SECRET_KEY", "")
        self.passphrase = os.getenv("DEEPCOIN_PASSPHRASE", "")
        self.base_url = "https://api.deepcoin.com"

    def _get_server_time(self):
        return str(int(time.time() * 1000))

    def _sign(self, timestamp, method, request_path, body=""):
        message = str(timestamp) + method.upper() + request_path + str(body)
        mac = hmac.new(bytes(self.secret_key, encoding='utf8'), bytes(message, encoding='utf-8'), digestmod='sha256')
        d = mac.digest()
        return base64.b64encode(d).decode('utf-8')

    def _request(self, method, endpoint, params=None):
        if not self.api_key or not self.secret_key:
            logger.error("⚠️ Deepcoin API 密钥未配置！")
            return None

        url = self.base_url + endpoint
        timestamp = self._get_server_time()
        body_str = ""
        request_path = endpoint

        if method == "GET" and params:
            query_string = urlencode(params)
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
            
            res_json = response.json()
            if str(res_json.get("code")) != "0":
                logger.warning(f"Deepcoin API 返回异常: {res_json}")
            return res_json
        except Exception as e:
            logger.error(f"Deepcoin 请求失败 {endpoint}: {e}")
            return None

    def get_current_price(self, symbol="ETH-USDT-SWAP"):
        # 获取实时盘口价格
        res = self._request("GET", "/deepcoin/market/tickers", {"instId": symbol})
        if res and res.get("data"):
            for item in res["data"]:
                if item.get("instId") == symbol:
                    return float(item.get("last", 0))
        return 0.0

    def get_available_balance(self, ccy="USDT"):
        # 获取合约账户可用余额
        res = self._request("GET", "/deepcoin/account/balance", {"ccy": ccy})
        if res and res.get("data"):
            for item in res["data"]:
                if item.get("ccy") == ccy:
                    return float(item.get("availEq", 0))
        return 0.0

    def get_position_info(self, symbol="ETH-USDT-SWAP"):
        # 获取当前持仓情况
        res = self._request("GET", "/deepcoin/account/positions", {"instId": symbol})
        return res

    def place_market_order(self, symbol, side, pos_side, qty):
        # 现价吃单入场
        params = {
            "instId": symbol,
            "tdMode": "cross",
            "side": side,
            "posSide": pos_side,
            "ordType": "market",
            "sz": str(int(qty))
        }
        return self._request("POST", "/deepcoin/trade/order", params)

    def place_limit_order(self, symbol, side, pos_side, px, qty):
        # 挂限价单（止盈防线）
        params = {
            "instId": symbol,
            "tdMode": "cross",
            "side": side,
            "posSide": pos_side,
            "ordType": "limit",
            "px": str(px),
            "sz": str(int(qty))
        }
        return self._request("POST", "/deepcoin/trade/order", params)

    def place_conditional_order(self, symbol, side, pos_side, trigger_px, qty):
        # 挂条件止损单
        params = {
            "instId": symbol,
            "tdMode": "cross",
            "side": side,
            "posSide": pos_side,
            "ordType": "conditional",
            "triggerPx": str(trigger_px),
            "ordPx": str(trigger_px), # 触发后市价或同价成交
            "sz": str(int(qty))
        }
        return self._request("POST", "/deepcoin/trade/order-algo", params)

    def cancel_all_open_orders(self, symbol="ETH-USDT-SWAP"):
        """
        🚀 V10.1 幽灵单双重地毯式轰炸机制
        撤销所有的限价单与条件触发单，带延迟与二次确认
        """
        try:
            inst_id_base = symbol.replace("-SWAP", "").replace("-", "")
            p1 = {
                "InstrumentID": inst_id_base, 
                "ProductGroup": "SwapU", 
                "IsCrossMargin": 1, 
                "IsMergeMode": 1
            }
            
            # 🚨 第一轮轰炸
            self._request("POST", "/deepcoin/trade/cancel-all", p1)
            self._request("POST", "/deepcoin/trade/cancel-algos-all", p1)
            
            # 🚀 强制程序深呼吸 0.5 秒，给深币 API 接口消化状态的时间
            time.sleep(0.5) 
            
            # 🚨 第二轮终极确认轰炸 (专治漏网之鱼和 API 状态滞后)
            self._request("POST", "/deepcoin/trade/cancel-all", p1)
            self._request("POST", "/deepcoin/trade/cancel-algos-all", p1)
            logger.info("🧹 双重撤单轰炸完成，盘口已物理级清空！")
        except Exception as e:
            logger.error(f"批量撤单发生异常: {e}")

    def close_all_positions(self, symbol="ETH-USDT-SWAP"):
        """
        铁血平仓：直接向深币引擎发送全平指令
        """
        try:
            params = {
                "instId": symbol,
                "mgnMode": "cross",
                "autoCxl": True
            }
            res = self._request("POST", "/deepcoin/trade/close-position", params)
            if res and str(res.get("code")) == "0":
                logger.info(f"✅ {symbol} 全平指令下达成功！")
            return res
        except Exception as e:
            logger.error(f"全平请求异常: {e}")
            return None

deepcoin_client = DeepcoinClient()
