import datetime
import programs
import unittest


class TestLightProgram(unittest.TestCase):
    def setUp(self):
        self.morning_program = programs.LightProgram("weekday", "morning", {"start_at": "08:15", "duration": 3600, "brightness": 100})
        self.evening_program = programs.LightProgram("weekday", "evening", {"start_at": "22:15", "duration": 1800})
        self.lightprograms = programs.LightPrograms(force_defaults=False)

    def test_duration(self):
        now = datetime.datetime(2016, 3, 30, 8, 34, 5, 690085)
        percent_done = self.morning_program.percent_done(now)
        self.assertIsNotNone(percent_done)

        self.assertAlmostEqual(percent_done, 0.318247245833)
        now = datetime.datetime(2016, 3, 30, 9, 34, 5, 690085)
        self.assertIsNone(self.morning_program.percent_done(now))
        now = datetime.datetime(2016, 3, 30, 6, 34, 5, 690085)
        self.assertIsNone(self.morning_program.percent_done(now))

    def test_dump(self):
        data = self.morning_program.dump()
        self.assertEqual(data["start_at"], "08:15")
        self.assertEqual(data["duration"], 3600)
        self.assertEqual(data["brightness"], 100)

    def test_next_start_running_now(self):
        now = datetime.datetime(2016, 3, 28, 8, 34, 5, 690085)
        self.assertEqual(self.morning_program.start_datetime(now), datetime.datetime(2016, 3, 28, 8, 15, 0))

    def test_next_end_running_now(self):
        now = datetime.datetime(2016, 3, 28, 8, 34, 5, 690085)
        self.assertEqual(self.morning_program.end_datetime(now), datetime.datetime(2016, 3, 28, 9, 15, 0))

    def test_next_start_running_done(self):
        now = datetime.datetime(2016, 3, 28, 9, 34, 5, 690085)
        self.assertEqual(self.morning_program.start_datetime(now), datetime.datetime(2016, 3, 29, 8, 15, 0))

    def test_next_end_running_done(self):
        now = datetime.datetime(2016, 3, 28, 9, 34, 5, 690085)
        self.assertEqual(self.morning_program.end_datetime(now), datetime.datetime(2016, 3, 29, 9, 15, 0))

    def test_next_wrapup(self):
        now = datetime.datetime(2016, 4, 2, 10, 0, 0)
        self.assertEqual(self.morning_program.end_datetime(now), datetime.datetime(2016, 4, 4, 9, 15))

    def test_calc_to_days(self):
        self.assertEqual(self.morning_program.calc_days_to(6, (0,)), 1)
        self.assertEqual(self.morning_program.calc_days_to(5, (0, 1)), 2)
        self.assertEqual(self.morning_program.calc_days_to(0, (5, 6)), 5)
        self.assertEqual(self.morning_program.calc_days_to(2, (0, 1, 2, 3, 4)), 0)

    def test_is_running(self):
        now = datetime.datetime(2016, 3, 30, 8, 34, 5, 690085)
        self.assertTrue(self.lightprograms.is_program_running(now, self.morning_program))


class TestLightPrograms(unittest.TestCase):
    def setUp(self):
        self.morning_program = programs.LightProgram("weekday", "morning", {"start_at": "08:15", "duration": 60, "brightness": 100})
        self.evening_program = programs.LightProgram("weekday", "evening", {"start_at": "22:15", "duration": 45})
        self.lightprograms = programs.LightPrograms(force_defaults=True)

    def test_get_day_programs(self):
        morning, evening = self.lightprograms.get_day_programs(0)
        self.assertIsNotNone(morning)
        self.assertIsNotNone(evening)
        self.assertEqual(morning.tod, "morning")
        self.assertEqual(evening.tod, "evening")
        self.assertEqual(morning.period, "weekday")
        self.assertEqual(evening.period, "weekday")
        morning, evening = self.lightprograms.get_day_programs(4)
        self.assertEqual(morning.period, "weekday")
        self.assertEqual(evening.period, "weekend")
        morning, evening = self.lightprograms.get_day_programs(5)
        self.assertEqual(morning.period, "weekend")
        self.assertEqual(evening.period, "weekend")
        morning, evening = self.lightprograms.get_day_programs(6)
        self.assertEqual(morning.period, "weekend")
        self.assertEqual(evening.period, "weekday")

    def test_is_day_or_night(self):
        now = datetime.datetime(2016, 3, 30, 8, 34, 5, 690085)
        self.assertTrue(self.lightprograms.is_day(now))
        self.assertFalse(self.lightprograms.is_night(now))

        now = datetime.datetime(2016, 3, 30, 7, 34, 5, 690085)
        self.assertFalse(self.lightprograms.is_day(now))
        self.assertTrue(self.lightprograms.is_night(now))

        now = datetime.datetime(2016, 3, 30, 16, 34, 5, 690085)
        self.assertTrue(self.lightprograms.is_day(now))
        self.assertFalse(self.lightprograms.is_night(now))

        now = datetime.datetime(2016, 3, 30, 23, 0, 5, 690085)
        self.assertFalse(self.lightprograms.is_day(now))
        self.assertTrue(self.lightprograms.is_night(now))

        now = datetime.datetime(2016, 3, 30, 1, 0, 5, 690085)
        self.assertFalse(self.lightprograms.is_day(now))
        self.assertTrue(self.lightprograms.is_night(now))

    def test_timer_length(self):
        now = datetime.datetime(2016, 3, 30, 8, 34, 5, 690085)
        self.assertEqual(self.lightprograms.set_default_timer_length(now), 15)

    def test_get_running_program(self):
        now = datetime.datetime(2016, 3, 30, 8, 34, 5, 690085)
        data = self.lightprograms.get_running_program(now)
        self.assertIsNotNone(data)
        self.assertEqual(data.period, "weekday")
        self.assertEqual(data.tod, "morning")

    def test_no_program_running(self):
        now = datetime.datetime(2016, 3, 30, 9, 34, 5, 690085)
        data = self.lightprograms.get_running_program(now)
        self.assertIsNone(data)


class TestRunningMorning(unittest.TestCase):
    pass

if __name__ == '__main__':
    unittest.main()
