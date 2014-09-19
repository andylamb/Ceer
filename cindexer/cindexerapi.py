'''
Classes:

ClassProperty -- Allows properties on class objects, for internal use.
Config -- An interface to cindex.Config, must use to set the libclang.dylib
path
File -- An interface to cindex.File.
SourceLocation -- An interface to cindex.SourceLocation
Indexer -- The main class of the module, most operations will run through an
instance of this class

Exceptions:
InternalError
'''
from fnmatch import fnmatch
import os
import subprocess
import sys
import threading

DEPENDENCIES_PATH = os.path.join(os.path.abspath(os.path.dirname(__file__)), 
                                 'dependencies')
MODULES_PATH = os.path.join(DEPENDENCIES_PATH, 'modules')
LIB_DYNLOAD_PATH = os.path.join(MODULES_PATH, 'lib-dynload')

if MODULES_PATH not in sys.path:
    sys.path.append(MODULES_PATH)
if LIB_DYNLOAD_PATH not in sys.path:
    sys.path.append(LIB_DYNLOAD_PATH)

import sqlite3
from clang import cindex

LIB_PATH = os.path.join(DEPENDENCIES_PATH, 'lib')

if not cindex.Config.loaded:
    cindex.Config.set_library_path(LIB_PATH)
    
BIN_PATH = os.path.join(DEPENDENCIES_PATH, 'bin')
ETC_PATH = os.path.join(DEPENDENCIES_PATH, 'etc')


class CIndexerError(Exception):

    '''
    Base class for all errors in this module.
    '''
    
    def __init__(self):
        '''
        Should only be subclassed.
        '''
        raise NotImplementedError


class InternalError(CIndexerError):
    
    '''Used mainly for debugging, by exposing state.'''
    
    def __init__(self, **kwargs):
        '''
        Create an InternalError instance, passing in arbitrary arguments.
        
        Parameters:
        **kwargs -- Any keyword parameters will be dumped.
        '''
        self.kwargs = kwargs
        
    def __str__(self):
        '''
        Returns the argument's __str__.
        '''
        return self.kwargs.__str__()
            

class ClassProperty(property):

    '''
    A property on a class object. For internal use only.
    '''

    def __get__(self, obj, objtype):
        if self.fget is None:
            raise AttributeError('unreadable attribute')

        return self.fget(objtype)


class File:

    '''
    Provides an interface to cindex.File

    Static Methods:
    from_name(indexer, file_name)
    '''

    @staticmethod
    def from_name(indexer, path):
        '''
        Returns a new File instance.

        Parameters:
        indexer -- An Indexer instance that has indexed the file at path.
        path -- An absolute or relative path, as bytes or str.
        '''
        if type(path) is str:
            path = bytes(path, 'utf-8')

        path = os.path.abspath(path)

        return indexer._file_from_name(path)


class SourceLocation:

    '''
    Provides an interface to cindex.SourceLocation

    Static Methods:
    from_position(indexer, cindexer_file, line, column)
    from_offset(indexer, cindexer_file, offset)
    '''

    @staticmethod
    def from_position(indexer, cindexer_file, line, column):
        '''
        Return a SourceLocation instance.

        Parameters:
        indexer -- An Indexer instance that constructed cindexer_file.
        cindexer_file -- A File instance, constructed by indexer.
        line -- The line number, 1 indexed.
        column -- The column number, 1 indexed.
        '''
        return indexer._source_location_from_position(
            cindexer_file, line, column)

    @staticmethod
    def from_offset(indexer, cindexer_file, offset):
        '''
        Returns a SourceLocation instance.

        Parameters:
        indexer -- An Indexer instance that constructed cindexer_file.
        cindexer_file -- A File instance, constructed by indexer.
        offset -- The offset into the source code, 1 indexed.
        '''
        return indexer._source_location_from_offset(cindexer_file, offset)


