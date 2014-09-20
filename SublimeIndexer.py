'''
Context Menu Commands:
Open Definition - When called with a reference selected, opens and highlights
the definition.

List References - When called with a reference or definition selected, displays
a quick menu of all the references to the selection. When a menu item is
highlighted, opens and highlights the reference.

Expand Superclasses - When called with a class selected, displays a quick menu
of all that class' superclasses, in breadth first search order. When a menu
item is highlighted, opens and highlights the class.

Expand Subclasses - When called with a class selected, displays a quick menu
of all that class' subclasses, in breadth first search order. When a menu item
is highlighted, opens and highlights the class.

Expand Includes - Displays a quick menu for all of the file's includes, in
depth first search order. When a menu item is highlighted, opens that file.

List Includers - Displays a quick menu for all of the file's includers, in
depth first search order. When a menu item is highlighted, opens that file.

View Issues In File - Displays a quick menu for all the the issues in the file.
When a menu item is selected, jumps to the issue.

Side Bar Commands:
Build Index - Builds an index for a project.

Clean Index - Destroys all in-memory and persistent data about an index on a
project.

View Issues In Project - Displays a quick menu for all the the issues in the
project. When a menu item is selected, opens the file and jumps to the issue.

Other:
When a issue is selected, it should be displayed as a status message.
'''
import os
import sys
import threading
import time

import sublime
import sublime_plugin

# The plugin is not in the path by default, so we need to make sure it is in
# order to import the cindexer package.
SUBLIME_INDEXER_PATH = os.path.dirname(os.path.abspath(__file__))

if SUBLIME_INDEXER_PATH not in sys.path:
    sys.path.append(SUBLIME_INDEXER_PATH)

import cindexer

indexers = {}
'''
A global dictionary of Indexer instances, keyed on absolute paths to projects,
as str.
'''
current_diagnostics = {}
'''
A global dictionary of DiagnosticIter instances, keyed on absolute paths to
files.
'''
severity_key = {
    0 : 'Ignored',
    1 : 'Note',
    2 : 'Warning',
    3 : 'Error',
    4 : 'Fatal'
}
'''
A dictionary to translate diagnostic severity enumerations.
'''


class StatusUpdater(object):
    '''
    A singleton class that manages status updates returned by cindexer's
    progress callback functionality.

    There can only be one status at a time, so all methods are called on the
    StatusUpdater class object.

    Classmethods:
    start_update()
    set_status_message(status_message)
    end_update(status_message)
    '''

    def __init__(self):
        '''
        All methods should be called on the StatusUpdater class object,
        instances shouldn not be created.
        '''
        raise NotImplementedError

    _waiting_status_strs = [
        '[=  ] ',
        '[ = ] ',
        '[  =] ',
        '[ = ] '
    ]

    _updating = False
    _updating_thread = None
    _status_message = ''
    _status_message_lock = threading.Lock()

    @classmethod
    def start_update(cls):
        '''
        Start displaying the waiting indicator, and be prepared for updates.

        Should be called before set_status_message or end_update.
        '''
        cls._updating = True
        # Start a new thread to display the status updates.
        cls._updating_thread = threading.Thread(target=cls._update_target)
        cls._updating_thread.start()

    @classmethod
    def set_status_message(cls, status_message):
        '''
        Set a status message.

        Parameters:
        status_message - The message to be displayed, as str.
        '''
        cls._status_message_lock.acquire()
        cls._status_message = status_message
        cls._status_message_lock.release()

    @classmethod
    def end_update(cls, status_message=None):
        '''
        Stop displaying the waiting indicator, and optionally display a new
        status message.

        Parameters:
        status_message - An optional message to be displayed, as str.
        '''
        cls._updating = False
        cls._updating_thread.join()
        if status_message:
            sublime.status_message(status_message)

    @classmethod
    def _update_target(cls):
        '''
        Animate the waiting indicator, and update status messages.

        This method will be used as the target of a thread.
        '''
        i = 0
        # No lock needed for _updateing because assignment is atomic.
        while cls._updating:
            status_message = cls._waiting_status_strs[i]
            # This is the reason we need a lock. Assignment is atomic, but not
            # checking then assigning.
            cls._status_message_lock.acquire()
            if cls._status_message:
                status_message += ': ' + cls._status_message
            cls._status_message_lock.release()
            sublime.status_message(status_message)
            i = (i + 1) % len(cls._waiting_status_strs)
            # Switch to the next frame of the animation ever 0.3 seconds.
            time.sleep(0.3)


