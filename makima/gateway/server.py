import asyncio
import logging
from typing import Dict, Any, List

class GatewayServer:
    """Central daemon server routing inbound messages from Telegram/Discord to Hermes agent."""
    def __init__(self):
        self.active_adapters: List[Any] = []
        self.is_running = False

    async def start(self):
        self.is_running = True
        logging.info("Makima Gateway Server started on all configured channels.")
        while self.is_running:
            await asyncio.sleep(1)

    def stop(self):
        self.is_running = False
