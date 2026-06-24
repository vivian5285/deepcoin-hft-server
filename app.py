#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import threading
import json
import logging
from flask import Flask, request, jsonify
from position_supervisor_deepcoin import position_supervisor

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] Flask: %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    # 快速解析 JSON
    try:
        if request.is_json:
            data = request.get_json()
        else:
            raw_data = request.get_data(as_text=True)
            data = json.loads(raw_data) if raw_data else {}
    except Exception as e:
        logger.warning(f"[Webhook] JSON 解析失败: {e}")
        return jsonify({"status": "error", "message": "Invalid JSON"}), 400

    if not data:
        return jsonify({"status": "error", "message": "Empty payload"}), 400

    # 密钥校验
    secret = str(data.get("secret", "")).strip()
    if secret != os.getenv("WEBHOOK_SECRET", "528586"):
        logger.warning("[Webhook] Secret 校验失败")
        return jsonify({"status": "error", "message": "Invalid secret"}), 403

    action = data.get("action", "UNKNOWN")
    logger.info(f"[Webhook] 收到信号 → {action}")

    # 立即返回成功，处理放后台线程
    try:
        threading.Thread(
            target=position_supervisor.handle_signal,
            args=(data,),
            daemon=True
        ).start()
    except Exception as e:
        logger.error(f"[Webhook] 启动处理线程失败: {e}")
        return jsonify({"status": "success", "message": "Signal received (may have processing issue)"}), 200

    return jsonify({
        "status": "success",
        "message": "Signal received and processing started",
        "action": action
    }), 200


@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status": "ok",
        "service": "deepcoin_webhook",
        "version": "final-strong"
    }), 200


if __name__ == '__main__':
    logger.info("🚀 深币 Webhook 服务启动（强壮及时响应版）")
    app.run(host='127.0.0.1', port=5004, debug=False, threaded=True)
