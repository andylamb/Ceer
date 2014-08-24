import cindexer
import os
import unittest


class TestGetDefinition(unittest.TestCase):

    def setUp(self):
        if not cindexer.Config.loaded:
            cindexer.Config.set_library_path('../../lib/')
        self._indexer = cindexer.Indexer.from_empty('tinyCProj')

        with open('tinyCProj/ref.c', 'r') as f:
            self.ref_str = f.read()

        with open('tinyCProj/def.c', 'r') as f:
            self.def_str = f.read()

    def tearDown(self):
        self._indexer.clean_persistent()
        del self._indexer

    def test_tiny_c_proj(self):
        offset = self.ref_str.find('func(42)')
        file = cindexer.File.from_name(self._indexer, bytes('tinyCProj/ref.c', 'utf-8'))
        source_location = cindexer.SourceLocation.from_offset(self._indexer, file, offset)
        result = self._indexer.get_definition(source_location)
        self.assertIsNotNone(result)
        self.assertEqual(os.path.abspath('tinyCProj/def.c'), result.location.file.name.decode('utf-8'))
        def_offset = self.def_str.find('func')
        self.assertEqual(def_offset, result.location.offset)
        
    def test_tiny_c_proj_update(self):
        os.rename('tinyCProj/def.c', 'tinyCProj/def.c.orig')
        os.rename('tinyCProj/ref.c', 'tinyCProj/ref.c.orig')
        
        new_ref_str = '''
            void newFunc(int* newParam1, int newParam2); \n
            \n
            int main() \n
            { \n
                int someVar = 20; \n
                newFunc(&someVar, someVar + 2); \n
                return someVar; \n
            } \n
            '''
        
        with open('tinyCProj/ref.c', 'w') as f:
            f.write(new_ref_str)
        
        ref_file = cindexer.File.from_name(self._indexer, bytes('tinyCProj/ref.c', 'utf-8'))
        ref_file = self._indexer.update_index(ref_file)
        
        new_def_str = '''
            void newFunc(int* newParam1, int newParam2) \n
            { \n
                *newParam1 = newParam2 + 20; \n
            } \n
            '''
        
        with open('tinyCProj/def.c', 'w') as f:
            f.write(new_def_str)
            
        def_file = cindexer.File.from_name(self._indexer, bytes('tinyCProj/def.c', 'utf-8'))
        def_file = self._indexer.update_index(def_file)
        
        offset = new_ref_str.find('newFunc(&someVar')
        source_location = cindexer.SourceLocation.from_offset(self._indexer, ref_file, offset)
        result = self._indexer.get_definition(source_location)
        self.assertIsNotNone(result)
        self.assertEqual(os.path.abspath('tinyCProj/def.c'), result.location.file.name.decode('utf-8'))
        def_offset = new_def_str.find('newFunc')
        self.assertEqual(def_offset, result.location.offset)
        
        os.remove('tinyCProj/def.c')
        os.remove('tinyCProj/ref.c')
        os.rename('tinyCProj/def.c.orig', 'tinyCProj/def.c')
        os.rename('tinyCProj/ref.c.orig', 'tinyCProj/ref.c')
        
if __name__ == "__main__":
    unittest.main()