def _progress_callback(indexer_status, **kwargs):
    '''
    Use the StatusUpdater class object to respond to calls from cindexer.

    Parameters:
    indexer_status - An IndexerStatus enumeration.
    **kwargs - cindexer may provide additional arguments in the callback
    (documented in IndexerStatus)
    '''
    if indexer_status == cindexer.Indexer.IndexerStatus.STARTING_PARSE:
        message = 'Parsing file {}'.format(kwargs['path'])
    elif indexer_status == cindexer.Indexer.IndexerStatus.STARTING_INDEXING:
        message = 'Indexing file {} ({} of {})'.format(kwargs['path'],
                                                       kwargs['indexed'] + 1,
                                                       kwargs['total'])
    elif indexer_status == cindexer.Indexer.IndexerStatus.COMPLETED:
        message = 'Built index for {}'.format(kwargs['project_path'])
        StatusUpdater.end_update(message)
        return

    StatusUpdater.set_status_message(message)


def _from_persistent_wrapper(project_path, folders, progress_callback, window):

    '''
    Create a new Indexer instance from a persistent index file.

    This is used as a target for threads.

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

    window - A reference to the window where the index is being built.
    '''

    StatusUpdater.start_update()
    indexer = cindexer.Indexer.from_persistent(project_path,
                                               folders,
                                               progress_callback)
    indexers[project_path] = indexer
    _update_window_diagnostics(window, indexer)

    num_diagnostics = len(indexer.get_diagnostics())
    # TODO: Find a way to make this fit in the ruler.
    if num_diagnostics > 0:
        sublime.error_message('There are {} issues in the project, and indexing may be incomplete or inaccurate.'.format(num_diagnostics))


def _from_empty_wrapper(project_path, folders, progress_callback, window,
                        cmakelists_path, makefile_path):

    '''
    Create a new Indexer instance without a persistent index file.

    This is used as a target for threads.

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

    window - A reference to the window where the index is being built.

    cmakelists_path -- an optional path to the CMakeLists.txt file
    project's, which will be used to generate a compilation commands
    database.

    makefile_path -- an optional path to a Makefile, which will be used to
    generate a compilation commands database. If both cmakelists_path and
    makefile_path are provided, cmakelists_path will be used.
    '''

    StatusUpdater.start_update()
    indexer = cindexer.Indexer.from_empty(
        project_path, folders, progress_callback,
        cmakelists_path, makefile_path)
    indexers[project_path] = indexer
    _update_window_diagnostics(window, indexer)

    num_diagnostics = len(indexer.get_diagnostics())
    if num_diagnostics > 0:
        sublime.error_message('There are {} issues in the project, and indexing may be incomplete or inaccurate.'.format(num_diagnostics))

def _update_window_diagnostics(window, indexer):

    '''
    Update the diagnostics for every view in the index.

    Parameters:
    window - The window to be updated.
    indexer - The Indexer instance created for the window.
    '''

    for view in window.views():
        file_name = view.file_name()

        if file_name:
            _update_view_diagnostics(view, indexer)

def _update_view_diagnostics(view, indexer):

    '''
    Update the diagnostics for a view.

    Parameters:
    view - The view to be updated.
    indexer - The Indexer instance created for the window that the view is a
    part of.
    '''

    if indexer.indexed(view.file_name()):
        cindexer_file = cindexer.File.from_name(indexer, view.file_name())
        diagnostics = indexer.get_diagnostics(cindexer_file)

        # view_diagnostics is a list of tuples of regions and diagnostics, used
        # to lookup a diagnostic when one of its regions is highlighted.
        # all_regions is just a list of regions, used to update the view.
        view_diagnostics = []
        all_regions = []

        for diagnostic in diagnostics:
            regions = []
            # Each diagnostic can have multiple ranges, and/or one location.
            for diagnostic_range in diagnostic.ranges:
                regions.append(sublime.Region(diagnostic_range.start.offset,
                                              diagnostic_range.end.offset))

            # If the location is at the very end of the view, highlight the
            # last character. Otherwise, highlight the character following the
            # offset.
            if diagnostic.location.offset == view.size():
                regions.append(sublime.Region(diagnostic.location.offset - 1,
                                              diagnostic.location.offset))
            else:
                regions.append(sublime.Region(diagnostic.location.offset,
                                              diagnostic.location.offset + 1))

            all_regions.extend(regions)
            view_diagnostics.append((regions, diagnostic))

        view.erase_regions('diagnostics')
        view.add_regions(
            'diagnostics', all_regions, 'invalid',
            flags=(sublime.PERSISTENT |
                   sublime.DRAW_SQUIGGLY_UNDERLINE |
                   sublime.DRAW_NO_FILL |
                   sublime.DRAW_NO_OUTLINE))

        # Store the list of tuples of regions and diagnostics in the global
        # current_diagnostics dictionary so we can look it up when a
        # diagnostic's region is highlighted
        current_diagnostics[view.file_name()] = view_diagnostics

