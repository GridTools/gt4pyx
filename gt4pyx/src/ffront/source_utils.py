# GT4Py Project - GridTools Framework
#
# Copyright (c) 2014-2021, ETH Zurich
# All rights reserved.
#
# This file is part of the GT4Py project and the GridTools framework.
# GT4Py is free software: you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or any later
# version. See the LICENSE.txt file at the top-level directory of this
# distribution for a copy of the license or check <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import functools
import inspect
import pathlib
import symtable
import textwrap
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, Union, cast

from eve import extended_typing as xtyping
from functional import common
from functional.ffront import fbuiltins


MISSING_FILENAME = "<string>"


def make_source_definition_from_function(func: Callable) -> SourceDefinition:
    try:
        filename = str(pathlib.Path(inspect.getabsfile(func)).resolve()) or MISSING_FILENAME
        source = textwrap.dedent(inspect.getsource(func))
        starting_line = (
            inspect.getsourcelines(func)[1] if not filename.endswith(MISSING_FILENAME) else 1
        )
    except OSError as err:
        if filename.endswith(MISSING_FILENAME):
            message = "Can not create field operator from a function that is not in a source file!"
        else:
            message = f"Can not get source code of passed function ({func})"
        raise ValueError(message) from err

    return SourceDefinition(source, filename, starting_line)


def make_captured_vars_from_function(func: Callable) -> CapturedVars:
    (nonlocals, globals, inspect_builtins, inspect_unbound) = inspect.getclosurevars(  # noqa: A001
        func
    )
    # python builtins returned by getclosurevars() are not ffront.builtins
    unbound = set(inspect_builtins.keys()) | inspect_unbound
    builtins = unbound & set(fbuiltins.ALL_BUILTIN_NAMES)
    unbound -= builtins
    annotations = xtyping.get_type_hints(func)

    return CapturedVars(dict(nonlocals), dict(globals), dict(annotations), builtins, unbound)


def make_symbol_names_from_source(source: str, filename: str = MISSING_FILENAME) -> SymbolNames:
    try:
        mod_st = symtable.symtable(source, filename, "exec")
    except SyntaxError as err:
        raise common.GTValueError(
            f"Unexpected error when parsing provided source code (\n{source}\n)"
        ) from err

    assert mod_st.get_type() == "module"
    if len(children := mod_st.get_children()) != 1:
        raise common.GTValueError(
            f"Sources with multiple function definitions are not yet supported (\n{source}\n)"
        )

    assert children[0].get_type() == "function"
    func_st: symtable.Function = cast(symtable.Function, children[0])

    param_names: set[str] = set()
    imported_names: set[str] = set()
    local_names: set[str] = set()
    for name in func_st.get_locals():
        if (s := func_st.lookup(name)).is_imported():
            imported_names.add(name)
        elif s.is_parameter:
            param_names.add(name)
        else:
            local_names.add(name)

    # symtable returns regular free (or non-local) variables in 'get_frees()' and
    # the free variables introduced with the 'nonlocal' statement in 'get_nonlocals()'
    nonlocal_names = set(func_st.get_frees()) | set(func_st.get_nonlocals())  # type: ignore[attr-defined]
    global_names = set(func_st.get_globals())

    return SymbolNames(
        params=param_names,
        locals=local_names,
        imported=imported_names,
        nonlocals=nonlocal_names,
        globals=global_names,
    )


@dataclass(frozen=True)
class SourceDefinition:
    """
    A GT4Py source code definition encoded as a string.

    It can be created from an actual function object using :meth:`from_function()`.
    It also supports unpacking.


    Examples
    --------
    >>> def foo(a):
    ...     return a
    >>> src_def = SourceDefinition.from_function(foo)
    >>> print(src_def)
    SourceDefinition(source='def foo(a):... starting_line=1)

    >>> source, filename, starting_line = src_def
    >>> print(source)
    def foo(a):
        return a
    ...
    """

    source: str
    filename: str = MISSING_FILENAME
    starting_line: int = 1

    def __iter__(self) -> Iterator:
        yield self.source
        yield self.filename
        yield self.starting_line

    from_function = staticmethod(make_source_definition_from_function)


@dataclass(frozen=True)
class CapturedVars:
    """
    Mappings from external names used in a function to the actual values.

    It can be created from an actual Python function object using
    :meth:`from_function()`. It also supports unpacking.

    .. note::
        To avoid a name conflict with :class:`inspect.ClosureVars` we use a
        different name here.
    """

    nonlocals: dict[str, Any]
    globals: dict[str, Any]  # noqa: A003  # shadowing a python builtin
    annotations: dict[str, Any]
    builtins: set[str]
    unbound: set[str]

    def __iter__(self) -> Iterator[Union[dict[str, Any], set[str]]]:
        yield self.nonlocals
        yield self.globals
        yield self.annotations
        yield self.builtins
        yield self.unbound

    from_function = staticmethod(make_captured_vars_from_function)


@dataclass(frozen=True)
class SymbolNames:
    """
    Collection of symbol names used in a function classified by kind.

    It can be created directly from source code using :meth:`from_source()`.
    It also supports unpacking.
    """

    params: set[str]
    locals: set[str]  # noqa: A003  # shadowing a python builtin
    imported: set[str]
    nonlocals: set[str]
    globals: set[str]  # noqa: A003  # shadowing a python builtin

    @functools.cached_property
    def all_locals(self) -> set[str]:
        return self.params | self.locals | self.imported

    def __iter__(self) -> Iterator[set[str]]:
        yield self.params
        yield self.locals
        yield self.imported
        yield self.nonlocals
        yield self.globals

    from_source = staticmethod(make_symbol_names_from_source)
