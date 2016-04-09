"""Light timers - handles timers

Usage:
    timers.py run [--debug] [--redis-host=<hostname>] [--redis-port=<port>]

"""

import datetime
import docopt
import json
import logging
import multiprocessing
import redis
import threading
import os


class LightTimers(object):
    def __init__(self, **kwargs):
        redis_args = {}
        if "redis_host" in kwargs and kwargs["redis_host"]:
            redis_args["host"] = kwargs["redis_host"]
        if "redis_port" in kwargs and kwargs["redis_port"]:
            redis_args["port"] = kwargs["redis_port"]
        self.redis = redis.StrictRedis(**redis_args)
        self.timers = {}
        self.timers_length = {}

        self.logger = logging.getLogger("lightcontrol-timers")
        if kwargs.get("debug"):
            self.logger.setLevel(logging.DEBUG)
        else:
            self.logger.setLevel(logging.INFO)
        format_string = "%(asctime)s - %(levelname)s - %(message)s"
        formatter = logging.Formatter(format_string)
        ch = logging.StreamHandler()
        ch.setFormatter(formatter)
        self.logger.addHandler(ch)

    def off_timer(self, group_id):
        self.logger.info("off: %s", group_id)
        self.redis.publish("lightcontrol-control-pubsub", json.dumps({"group": group_id, "command": "off", "source": "trigger"}))

    def start_timer(self, group_id, length, **kwargs):
        self.logger.info("auto-trigger: %s", group_id)
        self.redis.publish("lightcontrol-control-pubsub", json.dumps({"group": group_id, "command": "auto-triggered", "source": "trigger"}))

        if group_id in self.timers_length:
            current_timer_expire_time = self.timers_length[group_id]
            new_expire_time = datetime.datetime.now() + datetime.timedelta(seconds=length)
            if not kwargs.get("force", False) and current_timer_expire_time > new_expire_time:
                self.logger.info("Timer for group %s is set to expire later than new expire time: %s > %s. Skip updating the timer.", group_id, current_timer_expire_time, new_expire_time)
                return

        if self.timers.get(group_id):
            self.logger.debug("Cancelling old timer for %s", group_id)
            self.timers.get(group_id).cancel()
        timer = threading.Timer(length, self.off_timer, [group_id])
        timer.start()
        self.logger.info("Started a new timer for group %s, length %ss", group_id, length)
        self.timers[group_id] = timer
        self.timers_length[group_id] = datetime.datetime.now() + datetime.timedelta(seconds=length)

    def run(self):
        """
        Expects input in following format:
        {
            "group": <0-4>,
            "duration": <length in seconds>,
            "force": True/False,
        }
        """
        pubsub = self.redis.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe("lightcontrol-timer-pubsub")
        for message in pubsub.listen():
            data = json.loads(message["data"])
            timer_length = data.get("duration")
            if timer_length is None:
                timer_length = self.redis.get("lightcontrol-timer-length")
                if timer_length is None:
                    timer_length = 120
                    self.logger.debug("Using default timer (%ss), as timer_length is not available from redis or command message", timer_length)
                else:
                    timer_length = float(timer_length)
                    self.logger.debug("Using timer length from redis: %ss", timer_length)
            else:
                self.logger.debug("Using timer length from command message: %ss", timer_length)
            if data["group"] == 0:
                for group_id in range(1, 5):
                    self.start_timer(group_id, timer_length)
            else:
                self.start_timer(data["group"], timer_length, force=data.get("force", False))


def main(args):
    kwargs = {
        "redis_host": args.get("--redis-host"),
        "redis_port": args.get("--redis-post"),
    }
    light_timers = LightTimers(debug=args.get("--debug", False), **kwargs)
    light_timers.run()


if __name__ == '__main__':
    arguments = docopt.docopt(__doc__, version="1.0")
    main(arguments)