def _get_diagnostic_summary(diagnostic):

    '''
    Return a summary string for a diagnostic.

    The format is "<file>:<line>:<col>: severity: spelling [option]". The
    location and option fields are not in every diagnostic.

    Parameters:
    diagnostic - The diagnostic to be summarized.
    '''
    if diagnostic.location.file:
        result = ':'.join([
            diagnostic.location.file.name.decode('utf-8'),
            str(diagnostic.location.line),
            str(diagnostic.location.column),
            ' ' + severity_key[diagnostic.severity],
            ' ' + diagnostic.spelling.decode('utf-8')
            ])
    else:
        result = ': '.join(severity_key[diagnostic.severity],
                           diagnostic.spelling.decode('utf-8'))

    if diagnostic.option:
        result += ' [' + diagnostic.option.decode('utf-8') + ']'

    return result


def plugin_loaded():

    '''
    Create indexer instances for any projects with persistent index files.
    '''

    for window in sublime.windows():
        project_file = window.project_file_name()

        if project_file:
            project_path = os.path.dirname(window.project_file_name())
            if cindexer.Indexer.has_persistent_index(project_path):
                project_data = window.project_data()
                folders = project_data.get('folders')
                indexer_thread = threading.Thread(
                    target=_from_persistent_wrapper,
                    args=(project_path, folders, _progress_callback, window))
                indexer_thread.start()


class SublimeIndexerListener(sublime_plugin.EventListener):

    '''
    Events:
    on_post_save
    on_load
    on_selection_modified
    '''

    def on_post_save(self, view):

        '''
        Update the file, if it is part of an index.
        '''

        project_file = view.window().project_file_name()

        if project_file:
            project_path = os.path.dirname(project_file)
            indexer = indexers.get(project_path)
            if indexer:
                name = view.file_name()
                if indexer.indexed(name):
                    cindexer_file = cindexer.File.from_name(indexer,
                                                            view.file_name())
                    StatusUpdater.start_update()
                    cindexer_file = indexer.update_file(cindexer_file,
                                                        _progress_callback)
                else:
                    StatusUpdater.start_update()
                    cindexer_file = indexer.add_file(name, _progress_callback)

                _update_view_diagnostics(view, indexer)

    def on_load(self, view):

        '''
        Update the diagnostics for the view, if it has any.
        '''

        window = view.window()
        if window:
            project_file = view.window().project_file_name()

            if project_file:
                project_path = os.path.dirname(project_file)
                indexer = indexers.get(project_path)
                if indexer:
                    name = view.file_name()
                    if indexer.indexed(name):
                        _update_view_diagnostics(view, indexer)

    def on_selection_modified(self, view):

        '''
        If a diagnostic's region is selected, display the diagnostic's
        summary as a status message.
        '''
        if len(view.sel()) == 1:
            offset = view.sel()[0].b
            view_diagnostics = current_diagnostics.get(view.file_name())
            if view_diagnostics:
                for regions, diagnostic in view_diagnostics:
                    contains = False
                    for region in regions:
                        if region.contains(offset):
                            contains = True
                            break

                    if contains:
                        sublime.status_message(
                            _get_diagnostic_summary(diagnostic))
                        break

    # def on_modified(self, view):
    #     project_file = view.window().project_file_name()

    #     if project_file:
    #         project_path = os.path.dirname(project_file)
    #         indexer = indexers.get(project_path)
    #         if indexer:
    #             name = view.file_name()
    #             if indexer.indexed(name):
    #                 offset = view.sel()[0].b
    #                 word = view.substr(view.word(offset))

    #                 triggers = ['.', '->', '::', ' ']
    #                 if any(word.startswith(trigger) for trigger in triggers):
    #                     unsaved_files = None
    #                     if view.is_dirty():
    #                         unsaved_files = [(view.file_name(), view.substr(sublime.Region(0, view.size())))]

    #                     cindexer_file = cindexer.File.from_name(indexer, view.file_name())
    #                     source_location = cindexer.SourceLocation.from_offset(indexer, cindexer_file, offset)
    #                     results = indexer.get_code_completion(source_location, unsaved_files)
    #                     strings = [result.string for result in results.results]
    #                     strings.sort(key=lambda string: string.priority)

    #                     view_completions = []
    #                     for string in strings:
    #                         placeholder_index = 1
    #                         description = ''
    #                         contents = ''
    #                         for chunk in string:
    #                             if chunk.isKindTypedText():
    #                                 trigger = chunk.spelling.decode('utf-8')
    #                                 description += chunk.spelling.decode('utf-8')
    #                                 contents += chunk.spelling.decode('utf-8')
    #                             elif chunk.isKindPlaceHolder():
    #                                 description += chunk.spelling.decode('utf-8')
    #                                 contents = '${' + str(placeholder_index) + ':' + chunk.spelling.decode('utf-8') + '}'
    #                                 placeholder_index += 1
    #                             elif chunk.isKindResultType():
    #                                 description += chunk.spelling.decode('utf-8') + ' '
    #                             elif chunk.isKindOptional():
    #                                 pass
    #                             elif chunk.isKindInformative():
    #                                 pass
    #                             else:
    #                                 spelling = chunk.spelling
    #                                 if type(spelling) is bytes:
    #                                     spelling = spelling.decode('utf-8')
    #                                 description += spelling
    #                                 contents += spelling

    #                         trigger += '\t' + description
    #                         view_completions.append((trigger, contents))

    #                     current_completions[view.file_name()] = view_completions

    # def on_query_completions(self, view, prefix, locations):
    #     view_completions = current_completions.get(view.file_name())
    #     if view_completions:
    #         return view_completions
    #     else:
    #         return []



