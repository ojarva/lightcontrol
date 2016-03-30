"""Light triggers

Usage:
    triggers.py run [--debug] [--redis-host=<hostname>] [--redis-port=<port>]

"""

import redis
import docopt
import os


class LightTriggers(object):
    def __init__(self, **kwargs):
        redis_args = {}
        if "redis_host" in kwargs and kwargs["redis_host"]:
            redis_args["host"] = kwargs["redis_host"]
        if "redis_port" in kwargs and kwargs["redis_port"]:
            redis_args["port"] = kwargs["redis_port"]
        self.redis = redis.StrictRedis(**redis_args)

    def process_command(self, command):
        if "key" not in command:
            self.logger.error("No key specified: %s", command)
            return
        trigger = command["key"]

        BED = 1
        TABLE = 2
        KITCHEN = 3
        DOOR = 4

        triggers = set()
        if trigger == "toilet-door":
            triggers.add(DOOR)
        if trigger == "front-door":
            triggers.add(DOOR)
        if trigger == "kitchen-room":
            triggers.update([KITCHEN, TABLE])
        if trigger == "hall-kitchen":
            triggers.update([KITCHEN, DOOR])
        if trigger == "table-above-kitchen":
            triggers.add(TABLE)
        if trigger == "kitchen-ceiling":
            triggers.add(KITCHEN)
        if trigger == "hall-ceiling":
            triggers.add(DOOR)
        if trigger == "table-center":
            triggers.add(TABLE)
        if trigger == "table-acceleration-sensor":
            triggers.add(TABLE)
        if trigger == "bed":
            triggers.add(BED)
        if trigger == "bed-shelf":
            triggers.add(BED)
        if trigger == "balcony-door-pir":
            triggers.add(BED)
        for group_id in triggers:
            self.redis.publish("lightcontrol-timer-pubsub", json.dumps({"group": group_id}))

    def run(self):
        pubsub = self.redis.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe("lightcontrol-triggers-pubsub")
        for message in pubsub.listen():
            try:
                command = json.loads(message["data"])
            except (ValueError, TypeError):
                self.logger.warning("Received invalid command from pubsub: %s", message)
                continue
            self.process_command(command)


def main(args):
    kwargs = {
        "redis_host": args.get("--redis-host"),
        "redis_port": args.get("--redis-post"),
    }
    light_triggers = LightTriggers(debug=arguments.get("--debug", False), **kwargs)
    light_triggers.run()


if __name__ == '__main__':
    arguments = docopt.docopt(__doc__, version="1.0")
    main(arguments)
