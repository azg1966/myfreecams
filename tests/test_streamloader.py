from pytest import fixture
import pytest
from aiohttp import web, ClientSession
from myfreecams.streamloader import StreamLoader, PlaylistLoadError
import asyncio
import random
from pathlib import Path
from pytest_aiohttp import TestServer


@fixture
async def loader() -> StreamLoader:
    loader = StreamLoader(ClientSession(raise_for_status=True), "test_model")
    return loader


async def test_loader(server: TestServer, loader: StreamLoader):
    loader = StreamLoader(ClientSession(raise_for_status=True), "test_model")
    loader.start_capture(server.make_url("/playlist.m3u8"))
    assert loader.in_progress
    await asyncio.sleep(3)
    loader.stop_capture()
    assert not loader.in_progress
    assert loader.capture_task is None
    if loader.output_filename is not None:
        out_file = Path(loader.output_filename)
        assert out_file.exists()
        out_file.unlink()


async def test_load_resource(server: TestServer, loader: StreamLoader):
    text = await loader.load_resource(server.make_url("/text"))
    assert text == "Test message"


async def test_load_playlist(server: TestServer, loader: StreamLoader):
    pl = await loader.load_playlist(server.make_url("/playlist.m3u8"))
    assert pl is not None


async def test_load_403_playlist(server: TestServer, loader: StreamLoader):
    with pytest.raises(PlaylistLoadError):
        await loader.load_playlist(server.make_url("/status403"))
