import datetime
import json
import os
import socket
import time
import xml.etree.ElementTree as ElementTree
from multiprocessing import shared_memory, Queue, Process
from queue import Empty
import re
import signal
import ErrorCodes
from Command import CommandInterface
from Logger import Logger
from QueueIO import *
from Requests import *
from threading import Thread
from methods import link
import fcntl

SERVER_PORT = int(os.getenv('TCP_SERVER_PORT', 5887))
SHAREDMEM_WRITE_READY = bytes([1])
SHAREDMEM_READ_READY = bytes([0])
TCP_MESSAGE_SIZE_LENGTH = 4
TCP_MESSAGE_NUMBER_LENGTH = 8
TCP_CLIENT_TIMEOUT = 4
TCP_CLIENT_DISCONNECT = 'disconnect'
SHAREDMEM_WAIT_LIMIT = 10  # seconds
QUEUE_RESPONSE_TIMEOUT = 8
SHARED_MEM_UPDATE_RATE = 4
TCP_CLIENT_RATE = 0.5
TCP_RESPONSE_ERROR = 1
TCP_RESPONSE_NO_ERROR = 0
TCPCLIENT_CONNECTION_TIMEOUT = 5
TCPSERVERCLIENT_QUEUE_TIMEOUT = 0.5
TCPSERVER_SOCKET_TIMEOUT = 0.5
DEFINITIONS_MESSAGE_SIZE = 1024
INACTIVITY_TIMEOUT = 4

TCP_MESSAGE_HEADER_LENGTH = TCP_MESSAGE_SIZE_LENGTH + MESSAGE_HEADER_LENGTH


class SocketWrapper:
    def __init__(self, _socket=None, address=None):
        self.socket = _socket or socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.address = address

    def accept(self):
        conn, address = self.socket.accept()
        return SocketWrapper(conn, address), address

    def finish(self):
        try:
            self.socket.settimeout(0.5)
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.socket.close()

    def send_message(self, message, address):
        self.socket.sendto(TCPMessage(message=message).encode(), address or self.address)

    def get_data(self):
        Logger('SocketWrapper.get_data starting', 'D')
        return TCPServerClient.get_socket_data(self.socket)

    def settimeout(self, timeout):
        self.socket.settimeout(timeout)

    def setsockopt(self, *args):
        self.socket.setsockopt(args[0], args[1], args[2])

    def bind(self, args):
        self.socket.bind(args)

    def listen(self, arg):
        self.socket.listen(arg)

    def connect(self, args):
        self.socket.connect(args)

    def shutdown(self, arg):
        self.socket.shutdown(arg)

    def close(self):
        self.socket.close()

    def send(self, data):
        self.socket.send(data)

    def sendto(self, data, address):
        self.socket.sendto(data, address)

    def recv(self, size):
        return self.socket.recv(size)


class TCPMessage(Message):

    def decode(self, encoded_data):
        if self.has_length(encoded_data):
            super().decode(encoded_data[TCP_MESSAGE_SIZE_LENGTH:])
        else:
            super().decode(encoded_data)

    def encode(self):
        encoded_data = super().encode()
        return len(encoded_data).to_bytes(TCP_MESSAGE_SIZE_LENGTH, byteorder='big') + encoded_data

    # Test: test_TCPMessage_has_length
    @staticmethod
    def has_length(encoded_data):
        copy_encoded_data = encoded_data
        header = encoded_data[:MESSAGE_HEADER_LENGTH]
        encoded_data = encoded_data[MESSAGE_HEADER_LENGTH:]
        while encoded_data:
            try:
                data = encoded_data.decode('utf-8')
                match = re.search(r'^[?|!][a-z_]+#', data, flags=re.DOTALL)
                if match:
                    if len(header) == TCP_MESSAGE_HEADER_LENGTH:
                        return True
                    elif len(header) == MESSAGE_HEADER_LENGTH:
                        return False
                    else:
                        break
                header += bytes([encoded_data[0]])
                encoded_data = encoded_data[1:]
            except UnicodeDecodeError:
                if encoded_data[-1] != ord('#'):
                    encoded_data = encoded_data[:-1]
                else:
                    header += bytes([encoded_data[0]])
                    encoded_data = encoded_data[1:]
        raise TCPException('Encoded data {} has invalid format'.format(copy_encoded_data))


