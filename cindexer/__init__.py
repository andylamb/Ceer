'''
The only module that should be used is cindexerapi. The classes exported are:

ClassProperty -- Allows properties on class objects, for internal use.
Config -- An interface to cindex.Config, must use to set the libclang.dylib
path
File -- An interface to cindex.File.
SourceLocation -- An interface to cindex.SourceLocation
Indexer -- The main class of the module, most operations will run through an
instance of this class
'''
from cindexer.cindexerapi import *
