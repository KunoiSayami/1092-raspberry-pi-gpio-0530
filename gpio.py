#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# gpio.py
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
import asyncio
import concurrent.futures
import logging
from typing import Optional, Sequence

import RPi.GPIO as GPIO
import Adafruit_DHT


logger = logging.getLogger('gpio.gpio')
logger.setLevel(logging.DEBUG)


class StandalonePWM:

    def __init__(self, pin: int):
        self.stop_request = asyncio.Event()
        self.pwm = GPIO.PWM(pin, 50)
        self.pwm.start(0)
        self._future: Optional[concurrent.futures.Future] = None

    async def runnable(self) -> None:
        while not self.stop_request.is_set():
            for dc in range(10):
                self.pwm.ChangeDutyCycle(dc * 10)
                await asyncio.sleep(.2)
            await asyncio.sleep(1)
            for dc in range(10, -1, -1):
                self.pwm.ChangeDutyCycle(dc * 10)
                await asyncio.sleep(.2)
            await asyncio.sleep(1)
        self.pwm.stop()
        self.pwm = None

    def set_stop(self) -> None:
        self.stop_request.set()

    def run(self) -> concurrent.futures.Future:
        self._future = asyncio.run_coroutine_threadsafe(self.runnable(), asyncio.get_event_loop())
        return self._future

    @property
    def future(self) -> concurrent.futures.Future:
        return self._future

    def force_stop(self):
        self._future.cancel()
        if self.pwm:
            self.pwm.stop()
            self.pwm = None


class LEDGPIO:
    pins = [17, 27, 22, 5, 6, 13, 19, 26]
    lock = asyncio.Lock()
    event = asyncio.Event()
    stop_event = asyncio.Event()

    def __init__(self) -> None:
        self.clean_required = asyncio.Event()
        self.breath_pwm: Optional[StandalonePWM] = None
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.pins, GPIO.OUT)

    @staticmethod
    async def _unsafe_set_light_flash(pins: Sequence[int]) -> None:
        for pin in pins:
            GPIO.output(pin, GPIO.HIGH)
        await asyncio.sleep(0.2)
        for pin in pins:
            GPIO.output(pin, GPIO.LOW)

    async def set_light_flash(
            self,
            times: int = 1,
            *,
            custom_pins: Sequence[int] = None,
            is_odd: bool = True) -> None:
        if custom_pins is None:
            pins = self.pins[int(not is_odd):: 2]
        else:
            pins = custom_pins
        await self._set_light_flash_num(times, pins)

    async def _set_light_flash_num(self, times: int, pins: Sequence[int]) -> None:
        if self.clean_required.is_set():
            await self.clean_number()
        async with self.lock:
            self.event.set()
            self.stop_event.clear()
            for _ in range(times):
                if self.stop_event.is_set():
                    break
                await self._unsafe_set_light_flash(pins)
            self.event.clear()

    @staticmethod
    async def _unsafe_light_breath(pwms: Sequence[GPIO.PWM]) -> None:
        for dc in range(10):
            for pwm in pwms:
                pwm.ChangeDutyCycle(dc * 10)
            await asyncio.sleep(.05)
        await asyncio.sleep(.05)
        for dc in range(10, -1, -1):
            for pwm in pwms:
                pwm.ChangeDutyCycle(dc * 10)
            await asyncio.sleep(.05)

    async def set_light_breath(
            self,
            times: Optional[int] = 1,
            pins: Optional[Sequence[int]] = None
    ) -> None:
        if pins is None:
            pins = self.pins
        else:
            pins = [self.pins[x - 1] for x in pins]
        if self.clean_required.is_set():
            await self.clean_number()
        async with self.lock:
            self.event.set()
            self.stop_event.clear()
            pwms = [GPIO.PWM(pin, 50) for pin in pins]
            for pwm in pwms:
                pwm.start(0)
            if times is None:
                while True:
                    if self.stop_event.is_set():
                        break
                    await self._unsafe_light_breath(pwms)
                    await asyncio.sleep(.05)
            else:
                for _ in range(times):
                    if self.stop_event.is_set():
                        break
                    await self._unsafe_light_breath(pwms)
                    await asyncio.sleep(.05)
            for pwm in pwms:
                pwm.stop()
            self.event.clear()

    async def show_number(self, number: int, show_breath: bool = True) -> None:
        print(number)
        if not (128 > number > 0):
            raise ValueError('Number should smaller then 128 or bigger then 0')
        async with self.lock:
            self.event.set()
            if show_breath:
                self.breath_pwm = StandalonePWM(self.pins[0])
                self.breath_pwm.run()
            self.clean_required.set()
            b = f'{int(bin(number)[2:]):07}'
            for i in range(7):
                GPIO.output(self.pins[i + 1], GPIO.HIGH if int(b[i]) else GPIO.LOW)
            self.event.clear()

    async def clean_number(self) -> None:
        async with self.lock:
            if self.breath_pwm:
                self.breath_pwm.set_stop()
                try:
                    self.breath_pwm.future.result(1)
                except concurrent.futures.TimeoutError:
                    self.breath_pwm.force_stop()
            for pin in self.pins:
                GPIO.output(pin, GPIO.LOW)
            self.clean_required.clear()

    async def close(self) -> None:
        if self.event.is_set():
            raise RuntimeError('Some work is still running')
        if self.clean_required:
            await self.clean_number()
        GPIO.cleanup()


class DHTSensor:
    DHT_SENSOR = Adafruit_DHT.DHT22
    DHT_PIN = 12

    @classmethod
    def get_data(cls) -> tuple[float, float]:
        humidity, temperature = Adafruit_DHT.read_retry(cls.DHT_SENSOR, cls.DHT_PIN)
        return humidity, temperature
