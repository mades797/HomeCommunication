import socket
import datetime
from queue import Empty
from Logger import Logger
import time
from Requests import *

INACTIVITY_TIMEOUT = 4


def get_data(medium):
    Logger('methods.get_data calling get_data on medium: {}'.format(medium), 'D')
    return medium.get_data()

def send_message(medium, message, address=None):
    Logger('methods.send_message called for sender: {} message {}'.format(medium, message), 'D')
    medium.send_message(message, address)
    # if isinstance(medium, socket):
    #     message = TCPMessage(message=message)
    #     medium.sendto(message.encode(), address)
    # else:
    #     medium.put(message.encode())


# Use cases
# 1. Expect response. A target request is provided. All messages that don't match the target request
#    are sent pack to the sender
# 2. Getting input messages. Messages are parsed and highest priority number is kept. When a message has been parsed
#    twice, meaning that all messages have been parsed, the priority request is returned
# 3. Routing forever. All messages that are not in routing dictionnary are sent back to sender. If message number
#    is in routing dictionary, the receiver is retreived from the routing dictionary. If message is a response,
#    the message number is deleted from routing dict.
def link(target_request=None, sender=None, receiver=None, timeout=None,
         # all_messages=False,
         routing=None, forever=False):
    # receiver is the receiver of data in this link, so the sender of the original target_request
    Logger('methods.link starting, sender is {}. receiver is {}. target_request is {}. '
           # 'all_messages is {} '
           'routing is {} forever is {}'.format(sender,
                                                receiver,
                                                target_request,
                                                # all_messages,
                                                routing, forever), 'D')
    response_found = False
    if timeout is None:
        timeout = INACTIVITY_TIMEOUT
    priority_request = None
    parsed_messages = []
    candidate_response = None
    # TODO: validate input
    timer = RequestTimer(timeout)
    timer.start()
    while not response_found or forever:
        try:
            Logger('methods.link start of iteration', 'D')
            message_data = get_data(sender)  # sender.queue_io.input_queue.get(timeout=0.5)
            if not message_data:
                return
            Logger('link received data {}'.format(message_data), 'D')
            # print('message data {}'.format(message_data))
            if message_data[ENCODED_MESSAGE_INDENTIFIER_INDEX] == REQUEST_IDENT:
                message = Request(encoded_data=message_data)
            else:
                message = Response(encoded_data=message_data)
            Logger('link message received is {}'.format(message), 'D')
            # 1. Expect response. A target request is provided. All messages that don't match the target request
            #    are sent pack to the sender
            if target_request:
                if target_request.number == message.number:
                    Logger('methods.link message matches target request. Reseting timer', 'D')
                    response_found = isinstance(message, Response)
                    timer.reset()
                    if response_found:
                        Logger('methods.link found target response. Setting response_candidate to message: {}'
                               .format(message), 'D')
                        candidate_response = message
                    elif receiver:
                        send_message(receiver, message)
                else:
                    Logger('methods.link received message does not match target request. Sending back to sender', 'D')
                    send_message(sender, message)
                    timer.check()
            # 3. Routing forever. All messages that are not in routing dictionnary are sent back to sender.
            #    If message number is in routing dictionary, the receiver is retreived from the routing
            #    dictionary. If message is a response, the message number is deleted from routing dict.
            elif forever:
                if routing is not None and message.number in routing:
                    message_receiver = routing[message.number]
                    send_message(message_receiver, message)
                    if isinstance(message, Response):
                        del routing[message.number]
                elif receiver:
                    send_message(receiver, message)
                else:
                    send_message(sender, message)
            # 2. Getting input messages. Messages are parsed and highest priority number is kept. When a
            #    message has been parsed twice, meaning that all messages have been parsed, the priority
            #    request is returned
            else:
                if not priority_request:
                    priority_request = message
                    Logger('methods.link message is first priority request', 'D')
                elif message.priority > priority_request.priority:
                    # message is new priority request. Send old message back to sender
                    Logger('methods.link message is new priority request. Sending previous priority '
                           'request back to sender', 'D')
                    send_message(sender, priority_request)
                    priority_request = message
                else:
                    # message is not new priority request
                    if message.number in parsed_messages:
                        Logger('methods.link message has already been parsed. Setting priority request {} as '
                               'canddiate response and breaking loop'.format(priority_request), 'D')
                        candidate_response = priority_request
                        response_found = True
                    else:
                        parsed_messages.append(message.number)
                    send_message(sender, message)
        except Empty:
            # 1 and #3. sleep and try again
            if target_request or forever:
                time.sleep(0.5)
            # 2. Set candidate response to priority request. Break loop
            else:
                candidate_response = priority_request
                break
        except RequestException as e:
            # create response_candidate with error code
            candidate_response = Response(message=target_request)
            candidate_response.identifier = e.error_code
    # End of loop
    if receiver and candidate_response:
        send_message(receiver, candidate_response)
    else:
        return candidate_response
    #         if target_request:
    #             Logger('link has target_request', 'D')
    #             if message.number == target_request.number:
    #                 Logger('link received message number is target_request number {}'.format(target_request.number), 'D')
    #                 last_alive_time = datetime.datetime.now()
    #                 if isinstance(message, Response):
    #                     Logger('link received target_request response', 'D')
    #                     response_found = True
    #                     Logger('link got expected response {} number {} with hop {}'
    #                            .format(message.what, message.number, message.hop), 'D')
    #                     if receiver_piping_numbers and receiver:
    #                         Logger('link removing target_request number {} piping_number lists'.format(target_request.number), 'D')
    #                         receiver_piping_numbers.remove(target_request.number)
    #                     if sender_piping_numbers:
    #                         sender.queue_io.piping_numbers.remove(target_request.number)
    #                 if receiver:
    #                     Logger('link has receiver. Sending data to receiver: {}'.format(message.encode()), 'D')
    #                     send_message(receiver, message, address=receiver_address)  # receiver.queue_io.output_queue.put(message.encode())
    #                 elif isinstance(message, Response):
    #                     Logger('link does not have a receiver and received a response. returning response {} number {} with hop {}'.format(message.what, message.number, message.hop), 'D')
    #                     return message
    #             else:
    #                 Logger('link received unmatched response {} number {} hop {}. '
    #                        'sending back to sender'.format(message.what, message.number, message.hop), 'D')
    #                 send_message(sender, message)  # sender.queue_io.input_queue.put(message_data)
    #         elif routing is not None and message.number in routing:
    #             Logger('methods.link message {} is in routing'.format(message), 'D')
    #             send_message(routing[message.number], message)
    #             if isinstance(message, Response):
    #                 Logger('methods.link routing message is response. Removing from routing', 'D')
    #                 del routing[message.number]
    #         elif (not receiver_piping_numbers or message.number not in receiver_piping_numbers) \
    #                 and (isinstance(message, Request) or all_messages) and routing is None:
    #             Logger('link received request not in piping_numbers. receiver_piping_numbers is {}'.format(receiver_piping_numbers), 'D')
    #             if not priority_request:
    #                 Logger('link message is first priority request', 'D')
    #                 priority_request = message
    #             elif priority_request.priority < message.priority:
    #                 Logger('link new message has priority {} higher then prioriy request {}. Will use new message as '
    #                        'priority request and send old priority back to sender'
    #                        .format(message.priority, priority_request.priority), 'D')
    #                 # New found message has higher priority. Put back old priority_request to sender
    #                 send_message(sender, priority_request)
    #                 # sender.send_message(priority_request)
    #                 priority_request = message
    #             else:
    #                 exit_loop = message.number in parsed_messages
    #                 send_message(sender, message)
    #                 # if receiver:
    #                 #     Logger('link has receiver. Sending message number {} data to receiver: {}'
    #                 #            .format(priority_request.number, priority_request.encode()), 'D')
    #                 #     send_message(receiver, priority_request)
    #                 #     priority_request = None
    #                 if exit_loop:
    #                     break
    #                 else:
    #                     parsed_messages.append(message.number)
    #         else:
    #             Logger('methods.link Sending back to sender', 'D')
    #             send_message(sender, message)
    #             if not forever:
    #                 if message.number in parsed_messages:
    #                     Logger('methods.link message {} is in parsed messages. Breaking loop'.format(message), 'D')
    #                     break
    #                 else:
    #                     parsed_messages.append(message.number)
    #         # time.sleep(0.5)
    #     except Empty:
    #         if target_request:
    #             time.sleep(0.5)
    #         elif not forever:
    #             Logger('link Received Empty exception. Will return priority request {}'.format(priority_request), 'D')
    #             return priority_request
    #     finally:
    #         timed_out = (datetime.datetime.now() - last_alive_time).total_seconds() > timeout \
    #                     and timeout and not forever
    # if timed_out and target_request and not response_found:
    #     Logger('link timed out because of inactivity waiting for data target_request number {}. '
    #            'Timeout is {}'.format(target_request.number, timeout), 'E')
    #     response = Response(message=target_request)
    #     response.identifier = ErrorCodes.INACTIVITY_TIMEOUT_ERROR
    #     if receiver:
    #         send_message(receiver, response, sender_address)  # receiver.queue_io.output_queue.put(response.encode())
    #     else:
    #         return response
    #     if receiver_piping_numbers and receiver:
    #         Logger('link removing target_request number {} from sender and receiver '
    #                'piping_number lists'.format(target_request.number), 'D')
    #         receiver_piping_numbers.remove(target_request.number)  # receiver.queue_io.piping_numbers.remove(target_request.number)
    #     if sender_piping_numbers:
    #         sender_piping_numbers.remove(target_request.number)  # sender.queue_io.piping_numbers.remove(target_request.number)
    #     return response
    # elif response_found:
    #     Logger('methods.link exited loop. Respons found. Will return response message {} number {} hop {}'.format(message.what, message.number, message.hop), 'D')
    #     return message
    # else:
    #     Logger('methods.link exited loop. Will return priority request: {}'.format(priority_request), 'D')
    #     return priority_request
