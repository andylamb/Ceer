# Ceer

>
Ceer is a C and C++ plugin for Sublime Text that provides code intelligence across source files by continuously parsing and indexing a project. Because Ceer is actually starting to compiling the code, but stopping before code generation, it reflects the true state and structure of the program.

## Table of Contents
1. [Features](#features)
  * [Open Definition](#open-definition)

### Features

#### Open Definition

Right clicking any reference to a method, field, class, etc. and selecting the Open Definition command will jump to the definition of that reference, even if it is defined in another source file. Note that in C or C++ a definition is not the same as a declaration. A declaration must be present in each file where there is a reference, while there must only be a single definition across all source files.

##### Example

The `main.cpp` file contains a call to `Foo`'s method `some_method`, which is declared in `main.cpp` by including `Foo.h`, and defined in `Foo.cpp`.

<img src="https://raw.githubusercontent.com/andylamb/Ceer/master/img/get_definition_1.png?token=4143035__eyJzY29wZSI6IlJhd0Jsb2I6YW5keWxhbWIvQ2Vlci9tYXN0ZXIvaW1nL2dldF9kZWZpbml0aW9uXzEucG5nIiwiZXhwaXJlcyI6MTQxMjk5NTUyOX0%3D--3a26bbb1ec4a3055ef3400c92c184484bcdae3bf">

Right click with the cursor anywhere in on `some_method` to call Open Definition.

<img src="https://raw.githubusercontent.com/andylamb/Ceer/master/img/get_definition_2.png?token=4143035__eyJzY29wZSI6IlJhd0Jsb2I6YW5keWxhbWIvQ2Vlci9tYXN0ZXIvaW1nL2dldF9kZWZpbml0aW9uXzIucG5nIiwiZXhwaXJlcyI6MTQxMzAwNDMzMH0%3D--f7dca5a81b23e277524a5619fb37ba0770d81f6e">

Open Definition will open `Foo.cpp` and highlight the `some_method` definition.

<img src="https://raw.githubusercontent.com/andylamb/Ceer/master/img/get_definition_3.png?token=4143035__eyJzY29wZSI6IlJhd0Jsb2I6YW5keWxhbWIvQ2Vlci9tYXN0ZXIvaW1nL2dldF9kZWZpbml0aW9uXzMucG5nIiwiZXhwaXJlcyI6MTQxMzAwNDQ3M30%3D--290b920ea98492299e88afd945b51a896a5260b6">
