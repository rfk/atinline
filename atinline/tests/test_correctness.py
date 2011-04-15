
import os
import unittest

import atinline
import atinline.tests


class Test_Correctness(unittest.TestCase):

    def test_basic_inlining(self):
        @atinline.inline
        def calculate(a):
            return 2*a + 1
        def aggregate(items):
            total = 0
            for item in items:
                total += calculate(item)
            return total
        aggregate([1])
        def calculate(a):
            raise ValueError("failed to inline")
        for i in xrange(20):
            self.assertEquals(aggregate(xrange(i)),
                              sum(2*a+1 for a in xrange(i)))

    def test_inlining_with_globals(self):
        def call_inlined_add_to_total(x):
            return atinline.tests.add_to_running_total(x)
        for i in xrange(20):
            self.assertEquals(call_inlined_add_to_total(i),
                              atinline.tests.running_total)

