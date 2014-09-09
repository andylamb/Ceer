import os
import sys
import threading

import sublime
import sublime_plugin

MODULES_PATH = os.path.join(os.path.dirname(__file__), 'modules')

if MODULES_PATH not in sys.path:
    sys.path.append(MODULES_PATH)

import cindexer

if not cindexer.Config.loaded:
    LIBCLANG_PATH = os.path.join(os.path.dirname(__file__), 'lib')
    cindexer.Config.set_library_path(LIBCLANG_PATH)


indexers = {}
current_diagnostics = {}
current_completions = {}
severity_key = {
    0 : 'Ignored',
    1 : 'Note',
    2 : 'Warning',
    3 : 'Error',
    4 : 'Fatal'
}

def progress_callback(indexer_status, **kwargs):
    if indexer_status == cindexer.Indexer.IndexerStatus.PARSING:
        message = 'Parsing file ' + kwargs['path']
    elif indexer_status == cindexer.Indexer.IndexerStatus.INDEXING:
        message = 'Indexing file ' + kwargs['path']
    elif indexer_status == cindexer.Indexer.IndexerStatus.COMPLETED:
        message = 'Built index for ' + kwargs['project_path']

    sublime.set_timeout(sublime.status_message(message), 0)

def from_persistent_wrapper(project_path, progress_callback):
    indexer = cindexer.Indexer.from_persistent(project_path, progress_callback)
    indexers[project_path] = indexer

def from_empty_wrapper(project_path, progress_callback):
    indexer = cindexer.Indexer.from_empty(project_path, progress_callback)
    indexers[project_path] = indexer

def plugin_loaded():
    for window in sublime.windows():
        project_file = window.project_file_name()

        if project_file:
            project_path = os.path.dirname(window.project_file_name())
            if cindexer.Indexer.has_persistent_index(project_path):
                indexer_thread = threading.Thread(target=from_persistent_wrapper, args=(project_path, progress_callback))
                indexer_thread.start()

class SublimeIndexerListener(sublime_plugin.EventListener):

    def on_post_save(self, view):
        project_file = view.window().project_file_name()

        if project_file:
            project_path = os.path.dirname(project_file)
            indexer = indexers.get(project_path)
            if indexer:
                name = view.file_name()
                if indexer.indexed(name):
                    cindexer_file = cindexer.File.from_name(indexer, view.file_name())
                    cindexer_file = indexer.update_file(cindexer_file)
                else:
                    cindexer_file = indexer.add_file(name)

    #             view_diagnostics = []
    #             for diagnostic in indexer.get_diagnostics(cindexer_file):
    #                 regions = []
    #                 for diagnostic_range in diagnostic.ranges:
    #                     regions.append(sublime.Region(diagnostic_range.start.offset, diagnostic_range.end.offset))

    #                 if diagnostic.location.offset == view.size():
    #                     regions.append(sublime.Region(diagnostic.location.offset - 1, diagnostic.location.offset))
    #                 else:
    #                     regions.append(sublime.Region(diagnostic.location.offset, diagnostic.location.offset + 1))

    #                 view_diagnostics.append((regions, diagnostic))

    #             current_diagnostics[view.file_name()] = view_diagnostics

    #             all_regions = []
    #             for regions, unused in view_diagnostics:
    #                 all_regions.extend(regions)

    #             view.erase_regions('diagnostics')
    #             view.add_regions('diagnostics', all_regions, 'invalid', flags=sublime.PERSISTENT | sublime.DRAW_SQUIGGLY_UNDERLINE | sublime.DRAW_NO_FILL | sublime.DRAW_NO_OUTLINE)

    # def on_selection_modified(self, view):
    #     if len(view.sel()) == 1:
    #         offset = view.sel()[0].b
    #         view_diagnostics = current_diagnostics.get(view.file_name())
    #         if view_diagnostics:
    #             for regions, diagnostic in view_diagnostics:
    #                 contains = False
    #                 for region in regions:
    #                     if region.contains(offset):
    #                         contains = True
    #                         break

    #                 if contains:
    #                     summary = severity_key[diagnostic.severity] + ': ' + diagnostic.spelling.decode('utf-8')

    #                     if diagnostic.option:
    #                         summary += ' [' + diagnostic.option.decode('utf-8') + ']'

    #                     sublime.status_message(summary)
    #                     break

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
        project_file = self.window.project_file_name()

        if project_file:
            project_path = os.path.dirname(project_file)
            return not cindexer.Indexer.has_persistent_index(project_path)

        return True

    def run(self):
        project_file = self.window.project_file_name()

        if project_file is None:
            sublime.error_message('SublimeIndexer requries a .sublime-project file to know which files to add to the index. To create a .sublime-project file, go to Project > Save Project As...')
            return

        project_path = os.path.dirname(project_file)

        indexer_thread = threading.Thread(target=from_empty_wrapper, args=(project_path, progress_callback))
        indexer_thread.start()
        

