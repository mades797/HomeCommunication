from unittest import mock, TestCase
from TCPServerClient import *
import ErrorCodes
import subprocess
from Requests import RequestDefinitions
import TCPServerClient as TcpServerClientPkg
from multiprocessing import Queue
from methods import link
from queue import Empty
import math
import datetime as datetime_pkg
import time as time_pkg

LOCALHOST = '127.0.0.1'


class HommeCommunicationTest(TestCase):

    def setUp(self) -> None:
        self.tcp_request = TCPRequest()
        self.tcp_response = TCPResponse()
        self.request = Request()
        self.response = Response()
        self.tcp_server_client = TCPServerClient()
        self.tcp_client_shared_mem = TCPClientSharedMem('sm_name', 40, 'data_type')
        self.tcp_client_sm_updater = TCPClientSMUpdater()
        self.tcp_server = TCPServer(ip_addr=LOCALHOST)
        self.tcp_client = TCPClient(ip_addr=LOCALHOST)
        self.tcp_client.set_request_definitions({'test': {'Name': 'test', 'Type': 'command', 'NumberOfArguments': 0,
                                                          'DataType': 'int'}})
        self.started_processes = []
        self.datetime = TcpServerClientPkg.datetime.datetime
        self.sleep = TcpServerClientPkg.time.sleep

    def tearDown(self):
        self.tcp_client.disconnect()
        for pid in self.started_processes:
            os.kill(pid, signal.SIGINT)
        TcpServerClientPkg.datetime.datetime = self.datetime
        TcpServerClientPkg.time.sleep = self.sleep
        print('tearDown done')

    ###########################
    # Unit tests for TCPMessage
    ###########################

    # Use cases:
    # 1. Encoded data has length bytes in leading bytes. Method returns True
    # 2. Encoded data does not have length bytes in leading bytes. Method returns False
    # 3. Endoded data header has invalid data. A TCPException is raised
    def test_TCPMessage_has_length(self):
        tcp_message = TCPMessage()
        encoded_data_no_length = b'\x00\x05\xa5\xa3\x96O.\xfe\x00\xff\x00\x02\x02?current_media_path#'
        encoded_data_with_length = int.to_bytes(len(encoded_data_no_length),
                                                TCP_MESSAGE_SIZE_LENGTH, byteorder='big') + encoded_data_no_length
        invalid_data_1 = b'\x00\x05\xa5\xa3\x96O.\xfe\x00\xff\x00\x02\x02current_media_path#'
        invalid_data_2 = b'\x00\x05\xa5\x96O.\xfe\x00\xff\x00\x02\x02?current_media_path#'
        # 1. Encoded data has length bytes in leading bytes. Method returns True
        self.assertTrue(tcp_message.has_length(encoded_data_with_length))
        # 2. Encoded data does not have length bytes in leading bytes. Method returns False
        self.assertFalse(tcp_message.has_length(encoded_data_no_length))
        # 3. Endoded data header has invalid data. A TCPException is raised
        with self.assertRaises(TCPException):
            try:
                tcp_message.has_length(invalid_data_1)
            except TCPException as e:
                self.assertEqual(str(e), 'Encoded data {} has invalid format'.format(invalid_data_1))
                raise e
        with self.assertRaises(TCPException):
            try:
                tcp_message.has_length(invalid_data_2)
            except TCPException as e:
                self.assertEqual(str(e), 'Encoded data {} has invalid format'.format(invalid_data_2))
                raise e
        print('test_TCPMessage_has_length done')

    ################################
    # Unit tests for TCPServerClient
    ################################

    # Use cases:
    # 1. Message length is received from the socket. The corresponding number of bytes is returned
    # 2. Message length is not received. Empty bytes is returned
    def test_TCPServerClient_get_socket_data(self):
        tcp_server_client = self.tcp_server_client
        mock_connection = mock.MagicMock()
        message = 'This is a message'
        returned_bytes = int.to_bytes(len(message), TCP_MESSAGE_SIZE_LENGTH, byteorder='big') + message.encode('utf-8')

        def recv_side_effect(length):
            nonlocal returned_bytes
            to_return = returned_bytes[:length]
            returned_bytes = returned_bytes[length:]
            return to_return
        mock_connection.recv.side_effect = recv_side_effect
        # 1. Message length is received from the socket. The corresponding number of bytes is returned
        self.assertEqual(tcp_server_client.get_socket_data(mock_connection).decode(), message)
        # 2. Message length is not received. Empty bytes is returned
        mock_connection.recv.side_effect = None
        mock_connection.recv.return_value = b''
        self.assertEqual(tcp_server_client.get_socket_data(mock_connection), b'')
        print('test_TCPServerClient_get_socket_data done')

    # Use cases:
    # 1. Response is created with request
    # 2. Response data is set to tcp_server_client state
    # 3. response identifier is set to tcp_server_client error_code
    @mock.patch('TCPServerClient.Response')
    def test_TCPServerClient_get_state_respond(self, mock_response):
        tcp_server_client = self.tcp_server_client
        request = self.request
        tcp_server_client.state = 'state'
        tcp_server_client.error_code = 'error_code'
        self.assertIs(tcp_server_client.get_state_respond(request), mock_response.return_value)
        self.assertEqual(mock_response.return_value.data_type, 'str')
        mock_response.return_value.set_data.assert_called_once_with('state')
        self.assertEqual(mock_response.return_value.identifier, 'error_code')
        mock_response.assert_called_once_with(message=request)
        print('test_TCPServerClient_get_state_respond done')

    # Use cases:
    # 1. Input request is ping. Response is created from request
    # 2. Input request is get_state. Response is created from request and data is set to state.
    #    Response.identifier is set to error_code
    # 3. input request is reset_definitions. reset_definitions is called
    # 4. Input request is connect. State is set to READY_STATE. Response is created from request and
    #    data is set to ErrorCodes.COMMAND_SUCCESS
    # 5. Input request is non of the above. none is returned
    @mock.patch('TCPServerClient.Response')
    def test_TCPServerClient_preprocess_request(self, mock_response):
        tcp_server_client = self.tcp_server_client
        tcp_server_client.state = 'state'
        tcp_server_client.reset_definitions = mock.MagicMock()
        tcp_server_client.set_state = mock.MagicMock()
        request = mock.MagicMock()
        # 1. Input request is ping. Response is created from request
        request.is_ping.return_value = True
        request.is_get_state.return_value = False
        request.is_reset_definitions.return_value = False
        request.is_connect.return_value = False
        self.assertIs(tcp_server_client.preprocess_request(request), mock_response.return_value)
        # Assertions
        tcp_server_client.reset_definitions.assert_not_called()
        tcp_server_client.set_state.assert_not_called()
        mock_response.assert_called_once_with(message=request)
        mock_response.return_value.set_data.assert_not_called()
        # Resets
        tcp_server_client.reset_definitions.reset_mock()
        tcp_server_client.set_state.reset_mock()
        mock_response.reset_mock()
        mock_response.return_value.set_data.reset_mock()
        # 2. Input request is get_state. Response is created from request and data is set to state.
        #    Response.identifier is set to error_code
        request.is_ping.return_value = False
        request.is_get_state.return_value = True
        request.is_reset_definitions.return_value = False
        request.is_connect.return_value = False
        tcp_server_client.error_code = 'error_code'
        self.assertIs(tcp_server_client.preprocess_request(request), mock_response.return_value)
        # Assertions
        tcp_server_client.reset_definitions.assert_not_called()
        tcp_server_client.set_state.assert_not_called()
        mock_response.assert_called_once_with(message=request)
        mock_response.return_value.set_data.assert_called_once_with('state')
        self.assertEqual(mock_response.return_value.identifier, 'error_code')
        # Resets
        tcp_server_client.reset_definitions.reset_mock()
        tcp_server_client.set_state.reset_mock()
        mock_response.reset_mock()
        mock_response.return_value.set_data.reset_mock()
        # 3. input request is reset_definitions. reset_definitions is called
        request.is_ping.return_value = False
        request.is_get_state.return_value = False
        request.is_reset_definitions.return_value = True
        request.is_connect.return_value = False
        self.assertIs(tcp_server_client.preprocess_request(request), tcp_server_client.reset_definitions.return_value)
        # Assertions
        tcp_server_client.reset_definitions.assert_called_once()
        tcp_server_client.set_state.assert_not_called()
        mock_response.assert_not_called()
        mock_response.return_value.set_data.assert_not_called()
        # Resets
        tcp_server_client.reset_definitions.reset_mock()
        tcp_server_client.set_state.reset_mock()
        mock_response.reset_mock()
        mock_response.return_value.set_data.reset_mock()
        # 4. Input request is connect. State is set to READY_STATE. Response is created from request and
        #    data is set to ErrorCodes.COMMAND_SUCCESS
        request.is_ping.return_value = False
        request.is_get_state.return_value = False
        request.is_reset_definitions.return_value = False
        request.is_connect.return_value = True
        self.assertIs(tcp_server_client.preprocess_request(request), mock_response.return_value)
        # Assertions
        tcp_server_client.reset_definitions.assert_not_called()
        tcp_server_client.set_state.assert_called_once_with(tcp_server_client.READY_STATE)
        mock_response.assert_called_once_with(message=request)
        mock_response.return_value.set_data.assert_called_once_with(ErrorCodes.COMMAND_SUCCESS)
        # Resets
        tcp_server_client.reset_definitions.reset_mock()
        tcp_server_client.set_state.reset_mock()
        mock_response.reset_mock()
        mock_response.return_value.set_data.reset_mock()
        # 5. Input request is non of the above. none is returned
        request.is_ping.return_value = False
        request.is_get_state.return_value = False
        request.is_reset_definitions.return_value = False
        request.is_connect.return_value = False
        self.assertIsNone(tcp_server_client.preprocess_request(request))
        # Assertions
        tcp_server_client.reset_definitions.assert_not_called()
        tcp_server_client.set_state.assert_not_called()
        mock_response.assert_not_called()
        mock_response.return_value.set_data.assert_not_called()
        print('test_TCPServerClient_preprocess_request done')

    # Use cases:
    # 1. Request from get_request is None nothing is sent back
    # 2. Request from get_request is not None but response from preprocess_request is None.
    #    A RequestException is raised
    # 3. Request from get_request is not none and response from preprocess_request is not None.
    #    The response is sent back
    def test_TCPServerClient_process_input_queue(self):
        tcp_server_client = self.tcp_server_client
        tcp_server_client.queue_io = mock.MagicMock()
        tcp_server_client.preprocess_request = mock.MagicMock()
        response = self.response
        request = self.request
        request.what = 'what'
        request.hop = 3
        # 1. Request from get_request is None nothing is sent back
        tcp_server_client.queue_io.get_input_message.return_value = None
        tcp_server_client.process_input_queue()
        # Assertions
        tcp_server_client.preprocess_request.assert_not_called()
        tcp_server_client.queue_io.send_response.assert_not_called()
        # Resets
        tcp_server_client.preprocess_request.reset_mock()
        tcp_server_client.queue_io.send_response.reset_mock()
        # 2. Request from get_request is not None but response from preprocess_request is None.
        #    A RequestException is raised
        tcp_server_client.queue_io.get_input_message.return_value = request
        tcp_server_client.preprocess_request.return_value = None
        with self.assertRaises(RequestException):
            try:
                tcp_server_client.process_input_queue()
            except RequestException as e:
                self.assertEqual(str(e),
                                 'TCPServerClient received unknown request what number {} hop 3'.format(request.number))
                self.assertEqual(e.error_code, ErrorCodes.UNDEFINED_REQUEST_ERROR)
                raise e
        # Assertions
        tcp_server_client.queue_io.send_response.assert_not_called()
        # Resets
        tcp_server_client.preprocess_request.reset_mock()
        tcp_server_client.queue_io.send_response.reset_mock()
        # 3. Request from get_request is not none and response from preprocess_request is not None.
        #    The response is sent back
        tcp_server_client.preprocess_request.return_value = response
        tcp_server_client.process_input_queue()
        # Assertions
        tcp_server_client.queue_io.send_response.assert_called_once_with(response)
        print('test_TCPServerClient_process_input_queue done')

    # Use cases:
    # 1. Request got a response from preprocess_quest. Send the response
    # 2. Hop is added to the request
    # 3. Hopped request is sent back to the socket
    # 4. The command thread is started
    # 5. Completion flag is retreived from the result queue. The response data is set and the
    #    response is sent to the socket
    # 6. Completion flag is not received but command thread is not alive. The loop is broken
    # 7. Result data is pulled from queue but completion flag is false. The request is sent back to the socket
    # 8. The command thread is joint and closed
    # 9. TCPRequest is created from the input request
    @mock.patch('TCPServerClient.Queue')
    @mock.patch('TCPServerClient.Thread')
    @mock.patch('TCPServerClient.TCPRequest')
    @mock.patch('TCPServerClient.TCPResponse')
    def test_TCPServerClient_process_request(self, mock_tcpresponse, mock_tcprequest, mock_thread, mock_queue):
        tcp_server_client = self.tcp_server_client
        tcp_response = self.tcp_response
        tcp_response.set_data = mock.MagicMock()
        tcp_request = self.tcp_request
        tcp_request.what = 'what'
        tcp_request.args = ['arg1', 'arg2', 'arg3']
        tcp_request.add_hop = mock.MagicMock()
        tcp_request.encode = mock.MagicMock(return_value='encoded_request')
        mock_tcpresponse.return_value = tcp_response
        mock_tcprequest.return_value = tcp_request
        tcp_response.encode = mock.MagicMock(return_value='encoded_response')
        tcp_server_client.preprocess_request = mock.MagicMock()
        request = Request()
        mock_connection = mock.MagicMock()
        address = 'address'
        tcp_server_client.queue_io = mock.MagicMock()
        mock_command = mock.MagicMock()
        tcp_server_client.queue_io.request_definitions.get.return_value = mock_command
        # 1. Request got a response from preprocess_quest. Send the response
        # 9. TCPRequest is created from the input request
        preprocessed_response = Response()
        tcp_server_client.preprocess_request.return_value = preprocessed_response
        tcp_server_client.process_request(request, mock_connection, address)
        # Assertions
        mock_tcprequest.assert_called_once_with(message=request)  # 9
        mock_tcpresponse.assert_called_once_with(message=preprocessed_response)  # 1
        mock_connection.sendto.assert_called_once_with('encoded_response', 'address')  # 1
        tcp_server_client.preprocess_request.assert_called_once_with(tcp_request)  # 1
        mock_thread.assert_not_called()  # 1
        mock_queue.assert_not_called()  # 1
        tcp_response.set_data.assert_not_called()  # 1
        # Resets
        mock_tcprequest.reset_mock()
        mock_tcpresponse.reset_mock()
        mock_connection.sendto.reset_mock()
        tcp_server_client.preprocess_request.reset_mock()
        mock_thread.reset_mock()
        mock_queue.reset_mock()
        tcp_request.add_hop.reset_mock()
        tcp_server_client.queue_io.request_definitions.get.reset_mock()
        tcp_response.set_data.reset_mock()
        # 2. Hop is added to the request
        # 3. Hopped request is sent back to the socket
        # 4. The command thread is started with the request arguments
        # 5. Completion flag is retreived from the result queue. The response data is set and the
        #    response is sent to the socket
        # 7. Result data is pulled from queue but completion flag is false. The request is sent back to the socket
        # 8. The command thread is joint and closed

        # Command thread sens 4 command results. The last one has completion flag
        mock_thread.return_value.is_alive.return_value = True
        command_results = [
            (None, None, False),
            (None, None, False),
            (None, None, False),
            (56, ErrorCodes.COMMAND_SUCCESS, True),
        ]
        num_commands = len(command_results)
        command_results.reverse()
        queue_empty = False

        def get_side_effect(**_kwargs):
            nonlocal command_results, queue_empty
            queue_empty = not queue_empty
            if queue_empty or not command_results:
                raise Empty
            return command_results.pop()
        mock_queue.return_value.get.side_effect = get_side_effect
        tcp_server_client.preprocess_request.return_value = None
        tcp_server_client.process_request(request, mock_connection, address)
        # Assertions
        tcp_request.add_hop.assert_called_once()  # 2
        mock_connection.sendto.assert_has_calls([mock.call('encoded_request', address)
                                                 for _ in range(0, num_commands)] +  # 7, 3
                                                [mock.call('encoded_response', address)])  # 5
        tcp_server_client.queue_io.request_definitions.get.assert_called_once_with('what')
        mock_tcpresponse.assert_called_once_with(message=tcp_request)
        mock_queue.assert_has_calls([mock.call(), mock.call().close()], any_order=True)  # 8
        mock_thread.assert_has_calls([mock.call(target=tcp_server_client.command_interface.send_command,
                                                args=[mock_command, 'arg1', 'arg2', 'arg3'],
                                                kwargs={'queue': mock_queue.return_value}),  # 4
                                      mock.call().start(),  # 4
                                      mock.call().join()],
                                     any_order=True)  # 8
        tcp_response.set_data.assert_called_once_with(56)  # 5
        self.assertEqual(tcp_response.identifier, ErrorCodes.COMMAND_SUCCESS)  # 5
        # Resets
        mock_tcprequest.reset_mock()
        mock_tcpresponse.reset_mock()
        mock_connection.sendto.reset_mock()
        tcp_server_client.preprocess_request.reset_mock()
        mock_thread.reset_mock()
        mock_queue.reset_mock()
        tcp_request.add_hop.reset_mock()
        tcp_server_client.queue_io.request_definitions.get.reset_mock()
        tcp_response.set_data.reset_mock()
        # 6. Completion flag is not received but command thread is not alive. The loop is broken
        command_results = [(None, None, False)]
        num_commands = len(command_results)
        mock_thread.return_value.is_alive.return_value = False
        tcp_server_client.process_request(request, mock_connection, address)
        # Assertions
        mock_connection.sendto.assert_has_calls([mock.call('encoded_request', address)
                                                 for _ in range(0, num_commands + 1)])  # 6
        tcp_response.set_data.assert_not_called()  # 6
        print('test_TCPServerClient_process_request done')

    # Use cases:
    # 1. The input request is a TCPRequest. The request is put in the input queue and the
    #    response is retreived from link method
    # 2. The input request is not a TCPRequest. The reset_definitions metho is set on the queue_io object
    # 3. state is set to PENDING_DEFINITIONS_STATE
    # 4. Response data is set to ErrorCodes.COMMAND_SUCCESS
    @mock.patch('TCPServerClient.link')
    @mock.patch('TCPServerClient.Request')
    @mock.patch('TCPServerClient.Response')
    def test_TCPServerClient_reset_definitions(self, mock_response, mock_request, mock_link):
        tcp_server_client = self.tcp_server_client
        tcp_server_client.queue_io = mock.MagicMock()
        tcp_server_client.set_state = mock.MagicMock()
        # 1. The input request is a TCPRequest. The request is put in the input queue and the
        #    response is retreived from link method
        # 3. state is set to PENDING_DEFINITIONS_STATE
        # 4. Response data is set to ErrorCodes.COMMAND_SUCCESS
        tcp_request = self.tcp_request
        self.assertIs(tcp_server_client.reset_definitions(tcp_request), mock_link.return_value)
        # Assertions
        mock_link.assert_called_once_with(target_request=tcp_request, sender=tcp_server_client.queue_io.output_queue)
        tcp_server_client.queue_io.input_queue.put\
            .assert_called_once_with(mock_request.return_value.encode.return_value)  # 1
        mock_request.assert_called_once_with(message=tcp_request)  # 1
        tcp_server_client.set_state.assert_called_once_with(tcp_server_client.PENDING_DEFINITIONS_STATE)  # 3
        mock_link.return_value.set_data.assert_called_once_with(ErrorCodes.COMMAND_SUCCESS)
        tcp_server_client.queue_io.reset_definitions.assert_not_called()
        # Resets
        tcp_server_client.queue_io.reset_mock()
        mock_request.reset_mock()
        tcp_server_client.set_state.reset_mock()
        mock_link.reset_mock()
        # 2. The input request is not a TCPRequest. The reset_definitions metho is set on the queue_io object
        request = self.request
        self.assertIs(tcp_server_client.reset_definitions(request), mock_response.return_value)
        # Assertions
        mock_link.assert_not_called()
        tcp_server_client.queue_io.reset_definitions.assert_called_once()  # 2
        mock_response.assert_called_once_with(message=request)
        tcp_server_client.set_state.assert_called_once_with(tcp_server_client.PENDING_DEFINITIONS_STATE)  # 3
        mock_response.return_value.set_data.assert_called_once_with(ErrorCodes.COMMAND_SUCCESS)
        print('test_TCPServerClient_reset_definitions done')

    ##########################
    # Unit tests for TCPClient
    ##########################

    # Use cases:
    # 1. Client has no server address. state is set to ERROR_STATE, error code is set to
    #    NO_SERVER_DEFINED_ERROR and function returns
    # 2. attempt is higher then max_attempt. TCPexception is raised
    # 3. Client has a socket. The socket is closed
    # 4. Server state is not READY_STATE. The connection attempt is failed and function is recalled
    #    with incremented attempt number
    # 5. SocketWrapper is created and connect command is sent to the new socket
    # 6. Connect command response data is not COMMAND_SUCCESS. The connection attempt it failed. socket finish
    #    method is called and connect method is recalled with incremented attempt number
    # 7. Sending connect command raises a TCPException. The connection attempt it failed. socket finish
    #    method is called and connect method is recalled with incremented attempt number
    # 8. Connect command response data is COMMAND_SUCCESS. The connected attribute is set to True, the receiver
    #    process is started, error code and state are set
    @mock.patch('TCPServerClient.SocketWrapper')
    @mock.patch('TCPServerClient.TCPRequest')
    @mock.patch('TCPServerClient.get_data')
    @mock.patch('TCPServerClient.Response')
    @mock.patch('time.sleep')
    @mock.patch('socket.socket')
    def test_TCPClient_connect(self, mock_socket, _mock_sleep, mock_response, mock_get_data,
                               mock_tcprequest, mock_socketwrapper):
        tcp_client = self.tcp_client
        tcp_client.socket_port = 'socket_port'
        tcp_client.set_state = mock.MagicMock()
        tcp_client.get_server_state = mock.MagicMock()
        tcp_client.start_receiver_process = mock.MagicMock()
        response = self.response
        response.get_payload_data = mock.MagicMock()
        # 1. Client has no server address. state is set to ERROR_STATE, error code is set to
        #    NO_SERVER_DEFINED_ERROR and function returns
        tcp_client.server_addr = None
        tcp_client.connect()
        # Assertions
        tcp_client.set_state.assert_called_once_with(tcp_client.ERROR_STATE)
        self.assertEqual(tcp_client.error_code, ErrorCodes.NO_SERVER_DEFINED_ERROR)
        mock_socketwrapper.assert_not_called()
        tcp_client.get_server_state.assert_not_called()
        mock_response.assert_not_called()
        mock_tcprequest.assert_not_called()
        tcp_client.start_receiver_process.assert_not_called()
        mock_get_data.assert_not_called()
        self.assertFalse(tcp_client.connected)
        # Resets
        tcp_client.set_state.reset_mock()
        mock_socketwrapper.reset_mock()
        tcp_client.get_server_state.reset_mock()
        mock_response.reset_mock()
        mock_tcprequest.reset_mock()
        tcp_client.start_receiver_process.reset_mock()
        mock_get_data.reset_mock()
        # 2. attempt is higher then max_attempt. TCPexception is raised
        tcp_client.server_addr = 'server_addr'
        with self.assertRaises(TCPException):
            try:
                tcp_client.connect(attempt=1, max_attempt=1)
            except TCPException as e:
                self.assertEqual(str(e), 'Maximum number of connection attemps reached: 1')
                self.assertEqual(e.error_code, ErrorCodes.CLIENT_CONNECTION_ERROR)
                raise e
        tcp_client.get_server_state.assert_not_called()
        mock_socketwrapper.assert_not_called()
        mock_response.assert_not_called()
        mock_tcprequest.assert_not_called()
        mock_get_data.assert_not_called()
        tcp_client.start_receiver_process.assert_not_called()
        # Resets
        tcp_client.set_state.reset_mock()
        mock_socketwrapper.reset_mock()
        tcp_client.get_server_state.reset_mock()
        mock_response.reset_mock()
        mock_tcprequest.reset_mock()
        tcp_client.start_receiver_process.reset_mock()
        mock_get_data.reset_mock()
        # 3. Client has a socket. The socket is closed
        # 4. Server state is not READY_STATE. The connection attempt is failed and function is recalled
        #    with incremented attempt number
        # 5. SocketWrapper is created and connect command is sent to the new socket
        # 6. Connect command response data is not COMMAND_SUCCESS. The connection attempt it failed. socket finish
        #    method is called and connect method is recalled with incremented attempt number
        # 7. Sending connect command raises a TCPException. The connection attempt it failed. socket finish
        #    method is called and connect method is recalled with incremented attempt number
        # 8. Connect command response data is COMMAND_SUCCESS. The connected attribute is set to True, the receiver
        #    process is started, error code and state are set
        # Attempt 0: server state is not READY_STATE
        # Attempt 1: command response is not COMMAND_SUCCESS
        # Attempt 2: Sending connect request raises TCPException
        # Attempt 3: Connection is successfull

        class FakeAttemptNumber:
            value = 0

            def __add__(self, val):
                self.value += val
                return self

            def __ge__(self, val):
                return self.value >= val

        attempt = FakeAttemptNumber()
        successfull_attempt_number = 3

        def get_server_state_side_effect():
            nonlocal response, attempt
            if attempt.value == 0:
                response.get_payload_data.return_value = 'PENDING_DEFINITIONS_STATE'
            else:
                response.get_payload_data.return_value = 'READY_STATE'
            return response
        tcp_client.get_server_state.side_effect = get_server_state_side_effect

        def response_side_effect(*_, **__):
            nonlocal response, attempt
            if attempt.value == 1:
                payload = ErrorCodes.COMMAND_ERROR
            else:
                payload = ErrorCodes.COMMAND_SUCCESS
            response.get_payload_data.return_value = payload
            return response
        mock_response.side_effect = response_side_effect

        def get_data_side_effect(*_):
            nonlocal attempt
            if attempt.value == 2:
                raise TCPException
            return b'data'
        mock_get_data.side_effect = get_data_side_effect

        mock_socket_ = mock.MagicMock()
        tcp_client.socket = mock_socket_
        tcp_client.connect(attempt=attempt)
        # Assertions
        mock_socket_.close.assert_called_once()
        tcp_client.get_server_state.assert_has_calls([mock.call() for _ in range(0, successfull_attempt_number + 1)])
        mock_socketwrapper.assert_has_calls([
            # Attempt 1
            mock.call(mock_socket.return_value, ('server_addr', 'socket_port')),
            mock.call().connect(('server_addr', 'socket_port')),
            mock.call().send(mock_tcprequest.return_value.encode.return_value),
            mock.call().__bool__(),
            mock.call().finish(),
            # Attempt 2
            mock.call(mock_socket.return_value, ('server_addr', 'socket_port')),
            mock.call().connect(('server_addr', 'socket_port')),
            mock.call().send(mock_tcprequest.return_value.encode.return_value),
            mock.call().__bool__(),
            mock.call().finish(),
            # Attempt 3for mock.call(mock_socket.return_value),
            mock.call(mock_socket.return_value, ('server_addr', 'socket_port')),
            mock.call().connect(('server_addr', 'socket_port')),
            mock.call().send(mock_tcprequest.return_value.encode.return_value),
        ])
        expected_tcprequest_calls = []
        for _ in range(1, successfull_attempt_number + 1):
            expected_tcprequest_calls += [mock.call(what='connect', message_type='command', data_type='int'),
                                          mock.call().encode()]
        mock_tcprequest.assert_has_calls(expected_tcprequest_calls)
        mock_get_data.assert_has_calls([mock.call(mock_socketwrapper.return_value)
                                        for _ in range(1, successfull_attempt_number + 1)])
        mock_response.assert_has_calls([mock.call(encoded_data=b'data')
                                        for _ in range(2, successfull_attempt_number + 1)])
        self.assertTrue(tcp_client.connected)
        tcp_client.start_receiver_process.assert_called_once()
        self.assertEqual(tcp_client.error_code, ErrorCodes.NO_ERROR)
        tcp_client.set_state.assert_called_once_with(tcp_client.READY_STATE)
        print('test_TCPClient_connect done')

    # Use cases:
    # 1. Client is not connect. A TCPException is raised
    # 2. A TCPException is raised when receiving response. The client is disconnected and the exception is raised
    # 3. The received response what does not match the request. Client is disconnected and A TCPException is raised
    # 4. The received response identifier is not ErrorCodes.NO_ERROR and ignore_error parameter is False.
    #    The client is disconnected and a TCPException is raised
    # 5. The received response has a identifier that is not errorCodes.NO_ERROR and ignore_error input is True. The
    #    response is returned
    # 6. The received response is reset_definitions. The client is disconnected and response is returned
    def test_TCPClient_get_response(self):
        tcp_client = self.tcp_client
        tcp_client.socket = mock.MagicMock()
        tcp_client.disconnect = mock.MagicMock()
        response = self.response
        tcp_client.get_from_reception_queue = mock.MagicMock(return_value=response)
        tcp_request = self.tcp_request
        tcp_request.encode = mock.MagicMock(return_value='encoded_request')
        # 1. Client is not connect. A TCPException is raised
        tcp_client.connected = False
        with self.assertRaises(TCPException):
            try:
                tcp_client.get_response(tcp_request)
            except TCPException as e:
                self.assertEqual(str(e), 'TCPClient is not connected')
                self.assertEqual(e.error_code, ErrorCodes.CLIENT_NOT_CONNECTED_ERROR)
                raise e
        # Assertions
        tcp_client.socket.assert_not_called()
        tcp_client.get_from_reception_queue.assert_not_called()
        tcp_client.disconnect.assert_not_called()
        # Resets
        tcp_client.socket.reset_mock()
        tcp_client.get_from_reception_queue.reset_mock()
        tcp_client.disconnect.reset_mock()
        tcp_client.connected = True
        # 2. A TCPException is raised when receiving response. The client is disconnected and the exception is raised
        exception = TCPException()

        def get_from_reception_queue_side_effect(*_):
            nonlocal exception
            raise exception
        tcp_client.get_from_reception_queue.side_effect = get_from_reception_queue_side_effect
        with self.assertRaises(TCPException):
            try:
                tcp_client.get_response(tcp_request)
            except TCPException as e:
                self.assertIs(e, exception)
                raise e
        tcp_client.disconnect.assert_called_once()
        tcp_client.socket.send.assert_called_once_with('encoded_request')
        tcp_client.get_from_reception_queue.assert_called_once_with(tcp_request)
        # Resets
        tcp_client.socket.reset_mock()
        tcp_client.get_from_reception_queue.reset_mock()
        tcp_client.disconnect.reset_mock()
        tcp_client.get_from_reception_queue.side_effect = None
        # 3. The received response what does not match the request. Client is disconnected and A TCPException is raised
        response.what = 'response_what'
        with self.assertRaises(TCPException):
            try:
                tcp_client.get_response(tcp_request)
            except TCPException as e:
                self.assertEqual(str(e), 'The response ({}) is not the same as the request ({})'
                                 .format(response, tcp_request))
                raise e
        tcp_client.disconnect.assert_called_once()
        tcp_client.socket.send.assert_called_once_with('encoded_request')
        tcp_client.get_from_reception_queue.assert_called_once_with(tcp_request)
        # Resets
        tcp_client.socket.reset_mock()
        tcp_client.get_from_reception_queue.reset_mock()
        tcp_client.disconnect.reset_mock()
        response.what = 'what'
        tcp_request.what = 'what'
        # 4. The received response identifier is not ErrorCodes.NO_ERROR and ignore_error parameter is False.
        #    The client is disconnected and a TCPException is raised
        response.identifier = ErrorCodes.CLIENT_NOT_CONNECTED_ERROR
        response.get_payload_data = mock.MagicMock(return_value='error_message')
        with self.assertRaises(TCPException):
            try:
                tcp_client.get_response(tcp_request)
            except TCPException as e:
                self.assertEqual(str(e),
                                 '{}. {}'.format(ErrorCodes.ErrorMessages[ErrorCodes.CLIENT_NOT_CONNECTED_ERROR],
                                                 'error_message'))
                raise e
        tcp_client.disconnect.assert_called_once()
        tcp_client.socket.send.assert_called_once_with('encoded_request')
        tcp_client.get_from_reception_queue.assert_called_once_with(tcp_request)
        # Resets
        tcp_client.socket.reset_mock()
        tcp_client.get_from_reception_queue.reset_mock()
        tcp_client.disconnect.reset_mock()
        # 5. The received response has a identifier that is not errorCodes.NO_ERROR and ignore_error input is True. The
        #    response is returned
        self.assertIs(tcp_client.get_response(tcp_request, ignore_error=True), response)
        # Assertions
        tcp_client.disconnect.assert_not_called()
        response.identifier = ErrorCodes.NO_ERROR
        self.assertIs(tcp_client.get_response(tcp_request), response)
        tcp_client.disconnect.assert_not_called()
        # Resets
        tcp_client.socket.reset_mock()
        tcp_client.get_from_reception_queue.reset_mock()
        tcp_client.disconnect.reset_mock()
        # 6. The received response is reset_definitions. The client is disconnected and response is returned
        tcp_request.what = 'reset_definitions'
        response.what = 'reset_definitions'
        self.assertIs(tcp_client.get_response(tcp_request), response)
        tcp_client.disconnect.assert_called_once_with()
        print('test_TCPClient_get_response done')

    # Use cases:
    # 1. Connecting or sending to socket raises ConnectionRefusedError. A TCPException is raised
    # 2. No exception is raised. The request is sent to the socket and response is retreived from the socket
    # 3. finish is called on SocketWrapper object
    @mock.patch('TCPServerClient.TCPRequest')
    @mock.patch('TCPServerClient.TCPResponse')
    @mock.patch('TCPServerClient.SocketWrapper')
    @mock.patch('TCPServerClient.get_data')
    @mock.patch('socket.socket')
    def test_TCPClient_get_unconnected_response(self, mock_socket, mock_get_data, mock_socketwrapper,
                                                mock_tcp_response, mock_tcp_request):
        tcp_client = self.tcp_client
        tcp_client.server_addr = 'server_ipaddr'
        tcp_client.socket_port = 'socket_port'
        mock_tcp_request.return_value.encode.return_value = 'encoded_tcp_request'
        request = self.request
        tcp_response = self.tcp_response
        mock_tcp_response.return_value = tcp_response
        # 1. Connecting or sending to socket raises ConnectionRefusedError. A TCPException is raised
        # 3. finish is called on SocketWrapper object

        def send_side_effect(*_args):
            raise ConnectionRefusedError
        mock_socketwrapper.return_value.send.side_effect = send_side_effect
        with self.assertRaises(TCPException):
            try:
                tcp_client.get_unconnected_response(request)
            except TCPException as e:
                self.assertEqual(e.error_code, ErrorCodes.CLIENT_CONNECTION_ERROR)
                self.assertEqual(str(e), 'Connection was refused by the server or the server is not running')
                raise e
        # Assertions:
        mock_socketwrapper.assert_called_once_with(mock_socket.return_value)
        mock_socket.assert_called_once_with(socket.AF_INET, socket.SOCK_STREAM)
        mock_socketwrapper.return_value.connect.assert_called_once_with(('server_ipaddr', 'socket_port'))
        mock_get_data.assert_not_called()
        mock_tcp_response.assert_not_called()
        mock_tcp_request.assert_called_once_with(message=request)
        mock_socketwrapper.return_value.send.assert_called_once_with('encoded_tcp_request')
        mock_socketwrapper.return_value.finish.assert_called_once()
        # Resets
        mock_socketwrapper.reset_mock()
        mock_socket.reset_mock()
        mock_get_data.reset_mock()
        mock_tcp_request.reset_mock()
        mock_tcp_response.reset_mock()
        # 2. No exception is raised. The request is sent to the socket and response is retreived from the socket
        # 3. finish is called on SocketWrapper object
        mock_socketwrapper.return_value.send.side_effect = None
        self.assertIs(tcp_client.get_unconnected_response(request), tcp_response)
        # Asserions
        mock_socketwrapper.assert_called_once_with(mock_socket.return_value)
        mock_socket.assert_called_once_with(socket.AF_INET, socket.SOCK_STREAM)
        mock_socketwrapper.return_value.connect.assert_called_once_with(('server_ipaddr', 'socket_port'))
        mock_get_data.assert_called_once_with(mock_socketwrapper.return_value)
        mock_tcp_response.assert_called_once_with(encoded_data=mock_get_data.return_value)
        mock_tcp_request.assert_called_once_with(message=request)
        mock_socketwrapper.return_value.send.assert_called_once_with('encoded_tcp_request')
        mock_socketwrapper.return_value.finish.assert_called_once()
        print('test_TCPClient_get_unconnected_response done')

    # Use cases:
    # 1. No request is provided as intput. Request is retreived through queue_io.get_input_message
    # 2. No request is providied as input and get_request returns None. Nothing is done
    # 3. Request produces response through preprocess_request. The response is put in output queue
    # 4. preprocess_request returns no response. process_queue_request is started in new thread with
    #    request as argument
    # 5. Request is provided as input. That request is processed
    @mock.patch('TCPServerClient.Thread')
    def test_TCPClient_process_input_queue(self, mock_thread):
        tcp_client = self.tcp_client
        tcp_client.preprocess_request = mock.MagicMock()
        tcp_client.queue_io = mock.MagicMock()
        request = self.request
        response = self.response
        response.encode = mock.MagicMock(return_value='encoded_response')
        # 1. No request is provided as intput. request is retreived through queue_io.get_input_message
        # 2. No request is providied as input and get_request returns None. Nothing is done
        tcp_client.queue_io.get_input_message.return_value = None
        tcp_client.process_input_queue()
        # Assertions
        tcp_client.queue_io.get_input_message.assert_called_once()  # 1
        tcp_client.preprocess_request.assert_not_called()  # 2
        tcp_client.queue_io.output_queue.assert_not_called()  # 2
        mock_thread.assert_not_called()  # 2
        # Resets
        tcp_client.queue_io.reset_mock()
        tcp_client.preprocess_request.reset_mock()
        mock_thread.reset_mock()
        # 3. Request produces response through preprocess_request. The response is put in output queue
        # 5. Request is provided as input. That request is processed
        tcp_client.preprocess_request.return_value = response
        tcp_client.process_input_queue(request)
        # Assertions
        tcp_client.queue_io.get_input_message.assert_not_called()  # 5
        tcp_client.queue_io.output_queue.put.assert_called_once_with('encoded_response')
        mock_thread.assert_not_called()
        # Resets
        tcp_client.queue_io.reset_mock()
        tcp_client.preprocess_request.reset_mock()
        mock_thread.reset_mock()
        # 4. preprocess_request returns no response. process_queue_request is started in new thread with
        #    request as argument
        tcp_client.queue_io.get_input_message.return_value = request
        tcp_client.preprocess_request.return_value = None
        tcp_client.process_input_queue()
        # Assertions
        tcp_client.queue_io.output_queue.assert_not_called()
        mock_thread.assert_has_calls([mock.call(target=tcp_client.process_queue_request, args=(request,)),
                                      mock.call().start()])
        print('test_TCPClient_process_input_queue done')

    # Use cases:
    # 1. The request hop is incremented and put in output queue
    # 2. A new SocketWrapped is created
    # 3. TCPRequest is sent to the socket
    # 4. Link is created with link method between the socket and output queue
    # 5. A ConnectionRefusedError is raised when sending data to socket. A response with error code is sent
    #    to output queue
    # 6. finish is called on SocketWrapper
    # 7. Request number is added to piping numbers list
    @mock.patch('socket.socket')
    @mock.patch('TCPServerClient.SocketWrapper')
    @mock.patch('TCPServerClient.TCPRequest')
    @mock.patch('TCPServerClient.Response')
    @mock.patch('TCPServerClient.link')
    def test_TCPClient_process_queue_request(self, mock_link, mock_response, mock_tcprequest, mock_socketwrapper,
                                             mock_socket):
        tcp_client = self.tcp_client
        tcp_client.server_addr = 'server_addr'
        tcp_client.socket_port = 'socket_port'
        tcp_client.queue_io = mock.MagicMock()
        request = self.request
        request.encode = mock.MagicMock(return_value='encoded_request')
        request.add_hop = mock.MagicMock()
        response = self.response
        response.encode = mock.MagicMock(return_value='encoded_response')
        mock_response.return_value = response
        # 1. The request hop is incremented and put in output queue
        # 2. A new SocketWrapped is created
        # 3. TCPRequest is sent to the socket
        # 4. Link is created with link method between the socket and output queue
        # 6. finish is called on SocketWrapper
        # 7. Request number is added to piping numbers list
        tcp_client.process_queue_request(request)

        # Assertions
        request.add_hop.assert_called_once()  # 1
        tcp_client.queue_io.output_queue.put.assert_called_once_with('encoded_request')
        mock_socketwrapper.assert_called_once_with(mock_socket.return_value)  # 2
        mock_socket.assert_called_once_with(socket.AF_INET, socket.SOCK_STREAM)  # 2
        mock_socketwrapper.return_value.connect.assert_called_once_with(('server_addr', 'socket_port'))  # 3
        tcp_client.queue_io.piping_numbers.append.assert_called_once_with(request.number)  # 7
        mock_tcprequest.assert_called_once_with(message=request)  # 3
        mock_socketwrapper.return_value.send \
            .assert_called_once_with(mock_tcprequest.return_value.encode.return_value)  # 3
        mock_link.assert_called_once_with(sender=mock_socketwrapper.return_value,
                                          receiver=tcp_client.queue_io.output_queue,
                                          # receiver_piping_numbers=tcp_client.queue_io.piping_numbers,
                                          target_request=mock_tcprequest.return_value)  # 4
        mock_socketwrapper.return_value.finish.assert_called_once()  # 6
        # Resets
        request.add_hop.reset_mock()
        tcp_client.queue_io.reset_mock()
        mock_socketwrapper.reset_mock()
        mock_socket.reset_mock()
        mock_tcprequest.reset_mock()
        mock_link.reset_mock()
        mock_response.reset_mock()
        # 5. A ConnectionRefusedError is raised when sending data to socket. A response with error code is sent
        #    to output queue
        # 6. finish is called on SocketWrapper

        def connect_side_effect(*_args):
            raise ConnectionRefusedError
        mock_socketwrapper.return_value.connect.side_effect = connect_side_effect
        tcp_client.process_queue_request(request)
        # Assertions
        request.add_hop.assert_called_once()  # 1
        tcp_client.queue_io.output_queue.put.assert_called_once_with('encoded_response')  # 5
        mock_tcprequest.assert_not_called()
        mock_socketwrapper.return_value.send.assert_not_called()
        mock_link.assert_not_called()
        mock_response.assert_called_once_with(message=request)  # 5
        self.assertEqual(response.identifier, ErrorCodes.CLIENT_CONNECTION_ERROR)
        mock_socketwrapper.return_value.finish.assert_called_once()  # 6
        print('test_TCPClient_process_queue_request done')

    # Use cases:
    # 1. State is set to READY_STATE
    # 2. Client is not connected. try_connect is called
    # 3. Time since last do call is higher then do_rate. Method do is called
    # 4. Method process_input_queue is called
    # 5. Method sleeps for self.rate
    # 6. KeyboardInterrupt is received. Method self.disconnect is called
    def test_TCPClient_run(self):
        mock_sleep = mock.MagicMock()
        TcpServerClientPkg.time.sleep = mock_sleep
        tcp_client = self.tcp_client
        tcp_client.do_rate = 1
        tcp_client.try_connect = mock.MagicMock()
        tcp_client.set_state = mock.MagicMock()
        tcp_client.process_input_queue = mock.MagicMock()
        tcp_client.do = mock.MagicMock()
        tcp_client.disconnect = mock.MagicMock()
        TcpServerClientPkg.datetime.datetime = MockDatetime
        mock_time_delta = mock.MagicMock()
        mock_time_delta.total_seconds.return_value = 0
        mock_now = MockNow(mock_time_delta)
        MockDatetime.now = lambda: mock_now
        time_delta_return = 0

        # main loop runs 5 iterations. KeyboardInterrupt is raised on sleep of 5th iteration
        # client is not connected but receives connection when try_connect is called
        # do method is run every 2 iterations as total_seconds increases by 0.5 every iteration and do_rate is 1
        number_iterations = 5
        iteration_numer = 1

        def sleep_side_effect(*_):
            nonlocal number_iterations, iteration_numer, mock_time_delta, time_delta_return
            time_delta_return += 0.5
            mock_time_delta.total_seconds.return_value = time_delta_return
            if iteration_numer < number_iterations:
                iteration_numer += 1
            else:
                # pass
                raise KeyboardInterrupt

        def try_connect_side_effect():
            nonlocal tcp_client
            tcp_client.connected = True
        tcp_client.try_connect.side_effect = try_connect_side_effect
        mock_sleep.side_effect = sleep_side_effect
        tcp_client.run()
        # Assertions
        tcp_client.set_state.assert_called_once_with(tcp_client.READY_STATE)
        tcp_client.try_connect.assert_called_once()
        tcp_client.process_input_queue.assert_has_calls([mock.call() for _ in range(0, number_iterations)])
        tcp_client.do.assert_has_calls([mock.call() for _ in range(0, math.ceil(number_iterations / 2))])
        tcp_client.disconnect.assert_called_once()
        print('test_TCPClient_run done')

    # Use cases:
    # 1. Initial response has error code other then NO_ERROR and DEFINITIONS_NOT_RECEIVED_ERROR. A TCPExceptions
    #    is raised
    # 2. Initial response has error code of NO_ERROR or DEFINITIONS_NOT_RECEIVED_ERROR. The definitions
    #    are sent
    # 3. SocketWrapper is shutdown and close
    @mock.patch('socket.socket')
    @mock.patch('TCPServerClient.json')
    @mock.patch('TCPServerClient.SocketWrapper')
    @mock.patch('TCPServerClient.TCPRequest')
    @mock.patch('TCPServerClient.TCPResponse')
    def test_TCPClient_send_definitions(self, mock_tcpresponse, mock_tcprequest, mock_socketwrapper,
                                        mock_json, _mock_socket):
        def_min_size = DEFINITIONS_MESSAGE_SIZE * 3
        i = 0
        encoded_defs = b''
        while len(encoded_defs) < def_min_size:
            encoded_defs += i.to_bytes(3, byteorder='big')
            i += 1
        tcp_client = self.tcp_client
        tcp_client.server_addr = 'server_addr'
        tcp_client.socket_port = 'socket_port'
        tcp_client.queue_io = mock.MagicMock()
        tcp_client.queue_io.request_definitions.as_dict.return_value = 'dict_definitions'
        tcp_request = self.tcp_request
        tcp_response = self.tcp_response
        mock_tcprequest.return_value = tcp_request
        tcp_request.encode = mock.MagicMock()
        mock_tcpresponse.return_value = tcp_response
        mock_json.dumps.return_value.encode.return_value = encoded_defs
        mock_socketwrapper.return_value.recv.return_value = 'recv'
        # 1. Initial response has error code other then NO_ERROR and DEFINITIONS_NOT_RECEIVED_ERROR. A TCPExceptions
        #    is raised
        tcp_response.identifier = ErrorCodes.UNDEFINED_REQUEST_ERROR
        with self.assertRaises(TCPException):
            try:
                tcp_client.send_definitions()
            except TCPException as e:
                self.assertEqual(str(e),
                                 'Sending definitions initial response has error code: {}'
                                 .format(ErrorCodes.UNDEFINED_REQUEST_ERROR))
                # raise e
            raise TCPException()
        # Assertions
        mock_json.dumps.assert_called_once_with('dict_definitions')
        mock_tcprequest.assert_called_once_with(what='accept_definitions', message_type='command', data_type='int')
        mock_socketwrapper.return_value.connect.assert_called_once_with(('server_addr', 'socket_port'))
        mock_socketwrapper.return_value.send.assert_called_once_with(mock_tcprequest.return_value.encode.return_value)
        mock_tcpresponse.assert_called_once_with(encoded_data='recv')
        # Resets
        mock_json.dumps.reset_mock()
        mock_tcprequest.reset_mock()
        mock_socketwrapper.return_value.connect.reset_mock()
        mock_socketwrapper.reset_mock()
        mock_tcpresponse.reset_mock()
        # 2. Initial response has error code of NO_ERROR or DEFINITIONS_NOT_RECEIVED_ERROR. The definitions
        #    are sent
        # 3. SocketWrapper is shutdown and close
        tcp_response.identifier = ErrorCodes.NO_ERROR
        reconstructed_send_data = b''

        def send_side_effect(data):
            nonlocal reconstructed_send_data
            if isinstance(data, bytes):
                reconstructed_send_data += data[TCP_MESSAGE_SIZE_LENGTH:]
        mock_socketwrapper.return_value.send.side_effect = send_side_effect
        tcp_client.send_definitions()
        # Assertions
        mock_json.dumps.assert_called_once_with('dict_definitions')
        mock_tcprequest.assert_called_once_with(what='accept_definitions', message_type='command', data_type='int')
        mock_socketwrapper.return_value.connect.assert_called_once_with(('server_addr', 'socket_port'))
        mock_socketwrapper.return_value.send\
            .assert_has_calls([mock.call(mock_tcprequest.return_value.encode.return_value)])
        mock_tcpresponse.assert_called_once_with(encoded_data='recv')
        self.assertEqual(reconstructed_send_data, encoded_defs)
        mock_socketwrapper.return_value.shutdown.assert_called_once_with(socket.SHUT_RDWR)
        mock_socketwrapper.return_value.close.assert_called_once()
        print('test_TCPClient_send_definitions done')

    ###################################
    # Unit tests for TCPClientSMUpdater
    ###################################

    # Use cases:
    # 1. Client has no do_updates_thread. The do_updates_thread is started
    # 2. Client has do_updates_thread but the thread is not alive. A new thread is started
    # 3. Client has do_updates_thread and thread is alive. Nothing is done
    @mock.patch('TCPServerClient.Thread')
    def test_TCPClientSMUpdater_do(self, mock_thread):
        client = self.tcp_client_sm_updater
        # 1. Client has no do_updates_thread. The do_updates_thread is started
        client.do_updates_thread = None
        client.do()
        mock_thread.assert_has_calls([mock.call(target=client.do_updates), mock.call().start()])
        # Resets
        mock_thread.reset_mock()
        # 2. Client has do_updates_thread but the thread is not alive. A new thread is started
        client.do_updates_thread = mock.MagicMock()
        client.do_updates_thread.is_alive.return_value = False
        client.do()
        mock_thread.assert_has_calls([mock.call(target=client.do_updates), mock.call().start()])
        # Resets
        mock_thread.reset_mock()
        # 3. Client has do_updates_thread and thread is alive. Nothing is done
        client.do_updates_thread.is_alive.return_value = True
        client.do()
        mock_thread.assert_not_called()
        print('test_TCPClientSMUpdater_do done')

    # Use cases:
    # 1. A shared memory already exists. It is closed and re-created
    # 2. A shared memory does not exist. It is created
    @mock.patch('TCPServerClient.shared_memory.SharedMemory')
    def test_TCPClientSMUpdater_set_shared_mem(self, mock_sharedmemory):
        client = self.tcp_client_sm_updater
        client.shared_mem = {
            'sm_1': mock.MagicMock(),
            'sm_2': mock.MagicMock(),
        }
        client.shared_mem['sm_1'].name = 'sm_1'
        client.shared_mem['sm_1'].size = 10
        client.shared_mem['sm_1'].initialized = False
        client.shared_mem['sm_2'].name = 'sm_2'
        client.shared_mem['sm_2'].size = 20
        client.shared_mem['sm_2'].initialized = False

        def sharedmemory_side_effect(**kwargs):
            nonlocal client, mock_sharedmemory
            if kwargs.pop('name') == 'sm_1' and not kwargs.pop('create', False):
                raise FileNotFoundError
            return mock_sharedmemory.return_value
        mock_sharedmemory.side_effect = sharedmemory_side_effect
        client.set_shared_mem()
        # Assertions
        mock_sharedmemory.assert_has_calls([mock.call(name='sm_1'),
                                            mock.call(name='sm_1', create=True, size=18),
                                            mock.call(name='sm_2'),
                                            mock.call().close(),
                                            mock.call().unlink(),
                                            mock.call(name='sm_2', create=True, size=28)])
        self.assertTrue(client.shared_mem['sm_1'].initialized)
        self.assertTrue(client.shared_mem['sm_2'].initialized)
        print('test_TCPClientSMUpdater_set_shared_mem done')

    # Use cases:
    # 1. The shared memory is not read ready. A TCPException is raised
    # 2. The shared memory is ready ready. The counter is retreived through start_update, the request definitions
    #    is set, the response is retrived, the response data is written with the counter
    @mock.patch('TCPServerClient.TCPRequest')
    def test_TCPClientSMUpdater_update_shared_mem(self, mock_tcprequest):
        client = self.tcp_client_sm_updater
        client.get_request_definition = mock.MagicMock()
        client.get_response = mock.MagicMock()
        shared_mem = mock.MagicMock()
        client.shared_mem = {'name': shared_mem}
        # 1
        shared_mem.is_read_ready.return_value = False
        with self.assertRaises(TCPException):
            try:
                client.update_shared_mem('name')
            except TCPException as e:
                self.assertEqual(str(e), 'Shared memory name is not ready to be updated')
                raise e
        # Assertions
        shared_mem.start_update.assert_not_called()
        mock_tcprequest.assert_not_called()
        client.get_request_definition.assert_not_called()
        shared_mem.write_raw.assert_not_called()
        # 2
        shared_mem.is_read_ready.return_value = True
        client.update_shared_mem('name')
        # Assertions
        shared_mem.start_update.assert_called_once()
        mock_tcprequest.assert_called_once_with(message_type='query', what='name')
        client.get_request_definition.assert_called_once_with('name')
        mock_tcprequest.return_value.set_definition.assert_called_once_with(client.get_request_definition.return_value)
        client.get_response.assert_called_once_with(mock_tcprequest.return_value)
        shared_mem.write_raw.assert_called_once_with(shared_mem.start_update.return_value,
                                                     client.get_response.return_value.raw_data)
        print('test_TCPClientSMUpdater_update_shared_mem done')

    ###################################
    # Unit tests for TCPClientSharedMem
    ###################################

    @mock.patch('TCPServerClient.shared_memory.SharedMemory')
    def test_TCPClientSharedMem_close(self, mock_sharedmemory):
        sm = self.tcp_client_shared_mem
        sm.close()
        mock_sharedmemory.assert_has_calls([mock.call(name=sm.name), mock.call().close(), mock.call().unlink()])
        print('test_TCPClientSharedMem_close done')

    # Use cases:
    # 1. Shared memory is not read ready before wait limit. TCPException is raised
    # 2. Shared memory is not read ready but no_wait is True. Data is decoded and returned
    # 3. Shared memory is read ready and data type is bool. Non-zero data is returned as True
    # 4. Data type is int. Data is decoded as integer
    # 5. Data type is string. Data is decoded as string and returned
    # 6. Data type is float. Data is decoded as string and converted to float being returned
    # 7. Data type is float but data cannot be converted to float. A TCPException is raised
    @mock.patch('TCPServerClient.shared_memory.SharedMemory')
    @mock.patch('Requests.Logger')
    def test_TCPClientSharedMem_read(self, _mock_logger, mock_sharedmemory):
        sm = self.tcp_client_shared_mem
        sm.is_read_ready = mock.MagicMock(return_value=False)
        # 1. Shared memory is not read ready before wait limit. TCPException is raised
        mock_time_delta = mock.MagicMock()
        mock_time_delta.total_seconds.return_value = SHAREDMEM_WAIT_LIMIT + 1
        mock_now = MockNow(mock_time_delta)
        TcpServerClientPkg.datetime.datetime = MockDatetime
        MockDatetime.now = lambda: mock_now
        with self.assertRaises(TCPException):
            try:
                sm.read()
            except TCPException as e:
                self.assertEqual(str(e), 'Timed out waitong for shared memory sm_name')
                raise e
        # Assertions
        mock_sharedmemory.assert_not_called()
        # Resets
        mock_sharedmemory.reset_mock()
        # 2. Shared memory is not read ready but no_wait is True. Data is decoded and returned
        # 3. Shared memory is read ready and data type is bool. Non-zero data is returned as True
        sm.type = 'bool'
        mock_sharedmemory.return_value.buf.__getitem__.return_value = b'\x00'
        self.assertFalse(sm.read(no_wait=True))
        mock_time_delta.total_seconds.return_value = 0
        sm.is_read_ready.return_value = True
        mock_sharedmemory.return_value.buf.__getitem__.return_value = b'\x01'
        self.assertTrue(sm.read())
        # 4. Data type is int. Data is decoded as integer
        sm.type = 'int'
        mock_sharedmemory.return_value.buf.__getitem__.return_value = b'\x00\x00\x08'
        self.assertEqual(sm.read(), 8)
        mock_sharedmemory.return_value.buf.__getitem__.return_value = b'\xff\xff\xff\xfc'  # -4
        self.assertEqual(sm.read(), -4)
        # 5. Data type is string. Data is decoded as string and returned
        sm.type = 'str'
        mock_sharedmemory.return_value.buf.__getitem__.return_value = b'\x00\x00\x00test_data'
        self.assertEqual(sm.read(), 'test_data')
        # 6. Data type is float. Data is decoded as string and converted to float being returned
        sm.type = 'float'
        mock_sharedmemory.return_value.buf.__getitem__.return_value = b'\x00\x00\x0067.87'
        self.assertEqual(sm.read(), 67.87)
        mock_sharedmemory.return_value.buf.__getitem__.return_value = b'\x00\x00\x00-14.8'
        self.assertEqual(sm.read(), -14.8)
        # 7. Data type is float but data cannot be converted to float. A TCPException is raised
        mock_sharedmemory.return_value.buf.__getitem__.return_value = b'\x00\x00\x00not a float'
        with self.assertRaises(TCPException):
            try:
                sm.read()
            except TCPException as e:
                self.assertEqual(str(e), 'Could not read valid value from data: "not a float" for shared mem: sm_name')
                raise e
        print('test_TCPClientSharedMem_read done')

    @mock.patch('TCPServerClient.shared_memory.SharedMemory')
    def test_TCPClientSharedMem_start_update(self, mock_sharedmemory):
        sm = self.tcp_client_shared_mem
        sm.get_counter = mock.MagicMock()
        self.assertIs(sm.start_update(), sm.get_counter.return_value)
        mock_sharedmemory.assert_has_calls([mock.call(name=sm.name),
                                            mock.call().buf.__setitem__(slice(None, 1, None), SHAREDMEM_WRITE_READY)])
        print('test_TCPClientSharedMem_start_update done')

    # Use cases:
    # 1. Input counter and shared memory counter do not match. A TCPException is raised
    # 2. The shared memory is not write ready. A TCPException is raised
    # 3. The input data is smaller in size then the shared memory buffer. Leading 0s are added
    # 4. The data is writted to the shared memory buffer
    # 5. The counter in the buffer is incremented
    # 6. The reading byte is set to read ready
    @mock.patch('TCPServerClient.shared_memory.SharedMemory')
    def test_TCPClientSharedMem_write_raw(self, mock_sharedmemory):
        sm = self.tcp_client_shared_mem
        sm.name = 'name'
        sm.size = 6
        sm.get_counter = mock.MagicMock(return_value=1)
        sm.is_write_ready = mock.MagicMock(return_value=True)
        # 1. Input counter and shared memory counter do not match. A TCPException is raised
        with self.assertRaises(TCPException):
            try:
                sm.write_raw(2, b'data')
            except TCPException as e:
                self.assertEqual(str(e), 'Attempt to write to shared memory with counter 2 that does not match '
                                         'expected counter 1')
                raise e
        mock_sharedmemory.assert_not_called()
        # 2. The shared memory is not write ready. A TCPException is raised
        sm.is_write_ready.return_value = False
        with self.assertRaises(TCPException):
            try:
                sm.write_raw(1, b'data')
            except TCPException as e:
                self.assertEqual(str(e), 'Attempt to write to shared memory name while shared memory is '
                                         'not write ready')
                raise e
        mock_sharedmemory.assert_not_called()
        # 3. The input data is smaller in size then the shared memory buffer. Leading 0s are added
        # 4. The data is writted to the shared memory buffer
        # 5. The counter in the buffer is incremented
        # 6. The reading byte is set to read ready
        sm.is_write_ready.return_value = True
        sm.write_raw(1, b'data')
        mock_sharedmemory.assert_has_calls([
            mock.call(name='name'),
            mock.call().buf.__setitem__(slice(8, None, None), b'\x00\x00data'),  # 3, 4
            mock.call().buf.__setitem__(slice(1, 8, None), b'\x00\x00\x00\x00\x00\x00\x02'),  # 5
            mock.call().buf.__setitem__(slice(None, 1, None), SHAREDMEM_READ_READY),
        ])
        print('test_TCPClientSharedMem_write_raw done')

    ##########################
    # Unit tests for TCPServer
    ##########################

    # Use cases:
    # 1. SocketWrapper is created
    # 2. timeout is set
    # 3. setsockopt is set
    # 4. Bind raises OSError. The connection address and port are added to the exception and raised
    # 5. listen is called
    # 6. connect is set to True
    @mock.patch('socket.socket')
    @mock.patch('TCPServerClient.SocketWrapper')
    def test_TCPServer_connect(self, mock_socketwrapper, mock_socket):
        tcp_server = self.tcp_server
        tcp_server.connected = False
        tcp_server.host_ipaddr = 'host_ipaddr'
        tcp_server.socket_port = 'socket_port'

        def bind_side_effect(*_):
            raise OSError('some OSError')
        mock_socketwrapper.return_value.bind.side_effect = bind_side_effect
        with self.assertRaises(OSError):
            try:
                tcp_server.connect()
            except OSError as e:
                self.assertEqual(str(e), 'some OSError\nAttempted to bind address host_ipaddr and port socket_port')
                raise e
        mock_socketwrapper.return_value.finish.assert_called_once()
        self.assertIsNone(tcp_server.socket)
        mock_socketwrapper.return_value.bind.side_effect = None
        self.assertFalse(tcp_server.connected)
        mock_socketwrapper.reset_mock()
        mock_socket.reset_mock()
        # 1. SocketWrapper is created
        # 2. timeout is set
        # 3. setsockopt is set
        # 5. listen is called
        # 6. connect is set to True
        tcp_server.connect()
        mock_socketwrapper.assert_has_calls([
            mock.call(mock_socket.return_value),  # 1
            mock.call().settimeout(tcp_server.socket_timeout),  # 2
            mock.call().setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1),  # 3
            mock.call().bind(('host_ipaddr', 'socket_port')),
            mock.call().listen(1),
        ])
        self.assertTrue(tcp_server.connected)
        mock_socket.assert_called_once_with(socket.AF_INET, socket.SOCK_STREAM)
        print('test_TCPServer_connect done')

    # Use cases:
    # 1. get_data returns empty bytes. The loop is broken
    # 2. preprocess_request returns a response. The encoded response is sent to the socket
    # 3. preprocess_request returns None. The server state is set to READY_STATE and the request,
    #    connection and address are sent to process_request
    # 4. KeyboardInterrupt is raised. The loop is broken
    @mock.patch('TCPServerClient.TCPResponse')
    @mock.patch('TCPServerClient.get_data')
    def test_TCPServer_handle_connection(self, mock_get_data, mock_tcpresponse):
        tcp_server = self.tcp_server
        response = self.response
        request = self.request
        tcp_server.reconstruct_request = mock.MagicMock()
        tcp_server.preprocess_request = mock.MagicMock()
        tcp_server.set_state = mock.MagicMock()
        tcp_server.process_request = mock.MagicMock()
        mock_connection = mock.MagicMock()
        # 1. get_data returns empty bytes. The loop is broken
        mock_get_data.return_value = b''
        tcp_server.handle_connection(mock_connection, 'address')
        # Assertions
        mock_connection.assert_not_called()
        tcp_server.reconstruct_request.assert_not_called()
        tcp_server.preprocess_request.assert_not_called()
        tcp_server.set_state.assert_not_called()
        tcp_server.process_request.assert_not_called()
        mock_tcpresponse.assert_not_called()
        # Resets
        mock_connection.reset_mock()
        tcp_server.reconstruct_request.reset_mock()
        tcp_server.preprocess_request.reset_mock()
        tcp_server.set_state.reset_mock()
        tcp_server.process_request.reset_mock()
        mock_tcpresponse.reset_mock()
        # 2. preprocess_request returns a response. The encoded response is sent to the socket
        called = False
        tcp_server.reconstruct_request.return_value = request

        def get_data_side_effect(*_):
            nonlocal called
            if called:
                return b''
            else:
                called = True
                return b'data'
        mock_get_data.side_effect = get_data_side_effect
        tcp_server.preprocess_request.return_value = response
        tcp_server.handle_connection(mock_connection, 'address')
        # Assertions
        tcp_server.reconstruct_request.assert_called_once_with(b'data')
        tcp_server.preprocess_request.assert_called_once_with(request)
        mock_tcpresponse.assert_called_once_with(message=response)
        mock_connection.sendto.assert_called_once_with(mock_tcpresponse.return_value.encode.return_value, 'address')
        tcp_server.set_state.assert_not_called()
        tcp_server.process_request.assert_not_called()
        # Resets
        mock_connection.reset_mock()
        tcp_server.reconstruct_request.reset_mock()
        tcp_server.preprocess_request.reset_mock()
        tcp_server.set_state.reset_mock()
        tcp_server.process_request.reset_mock()
        mock_tcpresponse.reset_mock()
        # 3. preprocess_request returns None. The server state is set to READY_STATE and the request,
        #    connection and address are sent to process_request
        tcp_server.preprocess_request.return_value = None
        called = False
        tcp_server.handle_connection(mock_connection, 'address')
        # Assertions
        tcp_server.reconstruct_request.assert_called_once_with(b'data')
        tcp_server.preprocess_request.assert_called_once_with(request)
        mock_tcpresponse.assert_not_called()
        mock_connection.sendto.assert_not_called()
        tcp_server.set_state.assert_called_once_with(tcp_server.READY_STATE)
        tcp_server.process_request.assert_called_once_with(request, mock_connection, 'address')
        # Resets
        mock_connection.reset_mock()
        tcp_server.reconstruct_request.reset_mock()
        tcp_server.preprocess_request.reset_mock()
        tcp_server.set_state.reset_mock()
        tcp_server.process_request.reset_mock()
        mock_tcpresponse.reset_mock()
        # 4. KeyboardInterrupt is raised. The loop is broken

        def get_data_side_effect_ki(*_):
            raise KeyboardInterrupt
        mock_get_data.side_effect = get_data_side_effect_ki
        # Assertions
        mock_connection.assert_not_called()
        tcp_server.reconstruct_request.assert_not_called()
        tcp_server.preprocess_request.assert_not_called()
        tcp_server.set_state.assert_not_called()
        tcp_server.process_request.assert_not_called()
        mock_tcpresponse.assert_not_called()
        print('test_TCPServer_handle_connection done')

    def test_RequestDefinition_build_command(self):
        req_def = RequestDefinitions.RequestDefinition(**{'Name': 'test',
                                                          'Type': 'command',
                                                          'NumberOfArguments': '3',
                                                          'DataType': 'int',
                                                          'WaitForConfirmation': 'test_confirmation',
                                                          'ExpectedReturn': '$arg_1',
                                                          'WaitForReturn': 'false',
                                                          'CommandArguments':
                                                              'stat_arg_1,-stat_arg2,$dyn_arg_1,--stat_arg_3'
                                                              ',$dyn_arg_2,--stat_arg_4,$dyn_arg_3',
                                                          'Duplicatable': 'false',
                                                          'ProcessName': 'test'})
        self.assertEqual(req_def.build_command('dyn_arg_val_1', 'dyn_arg_val_2', 'dyn_arg_val_3'),
                         ['stat_arg_1', '-stat_arg2', 'dyn_arg_val_1', '--stat_arg_3',
                          'dyn_arg_val_2', '--stat_arg_4', 'dyn_arg_val_3'])
        req_def = RequestDefinitions.RequestDefinition(**{'Name': 'test',
                                                          'Type': 'command',
                                                          'NumberOfArguments': '3',
                                                          'DataType': 'int',
                                                          'WaitForConfirmation': 'test_confirmation',
                                                          'ExpectedReturn': '$arg_1',
                                                          'WaitForReturn': 'false',
                                                          'CommandArguments':
                                                              'stat_arg_1,-stat_arg2,$dyn_arg_1,--stat_arg_3'
                                                              ',$dyn_arg_2,--stat_arg_4,$dyn_arg_3',
                                                          'Duplicatable': 'false',
                                                          'ProcessName': 'test',
                                                          'DefaultArgumentValues': '$dyn_arg_2:def_val_2,'
                                                                                   '$dyn_arg_3:def_val_3'})
        self.assertEqual(req_def.build_command('dyn_arg_val_1'),
                         ['stat_arg_1', '-stat_arg2', 'dyn_arg_val_1', '--stat_arg_3',
                          'def_val_2', '--stat_arg_4', 'def_val_3'])
        req_def = RequestDefinitions.RequestDefinition(**{'Name': 'test',
                                                          'Type': 'command',
                                                          'NumberOfArguments': '0',
                                                          'DataType': 'int',
                                                          'WaitForConfirmation': 'test_confirmation',
                                                          'ExpectedReturn': 'None',
                                                          'WaitForReturn': 'false',
                                                          'CommandArguments': 'stat_arg_1,-stat_arg2',
                                                          'Duplicatable': 'false',
                                                          'ProcessName': 'test'})
        self.assertEqual(req_def.build_command(), ['stat_arg_1', '-stat_arg2'])
        print('test_RequestDefinition_build_command done')

    @mock.patch('TCPServerClient.TCPResponse')
    @mock.patch('TCPServerClient.TCPRequest')
    @mock.patch('subprocess.Popen')
    def test_TCPServer_process_request_send_command(self, mock_popen, mock_request, mock_response):
        tcp_server = self.tcp_server
        tcp_server.command_interface.find_running_process = mock.MagicMock(return_value=None)
        tcp_server.set_request_definitions({
            'test': {'Name': 'test',
                     'Type': 'command',
                     'NumberOfArguments': '3',
                     'DataType': 'int',
                     'WaitForConfirmation': 'test_confirmation',
                     'ExpectedReturn': '$dyn_arg_1',
                     'WaitForReturn': 'false',
                     'CommandArguments':
                         'stat_arg_1,-stat_arg2,$dyn_arg_1,--stat_arg_3'
                         ',$dyn_arg_2,--stat_arg_4,$dyn_arg_3',
                     'Duplicatable': 'false',
                     'ProcessName': 'test'},
            'test_confirmation': {'Name': 'test_confirmation',
                                  'Type': 'query',
                                  'NumberOfArguments': '0',
                                  'DataType': 'int',
                                  'ExpectedReturn': '',
                                  'WaitForReturn': 'true',
                                  'Duplicatable': 'false',
                                  'MaxRetries': '10',
                                  'ProcessName': 'test_confirmation'}
        })
        request = self.tcp_request
        response = self.tcp_response
        response.encode = mock.MagicMock(return_value=b'encoded_value')
        response.set_data = mock.MagicMock()
        # 1. Command has wait_for confirmation command and expected return is received on the 3rd try
        mock_popen.return_value.communicate.return_value = b'0', b''
        request.what = 'test'
        request.message_type = 'command'
        request.args = ['0', '1', '2']
        request.set_definition(tcp_server.queue_io.get_request_definition('test'))
        request.is_ping = mock.MagicMock(return_value=False)
        request.is_get_state = mock.MagicMock(return_value=False)
        mock_request.return_value = request
        mock_response.return_value = response
        confirmation_try = 0
        confirmation_success = 2

        def is_expected_return_side_effect(*_args, **_kwargs):
            nonlocal confirmation_try, confirmation_success
            success = confirmation_try >= confirmation_success
            confirmation_try += 1
            return success
        tcp_server.queue_io.request_definitions.request_definitions['test_confirmation'] \
            .is_expected_return = mock.MagicMock()
        tcp_server.queue_io.request_definitions.request_definitions['test_confirmation'] \
            .is_expected_return.side_effect = is_expected_return_side_effect
        request.encode = mock.MagicMock()
        mock_connection = mock.MagicMock()
        address = 'fake_address'
        tcp_server.process_request(request, mock_connection, address)
        mock_connection.sendto.assert_has_calls([mock.call(mock_request.return_value.encode.return_value, address)
                                                 for _ in range(0, confirmation_success + 1)] +
                                                [mock.call(mock_response.return_value.encode.return_value, address)])
        self.assertEqual(response.identifier, ErrorCodes.NO_ERROR)
        response.set_data.assert_called_once_with(ErrorCodes.COMMAND_SUCCESS)
        # Resets
        mock_connection.reset_mock()
        response.set_data.reset_mock()
        # 2. command has wait_for_return and expected_return is received on first try
        tcp_server.queue_io.request_definitions.request_definitions['test_confirmation'] \
            .is_expected_return.side_effect = None
        tcp_server.queue_io.request_definitions.request_definitions['test_confirmation'] \
            .is_expected_return.return_value = True
        tcp_server.process_request(request, mock_connection, address)
        mock_connection.sendto.assert_has_calls([mock.call(mock_request.return_value.encode.return_value, address),
                                                 mock.call(mock_response.return_value.encode.return_value, address)])
        self.assertEqual(response.identifier, ErrorCodes.NO_ERROR)
        response.set_data.assert_called_once_with(ErrorCodes.COMMAND_SUCCESS)
        # Resets
        mock_connection.reset_mock()
        response.set_data.reset_mock()
        # 3. Command has wait_for_confirmation_command and maximum retries is reached
        mock_popen.return_value.communicate.return_value = b'File not found', b''
        tcp_server.queue_io.request_definitions.request_definitions['test_confirmation'] \
            .is_expected_return.return_value = False
        tcp_server.process_request(request, mock_connection, address)
        mock_connection.sendto.assert_has_calls([mock.call(mock_request.return_value.encode.return_value, address)
                                                 for _ in range(0, tcp_server.queue_io.request_definitions
                                                                .request_definitions['test_confirmation'].max_retries
                                                                + 1)] +
                                                [mock.call(mock_response.return_value.encode.return_value, address)])
        self.assertEqual(response.identifier, ErrorCodes.COMMAND_ERROR)
        response.set_data.assert_called_once_with(ErrorCodes.COMMAND_ERROR)
        print('test_TCPServer_process_request_send_command done')

    def test_tcp_server(self):
        tcp_client = self.tcp_client
        tcp_server = self.tcp_server

        def process_request_side_effect(request, connection, address):
            response = TCPResponse(message=request)
            response.hop = 98
            response.set_data(89)
            connection.sendto(response.encode(), address)
        tcp_server.process_request = mock.MagicMock()
        tcp_server.process_request.side_effect = process_request_side_effect
        server_process = Process(target=tcp_server.run)
        server_process.start()
        self.started_processes.append(server_process.pid)
        time.sleep(1)
        # Assert server is awaiting definitions
        state_response = tcp_client.get_server_state()
        self.assertEqual(state_response.get_payload_data(), 'PENDING_DEFINITIONS_STATE')
        tcp_client.send_definitions()
        # Assert server is READY_STATE
        state_response = tcp_client.get_server_state()
        self.assertEqual(state_response.get_payload_data(), 'READY_STATE')
        time.sleep(1)
        print('test_tcp_server done')

    def test_reset_definitions(self):
        tcp_server = self.tcp_server
        tcp_client = self.tcp_client
        reset_def_request = TCPRequest(message_type='command')
        reset_def_request.set_definition(tcp_server.queue_io.get_request_definition('reset_definitions'))
        tcp_server_process = Process(target=tcp_server.run)
        tcp_server_process.start()
        time.sleep(1)
        self.started_processes.append(tcp_server_process.pid)
        get_state_response = tcp_client.get_server_state()
        self.assertEqual(get_state_response.get_payload_data(), 'PENDING_DEFINITIONS_STATE')
        # Send definitions
        tcp_client.send_definitions()
        get_state_response = tcp_client.get_server_state()
        self.assertEqual(get_state_response.get_payload_data(), 'READY_STATE')
        # Connect
        tcp_client.connect()
        get_state_response = tcp_client.get_server_state()
        self.assertEqual(get_state_response.get_payload_data(), 'READY_STATE')
        # Reset definitions
        reset_response = tcp_client.command('reset_definitions')
        self.assertEqual(reset_response.get_payload_data(), ErrorCodes.COMMAND_SUCCESS)
        get_state_response = tcp_client.get_server_state()
        self.assertEqual(get_state_response.get_payload_data(), 'PENDING_DEFINITIONS_STATE')
        tcp_server.reset_definitions(reset_def_request)
        # Re-send definitions
        tcp_client.send_definitions()
        get_state_response = tcp_client.get_server_state()
        self.assertEqual(get_state_response.get_payload_data(), 'READY_STATE')
        print('test_reset_definitions done')

    def test_TCPServer_reset_definitions(self):
        tcp_server = self.tcp_server
        request = Request(what='reset_definitions', message_type='command')
        tcp_server.reset_definitions(request)
        self.assertEqual(tcp_server.state, 'PENDING_DEFINITIONS_STATE')
        print('test_TCPServer_reset_definitions done')


class MockDatetime(datetime.datetime):
    pass


class MockNow:
    def __init__(self, time_delta):
        self.time_delta = time_delta

    def __sub__(self, _):
        return self.time_delta