class TCPServerClient:
    def __init__(self, def_file=None, app_name=None, input_queue=None, output_queue=None, member_id=0):
        # self.request_definitions = RequestDefinitions(def_file, app_name)
        self.command_interface = CommandInterface()
        self.queue_io = QueueIO(input_queue, output_queue, def_file=def_file, app_name=app_name)
        self._state = 0
        self.states = {
            'INIT_STATE': 0,
            'ERROR_STATE': 1,
            'PENDING_DEFINITIONS_STATE': 2,
            'READY_STATE': 3,
        }
        self.error_code = ErrorCodes.NO_ERROR
        self._connected = False
        self.socket_port = SERVER_PORT
        self.member_id = member_id
        self.routing = {}
        Logger('TCPServerClient init with queue_io input_queue: {} output_queue: {}'
               .format(self.queue_io.input_queue, self.queue_io.output_queue), 'D')

    def __getattr__(self, item):
        if item == 'state':
            for desc, code in self.states.items():
                if code == self._state:
                    return desc
        elif item in self.states:
            return self.states[item]
        else:
            return self.__getattribute__(item)

    @property
    def connected(self):
        return self._connected

    @connected.setter
    def connected(self, connected):
        self._connected = connected

    def get_queue_response(self, request):
        return self.queue_io.send_request(request)

    # Test: test_TCPServerClient_get_socket_data
    @staticmethod
    def get_socket_data(connection):
        message_data = b''
        try:
            message_size = connection.recv(TCP_MESSAGE_SIZE_LENGTH)
            Logger('TCPServerClient.get_socket_data got message length {}'.format(message_size), 'D')
            if message_size:
                message_data = connection.recv(int.from_bytes(message_size, byteorder='big'))
        except ConnectionResetError:
            pass
        return message_data

    # Test: test_TCPServerClient_get_state_respond
    def get_state_respond(self, request):
        response = Response(message=request)
        response.data_type = 'str'
        response.set_data(self.state)
        response.identifier = self.error_code
        return response

    # Test: test_TCPServerClient_preprocess_request
    def preprocess_request(self, request):
        response = None
        if request.is_ping():
            response = Response(message=request)
        elif request.is_get_state():
            response = Response(message=request)
            response.set_data(self.state)
            response.identifier = self.error_code
        elif request.is_reset_definitions():
            response = self.reset_definitions(request)
        elif request.is_connect():
            self.set_state(self.READY_STATE)
            response = Response(message=request)
            response.set_data(ErrorCodes.COMMAND_SUCCESS)
        return response

    # Test: test_TCPServerClient_process_input_queue
    def process_input_queue(self):
        request = self.queue_io.get_input_message()
        if request:
            response = self.preprocess_request(request)
            if response:
                self.queue_io.send_response(response)
            else:
                raise RequestException('TCPServerClient received unknown request {} number {} hop {}'
                                       .format(request.what, request.number, request.hop),
                                       error_code=ErrorCodes.UNDEFINED_REQUEST_ERROR)

    def read_definitions(self, def_file, app_name):
        self.read_request_definitions(def_file, app_name)

    def read_request_definitions(self, def_file, app_name):
        self.queue_io.read_request_definitions(def_file, app_name)

    # Test: test_TCPServerClient_reset_definitions
    def reset_definitions(self, request):
        if isinstance(request, TCPRequest):
            Logger('TCPServerClient.reset_definitions received reset_definitions command through '
                   'socket. Pushing command to queue', 'D')
            self.queue_io.input_queue.put(Request(message=request).encode())
            response = link(target_request=request, sender=self.queue_io.output_queue)
        else:
            # self.queue_io.request_definitions = RequestDefinitions()
            self.queue_io.reset_definitions()
            response = Response(message=request)
        self.set_state(self.PENDING_DEFINITIONS_STATE)
        response.set_data(ErrorCodes.COMMAND_SUCCESS)
        return response

    def set_request_definitions(self, request_definitions):
        self.queue_io.set_all_definitions(request_definitions)
        self.queue_io.request_definitions.received_definitions = True

    def set_state(self, state):
        self._state = state

    # Test: test_TCPServerClient_process_request
    def process_request(self, request, connection, address):
        request = TCPRequest(message=request)
        Logger('TCPServerClient.process_request Processing request {} number {}'
               .format(request.what, request.number), 'D')
        response = self.preprocess_request(request)
        if response:
            connection.sendto(TCPResponse(message=response).encode(), address)
        else:
            request.add_hop()
            connection.sendto(request.encode(), address)
            command = self.queue_io.request_definitions.get(request.what)
            Logger('TCPServerClient.process_request Command to run is {}. Number of arguments: {}'
                   ' provided arguments: {}'.format(command.name, command.number_arguments, request.args), 'D')
            response = TCPResponse(message=request)
            # Start send_command in seperate thread and monitor the result queue
            result_queue = Queue()
            command_thread = Thread(target=self.command_interface.send_command,
                                    args=[command] + request.args,
                                    kwargs={'queue': result_queue})
            Logger('TCPServerClient.process_request starting command thread', 'D')
            command_thread.start()
            command_finished = False
            queue_empty = False
            while not (command_finished and queue_empty):
                try:
                    # command result: (command output data, identifier, completion flag)
                    command_result = result_queue.get(timeout=0.5)
                    Logger('TCPServerClient.process_request got result from queue: {}'.format(command_result), 'D')
                    queue_empty = False
                    command_finished = command_result[2] is True or not command_thread.is_alive()
                    if command_result[2]:
                        response.set_data(command_result[0])
                        response.identifier = command_result[1]
                        Logger('TCPServerClient.process_request sending response data to socket: {}'
                               .format(response.encode()), 'D')
                        connection.sendto(response.encode(), address)
                    else:
                        Logger('TCPServerClient.process_request sending back request data to socket : {}'
                               .format(request.encode()), 'D')
                        connection.sendto(request.encode(), address)
                except Empty:
                    queue_empty = True
                    Logger('TCPServerClient.process_request result queue is empty', 'D')
                    time.sleep(0.5)
                except EOFError:
                    Logger('TCPServerClient.process_request got EOFError. Breaking loop', 'D')
                    break
            Logger('TCPServerClient.process_request will join command thread', 'D')
            command_thread.join()
            result_queue.close()

    def reconstruct_request(self, encoded_data):
        return TCPRequest(message=self.queue_io.request_definitions.reconstruct_request(encoded_data))


