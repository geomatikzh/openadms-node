#!/usr/bin/env python3
"""
Copyright (c) 2016 Hochschule Neubrandenburg.

Licensed under the EUPL, Version 1.1 or - as soon they will be approved
by the European Commission - subsequent versions of the EUPL (the
"Licence");

You may not use this work except in compliance with the Licence.

You may obtain a copy of the Licence at:

    http://ec.europa.eu/idabc/eupl

Unless required by applicable law or agreed to in writing, software
distributed under the Licence is distributed on an "AS IS" basis,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the Licence for the specific language governing permissions and
limitations under the Licence.
"""

import logging
import math
import random
import re
import time

from modules.prototype import Prototype

"""Module for virtual sensors."""

logger = logging.getLogger('openadms')


class VirtualSensor(Prototype):

    def __init__(self, name, config_manager, sensor_manager):
        Prototype.__init__(self, name, config_manager, sensor_manager)
        self.patterns = {}

    def action(self, obs):
        await_time = obs.get('AwaitTime')
        request = obs.get('Request')
        response = ''

        logger.info('Sending observation "{}" to sensor "{}" on virtual port '
                    '"{}"'.format(obs.get('Name'),
                                  obs.get('SensorName'),
                                  self.name))

        for pattern in self.patterns:
            reg_exp = re.compile(pattern)
            parsed = reg_exp.search(request)

            if not parsed:
                continue

            response = self.patterns[pattern](request)
            break

        obs.set('PortName', self._name)
        obs.set('Response', response)
        obs.set('TimeStamp', time.time())

        time.sleep(0.25 * await_time)

        return obs


class VirtualLeicaTM30(VirtualSensor):

    """
    VirtualLeicaTotalstation simulates a Leica TM30 totalstation by processing
    GeoCOM commands.
    """

    def __init__(self, name, config_manager, sensor_manager):
        VirtualSensor.__init__(self, name, config_manager,
                               sensor_manager)

        self.patterns['%R1Q,5003:'] = self.get_sensor_id
        self.patterns['%R1Q,5004:'] = self.get_sensor_name
        self.patterns['%R1Q,9027:(-?[0-9]*\.?[0-9]+),(-?[0-9]*\.?[0-9]+),2,1,0'] = self.set_direction
        self.patterns['%R1Q,2008:1,1'] = self.measure_distance
        self.patterns['%R1Q,2167:5000,1'] = self.do_complete_measurement

    def do_complete_measurement(self, request):
        return_code = '0'
        hz = '{:0.15f}'.format(random.uniform(0, 2 * math.pi))
        v = '{:0.15f}'.format(random.uniform(1, 2))
        acc_angle = '{:0.15f}'.format(random.uniform(-1, 1) * 10e-6)
        c = '{:0.15f}'.format(random.uniform(-1, 1) * 10e-5)
        l = '{:0.15f}'.format(random.uniform(-1, 1) * 10e-5)
        acc_incl = '{:0.15f}'.format(random.uniform(-1, 1) * 10e-6)
        slope_dist = '{:0.15f}'.format(random.uniform(1, 2000))
        dist_time = '{:8.0f}'.format(random.uniform(4, 5) * 10e8)

        response = '%R1P,0,0:{},{},{},{},{},{},{},{},{}\r\n'.format(
            return_code,
            hz,
            v,
            acc_angle,
            c,
            l,
            acc_incl,
            slope_dist,
            dist_time)

        return response

    def get_sensor_id(self, request):
        return_code = '0'
        response = '%R1P,0,0:{},999999'.format(return_code)

        return response

    def get_sensor_name(self, request):
        return_code = '0'
        response = '%R1P,0,0:{},"TM30 0.5"'.format(return_code)

        return response

    def measure_distance(self, request):
        return_code = '0'
        response = '%R1P,0,0:{}\r\n'.format(return_code)

        return response

    def set_direction(self, request):
        return_code = '0'
        response = '%R1P,0,0:{}\r\n'.format(return_code)

        return response


class VirtualDTM(VirtualSensor):

    def __init__(self, name, config_manager, sensor_manager):
        VirtualSensor.__init__(self, name, config_manager,
                               sensor_manager)

        self.patterns['^A'] = self.power_on
        self.patterns['CMDT 1'] = self.set_command_set
        self.patterns['SAVE'] = self.save
        self.patterns['PRES ?'] = self.get_pressure
        self.patterns['TEMP ?'] = self.get_temperature

    def get_pressure(self, request):
        return '+{:06.1f}\r'.format(random.uniform(980, 1150))

    def get_temperature(self, request):
        t = random.uniform(-20, 40)

        if t < 0:
            return '{:07.1f}\r'.format(t)
        else:
            return '+{:06.1f}\r'.format(t)

    def get_pressure(self, request):
        return '+{:06.1f}\r'.format(random.uniform(980, 1150))

    def power_on(self, request):
        return '#\r'

    def save(self, request):
        return '*\r'

    def set_command_set(self, request):
        return '*\r'