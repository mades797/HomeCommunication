import re
import subprocess
import xml.etree.ElementTree as ElementTree
from abc import ABCMeta, abstractmethod
import datetime

import ErrorCodes
from Logger import Logger

DEFAULT_MAX_RETRIES = 5
DEFAULT_RETRY_WAIT = 1

RESPONSE_ERROR = 1
RESPONSE_NO_ERROR = 0
REQUEST_IDENT = 255

DATA_TYPE_CODE_INT = 1
DATA_TYPE_CODE_STR = 2
DATA_TYPE_CODE_BOOL = 3
DATA_TYPE_CODE_FLOAT = 4
DATA_TYPE_CODES = {
    DATA_TYPE_CODE_INT: 'int',
    DATA_TYPE_CODE_STR: 'str',
    DATA_TYPE_CODE_BOOL: 'bool',
    DATA_TYPE_CODE_FLOAT: 'float',
}
ENCODED_MESSAGE_NUMBER_INDEX = 0
ENCODED_MESSAGE_NUMBER_LENGTH = 8
ENCODED_MESSAGE_SENDER_INDEX = 8
ENCODED_MESSAGE_SENDER_LENGTH = 1
ENCODED_MESSAGE_INDENTIFIER_INDEX = 9
ENCODED_MESSAGE_INDENTIFIER_LENGTH = 1
ENCODED_MESSAGE_PRIORITY_INDEX = 10
ENCODED_MESSAGE_PRIORITY_LENGTH = 1
ENCODED_MESSAGE_DATATYPE_INDEX = 11
ENCODED_MESSAGE_DATATYPE_LENGTH = 1
ENCODED_MESSAGE_HOP_INDEX = 12
ENCODED_MESSAGE_HOP_LENGTH = 1
ENCODED_MESSAGE_PAYLOAD_INDEX = 13

MESSAGE_HEADER_LENGTH = \
    ENCODED_MESSAGE_NUMBER_LENGTH + \
    ENCODED_MESSAGE_SENDER_LENGTH + \
    ENCODED_MESSAGE_INDENTIFIER_LENGTH + \
    ENCODED_MESSAGE_PRIORITY_LENGTH + \
    ENCODED_MESSAGE_DATATYPE_LENGTH + \
    ENCODED_MESSAGE_HOP_LENGTH


