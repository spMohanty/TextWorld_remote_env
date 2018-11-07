import redis
import json
import os
import pkg_resources
import sys
import numpy as np
import hashlib
import random
from textworld_remote_env import messages
import time
import textworld

class TextWorldRemoteEnv(object):
    """
        Redis client to interface with textworld_remote_env redis-service
        The Docker container hosts a redis-server inside the container.
        This client connects to the same redis-server, and communicates with the service.
        The service eventually will reside outside the docker container, and will communicate
        with the client only via the redis-server of the docker container.
        On the instantiation of the docker container, one service will be instantiated parallely.
        The service will accepts commands at "`service_id`::commands"
        where `service_id` is either provided as an `env` variable or is
        instantiated to "textworld_remote_redis_service_id"
    """
    def __init__(self, remote_host='127.0.0.1', remote_port=6379, remote_db=0, remote_password=None, verbose=False):
        self.remote_host = remote_host
        self.remote_port = remote_port
        self.remote_db = remote_db
        self.remote_password = remote_password
        
        self.redis_pool = redis.ConnectionPool(
                                host=remote_host, 
                                port=remote_port, 
                                db=remote_db, 
                                password=remote_password)
        self.namespace = "textworld_remote"
        try:
            self.service_id =  os.environ['textworld_remote_redis_service_id']
        except KeyError:
            self.service_id = "textworld_remote_redis_service_id"
        self.command_channel = "{}::{}::commands".format(
                                        self.namespace, 
                                        self.service_id
                                        )
        self.verbose = verbose
        self.display_command_during_render = self.verbose
        print("Connecting to Evaluator Service at {}:{}".format(
            self.remote_host,
            self.remote_port
        ))
        self.ping_pong()
        print("Connected !")

    def get_redis_connection(self):
        return redis.Redis(connection_pool=self.redis_pool)

    def _generate_response_channel(self):
        random_hash = hashlib.md5("{}".format(
                                random.randint(0, 10**10)
                            ).encode('utf-8')).hexdigest()
        response_channel = "{}::{}::response::{}".format(   self.namespace,
                                                            self.service_id,
                                                            random_hash)
        return response_channel

    def _blocking_request(self, _request):
        """
            request:
                -command_type
                -payload
                -response_channel
            response: (on response_channel)
                - RESULT
            * Send the payload on command_channel (self.namespace+"::command")
                ** redis-left-push (LPUSH)
            * Keep listening on response_channel (BLPOP)
        """
        assert type(_request) ==type({})
        _request['response_channel'] = self._generate_response_channel()

        _redis = self.get_redis_connection()
        """
            The client always pushes in the left
            and the service always pushes in the right
        """
        if self.verbose: print("Request : ", json.dumps(_response))
        # Push request in command_channel
        _redis.lpush(self.command_channel, json.dumps(_request))
        ## TODO: Check if we can use `repr` for json.dumps string serialization
        # Wait with a blocking pop for the response
        _response = _redis.blpop(_request['response_channel'])[1]
        if self.verbose: print("Response : ", _response)
        _response = json.loads(_response)
        if _response['type'] == messages.TEXTWORLD_REMOTE_ENV.ERROR:
            raise Exception(json.dumps(_response))
        else:
            return _response

    def ping_pong(self):
        """
            Official Handshake with the grading service
            Send a PING
            and wait for PONG
            If not PONG, raise error
        """
        _request = {}
        _request['type'] = messages.TEXTWORLD_REMOTE_ENV.PING
        _request['payload'] = {}
        _response = self._blocking_request(_request)
        if _response['type'] != messages.TEXTWORLD_REMOTE_ENV.PONG:
            raise Exception("Unable to perform handshake with the redis service. Expected PONG; received {}".format(json.dumps(_response)))
        else:
            return True

    def env_create(self):
        _request = {}
        _request['type'] = messages.TEXTWORLD_REMOTE_ENV.ENV_CREATE
        _request['payload'] = {}
        _response = self._blocking_request(_request)
        observation = _response['payload']['observation']
        return observation

    def env_reset(self):
        _request = {}
        _request['type'] = messages.TEXTWORLD_REMOTE_ENV.ENV_RESET
        _request['payload'] = {}
        _response = self._blocking_request(_request)
        observation = _response['payload']['observation']
        return observation

    def env_step(self, action, render=False):
        """
            Respond with [observation, reward, done, info]
        """
        _request = {}
        _request['type'] = messages.TEXTWORLD_REMOTE_ENV.ENV_STEP
        _request['payload'] = {}
        _request['payload']['action'] = action
        _response = self._blocking_request(_request)
        _payload = _response['payload']
        observation = _payload['observation']
        reward = _payload['reward']
        done = _payload['done']
        return [observation, reward, done]

    def submit(self):
        _request = {}
        _request['type'] = messages.TEXTWORLD_REMOTE_ENV.ENV_SUBMIT
        _request['payload'] = {}
        _response = self._blocking_request(_request)
        if os.getenv("CROWDAI_BLOCKING_SUBMIT"):
            """
            If the submission is supposed to happen as a blocking submit,
            then wait indefinitely for the evaluator to decide what to 
            do with the container.
            """
            while True:
                time.sleep(10)
        
        return _response['payload']