class TCPRequest(TCPMessage, Request):
    pass


class TCPResponse(TCPMessage, Response):
    pass


class TCPClient(TCPServerClient):
    def __init__(self, ip_addr=None, def_file=None, app_name=None,
                 input_queue=None, output_queue=None, **kwargs):
        super(TCPClient, self).__init__(def_file, app_name, input_queue, output_queue, **kwargs)
        self.socket = None
        self.response_receiver_process = None
        # self.reception_queue = None
        self.server_addr = ip_addr
        self.connection_time_out = TCPCLIENT_CONNECTION_TIMEOUT
        self.rate = TCP_CLIENT_RATE
        self.do_rate = SHARED_MEM_UPDATE_RATE

    def command(self, command, *args, priority=None):
        if not args:
            args = []
        request = TCPRequest(what=command, args=args, message_type='command')
        request.priority = priority or 1
        request.set_definition(self.get_request_definition(command))
        return self.get_response(request)

    # Test: test_TCPClient_connect
    def connect(self, attempt=0, max_attempt=None):
        if not self.server_addr:
            Logger('TCPClient.connect no server address is defined. Entering ERROR_STATE', 'E')
            self.set_state(self.ERROR_STATE)
            self.error_code = ErrorCodes.NO_SERVER_DEFINED_ERROR
            return
        if max_attempt and attempt >= max_attempt:
            raise TCPException('Maximum number of connection attemps reached: {}'.format(max_attempt),
                               error_code=ErrorCodes.CLIENT_CONNECTION_ERROR)
        if self.socket:
            self.socket.close()
        try:
            Logger('TCPClient.connect sending get_state_request', 'D')
            get_state_response = self.get_server_state()
            server_state = get_state_response.get_payload_data()
            Logger('TCPClient.connect got server state: {}'.format(server_state), 'D')
            if server_state != 'READY_STATE':
                raise ConnectionRefusedError
            self.socket = SocketWrapper(socket.socket(socket.AF_INET, socket.SOCK_STREAM),
                                        (self.server_addr, self.socket_port))
            self.socket.connect((self.server_addr, self.socket_port))
            time.sleep(1)
            # Get the state from the server
            try:
                connect_request = TCPRequest(what='connect', message_type='command', data_type='int')
                self.socket.send(connect_request.encode())
                response_data = get_data(self.socket)
                connect_response = Response(encoded_data=response_data)
                if connect_response.get_payload_data() != ErrorCodes.COMMAND_SUCCESS:
                    raise ConnectionRefusedError
                else:
                    self.connected = True
                    self.start_receiver_process()
                    self.error_code = ErrorCodes.NO_ERROR
                    self.set_state(self.READY_STATE)
            except TCPException:
                self.connected = False
                raise ConnectionRefusedError
        except ConnectionRefusedError:
            Logger('TCPClient.connect received ConnectionRefusedError', 'D')
            self.connected = False
            if self.socket:
                self.socket.finish()
            self.socket = None
            time.sleep(1)
            self.connect(attempt=attempt + 1, max_attempt=max_attempt)

    def disconnect(self):
        self.stop_receiver_process()
        Logger('TCPClient disconnecting', 'D')
        # if self.connected:
        if self.socket:
            Logger('Shutting down socket', 'D')
            self.socket.finish()
            Logger('Socket shutdown successfully', 'D')
        self.connected = False

    def do(self):
        pass

    def get_from_reception_queue(self, tcp_request):
        return self.queue_io.get_from_reception_queue(tcp_request)

    def get_request_definition(self, name):
        return self.queue_io.get_request_definition(name)

    # Test: test_TCPClient_get_response
    def get_response(self, tcp_request, ignore_error=False):
        if not self.connected:
            raise TCPException('TCPClient is not connected', error_code=ErrorCodes.CLIENT_NOT_CONNECTED_ERROR)
        Logger('TCPClient.get_response is sending request {} number: {}'
               .format(tcp_request.what, tcp_request.number), 'D')
        self.socket.send(tcp_request.encode())
        try:
            tcp_response = self.get_from_reception_queue(tcp_request)
        except TCPException as e:
            self.disconnect()
            raise e
        if tcp_request.what != tcp_response.what:
            self.disconnect()
            raise TCPException('The response ({}) is not the same as the request ({})'.format(tcp_response,
                                                                                              tcp_request))
        if tcp_response.identifier != ErrorCodes.NO_ERROR and not ignore_error:
            self.disconnect()
            raise TCPException('{}. {}'.format(ErrorCodes.ErrorMessages[tcp_response.identifier],
                                               tcp_response.get_payload_data()), error_code=tcp_response.identifier)
        if tcp_response.what == 'reset_definitions':
            self.disconnect()
        return tcp_response

    # TODO: test
    def get_server_state(self, s=None):
        request = TCPRequest(what='get_state', message_type='query', data_type='str')
        if self.connected:
            response = self.get_response(request)
        else:
            response = self.get_unconnected_response(request, s)
        response.data_type = 'str'
        return response

    # Test: test_TCPClient_get_unconnected_response
    def get_unconnected_response(self, request, s=None):
        try:
            if not s:
                Logger('TCPClient.get_unconnected_response no input socket. Creating new', 'D')
                s = SocketWrapper(socket.socket(socket.AF_INET, socket.SOCK_STREAM))
                s.connect((self.server_addr, self.socket_port))
            s.send(TCPRequest(message=request).encode())
            response_data = get_data(s)
            s.finish()
            response = TCPResponse(encoded_data=response_data)
            return response
        except ConnectionRefusedError:
            s.finish()
            # Manage error
            raise TCPException('Connection was refused by the server or the server is not running',
                               error_code=ErrorCodes.CLIENT_CONNECTION_ERROR)

    def ping_server(self):
        ping_request = TCPRequest(message=PingRequest())
        if self.connected:
            return self.get_response(ping_request)
        else:
            return self.get_unconnected_response(ping_request)

    # Test: test_TCPClient_process_input_queue
    def process_input_queue(self, request=None):
        Logger('TCPClient.process_input_queue starting', 'D')
        if not request:
            request = self.queue_io.get_input_message()
        if request:
            Logger('TCPClient.process_intput_queue found request {} number {}'
                   .format(request.what, request.number), 'D')
            response = self.preprocess_request(request)
            if response:
                Logger('TCPClient.process_intput_queue sending to output queue: {}'.format(response), 'D')
                self.queue_io.output_queue.put(response.encode())
            else:
                Logger('TCPClient.process_input_queue will get response for request {} number {} hop {}'
                       .format(request.what, request.number, request.hop), 'D')
                process_request_thread = Thread(target=self.process_queue_request, args=(request,))
                process_request_thread.start()

    # Test: test_TCPClient_process_queue_request
    def process_queue_request(self, request):
        Logger('TCPClient.process_queue_request will process request {} number {} hop {}'
               .format(request.what, request.number, request.hop), 'D')
        request.add_hop()
        s = None
        # Create a new socket connection
        try:
            s = SocketWrapper(socket.socket(socket.AF_INET, socket.SOCK_STREAM))
            s.connect((self.server_addr, self.socket_port))
            Logger('TCPClient.process_queue_request adding request number {} to queue_io '
                   'piping_number list'.format(request.number), 'D')
            self.queue_io.piping_numbers.append(request.number)
            Logger('TCPClient.process_queue_request sending back hopped request {} number {} hop {}'
                   .format(request.what, request.number, request.hop), 'D')
            self.queue_io.output_queue.put(request.encode())
            tcp_request = TCPRequest(message=request)
            Logger('TCPClient.process_queue_request forwarding data to socket: {}'.format(tcp_request.encode()), 'D')
            s.send(tcp_request.encode())
            link(sender=s, receiver=self.queue_io.output_queue,
                 # receiver_piping_numbers=self.queue_io.piping_numbers,
                 target_request=tcp_request)
        except ConnectionRefusedError:
            response = Response(message=request)
            response.identifier = ErrorCodes.CLIENT_CONNECTION_ERROR
            self.queue_io.output_queue.put(response.encode())
        finally:
            if s:
                s.finish()

    def query(self, what, ignore_error=False, priority=None):
        tcp_request = TCPRequest(what=what, message_type='query', sender_id=self.member_id)
        tcp_request.priority = priority or 1
        tcp_request.set_definition(self.get_request_definition(what))
        return self.get_response(tcp_request, ignore_error=ignore_error)

    def response_receiver(self, reception_queue):
        Logger('TCPClient.response_receiver started', 'D')
        try:
            link(receiver=reception_queue, sender=self.socket, forever=True,
                 # all_messages=True
                 )
        except KeyboardInterrupt:
            if self.socket:
                self.socket.finish()

    # Test: test_TCPClient_run
    def run(self):
        self.set_state(self.READY_STATE)
        last_do_time = None
        try:
            while True:
                Logger('TCPClient.run starting loop', 'D')
                if not self.connected:
                    Logger('TCPClient.run client is not connected. Will try to connect', 'D')
                    self.try_connect()
                if last_do_time:
                    do_delta_s = (datetime.datetime.now() - last_do_time).total_seconds()
                else:
                    do_delta_s = 0
                self.process_input_queue()
                if not last_do_time or do_delta_s >= self.do_rate:
                    Logger('TCPClient.run will call do', 'D')
                    self.do()
                    last_do_time = datetime.datetime.now()
                time.sleep(self.rate)
        except KeyboardInterrupt:
            self.disconnect()

    # TODO: implement a final confirmation request/response with checksum
    # Test: test_TCPClient_send_definitions
    def send_definitions(self):
        definitions = self.queue_io.request_definitions.as_dict()
        encoded_defs = json.dumps(definitions).encode('utf-8')
        init_request = TCPRequest(what='accept_definitions', message_type='command', data_type='int')
        s = SocketWrapper(socket.socket(socket.AF_INET, socket.SOCK_STREAM))
        s.connect((self.server_addr, self.socket_port))
        s.send(init_request.encode())
        init_response = TCPResponse(encoded_data=s.recv(1024))
        if init_response.identifier == ErrorCodes.NO_ERROR or \
                init_response.identifier == ErrorCodes.DEFINITIONS_NOT_RECEIVED_ERROR:
            while encoded_defs:
                if len(encoded_defs) <= DEFINITIONS_MESSAGE_SIZE:
                    message = encoded_defs
                    encoded_defs = b''
                else:
                    message = encoded_defs[:DEFINITIONS_MESSAGE_SIZE]
                    encoded_defs = encoded_defs[DEFINITIONS_MESSAGE_SIZE:]
                s.send(int.to_bytes(len(message), TCP_MESSAGE_SIZE_LENGTH, byteorder='big') + message)
        else:
            s.shutdown(socket.SHUT_RDWR)
            s.close()
            raise TCPException('Sending definitions initial response has error code: {}'
                               .format(init_response.identifier))
        try:
            s.shutdown(socket.SHUT_RDWR)
            s.close()
        except OSError:
            pass

    def try_connect(self):
        try:
            self.connect(max_attempt=1)
        except TCPException as e:
            Logger('Connection attempt failed with error: {}'.format(str(e)), 'I')

    def start_receiver_process(self):
        if self.response_receiver_process:
            self.response_receiver_process.terminate()
        # self.reception_queue = Queue()
        self.response_receiver_process = Process(target=self.response_receiver, args=(self.queue_io.reception_queue,))
        self.response_receiver_process.start()
        time.sleep(0.5)

    def stop_receiver_process(self):
        if self.response_receiver_process:
            try:
                os.kill(self.response_receiver_process.pid, signal.SIGINT)
            except ProcessLookupError:
                pass
            self.response_receiver_process = None