class Message(metaclass=ABCMeta):
    def __init__(self, encoded_data=None, what=None, args=None, message_type=None, message=None,
                 identifier=None, raw_data=None, data_type=None, hop=0, sender_id=0):
        # message format:
        # [0:8] message number
        # [8] message sender
        # [9] Message identifier (255 for a request and 0 - 254 for response error code)
        # [10] Message priority
        # [11] Message data type
        # [12] Message hop
        # [13:] message payload
        # message payload format:
        # message_type=command:
        # !command#arg1:arg2:arg3...
        # message_type=query
        # ?query#arg1:arg2:arg3.....
        # TODO: validation
        self._number = None
        self.what = None
        self.args = []
        self.message_type = None
        self.identifier = None
        self.raw_data = b''
        self.data_type = None
        self.priority = 0
        self.hop = 0
        self.sender_id = 0
        if not args:
            args = []
        if encoded_data:
            self.decode(encoded_data)
        elif message:
            self._number = message.number
            self.what = message.what
            self.args = message.args
            self.message_type = message.message_type
            self.identifier = message.identifier
            self.raw_data = message.raw_data
            self.data_type = message.data_type
            self.hop = message.hop
            self.sender_id = message.sender_id
        else:
            self.what = what
            self.args = args
            self.message_type = message_type
            self.identifier = identifier
            if raw_data:
                self.raw_data = raw_data
            else:
                self.raw_data = b''
            self.data_type = data_type
            self.hop = hop
            self.sender_id = sender_id
            self.generate_number()

    def __str__(self):
        return '{}: {} number {} hop {} sender {}'\
            .format(type(self).__name__, self.what, self.number, self.hop, self.sender_id)

    def generate_number(self):
        self._number = int(datetime.datetime.timestamp(datetime.datetime.now()) * 1000000)

    @property
    def number(self):
        return self._number

    def set_number(self, number):
        self._number = number

    def add_hop(self):
        self.hop += 1

    def match_message(self, response):
        return self.what == response.what and self.number == response.number and \
               self.message_type == response.message_type

    def is_next_hop(self, encoded_data, add_hop=True):
        request = Request(encoded_data=encoded_data)
        if self.match_message(request) and request.hop == self.hop + 1:
            if add_hop:
                self.add_hop()
            return True
        else:
            return False

    def set_definition(self, definition):
        self.data_type = definition.data_type
        self.what = definition.name

    @property
    def error_code(self):
        return self.identifier

    @abstractmethod
    def decode(self, _encoded_data):
        pass

    def is_ping(self):
        return self.message_type == 'query' and self.what == 'ping'

    def is_get_state(self):
        return self.message_type == 'query' and self.what == 'get_state'

    def is_reset_definitions(self):
        return self.message_type == 'command' and self.what == 'reset_definitions'

    def is_connect(self):
        return self.message_type == 'command' and self.what == 'connect'

    def set_data(self, data):
        Logger('Message setting data to value {}'.format(data), 'D')
        if self.identifier not in (REQUEST_IDENT, ErrorCodes.NO_ERROR):
            self.data_type = 'str'
        try:
            if self.data_type == 'int':
                if not data:
                    data = 0
                data = int(data)
                self.raw_data = int.to_bytes(data, 32, byteorder='big', signed=True)
            elif self.data_type == 'bool':
                if not data or (type(data) is str and data.lower() == 'false'):
                    self.raw_data = b'\x00'
                else:
                    self.raw_data = b'\x01'
            elif self.data_type == 'str' or self.data_type == 'float':
                self.raw_data = str(data).encode('utf-8')
        except (TypeError, UnicodeEncodeError):
            raise RequestException('Inavlid input data {} for data type {}'.format(data, self.data_type),
                                   error_code=ErrorCodes.INVALID_DATA_ERROR)

    def encode(self):
        # message format:
        # [0:8] message number
        # [8] message sender
        # [9] Message identifier (255 for a request and 0 - 254 for response error code)
        # [10] Message priority
        # [11] Message data type
        # [12] Message hop
        # [13:] message payload
        if self.message_type == 'command':
            header = '!'
        else:
            header = '?'
        data_type_code = None
        for code, ident in DATA_TYPE_CODES.items():
            if ident == self.data_type:
                data_type_code = code
                break
        if data_type_code is None:
            raise RequestException('Message does not have a data_type. self.data_type={}'.format(self.data_type))
        message = \
            int.to_bytes(self.number, ENCODED_MESSAGE_NUMBER_LENGTH, byteorder='big') + \
            int.to_bytes(self.sender_id, ENCODED_MESSAGE_SENDER_LENGTH, byteorder='big') + \
            int.to_bytes(self.identifier, ENCODED_MESSAGE_INDENTIFIER_LENGTH, byteorder='big') + \
            int.to_bytes(self.priority, ENCODED_MESSAGE_PRIORITY_LENGTH, byteorder='big') + \
            int.to_bytes(data_type_code, ENCODED_MESSAGE_DATATYPE_LENGTH, byteorder='big') + \
            int.to_bytes(self.hop, ENCODED_MESSAGE_HOP_LENGTH, byteorder='big') + \
            '{}{}#'.format(header, self.what).encode('utf-8') + \
            self.raw_data
        return message


