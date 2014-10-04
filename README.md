# Ceer

>
Ceer is a C and C++ plugin for Sublime Text that provides code intelligence across source files by continuously parsing and indexing a project. Because Ceer is actually starting to compiling the code, but stopping before code generation, it reflects the true state and structure of the program.

## Table of Contents
1. [Features](#features)
  * [Open Definition](#open-definition)
  * [List References](#list-references)

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

#### List References

The List References command can be called on any definition or reference, and will present list all references in menu. Highlighting a reference will navigate to its location in the project. 

##### Example

Call List References on `Baz`'s method `some_method`. Note that calling List References on any reference to `some_method` would be the same.

<img src="https://raw.githubusercontent.com/andylamb/Ceer/master/img/list_references1.png?token=4143035__eyJzY29wZSI6IlJhd0Jsb2I6YW5keWxhbWIvQ2Vlci9tYXN0ZXIvaW1nL2xpc3RfcmVmZXJlbmNlczEucG5nIiwiZXhwaXJlcyI6MTQxMzAwNjU4MH0%3D--ebae51c8c0629b57746236aafee80fab0445f01b">

The first reference found is in `main.cpp`. Here we can see that Ceer is able to infer the compile-time type of the expression `((Baz*)&myFoo)`. In fact, it should be able to perform type inference identical to a compiler for any valid expression.

<img src="https://raw.githubusercontent.com/andylamb/Ceer/master/img/list_references2.png?token=4143035__eyJzY29wZSI6IlJhd0Jsb2I6YW5keWxhbWIvQ2Vlci9tYXN0ZXIvaW1nL2xpc3RfcmVmZXJlbmNlczIucG5nIiwiZXhwaXJlcyI6MTQxMzAwNjc3Nn0%3D--a743c3d40d28474d44da1f10928304a1d8107804">

The second reference found is in `Baz`'s method `another_baz_method`.

<img src="https://raw.githubusercontent.com/andylamb/Ceer/master/img/list_references3.png?token=4143035__eyJzY29wZSI6IlJhd0Jsb2I6YW5keWxhbWIvQ2Vlci9tYXN0ZXIvaW1nL2xpc3RfcmVmZXJlbmNlczMucG5nIiwiZXhwaXJlcyI6MTQxMzAwNzA1Nn0%3D--82676b5d52d7970b3ac99eaf3cc93def6cacc637">
