#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, threading, json, logging
from flask import Flask, request, jsonify
from position_supervisor_deepcoin import position_supervisor

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] Flask: %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json() if request.is_json else (json.loads(request.get_data(as_text=True)) if request.get_data(as_text=True) else {})
    except Exception as e:
        return jsonify({"status": "error", "message": "Invalid JSON"}), 400

    if not data: return jsonify({"status": "error", "message": "Empty payload"}), 400
    if str(data.get("secret", "")).strip() != os.getenv("WEBHOOK_SECRET", "528586"): return jsonify({"status": "error", "message": "Invalid secret"}), 403

    logger.info(f"[Webhook] 收到信号 → {data.get('action', 'UNKNOWN')}")
    # 放进后台线程，秒回 TV，防止 TV 报 Timeout
    threading.Thread(target=position_supervisor.handle_signal, args=(data,), daemon=True).start()

    return jsonify({"status": "success", "message": "Signal processing started", "action": data.get("action")}), 200

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok", "service": "deepcoin_webhook", "version": "v7.1-nuclear"}), 200

if __name__ == '__main__':
    logger.info("🚀 深币 Webhook 服务启动（强壮及时响应版）")
    app.run(host='127.0.0.1', port=5004, debug=False, threaded=True)