class Indexer(object):

    '''
    Presents the main interface to the index, almost all logic about a
    project will be accessed through an Indexer instance.

    Methods:
    indexed(path)
    clean_persistent()
    get_definition(source_location)
    get_references(source_location)
    get_diagnostics(cindexer_file)
    get_code_completion(cindexer_file)
    add_file(path, args, progress_callback)
    update_file(cindexer_file, args, progress_callback)

    Class Methods:
    from_empty(project_path, folders, progress_callback, 
               cmakelists_path, makefile_path)
    from_persistent(project_path, folders, progress_callback, 
                    cmakelists_path, makefile_path)

    Static Methods:
    has_persistent_index(project_path)
    '''

    def __init__(self, connection, index, translation_units, project_path):
        '''
        Create an Indexer instance.

        Indexers should be created using from_empty or from_persistent,
        __init__ should only be called internally.
        '''
        self._connection = connection
        self._index = index
        self._translation_units = translation_units
        self._project_path = project_path
        self._clean_persistent = False

    @staticmethod
    def has_persistent_index(project_path):
        '''
        Return True if there is currently an index file.

        Parameters:
        project_path -- an absolute or relative path to the project, as bytes
        or str
        '''
        index_db_path = os.path.join(project_path, Indexer._DB_FILE_NAME)
        return os.path.exists(index_db_path)

    def indexed(self, path):
        '''
        Return True if the Indexer instance has indexed the file.

        Parameters:
        path -- an absolute or project relative path to the file, as bytes or
        str
        '''
        if type(path) is str:
            path = bytes(path, 'utf-8')
        if not os.path.isabs(path):
            path = os.path.join(self._project_path, path)

        if path in self._translation_units.keys():
            return True
        
        sql_cursor = self._connection.cursor()
        sql_cursor.execute('SELECT COUNT(*) FROM includes WHERE include = ?', 
                           (path,))
        (count,) = sql_cursor.fetchone()
        return count > 0

    class IndexerStatus(object):

        '''
        An enumeration describing the status of an Indexer instance while it 
        is parsing and building the index. This will be the first argument to 
        the callback function, if provided to from_empty or from_persistent.
        '''
        
        STARTING_PARSE = 1
        '''
        The Indexer instance is starting to parsing source code. There will be 
        a 'path' argument for the callback.
        '''
        
        STARTING_INDEXING = 2
        '''
        The Indexer instance is starting to traversing the ast and storing 
        references and declarations in the index file. There will be 'path',
        'indexed', and 'total' arguments for the callback, which are the file,
        number of files indexed, and total number of files indexed, 
        respectively.
        '''
        
        COMPLETED = 3
        '''
        The Indexer instance is finished building the index.
        '''


    @classmethod
    def from_empty(cls, project_path, folders=None, progress_callback=None, 
                   cmakelists_path=None, makefile_path=None):
        '''
        Create an Indexer instance from a project that has not been indexed.

        This method will create a database to store logic across translation
        units, and parse and store translation units in memory. from_empty
        should only be called once, unless the clean_persistent method has
        been called.

        Parameters:
        project_path -- an absolute or relative path to the project, as bytes
        or str
        
        folders -- an optional array of dictionaries. Each dictionary must 
        contain 'path', an absolute or project relative path, as bytes or str. 
        Each dictionary may contain 'file_exclude_patterns' and 
        'folder_exclude_patterns', arrays of bytes or str, and 
        'follow_symlinks', a bool. If provided, folders will determine which 
        files are indexed, otherwise all files rooted at project_path will be 
        indexed. 
        
        progress_callback -- an optional callback function, that should expect
        an Indexer.IndexerStatus as its first positional argument, and have 
        **kwargs to accept any additional arguments, as described in the 
        IndexerStatus attribute docstrings.
        
        cmakelists_path -- an optional path to the CMakeLists.txt file 
        project's, which will be used to generate a compilation commands 
        database.
        
        makefile_path -- an optional path to a Makefile, which will be used to 
        generate a compilation commands database. If both cmakelists_path and 
        makefile_path are provided, cmakelists_path will be used.
        '''

        if not os.path.isabs(project_path):
            project_path = os.path.abspath(project_path)

        index_db_path = os.path.join(project_path, cls._DB_FILE_NAME)

        connection = sqlite3.connect(index_db_path, check_same_thread=False)
        sql_cursor = connection.cursor()
        sql_cursor.execute(
            'CREATE TABLE defs(usr TEXT, path TEXT, offset INT)')
        sql_cursor.execute(
            '''CREATE TABLE refs(usr TEXT, path TEXT,
                                 offset INT, enclosing_offset INT)''')
        sql_cursor.execute(
            'CREATE UNIQUE INDEX path_offset_idx ON refs(path, offset)')
        sql_cursor.execute(
            '''CREATE TABLE classes(sub_usr TEXT, super_usr TEXT, 
                                    sub_path TEXT, super_path TEXT)''')
        sql_cursor.execute(
            'CREATE TABLE includes(source TEXT, include TEXT, depth INT)')

        index = cindex.Index.create()
        translation_units = cls._parse_project(
            index, project_path, folders, 
            progress_callback, cmakelists_path, makefile_path)

        for i, (path, translation_unit) in \
        enumerate(translation_units.items()):
        
            if progress_callback:
                progress_callback(
                    cls.IndexerStatus.STARTING_INDEXING,
                    path=path.decode('utf-8'),
                    indexed=i,
                    total=len(translation_units))
                
            cls._update_db(
                path, translation_unit.cursor, connection, sql_cursor)

        connection.commit()

        if progress_callback:
            progress_callback(cls.IndexerStatus.COMPLETED,
                              project_path=project_path)

        return cls(connection, index, translation_units, project_path)

    @classmethod
    def from_persistent(
        cls, project_path, folders=None, progress_callback=None, 
        cmakelists_path=None, makefile_path=None):
        '''
        Create an Indexer instance from an existing index.

        This method reconnects to a database stored in project_path, and then
        parses translation units and stores them in memory. from_persistent
        should only be called after a previous Indexer instance was created by
        a call to from_empty, and that indexer was deleted without a call to
        clean_persistent.

        Parameters:
        project_path -- an absolute or relative path to the project, as bytes
        or str
        
        folders -- an optional array of dictionaries. Each dictionary must 
        contain 'path', an absolute or project relative path, as bytes or str. 
        Each dictionary may contain 'file_exclude_patterns' and 
        'folder_exclude_patterns', arrays of bytes or str, and 
        'follow_symlinks', a bool. If provided, folders will determine which 
        files are indexed, otherwise all files rooted at project_path will be 
        indexed. 
        
        progress_callback -- an optional callback function, that should expect
        an Indexer.IndexerStatus as its first positional argument, and have 
        **kwargs to accept any additional arguments, as described in the 
        IndexerStatus attribute docstrings.
        
        cmakelists_path -- an optional path to the CMakeLists.txt file 
        project's, which will be used to generate a compilation commands 
        database.
        
        makefile_path -- an optional path to a Makefile, which will be used to 
        generate a compilation commands database. If both cmakelists_path and 
        makefile_path are provided, cmakelists_path will be used.
        '''

        if not os.path.isabs(project_path):
            project_path = os.path.abspath(project_path)

        index_db_path = os.path.join(project_path, cls._DB_FILE_NAME)

        connection = sqlite3.connect(index_db_path, check_same_thread=False)

        index = cindex.Index.create()
        translation_units = cls._parse_project(
            index, project_path, folders, progress_callback, 
            cmakelists_path, makefile_path)

        if progress_callback:
            progress_callback(cls.IndexerStatus.COMPLETED,
                              project_path=project_path)

        return cls(connection, index, translation_units, project_path)

    def clean_persistent(self):
        '''
        Remove the database file associated with the Indexer instance.

        The Indexer instance should not be used after the call. After the 
        instance is deleted, a new index can be created using from_empty.
        '''
        self._connection.close()
        index_db_path = os.path.join(self._project_path, self._DB_FILE_NAME)
        os.remove(index_db_path)

    def get_definition(self, source_location):
        '''
        Return a cursor to a definition.

        If source_location is not a reference, None will be returned.

        Parameters:
        source_location -- A SourceLocation instance, created by a call
        to from_position or from_offset. The offset can be anywhere within
        the reference, i.e. any offset between |func and func| is acceptable
        '''

        translation_unit = self._translation_units[source_location.file._translation_unit_name]
        cursor = cindex.Cursor.from_location(
            translation_unit, source_location)
        def_cursor = cursor.referenced

        if def_cursor:
            if not def_cursor.is_definition():
                sql_cursor = self._connection.cursor()
                sql_cursor.execute(
                    'SELECT path, offset FROM defs WHERE usr = ?',
                    (def_cursor.get_usr(),))
                result = sql_cursor.fetchone()

                if result:
                    path, offset = result
                    def_translation_unit = self._translation_units[path]
                    def_file = cindex.File.from_name(
                        def_translation_unit, path)
                    def_source_location = cindex.SourceLocation.from_offset(
                        def_translation_unit, def_file, offset)
                    def_cursor = cindex.Cursor.from_location(
                        def_translation_unit, def_source_location)

            return def_cursor

    def get_references(self, source_location):
        '''
        Return a list of tuples of cursors to references and enclosing
        functions.

        source_location can be either a reference or definition. If no
        references are found, an empty list will be returned.

        Parameters:
        source_location -- A SourceLocation instance, created by a call
        to from_position or from_offset. The offset can be anywhere within
        the reference, i.e. any offset between |func and func| is acceptable
        '''

        translation_unit = self._translation_units[source_location.file._translation_unit_name]
        cursor = cindex.Cursor.from_location(translation_unit, source_location)
        cursor = cursor.referenced

        result = []
        if not cursor:
            return result

        sql_cursor = self._connection.cursor()
        sql_cursor.execute(
            'SELECT path, offset, enclosing_offset FROM refs WHERE usr = ?',
            (cursor.get_usr(),))

        for path, offset, enclosing_offset in sql_cursor.fetchall():
            ref_translation_unit = self._translation_units[path]
            ref_file = cindex.File.from_name(ref_translation_unit, path)
            ref_source_location = cindex.SourceLocation.from_offset(
                ref_translation_unit, ref_file, offset)
            ref_cursor = cindex.Cursor.from_location(
                ref_translation_unit, ref_source_location)

            enclosing_cursor = None
            if enclosing_offset != -1:
                enclosing_source_location = cindex.SourceLocation.from_offset(
                    ref_translation_unit, ref_file, enclosing_offset)
                enclosing_cursor = cindex.Cursor.from_location(
                    ref_translation_unit, enclosing_source_location)

            result.append((ref_cursor, enclosing_cursor))

        return result
    
    def get_superclasses(self, source_location):
        translation_unit = self._translation_units[source_location.file._translation_unit_name]
        cursor = cindex.Cursor.from_location(translation_unit, source_location)
        cursor = cursor.referenced

        superclasses = []
        if not cursor:
            return superclasses
        
        sql_cursor = self._connection.cursor()
        sub_usrs = [cursor.get_usr()]
        while len(sub_usrs) > 0:
            super_usrs = []
            for sub_usr in sub_usrs:
                sql_cursor.execute(
                    'SELECT super_usr FROM classes WHERE sub_usr = ?', 
                    (sub_usr,))
                super_usrs.extend([
                    result[0] for result in sql_cursor.fetchall()
                ])
                
            for super_usr in super_usrs:
                sql_cursor.execute(
                    'SELECT path, offset FROM defs WHERE usr = ?',
                    (super_usr,))
                result = sql_cursor.fetchone()

                if result:
                    path, offset = result
                    super_translation_unit = self._translation_units[path]
                    super_file = cindex.File.from_name(
                        super_translation_unit, path)
                    super_source_location = cindex.SourceLocation.from_offset(
                        super_translation_unit, super_file, offset)
                    super_cursor = cindex.Cursor.from_location(
                        super_translation_unit, super_source_location)
                    superclasses.append(super_cursor)
                    
            sub_usrs = super_usrs
            
        return superclasses
    
    def get_subclasses(self, source_location):
        translation_unit = self._translation_units[source_location.file._translation_unit_name]
        cursor = cindex.Cursor.from_location(translation_unit, source_location)
        cursor = cursor.referenced

        subclasses = []
        if not cursor:
            return subclasses
        
        sql_cursor = self._connection.cursor()
        super_usrs = [cursor.get_usr()]
        while len(super_usrs) > 0:
            sub_usrs = []
            for super_usr in super_usrs:
                sql_cursor.execute(
                    'SELECT sub_usr FROM classes WHERE super_usr = ?', 
                    (super_usr,))
                sub_usrs.extend([
                    result[0] for result in sql_cursor.fetchall()
                ])
                
            for sub_usr in sub_usrs:
                sql_cursor.execute(
                    'SELECT path, offset FROM defs WHERE usr = ?',
                    (sub_usr,))
                result = sql_cursor.fetchone()

                if result:
                    path, offset = result
                    sub_translation_unit = self._translation_units[path]
                    sub_file = cindex.File.from_name(
                        sub_translation_unit, path)
                    sub_source_location = cindex.SourceLocation.from_offset(
                        sub_translation_unit, sub_file, offset)
                    sub_cursor = cindex.Cursor.from_location(
                        sub_translation_unit, sub_source_location)
                    subclasses.append(sub_cursor)
                    
            super_usrs = sub_usrs
            
        return subclasses
        
    def get_includes(self, cindexer_file):
        translation_unit = self._translation_units[cindexer_file._translation_unit_name]
        return [include for include in translation_unit.get_includes()]
    
    def get_includers(self, cindexer_file):
        sql_cursor = self._connection.cursor()
        sql_cursor.execute(
            'SELECT source, depth FROM includes WHERE include = ?',
            (cindexer_file.name,))
        result = [
            (source.decode('utf-8'), depth) 
            for source, depth in sql_cursor.fetchall()
        ]
        return result
        
    def get_diagnostics(self, cindexer_file=None):
        '''
        Return a DiagnosticsItr containing all the issues in the index, or in a
        file.

        Parameters:
        cindexer_file -- an optional File instance, created by a call to 
        from_name. If provided, only return the issues for the file, otherwise
        return all issues in the index.
        '''
        if cindexer_file:
            translation_unit = self._translation_units[
                cindexer_file._translation_unit_name
            ]
            return translation_unit.diagnostics
        else:
            result = []
            for translation_unit in self._translation_units.values():
                result.extend(translation_unit.diagnostics)
            return result
                
    def get_code_completion(self, source_location, unsaved_files=None):
        '''
        Return a CodeCompleteResults object, or None.

        Parameters:
        source_location -- A SourceLocation instance, created by a call
        to from_position or from_offset. The offset can be anywhere within
        the reference, i.e. any offset between |func and func| is acceptable
        '''

        if unsaved_files:
            for i, (name, value) in enumerate(unsaved_files):
                if type(name) is str:
                    name = bytes(name, 'utf-8')
                if type(value) is str:
                    value = bytes(value, 'utf-8')

                unsaved_files[i] = (name, value)

        translation_unit = self._translation_units[source_location.file._translation_unit_name]
        return translation_unit.codeComplete(
            source_location.file.name,
            source_location.line,
            source_location.column,
            unsaved_files)

    def add_file(self, path, progress_callback=None):
        '''
        Add a file to the index, and return a new File instance.

        cindexer.File.from_name cannot be called until the file is in the
        index, so a path to the file is passed in here, not a File instance.

        Parameters:
        path -- An absolute or project relative path, as bytes or str
        progress_callback -- an optional callback function, that should expect
        an Indexer.IndexerStatus as its first positional argument, and have 
        **kwargs to accept any additional arguments, as described in the 
        IndexerStatus attribute docstrings.
        '''
        if type(path) is str:
            path = bytes(path, 'utf-8')
        if not os.path.isabs(path):
            path = os.path.join(self._project_path, path)

        if progress_callback:
            progress_callback(self.IndexerStatus.STARTING_PARSE,
                              path=path.decode('utf-8'))
            
        translation_unit = self._index.parse(path)
        
        self._translation_units[path] = translation_unit
        
        if progress_callback:
            progress_callback(self.IndexerStatus.STARTING_INDEXING,
                              path=path.decode('utf_8'),
                              indexed=0,
                              total=1)
        
        Indexer._update_db(
            path, translation_unit.cursor,
            self._connection, self._connection.cursor())

        self._connection.commit()
        
        if progress_callback:
            progress_callback(self.IndexerStatus.COMPLETED,
                              project_path=self._project_path)
        
        return self._file_from_name(path)

    def update_file(self, cindexer_file, progress_callback=None):
        '''
        Update a file in the index, and return a new File instance.

        Reparsing a translation unit will destroy the file passed in,
        so we return a new instance with the same name as a convinience.

        Parameters:
        cindexer_file -- A file instance, created by a call to from_name.
        This file should not be used after update_index returns.
        args -- an optional array of command line arguments, as bytes or str
        progress_callback -- an optional callback function, that should expect
        an Indexer.IndexerStatus as its first positional argument, and have 
        **kwargs to accept any additional arguments, as described in the 
        IndexerStatus attribute docstrings.
        '''

        path = cindexer_file.name
        translation_unit = self._translation_units[
            cindexer_file._translation_unit_name
        ]
        sql_cursor = self._connection.cursor()

        if progress_callback:
            progress_callback(self.IndexerStatus.STARTING_PARSE,
                              path=path.decode('utf_8'))
            
        translation_unit.reparse()
        
        sql_cursor.execute('DELETE FROM defs WHERE path = ?', (path,))
        sql_cursor.execute('DELETE FROM refs WHERE path = ?', (path,))
        sql_cursor.execute(
            'DELETE FROM classes WHERE sub_path = ? or super_path = ?', 
            (path, path))
        
        if progress_callback:
            progress_callback(self.IndexerStatus.STARTING_INDEXING,
                              path=path.decode('utf_8'),
                              indexed=0,
                              total=1)
        
        Indexer._update_db(
            path, translation_unit.cursor,
            self._connection, self._connection.cursor())

        self._connection.commit()
        
        if progress_callback:
            progress_callback(self.IndexerStatus.COMPLETED,
                              project_path=self._project_path)
        
        return self._file_from_name(path)

    _DB_FILE_NAME = '.cindexer.db'
    '''The name of the database file an Indexer instance creates.'''

    @staticmethod
    def _indexable(file_name):
        file_name = str(file_name)
        exts = ['.c', '.cpp']
        return any(file_name.endswith(ext) for ext in exts)
    
    @classmethod
    def _parse_wrapper(cls, translation_units, index, abs_path, 
                       progress_callback, compilation_database, 
                       started_threads):
        if progress_callback:
            progress_callback(cls.IndexerStatus.STARTING_PARSE,
                              path=abs_path.decode('utf-8'))
            
        compile_commands = None
        if compilation_database:
            compile_commands = compilation_database.getCompileCommands(
                abs_path)
            
        args = []
        if compile_commands:
            for command in compile_commands:
                for arg in command.arguments:
                    if ((arg.decode('utf-8').startswith('-I') or
                         arg.decode('utf-8').startswith('-D') or
                         arg.decode('utf-8').startswith('-W')) and 
                         arg not in args):
                        args.append(arg)
                        
        cache_dir = os.path.join(os.path.dirname(abs_path), 
                                 bytes('.cindexer.cache', 'utf-8'))
        if not os.path.exists(cache_dir):
            os.mkdir(cache_dir)
        cache_file = os.path.join(
            cache_dir, 
            os.path.basename(abs_path + bytes('.ast','utf-8')))

        if os.path.exists(cache_file):
            translation_unit = cindex.TranslationUnit.from_ast_file(cache_file,
                                                                    index)
        else:
            translation_unit = cindex.TranslationUnit.from_source(abs_path,
                                                                  args=args,
                                                                  index=index)
        translation_units[abs_path] = translation_unit
        translation_unit.save(cache_file)
