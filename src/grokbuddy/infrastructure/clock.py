import time


class SystemClock:
    def now(self):
        return time.time_ns() // 1000


class ManualClock:
    def __init__(self, start=1_789_600_000_000_000):
        self.value = start

    def now(self):
        return self.value

    def advance(self, seconds):
        if seconds < 0:
            raise ValueError('Clock must not move backwards')
        self.value += int(seconds * 1_000_000)
