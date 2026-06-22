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
        self.api_key = os.getenv("DEEPCOIN_API_KEY", os.getenv("API_KEY", ""))
        self.secret_key = os.getenv("DEEPCOIN_API_SECRET", os.getenv("DEEPCOIN_SECRET_KEY", os.getenv("SECRET_KEY", "")))
        self.passphrase = os.getenv("DEEPCOIN_PASSPHRASE", os.getenv("PASSPHRASE", os.getenv("API_PASSPHRASE", "")))
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
            url = f"{self.base_url}{request_path}"
            resp = requests.request(method.upper(), url, data=body_str if body_str else None, headers=headers, timeout=10)
            res_json = resp.json()
            if str(res_json.get("code")) != "0":
                logger.warning(f"Deepcoin 接口返回异常: {res_json}")
            return res_json
        except Exception as e: 
            logger.error(f"Deepcoin 请求失败 {endpoint}: {e}")
            return None

    def get_available_balance(self, ccy="USDT"):
        res = self._request("GET", "/account/balances", {"instType": "SWAP"})
        if isinstance(res, dict) and "data" in res:
            for item in res["data"]:
                if item.get("ccy") == ccy: 
                    return float(item.get("availBal", 0)) 
        return 0.0

    def get_current_price(self, symbol="ETH-USDT-SWAP"):
        try:
            binance_symbol = symbol.split("-")[0] + "USDT" 
            res = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={binance_symbol}", timeout=5)
            return float(res.json().get("price", 0.0))
        except:
            return 0.0

    def get_position_info(self, symbol="ETH-USDT-SWAP"):
        return self._request("GET", "/account/positions", {"instType": "SWAP", "instId": symbol})

    def place_market_order(self, symbol, side, pos_side, qty):
        """基础市价下单接口（已被验证绝对稳定）"""
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
        # 修正 OKX/Deepcoin 架构标准的 Algo 终极路径
        params = {
            "instId": symbol, "tdMode": "cross",
            "side": side, "posSide": pos_side,
            "ordType": "conditional", "sz": str(int(qty)),
            "triggerPx": str(trigger_px), "ordPx": str(trigger_px),
            "reduceOnly": True
        }
        return self._request("POST", "/trade/order-algo", params)

    def cancel_all_open_orders(self, symbol="ETH-USDT-SWAP"):
        try:
            # 兼容性退化处理：如果一键撤单 404，至少不阻塞后续代码运行
            self._request("POST", "/trade/cancel-batch-orders", {"instId": symbol})
            self._request("POST", "/trade/cancel-algos", {"instId": symbol})
        except: pass

    def close_all_positions(self, symbol="ETH-USDT-SWAP"):
        """🚀 终极防爆修复：抛弃不稳定的 Close 接口，采用反向市价单物理平仓"""
        try:
            pos_info = self.get_position_info(symbol)
            if pos_info and 'data' in pos_info:
                for p in pos_info['data']:
                    sz = float(p.get("pos", 0))
                    if sz > 0:
                        pos_side = p.get("posSide", "").lower()
                        # 如果持有长仓(long)，就下卖单(sell)；如果持有短仓(short)，就下买单(buy)
                        close_side = "sell" if pos_side == "long" else "buy"
                        logger.info(f"🔨 启动物理清仓：发送 {close_side} {pos_side} {sz} 张市价单")
                        self.place_market_order(symbol, close_side, pos_side, sz)
        except Exception as e:
            logger.error(f"物理平仓执行异常: {e}")

deepcoin_client = DeepcoinClient()
