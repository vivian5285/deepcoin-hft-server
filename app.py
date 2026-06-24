#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import threading
import json
import logging
from flask import Flask, request, jsonify
from position_supervisor_deepcoin import deepcoin_processor

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] DeepcoinApp: %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    # 兼容 TradingView 多种格式
    data = request.get_json(force=True, silent=True)
    if not data:
        try:
            raw_data = request.get_data(as_text=True)
            data = json.loads(raw_data)
        except Exception as e:
            logger.warning(f"JSON 解析失败: {e}")
            return jsonify({"status": "error", "message": "无效的 JSON 数据"}), 400

    # 密钥校验
    secret = str(data.get("secret", "")).strip()
    expected_secret = os.getenv("WEBHOOK_SECRET", "528586")

    if secret != expected_secret:
        logger.warning("Secret 校验失败！")
        return jsonify({"status": "error", "message": "Invalid secret"}), 403

    action = data.get("action", "UNKNOWN")
    logger.info(f"收到信号 → Action: {action} | Regime: {data.get('regime', 'N/A')} | TV_TP1: {data.get('tv_tp1', 'N/A')}")

    # 异步处理
    try:
        threading.Thread(
            target=deepcoin_processor.process_signal,
            args=(data,),
            daemon=True
        ).start()
    except Exception as e:
        logger.error(f"启动处理线程失败: {e}")
        return jsonify({"status": "error", "message": "内部执行错误"}), 500

    return jsonify({
        "status": "success",
        "message": "Deepcoin Signal received",
        "action": action
    }), 200


@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "ok",
        "service": "deepcoin_webhook",
        "version": "v2.0-smart-fee"
    }), 200


if __name__ == '__main__':
    logger.info("🚀 Deepcoin Webhook 服务启动中...")
    app.run(host='127.0.0.1', port=5004, debug=False)
