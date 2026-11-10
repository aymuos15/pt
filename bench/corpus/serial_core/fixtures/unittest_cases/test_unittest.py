import unittest


class StandardLibraryCases(unittest.TestCase):
    def setUp(self):
        self.value = [1]

    def test_pass(self):
        self.assertEqual(self.value, [1])

    def test_fail(self):
        self.fail("PT_CORE_UNITTEST_FAILURE")
