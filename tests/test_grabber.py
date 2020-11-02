from myfreecams.mfcgrabber import MfcGrabber
from pytest import fixture
from server import server
from myfreecams.mfcgrabber import MfcGrabber
from myfreecams.mfcwschat import Message


@fixture
async def mfc_grabber(loop) -> MfcGrabber:
    grabber = await MfcGrabber.create(models=["Foo", "Bar"])
    grabber.server_config = {
        "h5video_servers": {"0": "", "1": "", "2": ""},
        "ngvideo_servers": {"0": "", "1": "", "2": ""},
        "wzobs_servers": {"0": "", "1": "", "2": ""},
    }
    yield grabber
    await grabber.stop()


async def test_handle_model(mfc_grabber: MfcGrabber):
    for model in mfc_grabber.models:
        payload = {"vs": 0, "nm": model, "uid": 321, "u": {"camserv": '1'}}
        msg = Message(10, 0, 0, 0, 0, payload=payload)
        await mfc_grabber.handle_model(msg)
