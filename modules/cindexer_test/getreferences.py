'''
Created on Sep 5, 2014

@author: Andy
'''
import cindexer
import os
import unittest


class TestGetReferences(unittest.TestCase):

    def setUp(self):
        if not cindexer.Config.loaded:
            cindexer.Config.set_library_path('../../lib/')

    def tearDown(self):
        self._indexer.clean_persistent()
        del self._indexer

    def test_tiny_c_proj(self):
        self._indexer = cindexer.Indexer.from_empty('tinyCProj')

        with open('tinyCProj/ref.c', 'r') as f:
            self.ref_str = f.read()

        with open('tinyCProj/def.c', 'r') as f:
            self.def_str = f.read()
        
        offset = self.def_str.find('func')
        file = cindexer.File.from_name(self._indexer, bytes('tinyCProj/def.c', 'utf-8'))
        source_location = cindexer.SourceLocation.from_offset(self._indexer, file, offset)
        result = self._indexer.get_references(source_location)
        self.assertIsNotNone(result)
        self.assertEqual(1, len(result))
        ref_cursor, enclosing_cursor = result[0]
        self.assertEqual(os.path.abspath('tinyCProj/ref.c'), ref_cursor.location.file.name.decode('utf-8'))
        self.assertEqual(os.path.abspath('tinyCProj/ref.c'), enclosing_cursor.location.file.name.decode('utf-8'))
        ref_offset = self.ref_str.find('func(42)')
        self.assertEqual(ref_offset, ref_cursor.location.offset)
        enclosing_offset = self.ref_str.find('main')
        self.assertEqual(enclosing_offset, enclosing_cursor.location.offset)
        
        
if __name__ == "__main__":
    unittest.main()