class SideBarBuildIndexCommand(sublime_plugin.WindowCommand):

    def is_enabled(self):

        '''
        Return True if the window has a project file, and no index file.
        '''
        project_file = self.window.project_file_name()

        if project_file:
            project_path = os.path.dirname(project_file)
            return not cindexer.Indexer.has_persistent_index(project_path)

        return True

    def run(self):

        '''
        Create a new persistent index file and Indexer instance on a project.
        '''

        project_file = self.window.project_file_name()

        # We require a project file so we know at a minimum where the index
        # should be rooted, and optionally for other configuration settings.
        if project_file is None:
            sublime.error_message('SublimeIndexer requries a .sublime-project file to know which files to add to the index. To create a .sublime-project file, go to Project > Save Project As...')
            return

        project_path = os.path.dirname(project_file)
        project_data = self.window.project_data()

        indexer_data = project_data.get('sublime_indexer')
        cmakelists_path = None
        makefile_path = None
        if indexer_data:
            cmakelists_path = indexer_data.get('cmakelists_path')
            makefile_path = indexer_data.get('makefile_path')

        # If the user hasn't set a CMakeLists.txt or Makefile, ask them if they
        # want to, and setup the .sublime-project to do so. These can be used
        # to build a compilation database.
        if not indexer_data or not (makefile_path or cmakelists_path):
            if sublime.ok_cancel_dialog('SublimeIndexer can use either a CMakeLists.txt or Makefile to generate a more accurate index by using the exact commands used to compile to project. To enable this feature, in the .sublime-project file, under the \"sublime_indexer\" section, set either \"cmakelists_path\" or \"makefile_path\". If you would like to stop building the index, to edit the .sublime-project file, click \"OK\". To continue building the index, click \"Cancel\"'):
                if not indexer_data:
                    indexer_data = {"cmakelists_path": "", "makefile_path": ""}
                    project_data['sublime_indexer'] = indexer_data
                    self.window.set_project_data(project_data)

                return



        folders = project_data.get('folders')
        indexer_thread = threading.Thread(
            target=_from_empty_wrapper,
            args=(project_path, folders, _progress_callback, self.window,
                  cmakelists_path, makefile_path))
        indexer_thread.start()


