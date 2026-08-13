from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import List, Dict, Any
from pydantic import BaseModel
from app.services.notifier import ws_manager, send_telegram_alert, format_telegram_message

router = APIRouter()

class AlertPayload(BaseModel):
    alerts: List[Dict[str, Any]]

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            # We don't expect the client to send us data, but we must keep connection alive
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
        print("A client disconnected from WebSocket")


@router.post("/notify")
async def notify_alerts(payload: AlertPayload):
    """
    Endpoint for internal scripts (like screener) to send signals.
    This will broadcast to WebSockets and send a Telegram alert.
    """
    alerts = payload.alerts
    
    if not alerts:
        return {"status": "ok", "message": "No alerts to process"}

    # 1. Broadcast to WebSocket clients (for the future frontend dashboard)
    ws_payload = {
        "type": "screener_signals",
        "data": alerts
    }
    await ws_manager.broadcast_json(ws_payload)

    # 2. Send Telegram Alert
    telegram_msg = format_telegram_message(alerts)
    send_telegram_alert(telegram_msg)

    return {"status": "ok", "message": "Alerts broadcasted to WS and Telegram"}