class TCPClientSMUpdater(TCPClient):
    def __init__(self, ip_addr=None, def_file=None, app_name=None, input_queue=None, output_queue=None, **kwargs):
        super(TCPClientSMUpdater, self).__init__(ip_addr, def_file, app_name, input_queue, output_queue, **kwargs)
        self.shared_mem = {}
        self.do_updates_thread = None
        if def_file and app_name:
            self.read_sm_definitions(def_file, app_name)
            self.set_shared_mem()

    def close_shared_mems(self):
        for sm_name, sm in self.shared_mem.items():
            Logger('Closing shared memory {}'.format(sm_name), 'D')
            sm.close()
            Logger('Shared memory closed siccessfully', 'D')
        self.shared_mem = {}

    # def command(self, command, *args):
    #     confirmation = self.get_request_definition(command).wait_for_confirmation
    #     init_value = None
    #     if confirmation:
    #         init_value = self.read(confirmation)
    #     response = super().command(command, *args)
    #     if init_value is not None:
    #         counter = self.get_counter(confirmation)
    #         if self.read(confirmation) == init_value:
    #             self.wait_for_update(confirmation, counter)
    #     return response

    def disconnect(self):
        self.close_shared_mems()
        super().disconnect()
        Logger('Closing shared memories', 'D')

    # Test: test_TCPClientSMUpdater_do
    def do(self):
        Logger('TCPClientSMUpdater.do starting', 'D')
        if not self.do_updates_thread or not self.do_updates_thread.is_alive():
            Logger('TCPClientSMUpdater.do do_updates_thread will start do_updates_thread', 'D')
            self.do_updates_thread = Thread(target=self.do_updates)
            self.do_updates_thread.start()

    def do_updates(self):
        while self.connected:
            for shared_mem_name in self.shared_mem:
                # Start update SM in seperate thread
                Logger('Updating SM {}'.format(shared_mem_name), 'D')
                self.update_shared_mem(shared_mem_name)

    def get_all_shared_mem_values(self):
        data = {shared_mem_name: self.read(shared_mem_name) for shared_mem_name in self.shared_mem}
        data['timestamp'] = datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')
        return data

    def get_counter(self, name):
        return self.shared_mem[name].get_counter()

    def read_definitions(self, def_file, app_name):
        super().read_definitions(def_file, app_name)
        self.read_sm_definitions(def_file, app_name)
        self.set_shared_mem()

    def read(self, name, no_wait=False):
        return self.read_shared_mem(name, no_wait=no_wait)

    def read_shared_mem(self, shared_mem_name, no_wait=False):
        return self.shared_mem[shared_mem_name].read(no_wait)

    def read_sm_definitions(self, def_file, app_name):
        if ElementTree.parse(def_file).getroot().find('AppDefinitions'). \
                find('AppDefinition[@AppName="{}"]'.format(app_name)).find('SharedMemoryDefinitions'):
            sm_definitions = ElementTree.parse(def_file).getroot().find('AppDefinitions').\
                find('AppDefinition[@AppName="{}"]'.format(app_name)).find('SharedMemoryDefinitions').\
                findall('SharedMemoryDefinition')
            for sm_def in sm_definitions:
                self.shared_mem[sm_def.attrib['Name']] = TCPClientSharedMem(
                    sm_def.attrib['Name'],
                    sm_def.attrib['Size'],
                    sm_def.attrib['Type'],
                    sm_def.get('Factor', 1))

    # Test: test_TCPClientSMUpdater_set_shared_mem
    def set_shared_mem(self):
        for name, sm in self.shared_mem.items():
            Logger('Creating shared memory {}'.format(name), 'D')
            try:
                sm_ = shared_memory.SharedMemory(name=name)
                sm_.close()
                sm_.unlink()
                # sm_.buf[:1] = SHAREDMEM_READ_READY
                Logger('Shared memory already exists. removing', 'D')
            except FileNotFoundError:
                pass
            finally:
                shared_memory.SharedMemory(name=name, create=True, size=sm.size + 8)
                Logger('Shared memory {} created successfully'.format(name), 'D')
            sm.initialized = True

    # Test: test_TCPClientSMUpdater_update_shared_mem
    def update_shared_mem(self, shared_mem_name):
        Logger('Starting update of shared mem {}'.format(shared_mem_name), 'D')
        sm = self.shared_mem[shared_mem_name]
        if not sm.is_read_ready():
            Logger('Shared memory is not read-ready. Dumping buffer content: {}'.format(sm.dump()), 'D')
            raise TCPException('Shared memory {} is not ready to be updated'.format(shared_mem_name))
        counter = sm.start_update()
        request = TCPRequest(message_type='query', what=shared_mem_name)
        req_def = self.get_request_definition(shared_mem_name)
        request.set_definition(req_def)
        response = self.get_response(request)
        sm.write_raw(counter, response.raw_data)

    def wait_for_update(self, name, counter):
        while not self.get_counter(name) > counter:
            time.sleep(0.1)


