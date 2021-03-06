#!/usr/bin/env python3.6

"""Module for sensor communication."""

__author__ = 'Philipp Engel'
__copyright__ = 'Copyright (c) 2017 Hochschule Neubrandenburg'
__license__ = 'BSD-2-Clause'

# Build-in modules.
import copy
import errno
import re
import socket
import time

from threading import Thread
from typing import Union

# Third-party modules.
import arrow
import serial

# OpenADMS Node modules.
from core.observation import Observation
from core.manager import Manager
from core.system import System
from core.prototype import Prototype


class BluetoothPort(Prototype):
    """
    BluetoothPort is used for RFCOMM serial communication. It initiates a
    socket connection to a sensor by using the native Bluetooth support of
    Python 3.3. At the moment, the class is not very useful and needs further
    testing.

    The JSON-based configuration for this module:

    Parameters:
        port (str): Port name.
        serverMacAddress (str): MAC address of the server.
    """

    def __init__(self, module_name: str, module_type: str, manager: Manager):
        super().__init__(module_name, module_type, manager)
        config = self.get_module_config('ports', 'bluetooth', self._name)
        self._port = config.get('port')
        self._server_mac_address = None
        self._sock = None

        valid_mac = self.get_mac_address(config.get('serverMacAddress'))

        if not valid_mac:
            raise ValueError(f'Invalid MAC address '
                             f'"{config.get("serverMacAddress")}"')

        self._server_mac_address = valid_mac

        if System.is_windows():
            raise EnvironmentError(errno.ESOCKTNOSUPPORT,
                                   'Operating system not supported (no '
                                   'socket.AF_BLUETOOTH on Microsoft Windows)')

    def __del__(self):
        self.close()

    def close(self) -> None:
        """Closes the socket connection."""
        if self._sock:
            self.logger.info(f'Closing port "{self._port}" ...')
            self._sock.close()

    def get_mac_address(self, s: str) -> Union[str, None]:
        """Re-formats a given MAC address.

        Args:
            s: String with MAC address.

        Returns:
            String with valid MAC address or None if address is invalid.
        """
        if re.match(r'^[a-fA-F0-9]{2}(?::[a-fA-F0-9]{2}){5}$', s):
            return s

        if re.match(r'^[a-fA-F0-9]{12}$', s):
            f = re.findall('..', s)
            return '{}:{}:{}:{}:{}:{}'.format(*f)

    def process_observation(self, obs: Observation) -> Union[Observation, None]:
        """Sends a request to the attached sensor and forwards the response.

        Args:
            obs: Observation object.

        Returns:
            The extended observation object or None if connection failed.
        """
        if not self._sock:
            # Open socket connection.
            if not self._open():
                return

        # Add the name of the Bluetooth port to the observation.
        obs.set('portName', self.name)

        requests_order = obs.get('requestsOrder', [])
        request_sets = obs.get('requestSets')

        if not requests_order:
            self.logger.notice(f'No requests order defined in observation '
                               f'"{obs.get("name")}" of target '
                               f'"{obs.get("target")}"')

        # Send requests sequentially to the sensor.
        for request_name in requests_order:
            request_set = request_sets.get(request_name)

            if not request_set:
                self.logger.error(f'Request set "{request_name}" not found in '
                                  f'observation "{obs.get("name")}" of target '
                                  f'"{obs.get("target")}"')
                return

            # The response of the sensor.
            response = ''
            response_delimiter = request_set.get('responseDelimiter')

            # Data of the request set.
            request = request_set.get('request')
            sleep_time = request_set.get('sleepTime') or 1.0
            timeout = request_set.get('timeout') or 1.0

            # Send the request of the observation to the attached sensor.
            self.logger.verbose(f'Sending request "{request_name}" of '
                                f'observation "{obs.get("name")}" to sensor '
                                f'"{obs.get("sensorName")}" ...')
            # Write to Bluetooth port.
            self._send(request)

            # Get the response of the sensor.
            response = self._receive(response_delimiter, timeout)

            self.logger.verbose(f'Received response '
                                f'"{self.sanitize(response)}" for request '
                                f'"{request_name}" of observation '
                                f'"{obs.get("name")}" from sensor '
                                f'"{obs.get("sensorName")}"')
            # Add the raw response of the sensor to the observation set.
            request_set['response'] = response

            # Add the timestamp to the observation.
            obs.set('timestamp', str(arrow.utcnow()))

            # Sleep until the next request.
            time.sleep(sleep_time)

        return obs

    def _open(self) -> None:
        """Opens a Bluetooth socket connection to a sensor."""
        if not self._server_mac_address:
            self.logger.error('MAC address of server not set')
            return

        try:
            self._sock = socket.socket(socket.AF_BLUETOOTH,
                                       socket.SOCK_STREAM,
                                       socket.BTPROTO_RFCOMM)
            self._sock.connect((self._server_mac_address, self._port))
        except OSError as e:
            self.logger.error(e)

    def _receive(self, eol: str, timeout: float = 30.0) -> str:
        """Reads from Bluetooth connection."""
        response = ''
        start_time = time.time()

        # Read from Bluetooth port until delimiter occurs.
        while True:
            try:
                rxd = self._sock.recv(1).decode()
                response += rxd

                # Did we get an end of line (e.g., '\r' or '\n')?
                i = len(eol)

                if len(response) >= len(eol) and response[-i:] == eol:
                    break
            except UnicodeDecodeError:
                self.logger.error('No sensor on port "{}"'
                                  .format(self._port))
                break

            if time.time() - start_time > timeout:
                self.logger.warning(f'Timeout on port "{self._port}" after '
                                    f'{timeout} s')
                break

        return response

    def sanitize(self, s: str) -> str:
        """Escapes some non-printable characters in a given string.

        Args:
            s: String to sanitize.

        Returns:
            Sanitized string.
        """
        return s.replace('\n', '\\n')\
                .replace('\r', '\\r')\
                .replace('\t', '\\t')\
                .strip()

    def _send(self, data: str) -> None:
        """Sends command to sensor.

        Args:
            data: Data to send.
        """
        self._sock.send(bytes(data, 'UTF-8'))


