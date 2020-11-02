#!/usr/bin/env python
import asyncio
from myfreecams.mfcgrabber import MfcGrabber
from argparse import ArgumentParser


def main():
    parser = ArgumentParser()
    parser.add_argument("models", nargs="+")
    args = parser.parse_args()
    loop = asyncio.get_event_loop()
    grabber = loop.run_until_complete(MfcGrabber.create(models=args.models))
    try:
        loop.run_until_complete(grabber.grab())
    except KeyboardInterrupt:
        loop.run_until_complete(grabber.stop())


if __name__ == "__main__":
    main()