#         def save_wrapper(translation_unit, path):
#             translation_unit.save(path)
#             
#         save_thread = threading.Thread(target=save_wrapper, 
#                                        args=(translation_unit, abs_path))
#         started_threads.append(save_thread)

    @classmethod
    def _parse_project(cls, index, project_path, folders, progress_callback, 
                       cmakelist_path, makefile_path):
        
        existing_compilation_database = False
        
        if os.path.exists(os.path.join(project_path, 'compile_commands.json')):
            existing_compilation_database = True
        elif cmakelist_path:
            if not os.path.isabs(cmakelist_path):
                cmakelist_path = os.path.join(project_path, cmakelist_path)
            subprocess.call(
                ['cmake -DCMAKE_EXPORT_COMPILE_COMMANDS=1 {}'.format(
                    cmakelist_path)], 
                cwd=project_path, shell=True)
            
        elif makefile_path:

            out_path = os.path.join(project_path, 'compile_commands.json')
            if not os.path.isabs(makefile_path):
                makefile_path = os.path.join(project_path, makefile_path)
            subprocess.call(
                [os.path.join(BIN_PATH, 'bear'), 
                 '-o', out_path, 
                 '-l', os.path.join(LIB_PATH, 'libear.dylib'),
                 '-c', os.path.join(ETC_PATH, 'bear.conf'),
                 '--', 'make'], 
                cwd=makefile_path)
            
        compilation_database = None
        if existing_compilation_database or cmakelist_path or makefile_path:
            compilation_database = cindex.CompilationDatabase.fromDirectory(
                bytes(project_path,'utf-8'))
        
        translation_units = {}
        started_threads = []
        if folders and len(folders) > 0:
            all_folder_paths = []
            for folder in folders:
                folder_path = folder['path']
                if not os.path.isabs(folder_path):
                    folder_path = os.path.join(project_path, folder_path)
                all_folder_paths.append(folder_path)

            for folder in folders:
                folder_path = folder['path']
                if not os.path.isabs(folder_path):
                    folder_path = os.path.join(project_path, folder_path)

                file_exclude_patterns = folder.get('file_exclude_patterns')
                if not file_exclude_patterns:
                    file_exclude_patterns = []

                folder_exclude_patterns = folder.get('folder_exclude_patterns')
                if not folder_exclude_patterns:
                    folder_exclude_patterns = []

                for path, subdirs, files in os.walk(
                        folder_path,
                        topdown=True,
                        followlinks=folder.get('follow_symlinks')):

                    for file in files:
                        if (cls._indexable(file) and
                            not any([fnmatch(file, pattern)
                                     for pattern in file_exclude_patterns])):

                            abs_path = os.path.abspath(os.path.join(path,
                                                                    file))
                            abs_path = bytes(abs_path, 'utf-8')
                            indexer_thread = threading.Thread(
                                target=cls._parse_wrapper, 
                                args=(translation_units, index, abs_path, 
                                      progress_callback, compilation_database,
                                      started_threads))
                            indexer_thread.start()
                            started_threads.append(indexer_thread)


                    for subdir in subdirs:
                        if (any([fnmatch(subdir, pattern)
                                 for pattern in folder_exclude_patterns]) or
                                os.path.abspath(subdir) in all_folder_paths):

                            subdirs.remove(subdir)

        else:
            for path, subdirs, files in os.walk(project_path):
                for file in files:
                    if cls._indexable(file):

                        abs_path = os.path.abspath(os.path.join(path, file))
                        abs_path = bytes(abs_path, 'utf-8')
                        indexer_thread = threading.Thread(
                            target=cls._parse_wrapper, 
                            args=(translation_units, index, abs_path, 
                                  progress_callback, compilation_database))
                        indexer_thread.start()
                        started_threads.append(indexer_thread)

        for thread in started_threads:
            thread.join()

        return translation_units

    @staticmethod
    def _is_enclosing_def(cursor):
        kinds = [
            cindex.CursorKind.STRUCT_DECL,
            cindex.CursorKind.UNION_DECL,
            cindex.CursorKind.CLASS_DECL,
            cindex.CursorKind.ENUM_DECL,
            cindex.CursorKind.FUNCTION_DECL,
            cindex.CursorKind.OBJC_INTERFACE_DECL,
            cindex.CursorKind.OBJC_CATEGORY_DECL,
            cindex.CursorKind.OBJC_PROTOCOL_DECL,
            cindex.CursorKind.OBJC_INSTANCE_METHOD_DECL,
            cindex.CursorKind.OBJC_CLASS_METHOD_DECL,
            cindex.CursorKind.OBJC_IMPLEMENTATION_DECL,
            cindex.CursorKind.OBJC_CATEGORY_IMPL_DECL,
            cindex.CursorKind.TYPEDEF_DECL,
            cindex.CursorKind.CXX_METHOD,
            cindex.CursorKind.NAMESPACE,
            cindex.CursorKind.CONSTRUCTOR,
            cindex.CursorKind.DESTRUCTOR,
            cindex.CursorKind.CONVERSION_FUNCTION
        ]
        return cursor.kind in kinds
    
    @staticmethod
    def _is_base_specifier(cursor):
        kinds = [
            cindex.CursorKind.CXX_BASE_SPECIFIER
        ]
        return cursor.kind in kinds

    @staticmethod
    def _update_db(path, cursor, connection,
                   sql_cursor, enclosing_def_cursor=None):
        if cursor.is_definition():
            sql_cursor.execute(
                'INSERT INTO defs VALUES (?, ?, ?)',
                (cursor.get_usr(), path, cursor.location.offset))
            if Indexer._is_enclosing_def(cursor):
                enclosing_def_cursor = cursor
        elif (cursor.referenced and 
              cursor != cursor.referenced and 
              cursor.location.file and
              cursor.location.file.name == path):
            
            if enclosing_def_cursor:
                enclosing_offset = enclosing_def_cursor.location.offset
            else:
                enclosing_offset = -1

            sql_cursor.execute(
                'INSERT OR IGNORE INTO refs VALUES (?, ?, ?, ?)',
                (cursor.referenced.get_usr(),
                 path,
                 cursor.location.offset,
                 enclosing_offset))
            
        if (Indexer._is_base_specifier(cursor) and 
            cursor.referenced.kind != cindex.CursorKind.NO_DECL_FOUND):
            sql_cursor.execute(
                'INSERT INTO classes VALUES (?, ?, ?, ?)',
                (enclosing_def_cursor.get_usr(), 
                 cursor.referenced.get_usr(),
                 path,
                 cursor.referenced.location.file.name
                 ))
            
        if cursor.kind == cindex.CursorKind.TRANSLATION_UNIT:
            includes = cursor.translation_unit.get_includes()
            for include in includes:
                sql_cursor.execute('INSERT INTO includes VALUES (?, ?, ?)',
                                   (include.source.name, 
                                    include.include.name, 
                                    include.depth))

        for child in cursor.get_children():
            Indexer._update_db(
                path, child, connection, sql_cursor, enclosing_def_cursor)

    def _file_from_name(self, file_name):
        translation_unit = self._translation_units.get(file_name)
        
        if not translation_unit:
            sql_cursor = self._connection.cursor()
            sql_cursor.execute('SELECT source FROM includes WHERE include = ?',
                               (file_name,))
            (source,) = sql_cursor.fetchone()
            translation_unit = self._translation_units[source]
        
        cindex_file = cindex.File.from_name(translation_unit, file_name)
        cindex_file._translation_unit_name = translation_unit.spelling
        return cindex_file

    def _source_location_from_position(self, cindexer_file, line, column):
        translation_unit_name = cindexer_file._translation_unit_name
        translation_unit = self._translation_units[translation_unit_name]
        source_location = cindex.SourceLocation.from_position(
            translation_unit, cindexer_file, line, column)
        source_location.file._translation_unit_name = translation_unit_name
        return source_location

    def _source_location_from_offset(self, cindexer_file, offset):
        translation_unit_name = cindexer_file._translation_unit_name
        translation_unit = self._translation_units[translation_unit_name]
        source_location = cindex.SourceLocation.from_offset(
            translation_unit, cindexer_file, offset)
        source_location.file._translation_unit_name = translation_unit_name
        return source_location