class SideBarCleanIndexCommand(sublime_plugin.WindowCommand):

    def is_enabled(self):
        project_file = self.window.project_file_name()

        if project_file:
            project_path = os.path.dirname(project_file)
            return cindexer.Indexer.has_persistent_index(project_path)

        return False

    def run(self):
        project_path = os.path.dirname(self.window.project_file_name())
        indexer = indexers[project_path]
        indexer.clean_persistent()
        indexers.pop(project_path)


class OpenDefinitionCommand(sublime_plugin.TextCommand):

    def is_enabled(self):
        project_file = self.view.window().project_file_name()

        if project_file:
            project_path = os.path.dirname(project_file)
            return project_path in indexers.keys()

        return false

    def run(self, edit):
        if len(self.view.sel()) != 1:
            sublime.error_message('The open definition command requires a single selection')
            return

        indexer = indexers[os.path.dirname(self.view.window().project_file_name())]
        offset = self.view.sel()[0].b 
        cindexer_file = cindexer.File.from_name(indexer, self.view.file_name()) 
        source_location = cindexer.SourceLocation.from_offset(indexer, cindexer_file, offset)
        def_cursor = indexer.get_definition(source_location)

        if not def_cursor:
            sublime.status_message('No definition found in the index.')
            return

        def_location_string = ':'.join([
            def_cursor.location.file.name.decode('utf-8'),
            str(def_cursor.location.line),
            str(def_cursor.location.column)
            ])
        def_view = self.view.window().open_file(def_location_string, sublime.ENCODED_POSITION | sublime.TRANSIENT)
        def_view.sel().clear()
        def_view.sel().add(def_view.word(def_cursor.location.offset))

class ListReferencesCommand(sublime_plugin.TextCommand):

    def is_enabled(self):
        project_file = self.view.window().project_file_name()

        if project_file:
            project_path = os.path.dirname(project_file)
            return project_path in indexers.keys()

        return false

    def run(self, edit):
        if len(self.view.sel()) != 1:
            sublime.error_message('The list references command requires a single selection')
            return

        indexer = indexers[os.path.dirname(self.view.window().project_file_name())]
        offset = self.view.sel()[0].b 
        cindexer_file = cindexer.File.from_name(indexer, self.view.file_name()) 
        source_location = cindexer.SourceLocation.from_offset(indexer, cindexer_file, offset)
        references = indexer.get_references(source_location)

        if len(references) < 1:
            sublime.status_message('No references found in the index.')
            return

        reference_strings = []
        for cursor, enclosing_cursor in references:
            reference_string = ':'.join([
                os.path.basename(cursor.location.file.name.decode('utf-8')),
                str(cursor.location.line),
                str(cursor.location.column)
                ])

            if enclosing_cursor:
                reference_string += ' - ' + enclosing_cursor.displayname.decode('utf-8') 

            reference_strings.append(reference_string)

        def on_done(index):
            if index is not -1:
                ref_cursor = references[index][0]
                ref_location_string = ':'.join([
                    ref_cursor.location.file.name.decode('utf-8'),
                    str(ref_cursor.location.line),
                    str(ref_cursor.location.column)
                    ])
                ref_view = self.view.window().open_file(ref_location_string, sublime.ENCODED_POSITION | sublime.TRANSIENT)
                ref_view.sel().clear()
                ref_view.sel().add(ref_view.word(ref_cursor.location.offset))

        self.view.window().show_quick_panel(reference_strings, on_done, flags=sublime.MONOSPACE_FONT)

