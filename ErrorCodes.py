NO_ERROR = 0
COMMAND_SUCCESS = 0
ERROR = 1
IS_RESPONSE_ERROR = 2
INVALID_DATA_ERROR = 3
UNDEFINED_REQUEST_ERROR = 4
NO_SERVER_DEFINED_ERROR = 5
INVALID_DEFINTIONS_ERROR = 6
DEFINITIONS_NOT_RECEIVED_ERROR = 7
CLIENT_CONNECTION_ERROR = 8
COMMAND_ERROR = 9
CLIENT_NOT_CONNECTED_ERROR = 10
NO_RESPONSE_ERROR = 11
SHARED_MEMORY_ERROR = 12
HOST_UNREACHABLE_ERROR = 13
INACTIVITY_TIMEOUT_ERROR = 14
ErrorMessages = {
    IS_RESPONSE_ERROR: 'A Request was expected nut the message is a response',
    INVALID_DATA_ERROR: 'The message data has an invalid format',
    UNDEFINED_REQUEST_ERROR: 'The request is not defined',
    NO_SERVER_DEFINED_ERROR: 'The client does not have a server address defined',
    INVALID_DEFINTIONS_ERROR: 'The server received invalid definitions',
    DEFINITIONS_NOT_RECEIVED_ERROR: 'The server has not received definitions',
    CLIENT_CONNECTION_ERROR: 'The client could not connect to the server',
    COMMAND_ERROR: 'Error running a command',
    CLIENT_NOT_CONNECTED_ERROR: 'the client is not connected',
    NO_RESPONSE_ERROR: 'Did not receive a response for the request',
    SHARED_MEMORY_ERROR: 'A shared memory is in error state',
    HOST_UNREACHABLE_ERROR: 'Host is not reachable',
    INACTIVITY_TIMEOUT_ERROR: 'Timed out because of inactivity'
}