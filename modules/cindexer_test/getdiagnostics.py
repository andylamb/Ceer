'''
Created on Sep 5, 2014

@author: Andy
'''
import cindexer
import unittest


class TestGetDiagnostics(unittest.TestCase):

    def setUp(self):
        cindexer.Config.set_library_path('../../lib/')
        self._indexer = cindexer.Indexer.from_empty('buggyCProj')

    def tearDown(self):
        self._indexer.clean_persistent()
        del self._indexer

    def test_buggy_c_proj(self):
        file = cindexer.File.from_name(self._indexer, bytes('buggyCProj/problemFile.c', 'utf-8'))
        diagnostics = self._indexer.get_diagnostics(file)
        self.assertEqual(2, len(diagnostics))
        self.assertEqual('variable has incomplete type \'void\'', diagnostics[0].spelling.decode('utf-8'))
        self.assertEqual('expected \';\' at end of declaration', diagnostics[1].spelling.decode('utf-8'))


if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.testName']
    unittest.main()