class SerialPortConfiguration:
    """
    SerialPortConfiguration saves a serial port configuration.

    Args:
        port: Name of the port (e.g.: `COM1` or `/dev/tty0`).
        baudrate: Baud rate (e.g.: 4800, 9600, or 115200).
        bytesize: Start bits, either 5, 6, 7, or 8.
        stopbits: Stop bits, either 1, 1.5, or 2.
        parity: Parity, either `none`, `even`, `odd`, `mark`, or `space`.
        timeout (float): Timeout in seconds.
        xonxoff: Software flow control.
        rtscts: Hardware flow control.
    """

    def __init__(self,
                 port: str,
                 baudrate: int,
                 bytesize: int,
                 stopbits: float,
                 parity: str,
                 timeout: float,
                 xonxoff: bool,
                 rtscts: bool):
        """Converts data from JSON format to serial.Serial format."""
        self._port = port
        self._baudrate = baudrate
        self._bytesize = {
            5: serial.FIVEBITS,
            6: serial.SIXBITS,
            7: serial.SEVENBITS,
            8: serial.EIGHTBITS
        }[bytesize]
        self._stopbits = {
            1: serial.STOPBITS_ONE,
            1.5: serial.STOPBITS_ONE_POINT_FIVE,
            2: serial.STOPBITS_TWO
        }[stopbits]
        self._parity = {
            'none': serial.PARITY_NONE,
            'even': serial.PARITY_EVEN,
            'odd': serial.PARITY_ODD,
            'mark': serial.PARITY_MARK,
            'space': serial.PARITY_SPACE
        }[parity]
        self._timeout = timeout
        self._xonxoff = xonxoff
        self._rtscts = rtscts

    @property
    def port(self):
        return self._port

    @property
    def baudrate(self):
        return self._baudrate

    @property
    def bytesize(self):
        return self._bytesize

    @property
    def stopbits(self):
        return self._stopbits

    @property
    def parity(self):
        return self._parity

    @property
    def timeout(self):
        return self._timeout

    @property
    def xonxoff(self):
        return self._xonxoff

    @property
    def rtscts(self):
        return self._rtscts


