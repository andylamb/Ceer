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
ExistingPersistentIndexError
NoPersistentIndexError
'''
from clang import cindex
from fnmatch import fnmatch
import os
import sqlite3
import threading


class CIndexerError(Exception):

    '''Base class for all errors in this module.'''
    pass


class ExistingPersistentIndexError(CIndexerError):

    '''
    Raised when from_empty is called on a project with an index file.

    Attributes:
    path -- the absolute path to the existing index file
    '''

    def __init__(self, path):
        CIndexerError.__init__(self)
        self.path = path


class NoPersistentIndexError(CIndexerError):

    '''
    Raise when from_persistent is called on a project without an index file.

    Attributes:
    path -- the absolute path to the existing index file
    '''

    def __init__(self, path):
        CIndexerError.__init__(self)
        self.path = path


class MalformedFolderDataError(CIndexerError):
    pass


class ClassProperty(property):

    '''
    A property on a class object. For internal use only.
    '''

    def __get__(self, obj, objtype):
        if self.fget is None:
            raise AttributeError('unreadable attribute')

        return self.fget(objtype)


class Config:

    '''
    Provides an interface to cindex.Config

    Methods:
    set_library_path(path)

    Attributes:
    loaded
    '''

    set_library_path = cindex.Config.set_library_path
    '''
    Sets the path to libclang.dylib.

    Must be called before an Indexer instance is created, if
    cindex.Config.loaded is False.

    Parameters:
    path -- an absolute or relative path to the library, as str.
    '''

    @ClassProperty
    def loaded(cls):
        '''Returns True if libclang has been loaded'''
        return cindex.Config.loaded


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
    add_file(path)
    update_file(cindexer_file)

    Class Methods:
    from_empty(project_path)
    from_persistent(project_path)

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

    def __del__(self):
        if self._clean_persistent:
            self._connection.close()
            index_db_path = os.path.join(
                self._project_path, self._DB_FILE_NAME)
            os.remove(index_db_path)

            del self._index

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

        return path in self._translation_units.keys()

    class IndexerStatus(object):

        '''
        An enumeration describing the status of an Indexer instance while it 
        is parsing and building the index. This will be the first argument to 
        the callback function, if provided to from_empty or from_persistent.
        '''
        PARSING = 1
        '''
        The Indexer instance is parsing source code. There will be a 'path' 
        argument for the callback.
        '''
        INDEXING = 2
        '''
        The Indexer instance is traversing the ast and storing references and 
        declarations in the index file. There will be a 'path' argument for 
        the callback. 
        '''
        COMPLETED = 3
        '''
        The Indexer instance is finished building the index.
        '''

    @classmethod
    def from_empty(cls, project_path, folders=None, progress_callback=None):
        '''
        Create an Indexer instance from a project that has not been indexed.

        This method will create a database to store logic across translation
        units, and parse and store translation units in memory. from_empty
        should only be called once, unless the clean_persistent method has
        been called.

        Parameters:
        project_path -- an absolute or relative path to the project, as bytes
        or str
        progress_callback -- an optional callback function, that should expect
        an Indexer.IndexerStatus as its first positional argument, and have 
        **kwargs to accept any additional arguments, as described in the 
        IndexerStatus attribute docstrings.

        Exceptions:
        ExistingPersistentIndexError -- raised if there is an existing index
        file
        '''

        if not os.path.isabs(project_path):
            project_path = os.path.abspath(project_path)

        index_db_path = os.path.join(project_path, cls._DB_FILE_NAME)
        if os.path.exists(index_db_path):
            raise ExistingPersistentIndexError(index_db_path)

        connection = sqlite3.connect(index_db_path, check_same_thread=False)
        sql_cursor = connection.cursor()
        sql_cursor.execute(
            'CREATE TABLE defs(usr TEXT, path TEXT, offset INT)')
        sql_cursor.execute(
            '''CREATE TABLE refs(usr TEXT, path TEXT,
                                 offset INT, enclosing_offset INT)''')
        sql_cursor.execute(
            'CREATE UNIQUE INDEX path_offset_idx ON refs(path, offset)')

        index = cindex.Index.create()
        translation_units = cls._parse_project(index, project_path,
                                               folders, progress_callback)

        for path, translation_unit in translation_units.items():
            cls._update_db(
                path, translation_unit.cursor, connection, sql_cursor)
            if progress_callback:
                progress_callback(
                    cls.IndexerStatus.INDEXING,
                    path=path.decode('utf-8'))

        connection.commit()

        if progress_callback:
            progress_callback(cls.IndexerStatus.COMPLETED,
                              project_path=project_path)

        return cls(connection, index, translation_units, project_path)

    @classmethod
    def from_persistent(cls, project_path, folders=None,
                        progress_callback=None):
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
        progress_callback -- an optional callback function, that should expect
        an Indexer.IndexerStatus as its first positional argument, and have 
        **kwargs to accept any additional arguments, as described in the 
        IndexerStatus attribute docstrings.

        Exceptions:
        NoPersistentIndexError -- raise if there is not an existing index file.
        '''

        if not os.path.isabs(project_path):
            project_path = os.path.abspath(project_path)

        index_db_path = os.path.join(project_path, cls._DB_FILE_NAME)
        if not os.path.exists(index_db_path):
            raise NoPersistentIndexError(index_db_path)

        connection = sqlite3.connect(index_db_path, check_same_thread=False)

        index = cindex.Index.create()
        translation_units = cls._parse_project(index, project_path,
                                               folders, progress_callback)

        if progress_callback:
            progress_callback(cls.IndexerStatus.COMPLETED,
                              project_path=project_path)

        return cls(connection, index, translation_units, project_path)

    def clean_persistent(self):
        '''
        Remove the database file when the Indexer instance is deleted.

        This method should be called before the Indexer instance is
        deleted. After the instance is deleted, a new index should
        be created using from_empty.
        '''
        self._clean_persistent = True

    def get_definition(self, source_location):
        '''
        Return a cursor to a definition.

        If source_location is not a reference, None will be returned.

        Parameters:
        source_location -- A SourceLocation instance, created by a call
        to from_position or from_offset. The offset can be anywhere within
        the reference, i.e. any offset between |func and func| is acceptable
        '''

        translation_unit = self._translation_units[source_location.file.name]
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

        translation_unit = self._translation_units[source_location.file.name]
        cursor = cindex.Cursor.from_location(translation_unit, source_location)
        cursor = cursor.referenced

        if not cursor:
            return []

        sql_cursor = self._connection.cursor()
        sql_cursor.execute(
            'SELECT path, offset, enclosing_offset FROM refs WHERE usr = ?',
            (cursor.get_usr(),))
        result = []

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

    def get_diagnostics(self, cindexer_file):
        '''
        Return an iteratable and _indexable object containing the diagnostics.

        Parameters:
        cindexer_file -- A File instance, created by a call to from_name.
        '''
        translation_unit = self._translation_units[cindexer_file.name]
        return translation_unit.diagnostics

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

        translation_unit = self._translation_units[source_location.file.name]
        return translation_unit.codeComplete(
            source_location.file.name,
            source_location.line,
            source_location.column,
            unsaved_files)

    def add_file(self, path):
        '''
        Add a file to the index, and return a new File instance.

        cindexer.File.from_name cannot be called until the file is in the
        index, so a path to the file is passed in here, not a File instance.

        Parameters:
        path -- An absolute or project relative path, as bytes or str
        '''
        if type(path) is str:
            path = bytes(path, 'utf-8')
        if not os.path.isabs(path):
            path = os.path.join(self._project_path, path)

        translation_unit = self._index.parse(path)
        self._translation_units[path] = translation_unit
        Indexer._update_db(
            path, translation_unit.cursor,
            self._connection, self._connection.cursor())

        self._connection.commit()
        return self._file_from_name(path)

    def update_file(self, cindexer_file):
        '''
        Update a file in the index, and return a new File instance.

        Reparsing a translation unit will destroy the file passed in,
        so we return a new instance with the same name as a convinience.

        Parameters:
        cindexer_file -- A file instance, created by a call to from_name.
        This file should not be used after update_index returns.
        '''

        path = cindexer_file.name
        translation_unit = self._translation_units.get(path)
        sql_cursor = self._connection.cursor()

        translation_unit.reparse()
        sql_cursor.execute('DELETE FROM defs WHERE path = ?', (path,))
        sql_cursor.execute('DELETE FROM refs WHERE path = ?', (path,))
        Indexer._update_db(
            path, translation_unit.cursor,
            self._connection, self._connection.cursor())

        self._connection.commit()
        return self._file_from_name(path)

    _DB_FILE_NAME = '.cindexer.db'
    '''The name of the database file an Indexer instance creates.'''

    @staticmethod
    def _indexable(file_name):
        file_name = str(file_name)
        exts = ['.c', '.h', '.cpp']
        return any(file_name.endswith(ext) for ext in exts)
    
    @classmethod
    def _parse_wrapper(cls, translation_units, index, 
                       abs_path, progress_callback):
        
        translation_units[abs_path] = index.parse(abs_path)
        if progress_callback:
            progress_callback(
                cls.IndexerStatus.PARSING,
                path=abs_path.decode('utf-8'))

    @classmethod
    def _parse_project(cls, index, project_path, folders, progress_callback):
        translation_units = {}
        started_threads = []
        if folders and len(folders) > 0:
            try:
                all_folder_paths = []
                for folder in folders:
                    folder_path = folder['path']
                    if not os.path.isabs(folder_path):
                        folder_path = os.path.join(project_path, folder_path)
                    all_folder_paths.append(folder_path)
            except KeyError:
                raise MalformedFolderDataError

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
                                args=(translation_units, index, 
                                      abs_path, progress_callback))
                            indexer_thread.start()
                            started_threads.append(indexer_thread)


                    for subdir in subdirs:
                        if (any([fnmatch(subdir, pattern)
                                 for pattern in folder_exclude_patterns]) or
                                os.path.abspath(subdir) in all_folder_paths):

                            subdirs.remove(subdir)

        else:
            for path, subdirs, files in os.walk(folder_path):
                for file in files:
                    if cls._indexable(file):

                        abs_path = os.path.abspath(os.path.join(path, file))
                        abs_path = bytes(abs_path, 'utf-8')
                        indexer_thread = threading.Thread(
                            target=cls._parse_wrapper, 
                            args=(translation_units, index, 
                                  abs_path, progress_callback))
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
    def _update_db(path, cursor, connection,
                   sql_cursor, enclosing_def_cursor=None):
        if cursor.is_definition():
            sql_cursor.execute(
                'INSERT INTO defs VALUES (?, ?, ?)',
                (cursor.get_usr(), path, cursor.location.offset))
            if Indexer._is_enclosing_def(cursor):
                enclosing_def_cursor = cursor
        elif (cursor.referenced and cursor != cursor.referenced
              and cursor.location.file.name == path):
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

        for child in cursor.get_children():
            Indexer._update_db(
                path, child, connection, sql_cursor, enclosing_def_cursor)

    def _file_from_name(self, file_name):
        translation_unit = self._translation_units[file_name]
        return cindex.File.from_name(translation_unit, file_name)

    def _source_location_from_position(self, cindexer_file, line, column):
        translation_unit = self._translation_units[cindexer_file.name]
        return cindex.SourceLocation.from_position(
            translation_unit, cindexer_file, line, column)

    def _source_location_from_offset(self, cindexer_file, offset):
        translation_unit = self._translation_units[cindexer_file.name]
        return cindex.SourceLocation.from_offset(
            translation_unit, cindexer_file, offset)