class SideBarCleanIndexCommand(sublime_plugin.WindowCommand):

    def is_enabled(self):

        '''
        Return True if the window has a project file and persistent index file.
        '''

        project_file = self.window.project_file_name()

        if project_file:
            project_path = os.path.dirname(project_file)
            return cindexer.Indexer.has_persistent_index(project_path)

        return False

    def run(self):
        '''
        Delete the Indexer instance, and clean up the persistent index file.
        '''
        project_path = os.path.dirname(self.window.project_file_name())
        indexer = indexers[project_path]
        indexer.clean_persistent()
        indexers.pop(project_path)


class SideBarViewIssuesCommand(sublime_plugin.WindowCommand):

    def is_enabled(self):

        '''
        Return True if the window has a project file and persistent index file.
        '''

        project_file = self.window.project_file_name()

        if project_file:
            project_path = os.path.dirname(project_file)
            return cindexer.Indexer.has_persistent_index(project_path)

        return False

    def run(self):

        '''
        Display all diagnostics from a project in a quick panel, and select
        them when they are highlighted.
        '''

        project_path = os.path.dirname(self.window.project_file_name())
        indexer = indexers[project_path]
        diagnostics = indexer.get_diagnostics()

        if len(diagnostics) == 0:
            sublime.status_message('No issues in the project.')
            return

        diagnostic_strings = [
            _get_diagnostic_summary(diagnostic) for diagnostic in diagnostics
        ]

        # We capture the window, current view, and current selection so they
        # can be used by the on_done and on_highlight callbacks.
        window = self.window
        initial_view = window.active_view()
        initial_sel = initial_view.sel()

        def on_done(index):
            '''
            If the user cancelled the quick panel, jump back to the initial
            view.
            '''
            if index == -1:
                window.focus_view(initial_view)
                initial_view.sel().clear()
                for region in initial_sel:
                    initial_view.sel().add(region)

        def on_highlight(index):
            '''
            Select the diagnostic's region.
            '''
            diagnostic = diagnostics[index]
            diagnostic_location_string = ':'.join([
                diagnostic.location.file.name.decode('utf-8'),
                str(diagnostic.location.line),
                str(diagnostic.location.column)
                ])
            diagnostic_view = window.open_file(
                diagnostic_location_string,
                sublime.ENCODED_POSITION | sublime.TRANSIENT)
            _update_view_diagnostics(diagnostic_view, indexer)
            diagnostic_view.sel().clear()
            diagnostic_view.sel().add(
                diagnostic_view.word(diagnostic.location.offset))

        self.window.show_quick_panel(
            diagnostic_strings, on_done, sublime.MONOSPACE_FONT,
            on_highlight=on_highlight)


class OpenDefinitionCommand(sublime_plugin.TextCommand):

    def is_enabled(self):

        '''
        Return True if the file has been indexed.
        '''

        project_file = self.view.window().project_file_name()

        if project_file:
            project_path = os.path.dirname(project_file)
            indexer = indexers.get(project_path)
            if indexer:
                return indexer.indexed(self.view.file_name())

        return False

    def run(self, edit):

        '''
        Open and select the definition found by the Indexer instance.
        '''

        if len(self.view.sel()) != 1:
            sublime.error_message('The open definition command requires a single selection')
            return

        indexer = indexers[
            os.path.dirname(self.view.window().project_file_name())
        ]
        # Use the first cursor location.
        offset = self.view.sel()[0].b
        cindexer_file = cindexer.File.from_name(indexer, self.view.file_name())
        source_location = cindexer.SourceLocation.from_offset(
            indexer, cindexer_file, offset)
        def_cursor = indexer.get_definition(source_location)

        if not def_cursor:
            sublime.status_message('No definition found in the index.')
            return

        def_location_string = ':'.join([
            def_cursor.location.file.name.decode('utf-8'),
            str(def_cursor.location.line),
            str(def_cursor.location.column)
            ])
        def_view = self.view.window().open_file(
            def_location_string, sublime.ENCODED_POSITION | sublime.TRANSIENT)
        def_view.sel().clear()
        def_view.sel().add(def_view.word(def_cursor.location.offset))

