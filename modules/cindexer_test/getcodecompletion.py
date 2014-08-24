'''
Created on Sep 6, 2014

@author: Andy
'''
import cindexer
import unittest


class TestGetCodeCompletion(unittest.TestCase):


    def setUp(self):
        if not cindexer.Config.loaded:
            cindexer.Config.set_library_path('../../lib/')
        self._indexer = cindexer.Indexer.from_empty('incompleteCppProj')

        with open('incompleteCppProj/incompleteFile.cpp', 'r') as f:
            self._str = f.read()

    def tearDown(self):
        self._indexer.clean_persistent()
        del self._indexer

    def test_tiny_c_proj(self):
        offset = self._str.find('c.') + 2
        file = cindexer.File.from_name(self._indexer, 'incompleteCppProj/incompleteFile.cpp')
        source_location = cindexer.SourceLocation.from_offset(self._indexer, file, offset)
        results = self._indexer.get_code_completion(source_location)
        self.assertEqual(6, len(results.results))

if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.testName']
    unittest.main()