import os
import requests
from typing import List, Dict, Any
from fastapi import WebSocket
from app.core.config import settings

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast_json(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                print(f"Failed to send to a websocket client: {e}")

# Global instance for the FastAPI app
ws_manager = ConnectionManager()


def send_telegram_alert(message: str) -> bool:
    """
    Sends a message to the configured Telegram chat.
    Returns True if successful, False otherwise.
    """
    bot_token = settings.telegram_bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = settings.telegram_chat_id or os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        print("[Notifier] Telegram token or chat ID is not configured. Skipping Telegram alert.")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        print("[Notifier] Telegram alert sent successfully.")
        return True
    except Exception as e:
        print(f"[Notifier] Failed to send Telegram alert: {e}")
        return False

def format_telegram_message(alerts: List[Dict[str, Any]]) -> str:
    """
    Formats the list of alerts into a single Telegram message block.
    """
    if not alerts:
        return "Tidak ada sinyal screener baru hari ini."

    msg = "🚨 <b>GOAT IDX ALERT: SCREENER SIGNALS</b> 🚨\n\n"
    for idx, alert in enumerate(alerts, 1):
        ticker = alert.get("ticker", "UNKNOWN")
        score = alert.get("score", 0)
        close_price = alert.get("close", 0)
        
        entry_low = alert.get("entry_range_low", close_price * 0.98)
        entry_high = alert.get("entry_range_high", close_price * 1.02)
        sl = alert.get("stop_loss", 0)
        
        tp1 = alert.get("tp1")
        tp2 = alert.get("tp2")
        tp3 = alert.get("tp3")
        
        msg += f"{idx}. <b>{ticker}</b> (Skor: {score}/100) ⭐\n"
        msg += f"🛒 <b>Entry Range</b>: Rp {entry_low:,.0f} - Rp {entry_high:,.0f}\n"
        msg += f"🛡️ <b>Stop Loss</b>: Rp {sl:,.0f}\n"
        
        if tp1:
            msg += f"🎯 <b>TP1 (Resisten 1)</b>: Rp {tp1:,.0f}\n"
        if tp2:
            msg += f"🎯 <b>TP2 (Resisten 2)</b>: Rp {tp2:,.0f}\n"
        if tp3:
            msg += f"🎯 <b>TP3 (Resisten 3)</b>: Rp {tp3:,.0f}\n"
        if not tp1:
            msg += f"🚀 <b>Target</b>: All Time High / No Resistance (Let Your Profit Run)\n"
            
        msg += "\n"
    
    msg += "<i>*Gunakan lot sizing yang bijak. Gunakan fitur trailing stop jika profit sudah melebihi TP1.</i>"
    return msg
