"""Light programs - scheduled programs

Usage:
    programs.py run [--debug] [--redis-host=<hostname>] [--redis-port=<port>]

"""

import datetime
import docopt
import multiprocessing
import os
import redis
import threading
import time
import logging
import json


class LightProgram(object):
    def __init__(self, period, tod, data):
        self.start_at = data["start_at"]
        self.duration = data["duration"]
        self.brightness = data.get("brightness")
        self.period = period
        self.tod = tod

    def dump(self):
        return {
            "start_at": self.start_at,
            "duration": self.duration,
            "brightness": self.brightness,
        }

    @classmethod
    def calc_days_to(cls, current_day, dest_days):
        for p in range(0, 7):
            if current_day in dest_days:
                return p
            current_day = (current_day + 1) % 7

    def get_start_end(self, now, advance=True):
        date = now.date()
        weekday = now.weekday()
        start_at_time = datetime.datetime.strptime(self.start_at, "%H:%M").time()
        start_at_datetime = datetime.datetime.combine(date, start_at_time)
        end_at_datetime = start_at_datetime + datetime.timedelta(seconds=self.duration)
        next_occurance = None
        if advance:
            if now > end_at_datetime:
                # Already finished for today
                weekday = (weekday + 1) % 7
                not_today = True
            else:
                not_today = False
            if self.tod == "morning":
                if self.period == "weekend":
                    plus_days = self.calc_days_to(weekday, (5, 6))
                else:  # weekday
                    plus_days = self.calc_days_to(weekday, (0, 1, 2, 3, 4))
            else:  # evening
                if self.period == "weekend":
                    plus_days = self.calc_days_to(weekday, (4, 5))
                else:  # weekday
                    plus_days = self.calc_days_to(weekday, (0, 1, 2, 3, 6))
            if not_today:
                plus_days += 1
            start_at_datetime += datetime.timedelta(days=plus_days)
            end_at_datetime += datetime.timedelta(days=plus_days)

        return start_at_datetime, end_at_datetime

    def start_datetime(self, now, advance=True):
        return self.get_start_end(now, advance)[0]

    def end_datetime(self, now, advance=True):
        return self.get_start_end(now, advance)[1]

    def percent_done(self, now):
        start = self.start_datetime(now)
        end = self.end_datetime(now)
        if start > now or now > end:
            return None  # Not running now
        return (now - start).total_seconds() / (self.duration)

    def __repr__(self):
        return u"LightProgram<%s-%s: %s+%ss, brightness=%s>" % (self.tod, self.period, self.start_at, self.duration, self.brightness)


