# Ceer

>
Ceer is a C and C++ plugin for Sublime Text that provides code intelligence across source files by continuously parsing and indexing a project. Because Ceer is actually starting to compiling the code, but stopping before code generation, it reflects the true state and structure of the program.

## Table of Contents
1. [Features](#features)
  * [Open Definition](#open-definition)
  * [List References](#list-references)
  * [Expand Superclasses](#expand-superclasses)
  * [Expand Subclasses](#expand-subclasses)
  * [Expand Includes](#expand-includes)
  * [List Includers](#list-includers)

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

The List References command can be called on any definition or reference, and will list all references in a menu. Highlighting a reference will navigate to its location in the project. 

##### Example

Call List References on `Baz`'s method `some_method`. Note that calling List References on any reference to `some_method` would be the same.

<img src="https://raw.githubusercontent.com/andylamb/Ceer/master/img/list_references1.png?token=4143035__eyJzY29wZSI6IlJhd0Jsb2I6YW5keWxhbWIvQ2Vlci9tYXN0ZXIvaW1nL2xpc3RfcmVmZXJlbmNlczEucG5nIiwiZXhwaXJlcyI6MTQxMzAwNjU4MH0%3D--ebae51c8c0629b57746236aafee80fab0445f01b">

The first reference found is in `main.cpp`. Here we can see that Ceer is able to infer the compile-time type of the expression `((Baz*)&myFoo)`. In fact, it should be able to perform type inference identical to a compiler for any valid expression.

<img src="https://raw.githubusercontent.com/andylamb/Ceer/master/img/list_references2.png?token=4143035__eyJzY29wZSI6IlJhd0Jsb2I6YW5keWxhbWIvQ2Vlci9tYXN0ZXIvaW1nL2xpc3RfcmVmZXJlbmNlczIucG5nIiwiZXhwaXJlcyI6MTQxMzAwNjc3Nn0%3D--a743c3d40d28474d44da1f10928304a1d8107804">

The second reference found is in `Baz`'s method `another_baz_method`.

<img src="https://raw.githubusercontent.com/andylamb/Ceer/master/img/list_references3.png?token=4143035__eyJzY29wZSI6IlJhd0Jsb2I6YW5keWxhbWIvQ2Vlci9tYXN0ZXIvaW1nL2xpc3RfcmVmZXJlbmNlczMucG5nIiwiZXhwaXJlcyI6MTQxMzAwNzA1Nn0%3D--82676b5d52d7970b3ac99eaf3cc93def6cacc637">

#### Expand Superclasses

The Expand Superclasses command can be called on any definition or reference for a C++ class, and displays inheritance hierarchy of the class in a menu. 

##### Example 

Call Expand Superclasses on `Foo`. As with List References, we could also call Expand Superclasses on a reference to `Foo`.

<img src="https://github.com/andylamb/Ceer/raw/master/img/expand_superclasses1.png">

`Foo` inherits from `Base`, which doesn't inherit from any other class.

<img src="https://raw.githubusercontent.com/andylamb/Ceer/master/img/expand_superclasses2.png?token=4143035__eyJzY29wZSI6IlJhd0Jsb2I6YW5keWxhbWIvQ2Vlci9tYXN0ZXIvaW1nL2V4cGFuZF9zdXBlcmNsYXNzZXMyLnBuZyIsImV4cGlyZXMiOjE0MTMwNDU2MjZ9--b9fd78ed07963ba3c587d4e853f321e45c78c04f">

`Baz` has a more interesting inheritance structure.

<img src="https://raw.githubusercontent.com/andylamb/Ceer/master/img/expand_superclasses3.png?token=4143035__eyJzY29wZSI6IlJhd0Jsb2I6YW5keWxhbWIvQ2Vlci9tYXN0ZXIvaW1nL2V4cGFuZF9zdXBlcmNsYXNzZXMzLnBuZyIsImV4cGlyZXMiOjE0MTMwNDU2NDB9--47ddb9d7e2da4864ddb9f1e5fc6e6626663fa0e1">

`Baz` inherits directly from both `Foo` and `Bar`, both of which inherit from `Base`. Note that in the menu, the superclasses are displayed in breath first search order, and are indented by their level in the inheritance hierarchy.

<img src="https://raw.githubusercontent.com/andylamb/Ceer/master/img/expand_superclasses4.png?token=4143035__eyJzY29wZSI6IlJhd0Jsb2I6YW5keWxhbWIvQ2Vlci9tYXN0ZXIvaW1nL2V4cGFuZF9zdXBlcmNsYXNzZXM0LnBuZyIsImV4cGlyZXMiOjE0MTMwNDU2NTR9--087d1c34a372628f6335955859403480f56d41f7">

#### Expand Subclasses

Naturally, the Expand Subclasses command behaves the same as the Expand Superclasses command, but displays classes that inherit from the selected class.

##### Example

Call Expand Subclasses on `Base`.

<img src="https://raw.githubusercontent.com/andylamb/Ceer/master/img/expand_subclasses1.png?token=4143035__eyJzY29wZSI6IlJhd0Jsb2I6YW5keWxhbWIvQ2Vlci9tYXN0ZXIvaW1nL2V4cGFuZF9zdWJjbGFzc2VzMS5wbmciLCJleHBpcmVzIjoxNDEzMDQ2MzQ1fQ%3D%3D--e025200ea1db926fdf21a6e729d8d4f16d1894af">

This diagram looks similar to when we called Expand Superclasses on `Baz`, but is reversed, because we are looking from the top of the inheritance hierarchy down, instead of from the bottom up.

<img src="https://github.com/andylamb/Ceer/blob/master/img/expand_subclasses2.png">

#### Expand Includes

Right clicking anywhere in a file and selecting the Expand Includes command will show all the files that file is including, whether directly or indirectly. The includes are ordered by depth first search, and indented based on how indirect the inclusion is.

##### Example

Call Expand Include on `Baz.h`.

<img src="https://raw.githubusercontent.com/andylamb/Ceer/master/img/expand_includes1.png?token=4143035__eyJzY29wZSI6IlJhd0Jsb2I6YW5keWxhbWIvQ2Vlci9tYXN0ZXIvaW1nL2V4cGFuZF9pbmNsdWRlczEucG5nIiwiZXhwaXJlcyI6MTQxMzA0OTMxOH0%3D--6e0553d6b1a2b4f570f6c00abcfc5d1c3f15ca17">

`Baz.h` includes `Foo.h` and `Bar.h`, which both include `Base.h`. Note that `Base.h` is indented because it is not directly included in `Baz.h`.

<img src="https://raw.githubusercontent.com/andylamb/Ceer/master/img/expand_includes2.png?token=4143035__eyJzY29wZSI6IlJhd0Jsb2I6YW5keWxhbWIvQ2Vlci9tYXN0ZXIvaW1nL2V4cGFuZF9pbmNsdWRlczIucG5nIiwiZXhwaXJlcyI6MTQxMzA0OTM0OH0%3D--fbdbf2a4f64220ef62905dd83324f923ef1e80e7">

#### List Includers

The List Includers displays a menu of all the files that are including the file the command is called on. Similarly to the Expand Includes command, the files are ordered by depth first search, and indented based on indirectness.

#### Example

Call List Includers on `Foo.h`.

<img src="https://raw.githubusercontent.com/andylamb/Ceer/master/img/list_includers1.png?token=4143035__eyJzY29wZSI6IlJhd0Jsb2I6YW5keWxhbWIvQ2Vlci9tYXN0ZXIvaW1nL2xpc3RfaW5jbHVkZXJzMS5wbmciLCJleHBpcmVzIjoxNDEzMDUwMTc4fQ%3D%3D--127a108dcea624649591620dc98182635d07c707">

`Baz.h`, `Foo.cpp`, and `main.cpp` all directly include `Foo.h`. `Baz.cpp` indirectly includes `Foo.h`, because it includes `Baz.h`.

<img src="https://raw.githubusercontent.com/andylamb/Ceer/master/img/list_includers2.png?token=4143035__eyJzY29wZSI6IlJhd0Jsb2I6YW5keWxhbWIvQ2Vlci9tYXN0ZXIvaW1nL2xpc3RfaW5jbHVkZXJzMi5wbmciLCJleHBpcmVzIjoxNDEzMDUwMjAxfQ%3D%3D--5544c74950f31a41f7a09d621a971f1207119923">
