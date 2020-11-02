import asyncio
import aiohttp
from typing import List, Union, Optional, Tuple
from yarl import URL
from time import time
from datetime import datetime
import logging
import math


logger = logging.getLogger(__name__)


class PlaylistLoadError(Exception):
    pass


class StreamLoader(object):

    session: aiohttp.ClientSession
    model_name: str
    playlist_url: URL
    sequence_number: int
    capture_task: Optional[asyncio.Task]
    loaded_bytes: int
    # log_msg_time: float
    output_filename: Optional[str]

    def __init__(
        self,
        session: aiohttp.ClientSession,
        model_name: str,
    ) -> None:
        self.session = session
        self.model_name = model_name
        self.sequence_number = 0
        self.loaded_bytes = 0
        self.capture_task = None
        self.log_msg_time = 0
        self.output_filename = None

    @property
    def in_progress(self) -> bool:
        if self.capture_task is None:
            return False
        if self.capture_task.done():
            self.capture_task = None
            return False
        return True


    @property
    def status(self) -> Optional[str]:
        return f"{self.model_name}: -> {self.output_filename} {self.convert_size(self.loaded_bytes)}"

    @staticmethod
    def convert_size(size_bytes: int) -> str:
        if size_bytes == 0:
            return "0B"
        size_names = ("B", "KB", "MB", "GB", "TB")
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s}{size_names[i]}"

    def get_filename(self) -> str:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        return f"{self.model_name}_{timestamp}.mp4"

    def start_capture(self, playlist_url: Union[str, URL]):
        self.loaded_bytes = 0
        self.sequence_number = 0
        # self.log_msg_time = time()
        self.output_filename = self.get_filename()
        self.capture_task: asyncio.Task = asyncio.create_task(
            self.capture_stream(playlist_url)
        )
        self.capture_task.add_done_callback(self.task_done)

    def task_done(self, task: asyncio.Task):
        self.capture_task = None

    def stop_capture(self):
        if self.capture_task is not None:
            self.capture_task.cancel()
            self.capture_task = None
        self.output_filename = None

    async def load_playlist(self, playlist_url: Union[str, URL]) -> str:
        max_tries = 10
        for i in range(max_tries):
            try:
                pl = await self.load_resource(playlist_url)
                return pl
            except aiohttp.ClientResponseError as e:
                logger.warning(
                    "{}: Cannot load master playlist {}, HTTPstatus: {}".format(
                        self.model_name, playlist_url, e.status
                    )
                )
        raise PlaylistLoadError



    async def capture_stream(self, playlist_url: Union[str, URL]):
        playlist_url = URL(playlist_url)
        try:
            mpl = await self.load_playlist(playlist_url)
        except PlaylistLoadError:
            logger.warning("Cannot load master playlist")
            return

        # parse chunklist url from master playlist
        chl_url = self.parse_playlist(mpl)
        if chl_url is None:
            logger.warning("No chunklist url in master playlist")
            return

        # change replace playlist path to chunklist path
        chl_url = playlist_url.join(URL(chl_url))
        broken_chunks_count = 0
        max_broken_chunks = 5
        while broken_chunks_count < max_broken_chunks:
            try:
                chl = await self.load_resource(chl_url)
            except aiohttp.client_exceptions.ClientResponseError as e:
                logger.warning(
                    "{}: Cannot load chunklist, HTTPstatus: {}".format(
                        self.model_name, e.status
                    )
                )
                return
            seq_number, total_duration, chunks = self.parse_chunklist(chl)
            cl_start = time()

            # if chunklist loaded for the first time
            if self.sequence_number == 0:
                self.sequence_number = seq_number

            # slice already loaded chunks from list
            if self.sequence_number > seq_number:
                chunks = chunks[self.sequence_number - seq_number :]
            for chunk in chunks:
                chunk_url = playlist_url.join(URL(chunk))
                try:
                    data = await self.load_resource(chunk_url, raw=True)
                    if len(data) == 0:
                        broken_chunks_count += 1
                        continue
                except aiohttp.client_exceptions.ClientResponseError as e:
                    logger.warning(
                        "{}: Cannot load video chunk, HTTPstatus: {}".format(
                            self.model_name, e.status
                        )
                    )
                    broken_chunks_count += 1
                    continue
                self.loaded_bytes += len(data)

                with open(self.output_filename, "ab") as fd:
                    fd.write(data)
                self.sequence_number += 1
            load_duration = time() - cl_start
            if load_duration < total_duration / 2:
                await asyncio.sleep(total_duration / 4)
            # ct = time()
            # if ct - self.log_msg_time >= 6:
            #     logger.info(self.status)
            #     self.log_msg_time = ct


    async def load_resource(self, url: Union[str, URL], raw=False):
        resp: aiohttp.ClientResponse
        async with self.session.get(url) as resp:
            return await resp.text() if not raw else await resp.read()

    @staticmethod
    def parse_playlist(playlist: str) -> Optional[str]:
        for string in playlist.split("\n"):
            if string.startswith("chunklist"):
                return string
        return None

    @staticmethod
    def parse_chunklist(chunklist: str) -> Tuple[int, float, List[str]]:
        sequence_number: int = 0
        total_duration: float = 0
        chunks: List[str] = []
        for string in chunklist.split("\n"):
            if string.startswith("#EXT-X-MEDIA-SEQUENCE"):
                try:
                    sequence_number = int(string.split(":")[-1])
                except ValueError:
                    pass
            elif string.startswith("#EXTINF"):
                try:
                    total_duration += float(string.split(":")[-1][:-1])
                except ValueError:
                    pass
            elif string.startswith("media"):
                chunks.append(string)

        return (sequence_number, total_duration, chunks)