class TCPClientSharedMem:
    def __init__(self, name, size, data_type, factor=1):
        self.name = name
        self.size = int(size)
        self.type = data_type
        self.initialized = False
        self.factor = float(factor)
        # Shared memory buffer format:
        # [0:1] Ready bit
        # [1:8] counter
        # [8:] payload

    # Test: test_TCPClientSharedMem_close
    def close(self):
        sm = shared_memory.SharedMemory(name=self.name)
        sm.close()
        sm.unlink()

    def dump(self):
        sm = shared_memory.SharedMemory(name=self.name)
        return bytes(sm.buf)

    def get_counter(self):
        sm = shared_memory.SharedMemory(name=self.name)
        return int.from_bytes(sm.buf[1:8], byteorder='big')

    def is_read_ready(self):
        return self.is_ready('r')

    def is_ready(self, rw):
        if self.initialized:
            sm = shared_memory.SharedMemory(self.name)
            return (bytes(sm.buf[:1]) == SHAREDMEM_WRITE_READY and rw == 'w') \
                or (bytes(sm.buf[:1]) == SHAREDMEM_READ_READY and rw == 'r')
        else:
            raise TCPException('Shared memory {} is not initialized'.format(self.name))

    def is_write_ready(self):
        return self.is_ready('w')

    # Test: test_TCPClientSharedMem_read
    def read(self, no_wait=False):
        init_time = datetime.datetime.now()
        time_out = False
        while not (self.is_read_ready() or time_out or no_wait):
            time_out = (datetime.datetime.now() - init_time).total_seconds() > SHAREDMEM_WAIT_LIMIT
        if time_out:
            raise TCPException('Timed out waitong for shared memory {}'.format(self.name))
        sm = shared_memory.SharedMemory(name=self.name, create=False)
        data = bytes(sm.buf[8:])
        if self.type == 'bool':
            return not data == bytes([0])
        elif self.type == 'int':
            return int.from_bytes(data, byteorder='big', signed=True) * self.factor
        elif self.type == 'str' or self.type == 'float':
            while data and not data[0]:
                data = data[1:]
            data = data.decode('utf-8')
            if self.type == 'float':
                try:
                    return float(data.split('\n')[0])
                except ValueError:
                    raise TCPException('Could not read valid value from data: "{}" for shared mem: {}'
                                       .format(data, self.name))
            return data.split('\n')[0]

    # Test: test_TCPClientSharedMem_start_update
    def start_update(self):
        sm = shared_memory.SharedMemory(name=self.name)
        sm.buf[:1] = SHAREDMEM_WRITE_READY
        return self.get_counter()

    # def write(self, counter, data):
    #     if self.get_counter() != counter:
    #         raise TCPException('Attempt to write to shared memory with counter {} that does not match '
    #                            'expected counter {}'.format(counter, self.get_counter()))
    #     if not self.is_write_ready():
    #         raise TCPException('Attempt to write to shared memory {} while shared memory is '
    #                            'not write ready'.format(self.name))
    #     sm = shared_memory.SharedMemory(name=self.name)
    #     if self.type == 'int':
    #         data = int.to_bytes(data, self.size, byteorder='big', signed=True)
    #     elif self.type == 'bool':
    #         data = bytes([data])
    #     elif self.type == 'str':
    #         data = data.encode('utf-8') + int.to_bytes(0, self.size - len(data), byteorder='big')
    #     sm.buf[8:] = data
    #     sm.buf[1:8] = int.to_bytes(self.get_counter() + 1, 7, byteorder='big')
    #     sm.buf[:1] = SHAREDMEM_READ_READY

    # Test: test_TCPClientSharedMem_write_raw
    def write_raw(self, counter, data):
        if self.get_counter() != counter:
            raise TCPException('Attempt to write to shared memory with counter {} that does not match '
                               'expected counter {}'.format(counter, self.get_counter()))
        if not self.is_write_ready():
            raise TCPException('Attempt to write to shared memory {} while shared memory is '
                               'not write ready'.format(self.name))
        sm = shared_memory.SharedMemory(name=self.name)
        while len(data) < self.size:
            data = b'\x00' + data
        sm.buf[8:] = data
        sm.buf[1:8] = int.to_bytes(self.get_counter() + 1, 7, byteorder='big')
        sm.buf[:1] = SHAREDMEM_READ_READY


