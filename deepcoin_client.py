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
            return res_json
        except Exception as e:
            logger.error(f"Deepcoin 请求失败 {endpoint}: {e}")
            return None

    # ==================== 加强版撤单（核心优化） ====================
    def cancel_all_open_orders(self, symbol="ETH-USDT-SWAP"):
        logger.info(f"🧹 开始加强版撤单: {symbol}")
        try:
            # 第一步：获取所有待成交订单
            pending = self._request("GET", "/trade/orders-pending", {"instType": "SWAP", "instId": symbol})
            
            if not pending or not isinstance(pending, dict) or not pending.get('data'):
                logger.info(f"✅ {symbol} 当前无挂单")
                return True

            orders = pending['data']
            logger.info(f"发现 {len(orders)} 个待撤订单，开始逐个取消...")

            success_count = 0
            for order in orders:
                ord_id = order.get("ordId")
                if not ord_id:
                    continue

                # 每个订单尝试取消2次
                cancelled = False
                for attempt in range(2):
                    res = self._request("POST", "/trade/cancel-order", {"instId": symbol, "ordId": ord_id})
                    if res and str(res.get("code", "")) == "0":
                        cancelled = True
                        success_count += 1
                        break
                    time.sleep(0.3)

                if not cancelled:
                    logger.warning(f"订单 {ord_id} 取消失败")
                time.sleep(0.25)  # 避免频率限制

            # 最终验证
            time.sleep(0.8)
            final_check = self._request("GET", "/trade/orders-pending", {"instType": "SWAP", "instId": symbol})
            remaining = len(final_check.get('data', [])) if final_check and final_check.get('data') else 0

            if remaining == 0:
                logger.info(f"✅ 加强版撤单成功，共取消 {success_count} 个订单")
                return True
            else:
                logger.warning(f"⚠️ 撤单后仍剩余 {remaining} 个订单")
                return False

        except Exception as e:
            logger.error(f"加强版撤单异常: {e}")
            return False

    # ==================== 强制激进撤单（新信号到达时使用） ====================
    def force_cancel_all(self, symbol="ETH-USDT-SWAP"):
        logger.warning(f"🚨 执行强制激进撤单: {symbol}")
        for i in range(3):
            result = self.cancel_all_open_orders(symbol)
            if result:
                return True
            time.sleep(1)
        logger.error("强制撤单多次尝试后仍未完全成功")
        return False

    # ==================== 其他功能保持不变 ====================
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