class SerialPort(Prototype):
    """
    SerialPort does I/O on a given serial port. The port can be used in either
    active or passive mode. In active mode, the communication with the sensor is
    based on request/response. In passive mode, the port just listens for
    incoming data without sending any requests.

    The JSON-based configuration for this module:

    Parameters:
        port (str): Name of the port (e.g.: `COM1` or `/dev/tty0`).
        baudRate (int): Baud rate (e.g.: 4800, 9600, or 115200).
        byteSize (int): Start bits, either 5, 6, 7, or 8.
        stopBits (float): Stop bits, either 1, 1.5, or 2.
        parity (str): Parity, either `odd`, `even`, or `none`.
        softwareFlowControl (bool): XON/XOFF flow control.
        hardwareFlowControl (bool): RTS/CTS flow control.
        maxAttempts (int): Maximum number of attempts to access the port.
        timeout (float): Timeout in seconds.
    """

    def __init__(self, module_name: str, module_type: str, manager: Manager):
        super().__init__(module_name, module_type, manager)
        self._config = self.get_module_config('ports', 'serial', self.name)
        self._max_attempts = self._config.get('maxAttempts')

        # Serial port.
        self._serial = None
        self._serial_port_config = None

        # Passive mode.
        self._is_passive = False
        self._passive_listener = None

    def __del__(self):
        self._is_running = False

        if self._serial:
            self.close()

    def close(self) -> None:
        if self._serial:
            self.logger.verbose(f'Closing port '
                                f'"{self._serial_port_config.port}" ...')
            self._serial.close()

    def _create(self) -> None:
        """Opens a serial port."""
        if not self._serial_port_config:
            self._serial_port_config = self._get_port_config()

        self.logger.verbose(f'Opening port "{self._serial_port_config.port}" '
                            f'...')

        try:
            self._serial = serial.Serial(
                port=self._serial_port_config.port,
                baudrate=self._serial_port_config.baudrate,
                timeout=self._serial_port_config.timeout,
                bytesize=self._serial_port_config.bytesize,
                parity=self._serial_port_config.parity,
                stopbits=self._serial_port_config.stopbits,
                xonxoff=self._serial_port_config.xonxoff,
                rtscts=self._serial_port_config.rtscts)
        except serial.serialutil.SerialException:
            self.logger.error(f'Permission denied for port '
                              f'"{self._serial_port_config.port}"')

    def process_observation(self, obs: Observation) -> Union[Observation, None]:
        """Processes an observation object. Sends request to sensor and stores
        response.

        Args:
            obs: The observation object.

        Returns:
            The processed observation.
        """
        # Turn on passive mode.
        if obs.get('passiveMode'):
            if self._is_passive:
                # Restart passive listener.
                self._is_passive = False
                self._passive_listener.join()

            self._is_passive = True
            self._passive_listener = Thread(target=self.listen, args=(obs,))
            self._passive_listener.daemon = True
            self._passive_listener.start()
            self.logger.debug(f'Started passive listener of port "{self.name}"')
            return

        # Turn off passive mode.
        if self._is_passive and not obs.get('passiveMode'):
            self._is_passive = False
            self._passive_listener.join()
            self.logger.debug(f'Stopped passive listener of port "{self.name}"')

        # Create new serial connection.
        if not self._serial:
            self._create()

        if self._serial is None:
            self.logger.error(f'Could not access port '
                              f'"{self._serial_port_config.port}"')
            return

        if not self._serial.is_open:
            self.logger.verbose(f'Re-opening port '
                                f'"{self._serial_port_config.port}" ...')
            self._serial.open()
            self._serial.reset_output_buffer()
            self._serial.reset_input_buffer()

        # Add the name of this serial port module to the observation.
        obs.set('portName', self._name)

        requests_order = obs.get('requestsOrder', [])
        request_sets = obs.get('requestSets')

        if not requests_order:
            self.logger.notice(f'No requests order defined in observation '
                               f'"{obs.get("name")}" of target '
                               f'"{obs.get("target")}"')

        # Send requests sequentially to the sensor.
        for request_name in requests_order:
            request_set = request_sets.get(request_name)

            if not request_set:
                self.logger.error(f'Request set "{request_name}" not found in '
                                  f'observation "{obs.get("name")}" of target '
                                  f'"{obs.get("target")}"')
                return

            # The response of the sensor.
            response = ''
            response_delimiter = request_set.get('responseDelimiter')

            # Data of the request set.
            request = request_set.get('request')
            sleep_time = request_set.get('sleepTime') or 0.0
            timeout = request_set.get('timeout') or 0.0

            # Send the request of the observation to the attached sensor.
            self.logger.verbose(f'Sending request "{request_name}" of '
                                f'observation "{obs.get("name")}" to sensor '
                                f'"{obs.get("sensorName")}" ...')

            for attempt in range(self._max_attempts):
                if attempt > 0:
                    self.logger.info(f'Request attempt {attempt + 1} of '
                                     f'{self._max_attempts}')
                    time.sleep(1)

                # Write to the serial port.
                self._write(request)

                # Get the response of the sensor.
                response = self._read(eol=response_delimiter,
                                      length=0,
                                      timeout=timeout)

                self._serial.reset_output_buffer()
                self._serial.reset_input_buffer()

                if response:
                    self.logger.verbose(f'Received response '
                                        f'"{self.sanitize(response)}" for '
                                        f'request "{request_name}" of '
                                        f'observation "{obs.get("name")}" from '
                                        f'sensor "{obs.get("sensorName")}"')
                    break

                # Try next attempt if response is empty.
                self.logger.warning(f'No response from sensor '
                                    f'"{obs.get("sensorName")}" for '
                                    f'observation "{obs.get("name")}" of '
                                    f'target "{obs.get("target")}"')

            # Add the raw response of the sensor to the observation set.
            request_set['response'] = response
            # Add the timestamp to the observation.
            obs.set('timestamp', str(arrow.utcnow()))
            # Sleep until the next request.
            time.sleep(sleep_time)

        return obs

    def _get_port_config(self) -> SerialPortConfiguration:
        if not self._config:
            self.logger.debug(f'Port "{self.name}" is undefined')

        return SerialPortConfiguration(
            port=self._config.get('port'),
            baudrate=self._config.get('baudRate'),
            bytesize=self._config.get('byteSize'),
            stopbits=self._config.get('stopBits'),
            parity=self._config.get('parity'),
            timeout=self._config.get('timeout'),
            xonxoff=self._config.get('softwareFlowControl'),
            rtscts=self._config.get('hardwareFlowControl')
        )

    def listen(self, obs_draft: Observation) -> None:
        """Threaded method for passive mode. Reads incoming data from serial
        port. Used for sensors which start streaming data without prior
        request.

        Args:
            obs_draft: The observation draft with the response pattern.
        """
        while self._is_running and self._is_passive:
            if not obs_draft:
                self.logger.warning(f'No draft observation set for passive '
                                    f'listener on port "{self.name}"')
                break

            if not self._serial:
                self._create()

            if self._serial is None:
                self.logger.error(f'Can\'t access port '
                                  f'"{self._serial_port_config.port}" for '
                                  f'passive listening')

                return

            if not self._serial.is_open:
                self.logger.info(f'Re-opening port '
                                 f'"{self._serial_port_config.port}" for '
                                 f'passive listening ...')
                self._serial.open()
                self._serial.reset_input_buffer()

            obs = copy.deepcopy(obs_draft)
            obs.set('id', Observation.get_new_id())
            obs.set('portName', self.name)

            draft = obs.get('requestSets').get('draft')

            timeout = draft.get('timeout', 1.0)
            response_delimiter = draft.get('responseDelimiter', '')
            length = draft.get('responseLength', 0)
            request = draft.get('request')

            if request:
                self._write(request)

            response = self._read(eol=response_delimiter,
                                  length=length,
                                  timeout=timeout)

            if response:
                self.logger.verbose(f'Received "{self.sanitize(response)}" '
                                    f'from sensor "{obs.get("sensorName")}" on '
                                    f'port "{self._name}"')
                draft['response'] = response
                obs.set('timestamp', str(arrow.utcnow()))
                self.publish_observation(obs)

    def _read(self,
              eol: str = None,
              length: int = 0,
              timeout: float = 10.0) -> str:
        """Reads from serial port."""
        response = ''
        start_time = time.time()
        c = 0                       # Character index.

        # Read from serial port until delimiter occurs or maximum length of
        # response is reached.
        while True:
            try:
                rxd = self._serial.read(1).decode()
                response += rxd

                if length and length > 0:
                    c += 1

                    if c == length:
                        break

                if eol:
                    # Did we get an end of line (e.g., '\r' or '\n')?
                    i = len(eol)

                    if len(response) >= len(eol) and response[-i:] == eol:
                        break
            except UnicodeDecodeError:
                self.logger.error(f'No sensor on port '
                                  f'"{self._serial_port_config.port}"')
                break

            if time.time() - start_time > timeout:
                self.logger.warning(f'Timeout on port '
                                    f'"{self._serial_port_config.port}" after '
                                    f'{timeout} s')
                break

        return response

    def sanitize(self, s: str) -> str:
        """Escapes some non-printable characters in a given string."""
        return s.replace('\n', '\\n')\
                .replace('\r', '\\r')\
                .replace('\t', '\\t')\
                .strip()

    def _write(self, data: str):
        """Sends command to sensor."""
        self._serial.write(data.encode())