class ListReferencesCommand(sublime_plugin.TextCommand):

    def is_enabled(self):

        '''
        Return True if the file has been indexed.
        '''

        project_file = self.view.window().project_file_name()

        if project_file:
            project_path = os.path.dirname(project_file)
            indexer = indexers.get(project_path)
            if indexer:
                return indexer.indexed(self.view.file_name())

        return False

    def run(self, edit):

        '''
        Display the references and enclosing definitions found by the Indexer
        instance.
        '''

        if len(self.view.sel()) != 1:
            sublime.error_message('The list references command requires a single selection')
            return

        indexer = indexers[
            os.path.dirname(self.view.window().project_file_name())
        ]
        # Use the first cursor location.
        offset = self.view.sel()[0].b
        cindexer_file = cindexer.File.from_name(indexer, self.view.file_name())
        source_location = cindexer.SourceLocation.from_offset(
            indexer, cindexer_file, offset)
        references = indexer.get_references(source_location)

        if len(references) < 1:
            sublime.status_message('No references found in the index.')
            return

        # Build up strings describing the referneces and enclosing definitions.
        reference_strings = []
        for cursor, enclosing_cursor in references:
            reference_string = ':'.join([
                os.path.basename(cursor.location.file.name.decode('utf-8')),
                str(cursor.location.line),
                str(cursor.location.column)
                ])

            if enclosing_cursor:
                reference_string += (' - ' +
                    enclosing_cursor.displayname.decode('utf-8'))

            reference_strings.append(reference_string)

        # We capture the window and current selection so they can be used by
        # the on_done and on_highlight callbacks.
        window = self.view.window()
        initial_sel = self.view.sel()

        def on_done(index):
            '''
            If the user cancelled the quick panel, jump back to the initial
            view.
            '''
            if index == -1:
                window.focus_view(self.view)
                self.view.sel().clear()
                for region in initial_sel:
                    self.view.sel().add(region)

        def on_highlight(index):
            '''
            Select the highlighted reference.
            '''
            # References is a list of tuples of references and enclosing
            # cursors.
            ref_cursor = references[index][0]
            ref_location_string = ':'.join([
                ref_cursor.location.file.name.decode('utf-8'),
                str(ref_cursor.location.line),
                str(ref_cursor.location.column)
                ])
            ref_view = window.open_file(
                ref_location_string,
                sublime.ENCODED_POSITION | sublime.TRANSIENT)
            ref_view.sel().clear()
            ref_view.sel().add(ref_view.word(ref_cursor.location.offset))

        self.view.window().show_quick_panel(
            reference_strings, on_done, sublime.MONOSPACE_FONT,
            on_highlight=on_highlight)


class ExpandSuperclassesCommand(sublime_plugin.TextCommand):

    def is_enabled(self):

        '''
        Return True if the file has been indexed.
        '''

        project_file = self.view.window().project_file_name()

        if project_file:
            project_path = os.path.dirname(project_file)
            indexer = indexers.get(project_path)
            if indexer:
                return indexer.indexed(self.view.file_name())

        return False

    def run(self, edit):

        '''
        Display the superclasses found by the Indexer instance.
        '''

        if len(self.view.sel()) != 1:
            sublime.error_message('The expand superclasses command requires a single selection')
            return

        indexer = indexers[
            os.path.dirname(self.view.window().project_file_name())
        ]
        # Use the first cursor.
        offset = self.view.sel()[0].b
        cindexer_file = cindexer.File.from_name(indexer, self.view.file_name())
        source_location = cindexer.SourceLocation.from_offset(
            indexer, cindexer_file, offset)
        superclasses = indexer.get_superclasses(source_location)

        if len(superclasses) < 1:
            sublime.status_message('No superclasses found in the index.')
            return

        # The indexer will return the superclasses in DFS order, so the
        # immediate superclasses are first. We want to display those at the
        # bottom of the menu, so we reverse the list.
        superclasses.reverse()

        superclass_strings = []
        for cursor in superclasses:
            superclass_string = ':'.join([
               os.path.basename(cursor.location.file.name.decode('utf-8')),
               str(cursor.location.line),
               str(cursor.location.column),
               cursor.displayname.decode('utf-8')
               ])
            superclass_strings.append(superclass_string)

        # We capture the window and current selection so they can be used by
        # the on_done and on_highlight callbacks.
        window = self.view.window()
        initial_sel = self.view.sel()

        def on_done(index):
            '''
            If the user cancelled the quick panel, jump back to the initial
            view.
            '''
            if index == -1:
                window.focus_view(self.view)
                self.view.sel().clear()
                for region in initial_sel:
                    self.view.sel().add(region)

        def on_highlight(index):
            '''
            Select the highlighted class.
            '''
            super_cursor = superclasses[index]
            super_location_string = ':'.join([
                super_cursor.location.file.name.decode('utf-8'),
                str(super_cursor.location.line),
                str(super_cursor.location.column)
                ])
            super_view = window.open_file(
                super_location_string,
                sublime.ENCODED_POSITION | sublime.TRANSIENT)
            super_view.sel().clear()
            super_view.sel().add(super_view.word(super_cursor.location.offset))

        # Because we reversed the list of superclasses, and want to highlight
        # the first immediate superclasses, pass in an argument for
        # initial_selection.
        self.view.window().show_quick_panel(
            superclass_strings, on_done, sublime.MONOSPACE_FONT,
            len(superclasses) - 1, on_highlight)


