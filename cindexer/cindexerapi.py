'''
Classes:

ClassProperty -- Allows properties on class objects, for internal use.
Config -- An interface to cindex.Config, must use to set the libclang.dylib
path
File -- An interface to cindex.File.
SourceLocation -- An interface to cindex.SourceLocation
Indexer -- The main class of the module, most operations will run through an
instance of this class
'''
from fnmatch import fnmatch
import os
import subprocess
import sys
import threading

_DEPENDENCIES_PATH = os.path.join(os.path.abspath(os.path.dirname(__file__)),
                                  'dependencies')
_MODULES_PATH = os.path.join(_DEPENDENCIES_PATH, 'modules')
_LIB_DYNLOAD_PATH = os.path.join(_MODULES_PATH, 'lib-dynload')

if _MODULES_PATH not in sys.path:
    sys.path.append(_MODULES_PATH)
if _LIB_DYNLOAD_PATH not in sys.path:
    sys.path.append(_LIB_DYNLOAD_PATH)

import sqlite3
from clang import cindex

_LIB_PATH = os.path.join(_DEPENDENCIES_PATH, 'lib')

if not cindex.Config.loaded:
    cindex.Config.set_library_path(_LIB_PATH)

_BIN_PATH = os.path.join(_DEPENDENCIES_PATH, 'bin')
_ETC_PATH = os.path.join(_DEPENDENCIES_PATH, 'etc')


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

    '''
    Used for debugging, by exposing state. Should not be throw in released
    version.
    '''

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __str__(self):
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
    Provides an interface to cindex.File, and resolve unparsed header files to
    parsed files.

    Static Methods:
    from_name(indexer, file_name)
    '''

    def __init__(self):
        '''
        File instances should only be created using from_name.
        '''
        raise NotImplementedError

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

    def __init__(self):
        '''
        SourceLocation instances should only be created using from_position or
        from_offset.
        '''
        raise NotImplementedError

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
        project_path -- an absolute to the project, as bytes or str
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

        # First check if the file has actually been parsed.
        if path in self._translation_units.keys():
            return True

        # Header files will not be parsed, but may be included in files that
        # have been parsed, so we check the includes table.
        sql_cursor = self._connection.cursor()
        sql_cursor.execute('SELECT COUNT(*) FROM includes WHERE include = ?',
                           (path,))
        (count,) = sql_cursor.fetchone()
        return count > 0

    class IndexerStatus(object):

        '''
        An enumeration describing the status of an Indexer instance while it
        is parsing and building the index. This will be the first argument to
        the callback function provided to from_empty or from_persistent.
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
            'CREATE TABLE defs(usr TEXT PRIMARY KEY, path TEXT, offset INT)')

        sql_cursor.execute(
            '''CREATE TABLE refs(usr TEXT, path TEXT,
                                 offset INT, enclosing_offset INT)''')
        sql_cursor.execute(
            'CREATE UNIQUE INDEX refs_path_offset_idx ON refs(path, offset)')

        sql_cursor.execute(
            '''CREATE TABLE classes(sub_usr TEXT, super_usr TEXT,
                                    sub_path TEXT, super_path TEXT)''')
        sql_cursor.execute(
            '''CREATE UNIQUE INDEX sub_usr_super_usr_idx
               ON classes(sub_usr, super_usr)''')
        sql_cursor.execute(
            '''CREATE TABLE includes(translation_unit TEXT, source TEXT,
                                     include TEXT, depth INT)''')
        sql_cursor.execute(
            'CREATE INDEX tu_source_idx ON includes(translation_unit, source)')

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
        project_path -- an absolute path to the project, as bytes
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

        # When a File instance is created for the client we add a
        # _translation_unit_name attribute, that may not be the same as the
        # name attribute (e.g. creating a File instance for a header that is
        # not parsed, but is included in a file that is parsed).
        translation_unit = self._translation_units[
            source_location.file._translation_unit_name]
        cursor = cindex.Cursor.from_location(
            translation_unit, source_location)
        def_cursor = cursor.referenced

        if def_cursor:
            # def_cursor will be a definition if the reference is in the same
            # translation unit as the definition. Otherwise, it will be the
            # declaration in the translation unit, so we will look up the
            # definition.
            if not def_cursor.is_definition():
                sql_cursor = self._connection.cursor()
                sql_cursor.execute(
                    'SELECT path, offset FROM defs WHERE usr = ?',
                    (def_cursor.get_usr(),))
                result = sql_cursor.fetchone()

                # If we find the definition, create a cursor to return to the
                # client.
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

        # When a File instance is created for the client we add a
        # _translation_unit_name attribute, that may not be the same as the
        # name attribute (e.g. creating a File instance for a header that is
        # not parsed, but is included in a file that is parsed).
        translation_unit = self._translation_units[
            source_location.file._translation_unit_name]
        cursor = cindex.Cursor.from_location(translation_unit, source_location)
        cursor = cursor.referenced

        # At this point the cursor should be the declaration or definition of
        # source_location, so we can look up all the references.

        result = []
        if not cursor:
            return result

        sql_cursor = self._connection.cursor()
        sql_cursor.execute(
            'SELECT path, offset, enclosing_offset FROM refs WHERE usr = ?',
            (cursor.get_usr(),))

        for path, offset, enclosing_offset in sql_cursor.fetchall():
            # Create a cursor from the reference to return to the client.
            ref_file = File.from_name(self, path)
            ref_source_location = SourceLocation.from_offset(
                self, ref_file, offset)
            ref_translation_unit = self._translation_units[
                ref_file._translation_unit_name
            ]
            ref_cursor = cindex.Cursor.from_location(
                ref_translation_unit, ref_source_location)

            # We also return a cursor to the enclosing node to return to the
            # client (what counts as an enclosing node is decided by
            # _is_enclosing_def). It is possible this doesn't exist, in which
            # case a -1 will be stored as the offset.
            enclosing_cursor = None
            if enclosing_offset != -1:
                enclosing_source_location = cindex.SourceLocation.from_offset(
                    ref_translation_unit, ref_file, enclosing_offset)
                enclosing_cursor = cindex.Cursor.from_location(
                    ref_translation_unit, enclosing_source_location)

            result.append((ref_cursor, enclosing_cursor))

        return result

    def get_superclasses(self, source_location):

        '''
        Return an array of cursors to superclasses.

        The cursors are ordered ascending up the inheritance hierarchy, (i.e.
        all immediate superclasses are returned first, than all the
        superclasses of the immediate superclasses, etc.)

        Parameters:
        source_location -- A SourceLocation instance, created by a call
        to from_position or from_offset. The offset can be anywhere within
        the reference, i.e. any offset between |func and func| is acceptable
        '''

        # When a File instance is created for the client we add a
        # _translation_unit_name attribute, that may not be the same as the
        # name attribute (e.g. creating a File instance for a header that is
        # not parsed, but is included in a file that is parsed).
        translation_unit = self._translation_units[
            source_location.file._translation_unit_name]
        cursor = cindex.Cursor.from_location(translation_unit, source_location)
        cursor = cursor.referenced

        # At this point cursor should be a declaration of definition of a
        # class. We don't check explicitly, if it isn't an empty array will
        # just be returned.

        superclasses = []
        if not cursor:
            return superclasses

        # We do a BFS for all the superclasses, and return them in this order.
        sql_cursor = self._connection.cursor()
        sub_usrs = [cursor.get_usr()]
        while len(sub_usrs) > 0:

            # First, lookup all of the superclasses for the current subclasses.
            super_usrs = []
            for sub_usr in sub_usrs:
                sql_cursor.execute(
                    'SELECT super_usr FROM classes WHERE sub_usr = ?',
                    (sub_usr,))
                super_usrs.extend([
                    result[0] for result in sql_cursor.fetchall()
                ])

            # Now, we look up the location of the definition of the
            # superclasses we found, and create cursors.
            for super_usr in super_usrs:
                sql_cursor.execute(
                    'SELECT path, offset FROM defs WHERE usr = ?',
                    (super_usr,))
                result = sql_cursor.fetchone()

                if result:
                    path, offset = result
                    super_file = File.from_name(self, path)
                    super_source_location = SourceLocation.from_offset(
                        self, super_file, offset)
                    super_translation_unit = self._translation_units[
                        super_file._translation_unit_name
                    ]
                    super_cursor = cindex.Cursor.from_location(
                        super_translation_unit, super_source_location)
                    superclasses.append(super_cursor)

            # Iterate for the classes we just found.
            sub_usrs = super_usrs

        return superclasses

    def get_subclasses(self, source_location):

        '''
        Return an array of cursors to subclasses.

        The cursors are ordered descending down the inheritance hierarchy,
        (i.e. all immediate subclasses are returned first, than all the
        subclasses of the immediate subclasses, etc.)

        Parameters:
        source_location -- A SourceLocation instance, created by a call
        to from_position or from_offset. The offset can be anywhere within
        the reference, i.e. any offset between |func and func| is acceptable
        '''

        # When a File instance is created for the client we add a
        # _translation_unit_name attribute, that may not be the same as the
        # name attribute (e.g. creating a File instance for a header that is
        # not parsed, but is included in a file that is parsed).
        translation_unit = self._translation_units[
            source_location.file._translation_unit_name]
        cursor = cindex.Cursor.from_location(translation_unit, source_location)
        cursor = cursor.referenced

        # At this point cursor should be a declaration of definition of a
        # class. We don't check explicitly, if it isn't an empty array will
        # just be returned.

        subclasses = []
        if not cursor:
            return subclasses

        # We do a BFS for all the subclasses, and return them in this order.
        sql_cursor = self._connection.cursor()
        super_usrs = [cursor.get_usr()]
        while len(super_usrs) > 0:

            # First, lookup all of the subclasses for the current superclasses.
            sub_usrs = []
            for super_usr in super_usrs:
                sql_cursor.execute(
                    'SELECT sub_usr FROM classes WHERE super_usr = ?',
                    (super_usr,))
                sub_usrs.extend([
                    result[0] for result in sql_cursor.fetchall()
                ])

            # Now, we look up the location of the definition of the
            # subclasses we found, and create cursors.
            for sub_usr in sub_usrs:
                sql_cursor.execute(
                    'SELECT path, offset FROM defs WHERE usr = ?',
                    (sub_usr,))
                result = sql_cursor.fetchone()

                if result:
                    path, offset = result
                    sub_file = File.from_name(self, path)
                    sub_source_location = SourceLocation.from_offset(
                        self, sub_file, offset)
                    sub_translation_unit = self._translation_units[
                        sub_file._translation_unit_name
                    ]
                    sub_cursor = cindex.Cursor.from_location(
                        sub_translation_unit, sub_source_location)
                    subclasses.append(sub_cursor)

            # Iterate for the classes we just found.
            super_usrs = sub_usrs

        return subclasses

    def get_includes(self, cindexer_file):
        '''
        Return an array of tuples containing the path to the include and the
        depth of the include.

        Depth is 1 if the file is directly included in cindexer_file. The
        array is in depth first search order (i.e. an include is completely
        expanded before we start expanding the next one).

        Parameters:
        cindexer_file - A File instance, created by a call to from_name.
        '''
        sql_cursor = self._connection.cursor()
        # Call the recursive private method. We need to actually do a search
        # instead of looking up the TranslationUnit instance and calling
        # get_includes() because this may be called on a file that was not
        # actually parsed (e.g. a header file).
        return Indexer._get_includes(cindexer_file._translation_unit_name,
                                     cindexer_file.name, sql_cursor, [])

    @staticmethod
    def _get_includes(translation_unit_name, source, sql_cursor, visited):
        '''
        Return an array of tuples containing the path to the include and the
        depth of the include.

        Performs the actual search for includes.

        Parameters:
        translation_unit_name - The name of the translation unit that parsed
        the include.
        source - The path to the source file whose includes we are finding.
        sql_cursor - A cursor for the index file.
        '''
        # Do a recursive DFS for includes, using the visited list to prevent
        # infinite recursion on circular includes.
        visited.append(source)
        result = []
        sql_cursor.execute(
            '''
            SELECT include, depth FROM includes
            WHERE translation_unit = ? AND source = ?
            ''',
            (translation_unit_name, source))
        for include, depth in sql_cursor.fetchall():
            result.append((include.decode('utf-8'), depth))
            if include not in visited:
                result.extend(Indexer._get_includes(translation_unit_name,
                                                    include, sql_cursor,
                                                    visited))

        return result

    def get_includers(self, cindexer_file):
        '''
        Return an array of tuples containing the path to the source and the
        depth of the source.

        Depth is 1 if the file is directly includes the cindexer_file. The
        array is in depth first search order (i.e. when we find a file that
        includes cindexer_file we consider all the files including that file
        before we go to the next file).

        Parameters:
        cindexer_file - A File instance, created by a call to from_name.
        '''
        sql_cursor = self._connection.cursor()
        # Call the recursive private method.
        return Indexer._get_includers(cindexer_file.name, sql_cursor, 1, [])

    @staticmethod
    def _get_includers(include, sql_cursor, depth, visited):
        '''
        Return an array of tuples containing the path to the source and the
        depth of the source.

        Performs the actual search for includers.

        Parameters:
        include - The path to the included file whose sources we are finding.
        sql_cursor - A cursor for the index file.
        depth - The depth of the include, should be 1 for the top-level call.
        visited - An list of visited includes, should be empty for the
        top-level call.
        '''
        # Do a recursive DFS for includers, using the visited list to prevent
        # infinite recursion on circular includes.
        visited.append(include)
        result = []
        sql_cursor.execute(
            '''
            SELECT source FROM includes
            WHERE include = ?''',
            (include,))
        for (source,) in sql_cursor.fetchall():
            result.append((source.decode('utf-8'), depth))
            if source not in visited:
                result.extend(Indexer._get_includers(source, sql_cursor,
                                                     depth + 1, visited))

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
        # When a File instance is created for the client we add a
        # _translation_unit_name attribute, that may not be the same as the
        # name attribute (e.g. creating a File instance for a header that is
        # not parsed, but is included in a file that is parsed).
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

        translation_unit = self._translation_units[
            source_location.file._translation_unit_name]
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

        # Parse the file.
        translation_unit = self._index.parse(path)

        self._translation_units[path] = translation_unit

        if progress_callback:
            progress_callback(self.IndexerStatus.STARTING_INDEXING,
                              path=path.decode('utf_8'),
                              indexed=0,
                              total=1)

        # Update the index file.
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
        # When a File instance is created for the client we add a
        # _translation_unit_name attribute, that may not be the same as the
        # name attribute (e.g. creating a File instance for a header that is
        # not parsed, but is included in a file that is parsed).
        translation_unit = self._translation_units[
            cindexer_file._translation_unit_name
        ]
        sql_cursor = self._connection.cursor()

        if progress_callback:
            progress_callback(self.IndexerStatus.STARTING_PARSE,
                              path=path.decode('utf_8'))

        # Reparse the file.
        translation_unit.reparse()

        # Clear out all of the persistent information about the file.
        sql_cursor.execute('DELETE FROM defs WHERE path = ?', (path,))
        sql_cursor.execute('DELETE FROM refs WHERE path = ?', (path,))
        sql_cursor.execute(
            'DELETE FROM classes WHERE sub_path = ? or super_path = ?',
            (path, path))
        sql_cursor.execute(
            'DELETE FROM includes WHERE translation_unit = ?',
            (path,))

        if progress_callback:
            progress_callback(self.IndexerStatus.STARTING_INDEXING,
                              path=path.decode('utf_8'),
                              indexed=0,
                              total=1)

        # Insert the updated information.
        Indexer._update_db(
            path, translation_unit.cursor,
            self._connection, self._connection.cursor())

        # Update any files that are including this file.
        # TODO: Fix the progress callback, and check for circular inclusion.
        sql_cursor.execute('SELECT source FROM includes WHERE include = ?',
                           (path,))
        for (source,) in sql_cursor.fetchall():
            includer_file = File.from_name(self, source)
            self.update_file(includer_file, progress_callback)

        self._connection.commit()

        if progress_callback:
            progress_callback(self.IndexerStatus.COMPLETED,
                              project_path=self._project_path)

        return self._file_from_name(path)

    _DB_FILE_NAME = '.cindexer.db'
    '''The name of the database file an Indexer instance creates.'''

    @staticmethod
    def _indexable(file_name):
        '''
        Return True if the file should be indexed.

        Header files will not be directly parsed and indexed, but will be
        indirectly if they are included in a file that is parsed and indexed.

        Parameters:
        file_name - A path or basename of the file, as bytes or str.
        '''
        if type(file_name) is bytes:
            file_name = file_name.decode('utf-8')
        exts = ['.c', '.cpp', '.cc']
        return any(file_name.endswith(ext) for ext in exts)

    @classmethod
    def _parse_wrapper(cls, translation_units, index, abs_path,
                       progress_callback, compilation_database):
        '''
        Get the args from the compilation database and create the new
        translation unit.

        This method is usually used as a target for threads.

        Parameters:
        translation_units - A reference to a dictionary of translation units,
        keyed on absolute path (in bytes). This method will set a new
        translation unit.

        index - The index to add the translation unit to.

        abs_path - The absolute path to the file, in bytes.

        progress_callback -- an optional callback function, that should expect
        an Indexer.IndexerStatus as its first positional argument, and have
        **kwargs to accept any additional arguments, as described in the
        IndexerStatus attribute docstrings.

        compilation_database - The CompilationDatabase instance for the
        project, or None.
        '''
        if progress_callback:
            progress_callback(cls.IndexerStatus.STARTING_PARSE,
                              path=abs_path.decode('utf-8'))

        compile_commands = None
        if compilation_database:
            compile_commands = compilation_database.getCompileCommands(
                abs_path)

        args = []
        if compile_commands:
            # We only use include paths, definitions, and warnings as
            # arguments. Also make sure each argument is unique.
            for command in compile_commands:
                for arg in command.arguments:
                    if ((arg.decode('utf-8').startswith('-I') or
                         arg.decode('utf-8').startswith('-D') or
                         arg.decode('utf-8').startswith('-W')) and
                            arg not in args):
                        args.append(arg)

        translation_units[abs_path] = index.parse(abs_path, args=args)

    @classmethod
    def _parse_project(cls, index, project_path, folders, progress_callback,
                       cmakelist_path, makefile_path):
        '''
        Walk and parse the project, returning a dictionary of translation units
        keyed on absolute path (in bytes).

        Parameters:
        index - The index to add the translation units to.

        project_path -- The absolute path to the project, as bytes.

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
        existing_compilation_database = False

        # Attempt to find an existing compilation database. If one hasn't been
        # created yet, create one using CMake or Bear.
        #
        # TODO: Handle updates to CMakeLists.txt or Makefile.
        if os.path.exists(os.path.join(project_path, 'compile_commands.json')):
            existing_compilation_database = True
        elif cmakelist_path:
            if not os.path.isabs(cmakelist_path):
                cmakelist_path = os.path.join(project_path, cmakelist_path)

            subprocess.call(
                'cmake -DCMAKE_EXPORT_COMPILE_COMMANDS=1 {}'.format(
                    cmakelist_path),
                cwd=project_path, shell=True)

        elif makefile_path:

            out_path = os.path.join(project_path, 'compile_commands.json')
            if not os.path.isabs(makefile_path):
                makefile_path = os.path.join(project_path, makefile_path)

            subprocess.call(['make', 'clean'], cwd=makefile_path)

            subprocess.call(
                [os.path.join(_BIN_PATH, 'bear'),
                 '-o', out_path,
                 '-l', os.path.join(_LIB_PATH, 'libear.dylib'),
                 '-c', os.path.join(_ETC_PATH, 'bear.conf'),
                 '--', 'make'],
                cwd=makefile_path)

        # If we did find or create a compliation database, load it.
        compilation_database = None
        if existing_compilation_database or cmakelist_path or makefile_path:
            compilation_database = cindex.CompilationDatabase.fromDirectory(
                bytes(project_path, 'utf-8'))

        translation_units = {}
        started_threads = []
        # If folders are provided, use them to walk the project.
        if folders and len(folders) > 0:
            # We create a list of all folder roots because we do not want to
            # walk the same files twice because folders overlap (i.e. a folder
            # root may be a subdirectory of another folder root. In this case
            # we want to stop walking the parent folder when we hit the
            # subdirectory.
            all_folder_paths = []
            for folder in folders:
                # Each folder must have a 'path'.
                folder_path = folder['path']
                if not os.path.isabs(folder_path):
                    folder_path = os.path.join(project_path, folder_path)
                all_folder_paths.append(folder_path)

            for folder in folders:
                folder_path = folder['path']
                if not os.path.isabs(folder_path):
                    folder_path = os.path.join(project_path, folder_path)

                # Folders can optionally have a 'file_exclude_patterns'.
                file_exclude_patterns = folder.get('file_exclude_patterns')
                if not file_exclude_patterns:
                    file_exclude_patterns = []

                # Folders can optionally have a 'folder_exclude_patterns'.
                folder_exclude_patterns = folder.get('folder_exclude_patterns')
                if not folder_exclude_patterns:
                    folder_exclude_patterns = []

                # We need to walk topdown because we will modify subdirs.
                # Folders an optionally have a 'follow_symlinks'
                for path, subdirs, files in os.walk(
                        folder_path,
                        topdown=True,
                        followlinks=folder.get('follow_symlinks')):

                    for file_name in files:
                        # The fnmatch.fnmatch function uses wildcards.
                        if (cls._indexable(file_name) and
                            not any([fnmatch(file_name, pattern) \
                            for pattern in file_exclude_patterns])):

                            abs_path = os.path.abspath(os.path.join(path,
                                                                    file_name))
                            abs_path = bytes(abs_path, 'utf-8')

                            Indexer._parse_wrapper(
                                translation_units, index, abs_path,
                                progress_callback, compilation_database)

                    # Check if any subdirectories should be excluded.
                    for subdir in subdirs:
                        if (any([fnmatch(subdir, pattern)
                                 for pattern in folder_exclude_patterns]) or
                                os.path.abspath(subdir) in all_folder_paths):

                            subdirs.remove(subdir)

        else:
            # If folders was not provided, we walk the entire tree rooted at
            # project path.
            for path, subdirs, files in os.walk(project_path):
                for file_name in files:
                    if cls._indexable(file_name):

                        abs_path = os.path.abspath(os.path.join(path,
                                                                file_name))
                        abs_path = bytes(abs_path, 'utf-8')
                        Indexer._parse_wrapper(
                            translation_units, index, abs_path,
                            progress_callback, compilation_database)

        return translation_units

    @staticmethod
    def _is_enclosing_def(cursor):
        '''
        Return True if the cursor is considered an enclosing definition.

        This is used so we can return an enclosing definition along with a
        reference for the get_references method. Note that this does not use
        the same list as cindex's is_definition method.

        Parameters:
        cursor - The cursor we are considering.
        '''
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
        '''
        Update the database with a parsed translation unit.

        Parameters:
        path - An absolute path to the translation unit, as bytes.

        cursor - The cursor that is being inserted into the database. We will
        recursively walk through all of the children, so the top level call to
        _update_db should pass in the translation unit's cursor.

        connection - A connection to the database.

        sql_cursor - A cursor for the database.

        enclosing_def_cursor - A cursor to the closest enclosing definition (as
        defined by _is_enclosing_def). The top level call to _update_db not
        pass in an argument.
        '''
        # If the cursor is a definition, update the defs table, and check if it
        # should be set as an enclosing definition.
        if cursor.is_definition():
            sql_cursor.execute(
                'INSERT OR IGNORE INTO defs VALUES (?, ?, ?)',
                (cursor.get_usr(),
                 cursor.location.file.name,
                 cursor.location.offset))
        if Indexer._is_enclosing_def(cursor):
            enclosing_def_cursor = cursor

        # To insert into refs, check that the cursor is referencing a different
        # cursor, and is in the file we are indexing.
        #
        # TODO: does this handle headers correctly?
        if (cursor.referenced and
            cursor != cursor.referenced and
            cursor.location.file):

            # If an enclosing definition cursor has been set, store its
            # location, otherwise store -1 to signal there is none.
            if enclosing_def_cursor:
                enclosing_offset = enclosing_def_cursor.location.offset
            else:
                enclosing_offset = -1

            sql_cursor.execute(
                'INSERT OR IGNORE INTO refs VALUES (?, ?, ?, ?)',
                (cursor.referenced.get_usr(),
                 cursor.location.file.name,
                 cursor.location.offset,
                 enclosing_offset))

        # If the cursor is a base specifier, update the classes table with
        # inheritance information. Conviniently, we can use the enclosing
        # def cursor to get the subclass declaration.
        if (cursor.kind == cindex.CursorKind.CXX_BASE_SPECIFIER and
            cursor.referenced.kind != cindex.CursorKind.NO_DECL_FOUND):
            sql_cursor.execute(
                'INSERT OR IGNORE INTO classes VALUES (?, ?, ?, ?)',
                (enclosing_def_cursor.get_usr(),
                 cursor.referenced.get_usr(),
                 path,
                 cursor.referenced.location.file.name))

        # We only want to update includes once per translation unit.
        if cursor.kind == cindex.CursorKind.TRANSLATION_UNIT:
            includes = cursor.translation_unit.get_includes()
            for include in includes:
                sql_cursor.execute('INSERT INTO includes VALUES (?, ?, ?, ?)',
                                   (path,
                                    include.source.name,
                                    include.include.name,
                                    include.depth))

        # Recursively index all the children.
        for child in cursor.get_children():
            Indexer._update_db(
                path, child, connection, sql_cursor, enclosing_def_cursor)

    def _file_from_name(self, file_name):
        '''
        Return a File instance for the given name.

        This method resolves header files to a file that includes them and was
        actually compiled, so we can get a Translation Unit instance to create
        the File with. It also stores a private attribute with the translation
        unit name, so we can lookup the Translation Unit instance again later.

        Parameters:
        file_name -- An absolute path to the file, as bytes.
        '''
        translation_unit = self._translation_units.get(file_name)

        source = file_name
        # If there was not a translation unit for the file, look for a file
        # that includes it and does have a translation unit.
        # TODO: fix this so it does an actual search.
        while not translation_unit:
            sql_cursor = self._connection.cursor()
            sql_cursor.execute('SELECT source FROM includes WHERE include = ?',
                               (source,))
            (source,) = sql_cursor.fetchone()
            translation_unit = self._translation_units.get(source)

        cindex_file = cindex.File.from_name(translation_unit, file_name)
        cindex_file._translation_unit_name = translation_unit.spelling
        return cindex_file

    def _source_location_from_position(self, cindexer_file, line, column):
        '''
        Return a SourceLocation instance for the given File instance, and line
        and column number.

        Parameters:
        cindexer_file - A File instance.
        line - The line number, 1 indexed.
        column - The column number, 1 indexed.
        '''
        translation_unit_name = cindexer_file._translation_unit_name
        translation_unit = self._translation_units[translation_unit_name]
        source_location = cindex.SourceLocation.from_position(
            translation_unit, cindexer_file, line, column)
        # Because from_position creates a new File instance, set the private
        # attribute we add to File instances when they are created.
        source_location.file._translation_unit_name = translation_unit_name
        return source_location

    def _source_location_from_offset(self, cindexer_file, offset):
        '''
        Return a SourceLocation instance for the given File instance and
        offset.

        Parameters:
        cindexer_file - A File instance.
        offset - The offset into the file, 1 indexed.
        '''
        translation_unit_name = cindexer_file._translation_unit_name
        translation_unit = self._translation_units[translation_unit_name]
        source_location = cindex.SourceLocation.from_offset(
            translation_unit, cindexer_file, offset)
        # Because from_position creates a new File instance, set the private
        # attribute we add to File instances when they are created.
        source_location.file._translation_unit_name = translation_unit_name
        return source_location
