import asyncio
import logging
import re
from random import choice, random
from time import time
from typing import List, Dict, Any, Optional, cast
from aiohttp import ClientSession, ClientResponse
from yarl import URL
from .mfcwschat import MfcWsChat, Message
from .mfccrc import MfcCrc32
from .streamloader import StreamLoader

# import fcs

REFERRER = "https://www.myfreecams.com/"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/85.0.4183.121 Safari/537.36"
)
MODEL_STATUS = {
    0: "public chat",
    2: "away",
    12: "in private",
    90: "webcam is off",
    127: "offline",
}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# class ServerConfig(TypedDict):
#     ajax_servers: List[str]
#     chat_servers: List[str]
#     h5video_servers: Dict[str, str]
#     ngvideo_servers: Dict[str, str]
#     video_servers: List[str]
#     websocket_servers: Dict[str, str]
#     wzext_servers: Dict[str, str]
#     wzobs_servers: Dict[str, str]


class MfcGrabber(object):

    session: ClientSession
    server_config: Dict[str, Any]
    models: List[str]
    chat: MfcWsChat
    streams: Dict[str, StreamLoader]
    progress_log_task: Optional[asyncio.Task]

    def __init__(self, session: ClientSession, models=[]):
        self.session = session
        self.chat = MfcWsChat(session)
        self.server_config = dict(
            ajax_servers=[],
        )
        self.models = [m.lower() for m in models]
        self.streams = {}
        self.progress_log_task = None

    @classmethod
    async def create(cls, models: List[str] = []):
        headers = {"Referrer": REFERRER, "User-Agent": USER_AGENT}
        session = ClientSession(headers=headers, raise_for_status=True)
        return cls(session, models=models)

    async def progress_log(self):
        try:
            while True:
                for mn in sorted(self.streams):
                    stream_loader: StreamLoader
                    stream_loader = self.streams[mn]
                    if stream_loader.in_progress:
                        logger.info(f'{mn} -> {stream_loader.status}')
                await asyncio.sleep(6)
        except asyncio.CancelledError:
            pass

    async def grab(self):
        await self.get_server_config()
        logger.info("Server config loaded")
        ws_server = self.get_ws_server()
        await self.chat.connect(ws_server)
        await self.lookup_modes()
        self.progress_log_task = asyncio.create_task(self.progress_log())

        message: Message
        async for message in self.chat:
            if not message:
                break
            if message.n_type in (10, 20):
                if not isinstance(message.payload, dict):
                    continue
                if nm := message.payload.get("nm", None):
                    if nm.lower() in self.models:
                        await self.handle_model(message)

    async def handle_model(self, message: Message):
        message.payload = cast(dict, message.payload)
        model_name = message.payload["nm"]
        if model_name not in self.streams:
            stream_loader = StreamLoader(self.session, model_name)
            self.streams[model_name] = stream_loader

        stream_loader = self.streams[model_name]

        video_status = message.payload["vs"]
        # 0 == model in public chat
        if video_status == 0:
            if stream_loader.in_progress:
                logger.debug('{} already in progress'.format(
                    model_name
                ))
                return
            logger.info(f"{model_name} status is {MODEL_STATUS[video_status]}")
            try:
                camserv = message.payload["u"]["camserv"]
            except KeyError:
                logger.warning(
                    f"{model_name}:No camserver - model webcam is offline yet"
                )
                return
            model_uid = message.payload["uid"]
            hls_url = self.build_hls_url(camserv, model_uid)
            if hls_url is not None:
                stream_loader.start_capture(hls_url)
            else:
                logger.info(f"Cannot get sream URL for {model_name}")
        else:

            m_status = MODEL_STATUS.get(video_status, video_status)
            logger.info(f"{model_name} status is {m_status}")
            stream_loader.stop_capture()

    def get_video_server(self, camserv: int):
        camserv = str(camserv)
        server_types = [
            "h5video_servers",
            "ngvideo_servers",
            "wzobs_servers",
        ]
        server_type: str
        for server_type in server_types:
            v_servers = self.server_config[server_type]
            if camserv in v_servers:
                return v_servers[camserv]

    def build_hls_url(
        self,
        camserv: int,
        model_uid: int,
    ):
        video_server = self.get_video_server(camserv)
        if not video_server:
            return
        room_id = model_uid + 100000000
        path = f"/NxServer/ngrp:mfc_{room_id}.f4v_mobile/playlist.m3u8"
        url = URL.build(
            scheme="https",
            port=443,
            host=f"{video_server}.myfreecams.com",
            path=path,
            query={"nc": random()},
        )
        return url

    def get_ws_server(self):
        ws_servers = list(self.server_config["websocket_servers"].keys())
        return choice(ws_servers)

    async def get_server_config(self):
        main_page = await self.load_main_page()
        g_nVcc = re.search(r"var g_nVcc = (\d+);", main_page).group(1)
        g_nVcc = int(g_nVcc)
        nc = time() * 1000 // 86400 + g_nVcc
        server_config_url = URL.build(
            scheme="https",
            host="assets.mfcimg.com",
            path="/_js/serverconfig.js",
            query={"nc": str(nc)},
        )
        resp: ClientResponse
        async with self.session.get(server_config_url) as resp:
            self.server_config = await resp.json(content_type=None)

    async def load_main_page(self):
        url = "https://www.myfreecams.com/"
        async with self.session.get(url) as resp:
            return await resp.text()

    async def lookup_modes(self):
        for model in self.models:
            query_type = 10
            query_sign = self.get_lookup_query_sign(model)
            query_string = "{} {} 0 {} 0 {}\n".format(
                query_type, self.chat.user_session_id, query_sign, model
            )
            await self.chat.send_message(query_string)

    @staticmethod
    def get_lookup_query_sign(model_name: str) -> int:
        now = int(time() * 1000)
        s = f"{model_name}{now}{{}}"
        return abs(MfcCrc32.string(s))

    async def stop(self):
        if self.session and not self.session.closed:
            if self.chat.connected:
                logger.info("Stop chat")
                await self.chat.disconnect()
            await self.session.close()
        if self.progress_log_task is not None:
            if not self.progress_log_task.done():
                self.progress_log_task.cancel()
                await self.progress_log_task


def main():
    loop = asyncio.get_event_loop()
    grabber = loop.run_until_complete(
        MfcGrabber.create(
            models=[
                "abbypink",
                "ENGLISH_GIGI",
                "Boobylana",
                "Megan_slut",
                "Hanna_BBW",
                "KattyDesire",
                "MaaaJooo",
                "Sasha_foxy",
                "AshleyBlondyy",
            ]
        )
    )
    try:
        loop.run_until_complete(grabber.grab())
    except KeyboardInterrupt:
        loop.run_until_complete(grabber.stop())


if __name__ == "__main__":
    main()