class ExpandSubclassesCommand(sublime_plugin.TextCommand):

    def is_enabled(self):

        '''
        Return True if the file has been indexed.
        '''

        project_file = self.view.window().project_file_name()

        if project_file:
            project_path = os.path.dirname(project_file)
            indexer = indexers.get(project_path)
            if indexer:
                return indexer.indexed(self.view.file_name())

        return False

    def run(self, edit):

        '''
        Display the subclasses returned by the indexer.
        '''

        if len(self.view.sel()) != 1:
            sublime.error_message('The expand subclasses command requires a single selection')
            return

        indexer = indexers[
            os.path.dirname(self.view.window().project_file_name())
        ]
        # Use the first cursor.
        offset = self.view.sel()[0].b
        cindexer_file = cindexer.File.from_name(indexer, self.view.file_name())
        source_location = cindexer.SourceLocation.from_offset(
            indexer, cindexer_file, offset)
        subclasses = indexer.get_subclasses(source_location)

        if len(subclasses) < 1:
            sublime.status_message('No subclasses found in the index.')
            return

        subclass_strings = []
        for cursor in subclasses:
            subclass_string = ':'.join([
               os.path.basename(cursor.location.file.name.decode('utf-8')),
               str(cursor.location.line),
               str(cursor.location.column),
               cursor.displayname.decode('utf-8')
               ])
            subclass_strings.append(subclass_string)

        # We capture the window and current selection so they can be used by
        # the on_done and on_highlight callbacks.
        window = self.view.window()
        initial_sel = self.view.sel()

        def on_done(index):
            '''
            If the user cancelled the quick panel, jump back to the initial
            view.
            '''
            if index == -1:
                window.focus_view(self.view)
                self.view.sel().clear()
                for region in initial_sel:
                    self.view.sel().add(region)

        def on_highlight(index):
            '''
            Select the highlighted class.
            '''
            sub_cursor = subclasses[index]
            sub_location_string = ':'.join([
                sub_cursor.location.file.name.decode('utf-8'),
                str(sub_cursor.location.line),
                str(sub_cursor.location.column)
                ])
            sub_view = window.open_file(
                sub_location_string,
                sublime.ENCODED_POSITION | sublime.TRANSIENT)
            sub_view.sel().clear()
            sub_view.sel().add(sub_view.word(sub_cursor.location.offset))

        self.view.window().show_quick_panel(
            subclass_strings, on_done, sublime.MONOSPACE_FONT,
            on_highlight=on_highlight)


class ExpandIncludesCommand(sublime_plugin.TextCommand):

    def is_enabled(self):

        '''
        Return True if the file has been indexed.
        '''

        project_file = self.view.window().project_file_name()

        if project_file:
            project_path = os.path.dirname(project_file)
            indexer = indexers.get(project_path)
            if indexer:
                return indexer.indexed(self.view.file_name())

        return False

    def run(self, edit):
        '''
        Display the includes found by the indexer.
        '''
        if len(self.view.sel()) != 1:
            sublime.error_message('The expand includes command requires a single selection')
            return

        indexer = indexers[
            os.path.dirname(self.view.window().project_file_name())
        ]
        cindexer_file = cindexer.File.from_name(indexer, self.view.file_name())
        includes = indexer.get_includes(cindexer_file)

        if len(includes) < 1:
            sublime.status_message('No includes found.')
            return

        # The indexer will return a list of tuples of includes and depths in
        # DFS order. We offset the file name by the depth.
        include_strings = []
        for include, depth in includes:
            include_string = (' ' * (depth - 1)) + include
            include_strings.append(include_string)

        # We capture the window and current selection so they can be used by
        # the on_done and on_highlight callbacks.
        window = self.view.window()

        def on_done(index):
            '''
            If the user cancelled the quick panel, jump back to the initial
            view.
            '''
            if index == -1:
                window.focus_view(self.view)

        def on_highlight(index):
            '''
            Open the highlighted file.
            '''
            include, unused = includes[index]
            include_view = window.open_file(include, sublime.TRANSIENT)

        self.view.window().show_quick_panel(
            include_strings, on_done, sublime.MONOSPACE_FONT,
            on_highlight=on_highlight)


