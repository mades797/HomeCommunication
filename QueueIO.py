import datetime
from Logger import Logger
import time
from queue import Empty
from multiprocessing import Queue, Process
import ErrorCodes
import signal
from threading import Thread
import os
import socket
from methods import *

QUEUE_RESPONSE_TIMEOUT = 0
QUEUE_GET_TIMEOUT = 0.5
RESPONSE_TIMEOUT = 6


class QueueWrapper:
    def __init__(self, queue=None):
        if isinstance(queue, QueueWrapper):
            queue = queue.queue
        self.queue = queue or Queue()

    def get_data(self, timeout=0.5):
        try:
            return self.queue.get(timeout=timeout)
        except (EOFError, OSError, ValueError):
            return b''

    def send_data(self, data):
        self.put(data)

    def send_message(self, message, _address):
        self.send_data(message.encode())

    def put(self, data):
        try:
            self.queue.put(data)
        except ValueError:
            pass

    def get(self, **kwargs):
        return self.queue.get(**kwargs)

    def full(self):
        return self.queue.full()

    def close(self):
        self.queue.close()


class QueueRequest(Request):
    pass


class QueueResponse(Response):
    pass


class QueueIO:
    def __init__(self, input_queue=None, output_queue=None, reception_queue=None, def_file=None, app_name=None):
        self.input_queue = QueueWrapper(input_queue)
        self.output_queue = QueueWrapper(output_queue)
        self.reception_queue = QueueWrapper(reception_queue)
        self.request_definitions = RequestDefinitions(def_file, app_name)
        self.piping_numbers = []

    def reset_definitions(self):
        self.request_definitions = RequestDefinitions()

    def get_request_definition(self, name):
        return self.request_definitions.get(name)

    def get_from_reception_queue(self, request):
        return link(target_request=request, sender=self.reception_queue)

    def reconstruct_request(self, encoded_data):
        return self.request_definitions.reconstruct_request(encoded_data)

    def read_request_definitions(self, definitions, app_name):
        self.request_definitions.read_request_definitions(definitions, app_name)

    def send_request(self, request):
        Logger('QueueIO.send_request will put data in output queue: {}'.format(request.encode()), 'D')
        self.piping_numbers.append(request.number)
        self.output_queue.put(request.encode())
        expect_response_thread = Thread(target=self.expect_response, args=(request,))
        expect_response_thread.start()
        try:
            return self.get_from_reception_queue(request)
        except QueueIOException:
            ping_response = PingResponse(number=request.number, identifier=Requests.RESPONSE_ERROR)
            return ping_response

    def set_all_definitions(self, definitions):
        self.request_definitions.set_all_definitions(definitions)

    def send_response(self, response):
        self.output_queue.put(response.encode())
        Logger('send_response put data in output_queue {}'.format(response.encode()), 'D')

    def get_input_message(self):
        return link(sender=self.input_queue,
                    # receiver_piping_numbers=self.piping_numbers,
                    # all_messages=True
                    )

    def expect_response(self, request):
        link(target_request=request, sender=self.input_queue,
             # receiver_piping_numbers=self.piping_numbers,
             receiver=self.reception_queue)

    def stop(self):
        if self.input_queue:
            Logger('Closing input_queue', 'D')
            self.input_queue.close()
            Logger('Closed input_queue successfully', 'D')
        if self.output_queue:
            Logger('Closing output_queue', 'D')
            self.output_queue.close()
            Logger('Closed output_queue successfully', 'D')


class QueueIOException(Exception):
    def __init__(self, message):
        Logger(self.__str__(), 'E')
        super().__init__(message)
