import asyncio
import logging
import json
from collections import deque
from dataclasses import dataclass
from typing import List, Optional, Deque, Union, cast
from random import choice, randint
from urllib.parse import unquote
from aiohttp import ClientSession, ClientWebSocketResponse, WSMsgType
from yarl import URL

logger = logging.getLogger(__name__)


@dataclass(init=True, repr=True)
class Message:
    n_type: int
    n_from: int
    n_to: int
    n_arg1: int
    n_arg2: int
    payload: Optional[Union[str, dict]] = None

    @classmethod
    def from_text(cls, text: str):
        text = unquote(text)
        args = text.split(maxsplit=5)
        payload = None
        if len(args) == 6:
            payload = args.pop()
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                logger.debug("Cannot parse payload, raw text is: ", payload)
        n_type, n_from, n_to, n_arg1, n_arg2 = [int(arg) for arg in args]
        return cls(n_type, n_from, n_to, n_arg1, n_arg2, payload=payload)


class MfcWsChat(object):
    session: ClientSession
    ws: Optional[ClientWebSocketResponse]
    ping_task: Optional[asyncio.Task]
    user_session_id: int
    user_session_name: Optional[str]
    messages_buffer: Deque[str]

    def __init__(self, session: ClientSession):
        self.session = session
        self.ws = None
        self.ping_task = None
        self.user_session_id = 0
        self.user_session_name = None
        self.messages_buffer = deque()

    @property
    def connected(self):
        if self.ws is None:
            return False
        return not self.ws.closed

    async def send_handshake(self, ws: ClientWebSocketResponse) -> None:
        await ws.send_str("fcsws_20180422\n\0")
        await ws.send_str("1 0 0 20071025 0 1/guest:guest\n\0")

    async def chat_ping(self, ws: ClientWebSocketResponse) -> None:
        while not ws.closed:
            try:
                await ws.send_str("0 0 0 0 0\n\0")
                ping_delay = randint(10, 19)
                await asyncio.sleep(ping_delay)
            except asyncio.exceptions.CancelledError:
                pass

    async def send_message(self, message: str):
        if self.connected:
            self.ws = cast(ClientWebSocketResponse, self.ws)
            await self.ws.send_str(message)

    async def connect(self, ws_server: str):
        ws_host = f"{ws_server}.myfreecams.com"
        ws_server_url = URL.build(scheme="wss", host=ws_host, port=443, path="/fcsl")

        self.ws = await self.session.ws_connect(ws_server_url)
        await self.send_handshake(self.ws)
        login_msg = await self.ws.receive()
        login_parts = login_msg.data.split()
        self.user_session_id = login_parts[2]
        self.user_session_name = login_parts[5]
        self.ping_task = asyncio.create_task(self.chat_ping(self.ws))

    async def disconnect(self):
        if self.ws is None:
            return
        await self.ws.close()
        if self.ping_task is not None:
            self.ping_task.cancel()
            await self.ping_task
        logger.info("Ping stopped")

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.connected:
            raise StopAsyncIteration
        if self.messages_buffer:
            return self.messages_buffer.popleft()
        msg = await self.ws.receive()
        if msg.type == WSMsgType.TEXT:
            data = msg.data
            while data:
                m_len = int(data[:6])
                message = Message.from_text(data[6 : m_len + 6])
                self.messages_buffer.append(message)
                data = data[m_len + 6 :]
            if self.messages_buffer:
                return self.messages_buffer.popleft()