class ListIncludersCommand(sublime_plugin.TextCommand):

    def is_enabled(self):

        '''
        Return True if the file has been indexed.
        '''

        project_file = self.view.window().project_file_name()

        if project_file:
            project_path = os.path.dirname(project_file)
            indexer = indexers.get(project_path)
            if indexer:
                return indexer.indexed(self.view.file_name())

        return False

    def run(self, edit):

        '''
        Display the includers found by the indexer.
        '''

        if len(self.view.sel()) != 1:
            sublime.error_message('The list includers command requires a single selection')
            return

        indexer = indexers[
            os.path.dirname(self.view.window().project_file_name())
        ]
        cindexer_file = cindexer.File.from_name(indexer, self.view.file_name())
        includers = indexer.get_includers(cindexer_file)

        if len(includers) < 1:
            sublime.status_message('No includers found in the index.')
            return

        # The indexer will return a list of tuples of includers and depths in
        # DFS order. We offset the file name by the depth.
        includer_strings = []
        for source, depth in includers:
            includer_string = (' ' * (depth - 1)) + source
            includer_strings.append(includer_string)

        # We capture the window and current selection so they can be used by
        # the on_done and on_highlight callbacks.
        window = self.view.window()

        def on_done(index):
            '''
            If the user cancelled the quick panel, jump back to the initial
            view.
            '''
            if index == -1:
                window.focus_view(self.view)

        def on_highlight(index):
            '''
            Open the highlighted file.
            '''
            source, unused = includers[index]
            include_view = window.open_file(source, sublime.TRANSIENT)

        self.view.window().show_quick_panel(
            includer_strings, on_done, sublime.MONOSPACE_FONT,
            on_highlight=on_highlight)


class ViewIssuesCommand(sublime_plugin.TextCommand):

    def is_enabled(self):

        '''
        Return True if the file has been indexed.
        '''

        project_file = self.view.window().project_file_name()

        if project_file:
            project_path = os.path.dirname(project_file)
            indexer = indexers.get(project_path)
            if indexer:
                return indexer.indexed(self.view.file_name())

        return False

    def run(self, edit):

        '''
        Display the issues for the file returned by the indexer.
        '''

        project_path = os.path.dirname(self.view.window().project_file_name())
        indexer = indexers[project_path]
        cindexer_file = cindexer.File.from_name(indexer, self.view.file_name())
        diagnostics = indexer.get_diagnostics(cindexer_file)

        if len(diagnostics) == 0:
            sublime.status_message('No issues in the file.')
            return

        diagnostic_strings = [
            _get_diagnostic_summary(diagnostic) for diagnostic in diagnostics
        ]

        # We capture the window and current selection so they can be used by
        # the on_done and on_highlight callbacks.
        window = self.view.window()
        initial_sel = self.view.sel()

        def on_done(index):
            '''
            If the user cancelled the quick panel, jump back to the initial
            view.
            '''
            if index == -1:
                window.focus_view(self.view)
                self.view.sel().clear()
                for region in initial_sel:
                    self.view.sel().add(region)

        def on_highlight(index):
            '''
            Open and select the highlighted diagnostic.
            '''
            diagnostic = diagnostics[index]
            diagnostic_location_string = ':'.join([
                diagnostic.location.file.name.decode('utf-8'),
                str(diagnostic.location.line),
                str(diagnostic.location.column)
                ])
            diagnostic_view = window.open_file(
                diagnostic_location_string,
                sublime.ENCODED_POSITION | sublime.TRANSIENT)
            _update_view_diagnostics(diagnostic_view, indexer)
            diagnostic_view.sel().clear()
            diagnostic_view.sel().add(
                diagnostic_view.word(diagnostic.location.offset))

        window.show_quick_panel(
            diagnostic_strings, on_done, sublime.MONOSPACE_FONT,
            on_highlight=on_highlight)
