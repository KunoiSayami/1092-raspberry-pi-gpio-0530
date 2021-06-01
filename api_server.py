#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# api_server.py
# Copyright (C) 2021 KunoiSayami
#
# This module is part of 1092-raspberry-pi-gpio-0530 and is released under
# the AGPL v3 License: https://www.gnu.org/licenses/agpl-3.0.txt
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
from __future__ import annotations
import asyncio
import logging
import sys
import signal
import os
from types import FrameType
from typing import Optional

from aiohttp import web

import gpio
from gpio import LEDGPIO, DHTSensor

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)


class Server:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.gpio: Optional[LEDGPIO] = None
        self.website = web.Application()
        self.bind = host
        self.port = port
        self.site = None
        self.runner = web.AppRunner(self.website)
        self._idled = False

    async def light_control(self, _request: web.Request) -> web.Response:
        await self.gpio.set_light_flash(3, custom_pins=self.gpio.pins)
        return web.json_response(dict(status=200))  # , headers={'Access-Control-Allow-Origin': '*'})

    async def breath_control(self, _request: web.Request) -> web.Response:
        await self.gpio.set_light_breath()
        return web.json_response(dict(status=200))

    async def show_number(self, request: web.Request) -> web.Response:
        req = await request.json()
        if (num := req.get('number')) is not None:
            try:
                await self.gpio.show_number(int(num))
            except ValueError:
                logger.exception('Got exception:')
                return web.json_response(dict(reason='Check your value'), status=400)
        return web.json_response(dict(status=200))

    @staticmethod
    async def get_temperature(_request: web.Request) -> web.Response:
        humidity, temperature = DHTSensor.get_data()
        return web.json_response(dict(status=200, humidity=humidity, temperature=temperature))

    @staticmethod
    async def hello(_request: web.Request) -> web.Response:
        return web.json_response(dict(status=200))

    async def start(self) -> None:
        self.gpio = LEDGPIO()
        self.website.router.add_get('/', self.hello)
        self.website.router.add_post('/light', self.light_control)
        self.website.router.add_post('/number', self.show_number)
        self.website.router.add_post('/breath', self.breath_control)
        self.website.router.add_get('/temperature', self.get_temperature)
        self.website.on_shutdown.append(self.handle_web_shutdown)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, self.bind, self.port)
        await self.site.start()

    @staticmethod
    async def handle_web_shutdown(_app: web.Application) -> None:
        pass

    async def idle(self):
        self._idled = True

        for sig in (signal.SIGINT, signal.SIGABRT, signal.SIGTERM):
            signal.signal(sig, self._reset_idle)

        while self._idled:
            await asyncio.sleep(1)

    def _reset_idle(self, signal_: signal.Signals, _frame_type: FrameType) -> None:
        if not self._idled:
            logger.debug('Got signal %s, killing...', signal_)
            os.kill(os.getpid(), signal.SIGKILL)
        else:
            logger.debug('Got signal %s, stopping...', signal_)
            self._idled = False

    async def stop(self) -> None:
        await self.site.stop()
        await self.runner.cleanup()
        try:
            await self.gpio.close()
        except:
            gpio.GPIO.close()
            raise


def get_argument(arg: str, default: Optional[str]) -> Optional[str]:
    try:
        index = sys.argv.index(arg)
        return sys.argv[index + 1]
    except (ValueError, IndexError):
        pass
    return default


async def main():
    server = Server(get_argument('--host', '0.0.0.0'), int(get_argument('--port', '8081')))
    await server.start()
    await server.idle()
    await server.stop()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(levelname)s - %(name)s - %(funcName)s - %(lineno)d - %(message)s')
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
    loop.run_until_complete(asyncio.sleep(0.25))
    loop.close()