class Request(Message):
    # Test: test_TCPRequest_init
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.identifier = REQUEST_IDENT

    def decode(self, encoded_data):
        # message format:
        # [0:8] message number
        # [8] message sender
        # [9] Message identifier (255 for a request and 0 - 254 for response error code)
        # [10] Message priority
        # [11] Message data type
        # [12] Message hop
        # [13:] message payload
        if chr(encoded_data[ENCODED_MESSAGE_PAYLOAD_INDEX]) == '!':
            self.message_type = 'command'
        else:
            self.message_type = 'query'
        request_ident = encoded_data[ENCODED_MESSAGE_INDENTIFIER_INDEX]
        if request_ident != REQUEST_IDENT:
            raise RequestException(error_code=ErrorCodes.IS_RESPONSE_ERROR)
        else:
            self.identifier = request_ident
        self.priority = encoded_data[ENCODED_MESSAGE_PRIORITY_INDEX]
        self.data_type = DATA_TYPE_CODES[encoded_data[ENCODED_MESSAGE_DATATYPE_INDEX]]
        self.set_number(int.from_bytes(encoded_data[:ENCODED_MESSAGE_NUMBER_LENGTH], byteorder='big'))
        self.sender_id = encoded_data[ENCODED_MESSAGE_SENDER_INDEX]
        self.hop = encoded_data[ENCODED_MESSAGE_HOP_INDEX]
        self.what = encoded_data[ENCODED_MESSAGE_PAYLOAD_INDEX + 1:].decode('utf-8').split('#')[0]
        self.args = encoded_data[ENCODED_MESSAGE_PAYLOAD_INDEX + 1:].decode('utf-8').split('#')[1].split(':')[:-1]
        self.raw_data = b''

    # Test: test_TCPRequest_encode
    def encode(self):
        args = ''
        for arg in self.args:
            args += '{}:'.format(arg)
        self.raw_data = args.encode('utf-8')
        return super().encode()


class PingRequest(Request):
    def __init__(self, encoded_data=None, **kwargs):
        if encoded_data:
            super().__init__(encoded_data=encoded_data, data_type='int')
        else:
            super().__init__(what='ping', message_type='query', raw_data=b'\x00', data_type='int', **kwargs)


class Response(Message):

    def __init__(self, message=None, **kwargs):
        if message:
            super().__init__(message=message)
            self.identifier = ErrorCodes.NO_ERROR
        else:
            super().__init__(**kwargs)

    def process_command_output(self, command_output, command_error_code):
        Logger('Processing command output: {} with error code: {}'.format(command_output, command_error_code), 'D')
        if self.message_type == 'command':
            self.set_data(command_error_code)
        else:
            self.set_data(command_output)
        self.identifier = command_error_code
        Logger('Processed command output. TCPResponse.raw_data={}. TCPResponse.identifier={}'
               .format(self.raw_data, self.identifier), 'D')

    # Test: test_TCPResponse_decode
    def decode(self, data):
        # message format:
        # [0:8] message number
        # [8] message sender
        # [9] Message identifier (255 for a request and 0 - 254 for response error code)
        # [10] Message priority
        # [11] Message data type
        # [12] Message hop
        # [13:] message payload
        Logger('Response.decode will decode data {}'.format(data), 'D')
        self.set_number(int.from_bytes(data[:ENCODED_MESSAGE_NUMBER_LENGTH], byteorder='big'))
        if data[ENCODED_MESSAGE_INDENTIFIER_INDEX] == REQUEST_IDENT:
            raise RequestException('Response decode received request data: {}'
                                   .format(data), error_code=ErrorCodes.IS_RESPONSE_ERROR)
        self.identifier = data[ENCODED_MESSAGE_INDENTIFIER_INDEX]
        self.sender_id = data[ENCODED_MESSAGE_SENDER_INDEX]
        self.priority = data[ENCODED_MESSAGE_PRIORITY_INDEX]
        self.data_type = DATA_TYPE_CODES[data[ENCODED_MESSAGE_DATATYPE_INDEX]]
        self.hop = data[ENCODED_MESSAGE_HOP_INDEX]
        data = data[ENCODED_MESSAGE_PAYLOAD_INDEX:]
        if chr(data[0]) == '!':
            self.message_type = 'command'
        else:
            self.message_type = 'query'
        data = data[1:]
        c = ''
        command = ''
        while not c == '#':
            command += c
            c = chr(data[0])
            data = data[1:]
        self.what = command
        self.raw_data = data
        self.args = []
        if self.identifier != ErrorCodes.NO_ERROR:
            self.data_type = 'str'

    @property
    def error_code(self):
        return self.identifier

    # Test: test_TCPResponse_get_response_data
    # TODO: update test
    def get_payload_data(self):
        try:
            if self.data_type == 'int' and not self.identifier:
                return int.from_bytes(self.raw_data, byteorder='big')
            elif self.data_type == 'bool' and not self.identifier:
                if self.raw_data == b'':
                    raise ValueError
                return self.raw_data == bytes([1])
            elif self.data_type == 'str' or self.identifier:
                return self.raw_data.decode('utf-8')
            elif self.data_type == 'float' and not self.identifier:
                return float(self.raw_data.decode('utf-8'))
            else:
                raise RequestException('Response has unknown data type: {}'.format(self.data_type))
        except ValueError:
            raise RequestException('Response data {} is not valid for response data type {}'
                                   .format(self.raw_data, self.data_type))


