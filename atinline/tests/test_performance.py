
import unittest
import timeit

from atinline import inline

def normal_calculate(x):
    return 3*x*x - 2*x + (1 / x)

@inline
def inline_calculate(x):
    return 3*x*x - 2*x + (1 / x)

def normal_aggregate(items):
    total = 0
    for item in items:
        total += normal_calculate(item)
    return total

def inline_aggregate(items):
    total = 0
    for item in items:
        total += inline_calculate(item)
    return total

def ugly_aggregate(items):
    total = 0
    for item in items:
        total += 3*item*item - 2*item + (1 / item)
    return total


class TestPerformance(unittest.TestCase):

    def test_performance(self):
        setup = "from atinline.tests.test_performance import"\
                "  normal_aggregate, ugly_aggregate, inline_aggregate"

        t1 = timeit.Timer("normal_aggregate(xrange(1,1000))",setup)
        t1 = min(int(x * 1000) for x in t1.repeat(number=100))

        t2 = timeit.Timer("ugly_aggregate(xrange(1,1000))",setup)
        t2 = min(int(x * 1000) for x in t2.repeat(number=100))

        t3 = timeit.Timer("inline_aggregate(xrange(1,1000))",setup)
        t3 = min(int(x * 1000) for x in t3.repeat(number=100))

        assert t1 > t2
        assert t1 > t3
        assert t3 > t2

