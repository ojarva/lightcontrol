# -*- coding: utf-8 -*-

"""Light control service

Usage:
    lights.py run <ip> [--debug] [--redis-host=<hostname>] [--redis-port=<port>]
"""

import docopt
import datetime
import json
import ledcontroller
import logging
import os
import programs
import redis


class LightControlCommand(object):
    def __init__(self, data):
        self.command = data["command"]
        self.group = data["group"]
        self.source = data["source"]
        self.brightness = data.get("brightness")
        self.color = data.get("color")

    def __repr__(self):
        return u"LightControlCommand<%s: %s - %s>" % (self.command, self.group, self.source)


class LightControlService(object):
    def __init__(self, controller_ip, **kwargs):
        self.led = ledcontroller.LedController(controller_ip)
        redis_args = {}
        if "redis_host" in kwargs and kwargs["redis_host"]:
            redis_args["host"] = kwargs["redis_host"]
        if "redis_port" in kwargs and kwargs["redis_port"]:
            redis_args["port"] = kwargs["redis_port"]
        self.redis = redis.StrictRedis(**redis_args)

        self.logger = logging.getLogger("lightcontrol-control")
        if kwargs.get("debug"):
            self.logger.setLevel(logging.DEBUG)
        else:
            self.logger.setLevel(logging.INFO)
        format_string = "%(asctime)s - {controller_ip} - %(levelname)s - %(message)s".format(controller_ip=controller_ip)
        formatter = logging.Formatter(format_string)
        ch = logging.StreamHandler()
        ch.setFormatter(formatter)
        self.logger.addHandler(ch)
        self.programs = programs.LightPrograms(**kwargs)
        self.set_group_names()

    def set_group_names(self):
        for i, name in enumerate(["Sänky", "Ruokapöytä", "Keittiö", "Eteinen"]):
            self.redis.set("lightcontrol-group-%s-name" % (i + 1), name)

    def get_redis(self, key, default_value=None):
        val = self.redis.get(key)
        if val is None:
            return default_value
        else:
            return val

    def is_group_on(self, group_id):
        group_on = self.get_redis("lightcontrol-state-{group_id}-on".format(group_id=group_id), False)
        return group_on not in ("False", False)

    def is_group_auto(self, group_id):
        return self.get_redis("lightcontrol-state-{group_id}-auto".format(group_id=group_id), True) in ("True", True)

    def sync(self, group_id):
        group_on = self.is_group_on(group_id)
        if group_on:
            self.logger.debug("Sync: switching on %s", group_id)
            self.set_on(True, group_id, force=True)
            color = self.get_redis("lightcontrol-state-{group_id}-color".format(group_id=group_id), "white")
            self.set_color(color, group_id, force=True)
            if color == "white":
                brightness_key = "white_brightness"
            else:
                brightness_key = "rgb_brightness"
            brightness = self.redis.get("lightcontrol-state-{group_id}-{brightness_key}".format(group_id=group_id, brightness_key=brightness_key))
            if brightness is None:
                self.logger.debug("No brightness specified for group %s (%s), fallback to 100", group_id, color)
                brightness = 100
            brightness = int(brightness)
            self.set_brightness(brightness, group_id, force=True)
        else:
            self.logger.debug("Sync: switching off %s", group_id)
            self.set_off(False, group_id, force=True)

    def program_sync(self, group_id):
        group_on = self.is_group_on(group_id)
        if not group_on:
            self.logger.debug("Not syncing group %s with program settings, as it is off", group_id)
            return
        user_override = self.get_redis("lightcontrol-state-{group_id}-user-override".format(group_id=group_id), False) not in ("False", False)
        if user_override:
            self.logger.debug("Not syncing group %s with program settings, as it is overridden by the user", group_id)
            return
        color = self.get_redis("lightcontrol-default-color", "white")
        brightness = int(self.get_redis("lightcontrol-default-brightness", 100))
        self.set_color(color, group_id)
        self.set_brightness(brightness, group_id)

    def set_auto_mode(self, group_id, mode):
        self.redis.set("lightcontrol-state-{group_id}-auto".format(group_id=group_id), mode)

    def run_auto_triggered(self, group_id):
        if not self.is_group_auto(group_id):
            self.logger.debug("Not processing automatic trigger for group %s, as it is marked as manually on", group_id)
            return
        color = self.get_redis("lightcontrol-default-color", "white")
        brightness = int(self.get_redis("lightcontrol-default-brightness", 100))
        self.set_on(True, group_id)
        self.set_color(color, group_id)
        self.set_brightness(brightness, group_id)

    def get_lightgroup(self, group_id):
        redis_key = "lightcontrol-state-%s" % group_id
        color = self.redis.get("%s-color" % redis_key)
        if color != "white":
            brightness_key = "rgb"
        else:
            brightness_key = "white"
        brightness = self.redis.get("%s-%s_brightness" % (redis_key, brightness_key))
        data = {
            "on": self.redis.get("%s-on" % redis_key) in ("true", "True"),
            "name": self.redis.get("lightcontrol-group-%s-name" % group_id),
            "color": color,
            "current_brightness": brightness,
            "id": group_id,
        }
        return data

    def run_operation(self, group_id, led_command, led_command_arg, key_name, force=False):
        redis_key = "lightcontrol-state-{group_id}-{key_name}".format(group_id=group_id, key_name=key_name)
        value = self.redis.get(redis_key)
        if value is not None:
            if value == str(led_command_arg) and not force:
                self.logger.debug("Not running operation %s for group %s, as force=False and light is already in correct state (%s).", key_name, group_id, led_command_arg)
                return
        if key_name in ("on", "off"):
            self.logger.debug("Executed %s for group %s", led_command, group_id)
            led_command(group_id)
        else:
            self.logger.debug("Executed %s for group %s with arg %s", led_command, group_id, led_command_arg)
            led_command(led_command_arg, group_id)
        self.logger.debug("Set %s to %s", redis_key, led_command_arg)
        self.redis.set(redis_key, led_command_arg)
        lightgroup_data = self.get_lightgroup(group_id)
        self.redis.publish("home:broadcast:generic", json.dumps({"key": "lightcontrol", "content": {"groups": [lightgroup_data]}}))

    def set_color(self, color, group_id, **kwargs):
        self.run_operation(group_id, self.led.set_color, color, "color", kwargs.get("force", False))

    def set_brightness(self, brightness, group_id, **kwargs):
        color = self.redis.get("lightcontrol-state-{group_id}-color".format(group_id=group_id))
        if color is None:
            self.logger.debug("No color specified for group %s - falling back to white", group_id)
            color = "white"
        if color == "white":
            key = "white_brightness"
        else:
            key = "rgb_brightness"
        if brightness < 5:
            brightness = 0
        if brightness > 95:
            brightness = 100
        self.run_operation(group_id, self.led.set_brightness, brightness, key, kwargs.get("force", False))

    def set_on(self, status, group_id, **kwargs):
        self.run_operation(group_id, self.led.on, True, "on", kwargs.get("force", False))

    def set_off(self, status, group_id, **kwargs):
        self.run_operation(group_id, self.led.off, False, "on", kwargs.get("force", False))

    def disabled_at_night(self, group_id):
        return self.get_redis("lightcontrol-group-%s-disabled-night" % group_id, False) not in (False, "False", "false")

    def process_command(self, data):
        if data["group"] == 0:
            for group in range(1, 5):
                data["group"] = group
                self.process_command(data)
            return

        self.logger.debug("process_command received %s", data)
        command = LightControlCommand(data)

        if command.command in ("off", "set_color", "set_brightness"):
            if command.source != "manual":
                if not self.is_group_auto(command.group):
                    self.logger.debug("Skipping automatic %s for %s as group is marked as manually controlled.", command.command, command.group)
                    return

        if command.command in ("set_color", "set_brightness", "on", "night", "auto-triggered"):
            if command.source == "manual":
                self.logger.debug("Setting group %s to manual control.", command.group)
                self.set_auto_mode(command.group, False)
            elif command.source == "trigger":
                if self.programs.is_night(datetime.datetime.now()):
                    if self.disabled_at_night(command.group):
                        self.logger.debug("Skipping %s for group %s - disabled during night", command.command, command.group)
                        return

        if command.command == "sync":
            self.sync(command.group)
            return
        if command.command == "on":
            self.set_on(True, command.group)
            return
        if command.command == "off":
            self.set_off(False, command.group)
            # Turning off lights - go back to automatic mode
            self.set_auto_mode(command.group, True)
            return
        if command.command == "set_color":
            self.set_color(command.color, command.group)
            return
        if command.command == "set_brightness":
            self.set_brightness(command.brightness, command.group)
            return
        if command.command == "auto-triggered":
            self.run_auto_triggered(command.group)
            return
        if command.command == "program-sync":
            self.program_sync(command.group)
            return
        if command.command == "night":
            self.set_on(True, command.group)
            color = self.get_redis("lightcontrol-state-{group}-color".format(group=command.group), "white")
            if color != "red":
                self.set_color("white", command.group)
                self.set_brightness(0, command.group)
            self.set_color("red", command.group)
            self.set_brightness(0, command.group)
            return
        self.logger.error("Unhandled data: %s", command)

    def run(self):
        pubsub = self.redis.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe("lightcontrol-control-pubsub")
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
    lcs = LightControlService(arguments["<ip>"], debug=arguments.get("--debug", False), **kwargs)
    lcs.run()

if __name__ == '__main__':
    arguments = docopt.docopt(__doc__, version='1.0')
    main(arguments)
