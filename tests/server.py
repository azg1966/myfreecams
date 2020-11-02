from pytest import fixture
from aiohttp import web
from pytest_aiohttp import TestServer
import random


async def playlist(request: web.Request):
    if request.app["pl_count"] < 1:
        request.app["pl_count"] += 1
        raise web.HTTPForbidden()
    with open("./tests/resources/playlist.m3u8", "rb") as fd:
        return web.Response(body=fd.read())

async def status403(request: web.Request):
    raise wen.HTTPForbidden()


async def chunklist(request: web.Request):
    chunk_number = request.app["chunk_number"]
    cl = (
        "#EXTM3U\n"
        "#EXT-X-VERSION:5\n"
        "#EXT-X-TARGETDURATION:1\n"
        f"#EXT-X-MEDIA-SEQUENCE:{chunk_number}\n"
        "#EXT-X-DISCONTINUITY-SEQUENCE:0\n"
    )
    for i in range(5):

        cl += "#EXTINF:0.767,\n"
        cl += f"media_{chunk_number}.ts?nc=0.35348945913478917\n"
        chunk_number += 1
    request.app["chunk_number"] = chunk_number
    return web.Response(text=cl)


async def chunk(request: web.Request):
    request.match_info["cn"]
    chunk = b"chunk"
    return web.Response(body=chunk)

async def text(request: web.Request) -> web.Response:
    return web.Response(text='Test message')



@fixture
async def server(aiohttp_server) -> TestServer:
    app = web.Application()
    app["pl_count"] = 0
    app["chunk_number"] = random.randint(100, 1000)
    app.router.add_get("/playlist.m3u8", playlist)
    app.router.add_get("/403", status403)
    app.router.add_get("/chunklist.m3u8", chunklist)
    app.router.add_get(r"/media_{cn:\d+}.ts", chunk)
    app.router.add_get("/text", text)
    server = await aiohttp_server(app)
    return server