class LightPrograms(object):
    def __init__(self, **kwargs):
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
        format_string = "%(asctime)s - %(levelname)s - %(message)s"
        formatter = logging.Formatter(format_string)
        ch = logging.StreamHandler()
        ch.setFormatter(formatter)
        self.logger.addHandler(ch)
        self.set_default_programs(kwargs.get("force_defaults", False))

    def set_default_programs(self, force=False):
        default_programs = {
            "morning-weekday": {
                "start_at": "08:15",
                "duration": 3600,
                "brightness": 100,
            },
            "morning-weekend": {
                "start_at": "09:30",
                "duration": 3600,
                "brightness": 100,
            },
            "evening-weekday": {
                "start_at": "22:30",
                "duration": 1800,
            },
            "evening-weekend": {
                "start_at": "23:00",
                "duration": 1800,
            },
        }
        for program, details in default_programs.items():
            if not force:
                if self.redis.exists("lightcontrol-program-%s" % program):
                    self.logger.debug("Skip setting %s - already exists and force is not enabled", program)
                    continue
            self.logger.info("Setting %s to defaults: %s.", program, details)
            self.redis.set("lightcontrol-program-%s" % program, json.dumps(details))

    def create_morning_program_timer(self, length, **kwargs):
        self.logger.info("Setting morning timer: %ss", length)
        data = {
            "group": 0,
            "duration": length
        }
        data.update(kwargs)
        self.redis.publish("lightcontrol-timer-pubsub", json.dumps(data))

    def refresh_program_timestamp(self, now):
        for program_period, program_tod in (("weekend", "morning"), ("weekend", "evening"), ("weekday", "morning"), ("weekday", "evening")):
            redis_key = "lightcontrol-program-%s-%s" % (program_tod, program_period)
            program = LightProgram(program_period, program_tod, json.loads(self.redis.get(redis_key)))
            self.redis.set("%s-next_start_at" % redis_key, program.start_datetime(now).isoformat())
            self.redis.set("%s-next_end_at" % redis_key, program.end_datetime(now).isoformat())

    def get_day_programs(self, weekday):
        morning_program = evening_program = "weekday"
        if weekday == 4:  # Friday
            evening_program = "weekend"
        if weekday == 5:  # Saturday
            morning_program = evening_program = "weekend"
        if weekday == 6:  # Sunday
            morning_program = "weekend"
        morning = json.loads(self.redis.get("lightcontrol-program-morning-%s" % morning_program))
        evening = json.loads(self.redis.get("lightcontrol-program-evening-%s" % evening_program))
        return LightProgram(morning_program, "morning", morning), LightProgram(evening_program, "evening", evening)

    def is_day(self, now):
        assert isinstance(now, datetime.datetime)
        weekday = now.weekday()
        morning, evening = self.get_day_programs(weekday)
        morning_start = morning.start_datetime(now, False)
        evening_start = evening.start_datetime(now)
        evening_end = evening.end_datetime(now, False)
        if now > evening_end or now < morning_start:
            return False
        return True

    def is_night(self, now):
        return not self.is_day(now)

    def is_program_running(self, now, program):
        assert isinstance(now, datetime.datetime)
        assert isinstance(program, LightProgram)

        if now > program.start_datetime(now) and now < program.end_datetime(now):
            return True
        return False

    def get_running_program(self, now):
        assert isinstance(now, datetime.datetime)
        weekday = now.weekday()
        morning, evening = self.get_day_programs(weekday)
        for program in morning, evening:
            running = self.is_program_running(now, program)
            if running:
                self.logger.debug("Program %s is currently running", program)
                return program

    def set_default_timer_length(self, now):
        assert isinstance(now, datetime.datetime)
        if self.is_day(now):
            timer = 15 * 60
        else:
            timer = 2 * 60
        self.redis.set("lightcontrol-timer-length", timer)
        return timer

    def execute_program(self, now, program):
        assert isinstance(now, datetime.datetime)
        assert isinstance(program, LightProgram)

        if self.redis.get("lightprogram-%s-%s-running" % (program.tod, program.period)) not in ("true", "True"):
            self.logger.debug("Skipping program %s, as it is marked as non-running", program)
            return

        if program.brightness is not None:
            self.redis.set("lightcontrol-default-brightness", program.brightness)
        if self.is_night(now):
            self.redis.set("lightcontrol-default-color", "red")
        else:
            self.redis.set("lightcontrol-default-color", "white")
        # Morning programs
        if program.tod == "morning":
            program_triggered_key = "lightprogram-%s-%s-triggered" % (program.period, program.tod)
            program_triggered = self.redis.get(program_triggered_key)
            if program_triggered:
                program_triggered = json.loads(program_triggered)
                if program_triggered["duration"] == program.duration and program_triggered["start_at"] == program.start_at:
                    self.logger.debug("Morning program %s (%s) has already been activated.", program.tod, program.period)
                    return
                else:
                    self.logger.debug("Morning program details (%s, %s) changed - reactivate timer.", program.tod, program.period)
            self.create_morning_program_timer(program.duration, force=True)
            self.redis.setex(program_triggered_key, program.duration + 10, json.dumps(program.dump()))
            return
        # Evening programs
        # TODO: do not brighten lights
        done = program.percent_done(now)
        if done is None:
            self.logger.warning("Tried to execute %s (%s) but percent_done returned None.", program.tod, program.period)
            return
        brightness = int((1 - done) * 100)
        self.logger.debug("Program %s (%s) - setting brightness to %s", program.tod, program.period, brightness)
        self.redis.set("lightcontrol-default-brightness", brightness)
        self.redis.publish("lightcontrol-control-pubsub", json.dumps({"command": "program-sync", "group": 0, "source": "program"}))

    def run(self):
        while True:
            now = datetime.datetime.now()
            self.refresh_program_timestamp(now)
            program = self.get_running_program(now)
            if not program:
                self.set_default_timer_length(now)
                if self.is_night(now):
                    self.redis.set("lightcontrol-default-color", "red")
                    self.redis.set("lightcontrol-default-brightness", 0)
                else:
                    self.redis.set("lightcontrol-default-color", "white")
                    self.redis.set("lightcontrol-default-brightness", 100)
                time.sleep(20)
                continue
            self.set_default_timer_length(now)
            self.execute_program(now, program)
            time.sleep(20)


def main(args):
    kwargs = {
        "redis_host": args.get("--redis-host"),
        "redis_port": args.get("--redis-post"),
    }
    light_programs = LightPrograms(debug=args.get("--debug", False), **kwargs)
    light_programs.run()


if __name__ == '__main__':
    arguments = docopt.docopt(__doc__, version="1.0")
    main(arguments)
