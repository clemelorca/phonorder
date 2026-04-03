from fastapi import APIRouter,WebSocket,WebSocketDisconnect
from typing import Dict,List
import json

router=APIRouter()

class Manager:
    def __init__(self): self.rooms:Dict[int,List[WebSocket]]={}
    async def connect(self,sid,ws): await ws.accept();self.rooms.setdefault(sid,[]).append(ws)
    def disconnect(self,sid,ws):
        try: self.rooms.get(sid,[]).remove(ws)
        except: pass
    async def broadcast(self,sid,msg):
        for ws in self.rooms.get(sid,[]):
            try: await ws.send_text(json.dumps(msg))
            except: pass

manager=Manager()

@router.websocket("/ws/store/{sid}")
async def ws_ep(websocket:WebSocket,sid:int):
    await manager.connect(sid,websocket)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(sid,websocket)
