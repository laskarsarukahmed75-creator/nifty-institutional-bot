#!/usr/bin/env python3
"""
websocket_manager.py – Nifty 50 Live WebSocket Data Stream & Event Bus Routing
"""
import asyncio
import json
import logging
from typing import Dict
from core.event_bus import EventBus

logger = logging.getLogger(__name__)

class WebSocketManager:
    def __init__(self, event_bus: EventBus):
        from broker.smart_connect_client import SmartConnectClient  # Angel One Client
        self.client = SmartConnectClient()
        self.event_bus = event_bus
        self._running = False
        self._tasks = []

    async def connect(self) -> None:
        self._running = True
        await self.client.connect_websocket()
        # Nifty 50 Institutional Stream Token Binding
        await self.client.subscribe_symbols() 
        self._tasks.append(asyncio.create_task(self._listen()))
        logger.info("Nifty 50 WebSocket Manager Live: Subscribed and routing to MARKET_DATA.")

    async def _listen(self) -> None:
        while self._running:
            try:
                if not self.client._ws:
                    await self.client.connect_websocket()
                message = await self.client._ws.recv()
                data = json.loads(message)
                await self._process_message(data)
            except Exception as e:
                logger.error(f"Nifty WS Loop Error: {e}")
                await asyncio.sleep(5)

    async def _process_message(self, data: Dict) -> None:
        # Check for live tick data structures from Angel One
        if data and "token" in data:
            candle = {
                "symbol": "NIFTY50",
                "timestamp": data.get("timestamp"),
                "open": float(data.get("open", 0)),
                "high": float(data.get("high", 0)),
                "low": float(data.get("low", 0)),
                "close": float(data.get("close", 0)),
                "volume": float(data.get("volume", 0))
            }
            # Direct injection into event bus pipeline
            await self.event_bus.publish("MARKET_DATA", candle)

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        await self.client.close()