class PingResponse(Response):
    def __init__(self, ping_request=None, **kwargs):
        if ping_request:
            super().__init__(message=ping_request)
        else:
            super().__init__(**kwargs)
        self.identifier = kwargs.get('identifier', RESPONSE_NO_ERROR)
        self.raw_data = b'\x00'


class RequestDefinitions:
    def __init__(self, definitions=None, app_name=None):
        self.request_definitions = {'disconnect': self.RequestDefinition(**{'Name': 'disconnect',
                                                                            'DataType': 'str',
                                                                            'NumberOfArguments': 0}),
                                    'ping': self.RequestDefinition(**{'Name': 'ping',
                                                                      'DataType': 'int',
                                                                      'NumberOfArguments': 0}),
                                    'connect': self.RequestDefinition(**{'Name': 'connect',
                                                                         'Type': 'command',
                                                                         'DataType': 'int',
                                                                         'NumberOfArguments': 0}),
                                    'get_state': self.RequestDefinition(**{'Name': 'get_state',
                                                                           'DataType': 'str',
                                                                           'NumberOfArguments': 0}),
                                    'reset_definitions': self.RequestDefinition(**{'Name': 'reset_definitions',
                                                                                   'DataType': 'int',
                                                                                   'NumberOfArguments': 0,
                                                                                   'Type': 'command'})}
        self.received_definitions = False
        self.running_commands = {}
        if definitions and app_name:
            self.read_request_definitions(definitions, app_name)

    def as_dict(self):
        definitions = {}
        for def_name, def_obj in self.request_definitions.items():
            definitions[def_name] = def_obj.as_dict()
        return definitions

    def reconstruct_request(self, encoded_data):
        request = Request(encoded_data=encoded_data)
        definition = self.get(request.what)
        if definition:
            request.set_definition(definition)
        else:
            raise RequestException(error_code=ErrorCodes.UNDEFINED_REQUEST_ERROR)
        return request

    def find_processes(self):
        for command_name, command in self.request_definitions.items():
            a = subprocess.check_output(['ps', '-A']).decode('utf-8').split('\n')
            for ps in a:
                r = re.search(r'([0-9]+)\s+pts/[0-9]+\s+[0-9]+:[0-9]+:[0-9]+\s{}$'.format(command.process_name), ps)
                if r:
                    self.running_commands[command_name] = int(r.group(1))
                    break

    def read_request_definitions(self, def_file, app_name):
        root = ElementTree.parse(def_file).getroot()
        request_definitions = root.find('AppDefinitions').find('AppDefinition[@AppName="{}"]'
                                                               .format(app_name)).find('RequestDefinitions')
        if request_definitions:
            for request_elem in request_definitions:
                self.request_definitions[request_elem.get('Name')] = self.RequestDefinition(**request_elem.attrib)
        self.received_definitions = True

    def get(self, definition_name):
        if definition_name in self.request_definitions:
            req_def = self.request_definitions[definition_name]
            if req_def.wait_for_confirmation:
                try:
                    req_def.wait_for_confirmation_command = self.request_definitions[req_def.wait_for_confirmation]
                except KeyError:
                    raise RequestException('Request {} has WaitForConfirmation to command {} that is not defined'.
                                           format(definition_name, req_def.wait_for_confirmation),
                                           error_code=ErrorCodes.UNDEFINED_REQUEST_ERROR)
            return req_def
        else:
            return None

    def set(self, **attributes):
        name = attributes.get('Name')
        self.request_definitions[name] = self.RequestDefinition(**attributes)

    def set_all_definitions(self, definitions):
        for _, attributes in definitions.items():
            self.set(**attributes)

    class RequestDefinition:
        def __init__(self, **kwargs):
            self.name = kwargs.pop('Name')
            self.number_arguments = int(kwargs.pop('NumberOfArguments'))
            self.data_type = kwargs.pop('DataType', 'str')
            self.wait_for_confirmation = kwargs.pop('WaitForConfirmation', None)
            if self.wait_for_confirmation == 'None':
                self.wait_for_confirmation = None
            self.expected_return = kwargs.pop('ExpectedReturn', '')
            self.max_retries = int(kwargs.pop('MaxRetries', DEFAULT_MAX_RETRIES))
            self.retry_wait = int(kwargs.pop('RetryWait', DEFAULT_RETRY_WAIT))
            self.wait_for_return = kwargs.pop('WaitForReturn', 'false').lower() == 'true'
            self.command_arguments = kwargs.pop('CommandArguments', '').split(',')
            if '' in self.command_arguments:
                self.command_arguments.remove('')
            self.input_arguments = []
            default_values = {}
            default_values_str = kwargs.pop('DefaultArgumentValues', '')
            if default_values_str:
                for df in default_values_str.split(','):
                    default_values[df.split(':')[0]] = df.split(':')[1]
            for command in self.command_arguments:
                if command[0] == '$':
                    if command in default_values:
                        def_val = default_values[command]
                    else:
                        def_val = None
                    self.input_arguments.append((command, def_val))
            self.duplicatable = kwargs.pop('Duplicatable', 'true').lower() == 'true'
            self.process_name = kwargs.pop('ProcessName', None)
            if self.process_name == 'None':
                self.process_name = None
            self.fail_on_error = kwargs.pop('FailOnError', 'true').lower() == 'true'
            self.default_value = kwargs.pop('DefaultValue', None)
            if self.default_value == 'None':
                self.default_value = None
            self.wait_for_confirmation_command = None
            self.return_match_regex = kwargs.pop('ReturnMatchRegex', None)
            if self.return_match_regex == 'None':
                self.return_match_regex = None
            self.return_output = kwargs.pop('ReturnOutput', 'true').lower() == 'true'

        def as_dict(self):
            attributes = {
                'Name': self.name,
                'NumberOfArguments': self.number_arguments,
                'DataType': self.data_type,
                'WaitForConfirmation': self.wait_for_confirmation,
                'ExpectedReturn': self.expected_return,
                'MaxRetries': self.max_retries,
                'RetryWait': self.retry_wait,
                'WaitForReturn': self.wait_for_return,
                'CommandArguments': ''.join('{},'.format(arg) for arg in self.command_arguments)[:-1],
                'Duplicatable': self.duplicatable,
                'ProcessName': self.process_name,
                'FailOnError': self.fail_on_error,
                'DefaultValue': self.default_value,
                'DefaultArgumentValues': ''.join('{}:{},'.format(df[0], df[1]) for df in self.input_arguments)[:-1],
                'ReturnMatchRegex': self.return_match_regex,
                'ReturnOutput': self.return_output,
            }
            return {key: str(item) for key, item in attributes.items()}

        # Test: test_Command_get_expected_return
        def get_expected_return(self, *args):
            r = re.search(r'([^$]*)(\$[a-zA-Z0-9_]*)(.*)', self.expected_return)
            if r and r.groups() and r.group(2):
                leading = r.group(1)
                arg_name = r.group(2)
                trailing = r.group(3)
                if self.input_arguments:
                    for i in range(0, len(self.input_arguments)):
                        if self.input_arguments[i][0] == arg_name or arg_name == '$':
                            arg_name = args[i]
                elif arg_name == '$':
                    arg_name = ''
                return leading + arg_name + trailing
            else:
                return self.expected_return

        def clean_output(self, output):
            if self.expected_return and not self.return_match_regex:
                r = re.search(r'([^$]*)\$[a-zA-Z0-9_]*(.*)', self.expected_return)
                if r and r.groups():
                    leading = r.group(1)
                    trailing = r.group(2)
                    output = output.replace(leading, '').replace(trailing, '')
                    return output
            return output


        def get_partial_pattern(self, arg_name):
            if arg_name in self.args_to_replace:
                partial_pattern = self.args_to_replace[arg_name]
                if self.data_type == 'float' and float(partial_pattern) == int(float(partial_pattern)):
                    partial_pattern += '|{}'.format(int(float(partial_pattern)))
                Logger('Argument name to replace: {}. Partial pattern is {}'.format(arg_name, partial_pattern), 'D')
            else:
                if self.data_type == 'int':
                    partial_pattern = r'[0-9]+'
                elif self.data_type == 'str':
                    partial_pattern = r'.+'
                elif self.data_type == 'float':
                    partial_pattern = r'[0-9\.]+'
                else:
                    raise RequestException('Invalid data type for command {}: {}'.format(self.name, self.data_type))
            return partial_pattern

        # Test: test_Command_is_expected_return
        # Use cases:
        # 1. expected_return is provided. Method returns True and output if output matches expected_return
        # 2. Command has expected_return and output matches regex. True, output is returned
        # 3. Command has expected_return and output  does not matches regex. True, None is returned
        # 4. expected_return is not provided and Command does not have expected_return. True, output is returned
        def is_expected_return(self, output, *args, expected_return=None):
            Logger('Checking if received output is expected. Output={}, expected_return={}, self.expected_return={}'
                   .format(output, expected_return, self.expected_return), 'D')
            if not expected_return:
                expected_return = self.get_expected_return(*args)
            if expected_return and not output:
                is_expected = False
            elif expected_return:
                match = re.search(r'{}'.format(expected_return), output)
                is_expected = bool(match) or (expected_return == output and output is not None and output != '')
            else:
                is_expected = True
            return is_expected

        # Test: test_Command_build_command
        def build_command(self, *args):
            Logger('Building command with args: {}'.format(args), 'D')
            args = list(args)
            args.reverse()
            input_arguments = list(self.input_arguments)
            input_arguments.reverse()
            command_arguments = list(self.command_arguments)
            command_arguments.reverse()
            built_args = []
            while command_arguments:
                arg_name = command_arguments.pop()
                if arg_name[0] == '$':
                    if args:
                        arg_name = args.pop()
                        input_arguments.pop()
                    elif input_arguments:
                        input_arg = input_arguments.pop()
                        assert input_arg[0] == arg_name
                        arg_name = input_arg[1]
                built_args.append(arg_name)
            return built_args


class RequestException(Exception):
    def __init__(self, message='', error_code=RESPONSE_ERROR):
        Logger(self.__str__(), 'E')
        super().__init__(message)
        self.error_code = error_code


class RequestTimer:

    def __init__(self, limit):
        self.init_time = None
        self.last_alive = None
        self.limit = limit

    def reset(self):
        self.last_alive = datetime.datetime.now()

    def check(self):
        if (datetime.datetime.now() - self.init_time).total_seconds() > self.limit:
            raise RequestException(error_code=ErrorCodes.INACTIVITY_TIMEOUT_ERROR)

    def start(self):
        self.init_time = datetime.datetime.now()