class TCPServerCommand:
    def __init__(self, command, args, request_type):
        self.command = command
        self.args = args
        self.request_type = request_type


class TCPServer(TCPServerClient):
    def __init__(self, ip_addr=None, def_file=None, input_queue=None, output_queue=None, app_name=None, **kwargs):
        super(TCPServer, self).__init__(def_file=def_file, input_queue=input_queue,
                                        output_queue=output_queue, app_name=app_name, **kwargs)
        self.queue_io.request_definitions.set(**{'Name': 'accept_definitions',
                                                 'DataType': 'int',
                                                 'NumberOfArguments': 0})
        self.subprocesses = []
        self.host_name = socket.gethostname()
        self.host_ipaddr = ip_addr
        self.socket = None
        self.socket_timeout = TCPSERVER_SOCKET_TIMEOUT
        if not self.received_definitions:
            self.set_state(self.PENDING_DEFINITIONS_STATE)
        self.request_number_pipe_read, self.request_number_pipe_write = os.pipe()
        fcntl.fcntl(self.request_number_pipe_read, fcntl.F_SETFL, os.O_NONBLOCK)

    def accept_definitions(self, connection, address):
        encoded_definitions = b''
        accepting_definitions = False
        reception_finished = False
        while connection and not reception_finished:
            message_size = connection.recv(TCP_MESSAGE_SIZE_LENGTH)
            Logger('accept_definitions received data {}'.format(message_size), 'D')
            if message_size and not accepting_definitions:
                message_data = connection.recv(int.from_bytes(message_size, byteorder='big'))
                Logger('Received data: {}'.format(message_data), 'D')
                try:
                    request = self.reconstruct_request(message_data)
                    Logger('Reconstrcted request: {}'.format(request.what), 'D')
                except RequestException as e:
                    if e.error_code != ErrorCodes.UNDEFINED_REQUEST_ERROR:
                        raise e
                    else:
                        request = TCPRequest(encoded_data=message_data)
                if request.what != 'accept_definitions':
                    # Server is only accepting defintions. Only answer to ping and get_state requests
                    response = TCPResponse(message=request)
                    if request.is_get_state():
                        Logger('Request is get_state', 'D')
                        response.set_data(self.state)
                    elif request.is_ping():
                        Logger('Request is ping', 'D')
                        response = TCPResponse(message=PingResponse(message=response))
                    else:
                        Logger('request is {}'.format(request.what), 'D')
                        response = self.tcp_response_error(request)
                    response.identifier = ErrorCodes.DEFINITIONS_NOT_RECEIVED_ERROR
                    Logger('Sending back data: {}'.format(response.encode()), 'D')
                    connection.sendto(response.encode(), address)
                    connection.finish()
                    connection = None
                else:
                    accepting_definitions = True
                    response = TCPResponse(what='accept_definitions',
                                           identifier=TCP_RESPONSE_NO_ERROR,
                                           data_type='int')
                    Logger('Setting accepting_definitions to True', 'D')
                    Logger('Sending back data: {}'.format(response.encode()), 'D')
                    connection.sendto(response.encode(), address)
            elif message_size:
                encoded_definitions += connection.recv(int.from_bytes(message_size, byteorder='big'))
            else:
                reception_finished = True
                # connection.close()
                connection.finish()
                connection = None
        Logger('Connection is closed', 'D')
        if not encoded_definitions and accepting_definitions:
            raise TCPException('No definitions received', error_code=ErrorCodes.INVALID_DEFINTIONS_ERROR)
        elif accepting_definitions:
            definitions = json.loads(encoded_definitions)
            Logger('Received definitions are: {}'.format(definitions), 'D')
            self.set_request_definitions(definitions)
            self.queue_io.request_definitions.find_processes()
            Logger('Successfully received definitions', 'I')
            self.set_state(self.READY_STATE)
            self.error_code = ErrorCodes.NO_ERROR
        Logger('TCPServer.accept_definitions end of function', 'D')

    # Test: test_TCPServer_connect
    def connect(self):
        self.socket = SocketWrapper(socket.socket(socket.AF_INET, socket.SOCK_STREAM))
        self.socket.settimeout(self.socket_timeout)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.socket.bind((self.host_ipaddr, self.socket_port))
        except OSError as e:
            message = str(e) + '\nAttempted to bind address {} and port {}'.format(self.host_ipaddr, self.socket_port)
            Logger(message, 'E')
            self.socket.finish()
            self.socket = None
            raise OSError(message)
        self.socket.listen(1)
        self.connected = True

    def do(self):
        self.process_input_queue()

    # Test: test_TCPServer_handle_connection
    def handle_connection(self, connection, address, _pipe=None):
        while connection:
            try:
                message_data = get_data(connection)
                if message_data:
                    Logger('TCPServer.handle_connection received data: {}'.format(message_data), 'D')
                    tcp_request = self.reconstruct_request(message_data)
                    Logger('TCPServer.handle_connection reconstructed tcp_request {} number {} with data type {}'
                           .format(tcp_request.what, tcp_request.number, tcp_request.data_type), 'D')
                    response = self.preprocess_request(tcp_request)
                    if not response:
                        Logger('Calling process_request', 'D')
                        self.set_state(self.READY_STATE)
                        self.process_request(tcp_request, connection, address)
                    else:
                        connection.sendto(TCPResponse(message=response).encode(), address)
                else:
                    Logger('TCPServer.handle_connection received empty message data: {}'.format(message_data), 'D')
                    connection.finish()
                    break
            except KeyboardInterrupt:
                connection.finish()
                break

    def handle_socket_timeout(self):
        pass

    @staticmethod
    def tcp_response_error(request, error_code=None):
        if not error_code:
            error_code = ErrorCodes.ERROR
        tcp_response = TCPResponse(message=request)
        tcp_response.identifier = error_code
        return tcp_response

    @property
    def received_definitions(self):
        return self.queue_io.request_definitions.received_definitions

    def read_request_number_pipe(self):
        pipe_empty = False
        while not pipe_empty:
            try:
                data = os.read(self.request_number_pipe_read, ENCODED_MESSAGE_NUMBER_LENGTH + 1)
                request_number = int.from_bytes(data[:-1], byteorder='big')
                remove = data[-1] == 0
                if remove and request_number not in self.queue_io.piping_numbers:
                    Logger('TCPserver.read_request_number_pipe received number {} not in list. List is {}'
                           .format(request_number, self.queue_io.piping_numbers), 'D')
                elif remove:
                    self.queue_io.piping_numbers.remove(request_number)
                    Logger('TCPserver.read_request_number_pipe received number {} to remove from list. List is {}'
                           .format(request_number, self.queue_io.piping_numbers), 'D')
                elif not remove:
                    self.queue_io.piping_numbers.append(request_number)
                    Logger('TCPserver.read_request_number_pipe received number {} to add to list. List is {}'
                           .format(request_number, self.queue_io.piping_numbers), 'D')

            except BlockingIOError:
                pipe_empty = True

    def run(self):
        Logger('TCPServer.run is running on process {} in cwd: {}'.format(os.getpid(), os.getcwd()), 'D')
        self.connect()
        try:
            while True:
                try:
                    conn, addr = self.socket.accept()
                    Logger('TCPServer.run received connection', 'D')
                    if not self.received_definitions:
                        self.set_state(self.PENDING_DEFINITIONS_STATE)
                        # Only accept request and command definitions
                        try:
                            self.accept_definitions(conn, addr)
                            Logger('TCPServer exited accept_definitions', 'D')
                        except TCPException as e:
                            if e.error_code == ErrorCodes.INVALID_DEFINTIONS_ERROR:
                                Logger('TCPServer.run received invalid definitions. Entering ERROR_STATE', 'E')
                                self.set_state(self.ERROR_STATE)
                            else:
                                raise e
                    else:
                        # self.set_state(self.READY_STATE)
                        connection_handling_process = Thread(target=self.handle_connection,
                                                             args=(conn,
                                                                   addr,
                                                                   self.request_number_pipe_write))
                        Logger('Starting connection_handling_process', 'D')
                        connection_handling_process.start()
                        Logger('Setting state to READY_STATE', 'D')
                        self.set_state(self.READY_STATE)
                        Logger('run function has state {}'.format(self.state), 'D')
                    # conn.close()
                    # ogger('Connection closed', 'D')
                except socket.timeout:
                    self.handle_socket_timeout()
                self.do()
        except KeyboardInterrupt:
            self.stop()
            # sys.exit(0)

    def stop(self):
        Logger('TCPServer received KeyboardInterrupt', 'D')
        for process in self.subprocesses:
            Logger('TCPServer.run joining subprocess: {}'.format(process), 'D')
            process.join()
        Logger('Closing down socket', 'D')
        self.socket.finish()


class TCPException(RequestException):
    pass
