"""
atinline:  forcibly inline python functions to their call site
==============================================================


This is a Python hack to let you specify functions as "inline" in much the
same way you'd do in C.  You save the cost of a function call by inlining
the code of the function right at the call site.  Of course, being Python,
the inlining is done at runtime.

WARNING:  Don't use this in any real code.  Seriously.  It's just a fun hack.

Now then, suppose you have some code like this::

    def calculate(x):
        return 3*x*x - 2*x + (1/x)

    def aggregate(items):
        total = 0
        for item in items:
            total += calculate(item)
        return total

This code pays the overhead of a function call for every item in the collection.
You can get substantial speedups by inlining the calculate function like so::

    def aggregate(items):
        total = 0
        for x in items:
            total += 3*x*x - 2*x + (1/x)
        return total

But now you're paying the costs in terms of code quality and re-use.  To get
the best of both worlds simply declare that the calculate function should be
inlined::

    from atinline import inline

    @inline
    def calculate(x):
        return 3*x*x - 2*x + (1/x)

    def aggregate(items):
        total = 0
        for item in items:
            total += calculate(item)
        return total

Now the first time the aggregate() function runs, it will detect that the
calculate() function should be inlined, make the necessary bytecode hacks
to do so, then continue on its way.  Any subsequent calls to aggregate()
will avoid the overhead of many function calls.

Currently only plain calls of top-level functions are supported; things won't
work correctly if you try to inline methods, functions looked up in a dict,
or other stuff like this.  It also doesn't work with keyword arguments.
These limitations might go away in future.

The heavy-lifting of bytecode regeneration is done by the fantastic "byteplay"
module, which is atinline's only dependency.

"""

__ver_major__ = 0
__ver_minor__ = 1
__ver_patch__ = 1
__ver_sub__ = ""
__version__ = "%d.%d.%d%s" % (__ver_major__,__ver_minor__,__ver_patch__,__ver_sub__)


import sys
import new
import timeit
import dis
import weakref
from dis import HAVE_ARGUMENT, findlabels
from byteplay import *


def inline(func):
    """Decorator to declare a function inline.

    Functions decorated with @inline will forcibly insert themselves into
    the bytecode of any function that calls them.  Like a parasite.
    """
    #  The magic is all done by the _inlineme helper function.
    #  We add a little loader at the top of func's bytecode that
    #  calls _inlineme with the appropriate arguments.
    c = Code.from_code(func.func_code)
    c.code.insert(0,(LOAD_CONST,_inlineme))
    c.code.insert(1,(LOAD_CONST,func))
    c.code.insert(2,(CALL_FUNCTION,1))
    c.code.insert(3,(POP_TOP,None))
    func.func_code = c.to_code()
    return func


def make_code_from_frame(frame):
    """Make a Code object from the given frame.

    Returns a two-tuple giving the Code object, and the offset of the
    last instruction executed by the frame.
    """
    code = frame.f_code
    offset = i = 0
    while i < frame.f_lasti:
        offset += 1
        if ord(code.co_code[i]) < HAVE_ARGUMENT:
            i += 1
        else:
            i += 3
    assert i == frame.f_lasti
    for j in findlabels(code.co_code):
        if j <= frame.f_lasti:
            offset += 1
    c = Code.from_code(code)
    c.code[:] = [op for op in c.code if op[0] != SetLineno]
    assert c.code[offset][0] == ord(code.co_code[frame.f_lasti])
    return (c,offset)


def find_caller(depth):
    """Find the calling function at the specified depth.

    This function finds out who's calling it at the specified depth up
    the stack.  It returns a 3-tuple giving the calling frame, namespace,
    and name of the executed function within that namespace.

    If the caller can't be determined, the tuple is filled with Nones.
    """
    #  Find the calling frame and corresponding code object.
    frame = sys._getframe(depth+1)
    (c,callsite) = make_code_from_frame(frame)
    if c.code[callsite][0] not in (CALL_FUNCTION,):
        return (None,None,None)
    #  Skip over the CALL_FUNCTION bytecode, as well as the bytecodes
    #  loading any arguments, to find the instruction loading the func.
    numargs = c.code[callsite][1]
    loadsite = callsite - 1
    while numargs > 0:
        #  This little loop is to handle calls like func(x.y.z) where
        #  there are multiple instructions used to load a single argument.
        #  We keep moving backwards until the stack-effect is to push
        #  a single item.
        (npop,npush) = getse(*c.code[loadsite])
        while npush - npop != 1:
            loadsite -= 1
            npop += getse(*c.code[loadsite])[0]
            npush += getse(*c.code[loadsite])[1]
        numargs -= 1
        loadsite -= 1
    #  Now branch based on how the function was loaded.
    #  We support basic lookups, and attribute-based lookups.
    name = ""
    while c.code[loadsite][0] in (LOAD_ATTR,):
        name = "." + c.code[loadsite][1] + name
        loadsite -= 1
    if c.code[loadsite][0] in (LOAD_GLOBAL,LOAD_NAME,):
        return (frame,frame.f_globals,c.code[loadsite][1] + name)
    if c.code[loadsite][0] in (LOAD_FAST,LOAD_DEREF,):
        return (frame,frame.f_locals,c.code[loadsite][1] + name)
    return (None,None,None)



_ALREADY_INLINED = weakref.WeakKeyDictionary()


def _inlineme(func):
    """Helper function to inline code at its call site.

    This function inlines the code of the given function at its call site.
    It expects to func the actual function executing at depth 2 up the stack,
    and will monkey-patch the function executing at depth 3.

    It exits without making any changes if it can't prove that the function
    is being called correctly.
    """
    #  The function to be inlined into should be executing at depth 3.
    #  If it's not there or not a function, bail out.
    (_,namespace,name) = find_caller(3)
    if name is None:
        return
    try:
        caller = lookup_in_namespace(name,namespace)
    except (KeyError,AttributeError):
        return
    if type(caller) != type(_inlineme):
        return
    #  The function to be inlined should be executing at depth 2.
    #  If we can't find it, bail out.
    #  If we already failed to inlne it, bail out.
    (frame,namespace,name) = find_caller(2)
    if name is None:
        return
    if frame.f_lasti in _ALREADY_INLINED.get(caller,[]):
        return
    try:
        if lookup_in_namespace(name,namespace) != func:
            return
    except (KeyError,AttributeError):
        return
    #  Verify that the code we're inlining is the code being executed.
    code = caller.func_code
    if frame.f_code != code:
        _ALREADY_INLINED.setdefault(caller,[]).append(frame.f_lasti)
        return
    #  Grab the bytecode for callsite of target function.
    (c,callsite) = make_code_from_frame(frame)
    #  Double-check that we're inlining at the site of a CALL_FUNCTION.
    if c.code[callsite][0] != CALL_FUNCTION:
        _ALREADY_INLINED.setdefault(caller,[]).append(frame.f_lasti)
        return
    #  Skip backwards over loading of arguments, to find the site where
    #  the target function is loaded.
    numargs = c.code[callsite][1]
    loadsite_end = callsite - 1
    while numargs > 0:
        (npop,npush) = getse(*c.code[loadsite_end])
        while npush - npop != 1:
            loadsite_end -= 1
            npop += getse(*c.code[loadsite_end])[0]
            npush += getse(*c.code[loadsite_end])[1]
        numargs -= 1
    #    loadsite_end -=1
    loadsite_start = loadsite_end - 1
    while c.code[loadsite_start][0] in (LOAD_ATTR,):
        loadsite_start -= 1
    #  Give new names to the locals in the source bytecode
    source_code = Code.from_code(func.func_code)
    dest_code = Code.from_code(caller.func_code)
    try:
        name_map = _rename_local_vars(source_code,func)
    except ValueError:
        _ALREADY_INLINED.setdefault(caller,[]).append(frame.f_lasti)
        return
    #  Remove any setlineno ops from the source and dest bytecode.
    #  Also remove 4-code preamble that calls into _inlineme.
    new_code = [op for op in source_code.code if op[0] != SetLineno]
    source_code.code[:] = new_code[4:]
    new_code = [op for op in dest_code.code if op[0] != SetLineno]
    dest_code.code[:] = new_code
    #  Pop the function arguments directly from the stack.
    #  Keyword args are currently not supported.
    numargs = dest_code.code[callsite][1] & 0xFF
    if numargs != dest_code.code[callsite][1]:
        _ALREADY_INLINED.setdefault(caller,[]).append(frame.f_lasti)
        return
    for i in xrange(numargs):
        argname = func.func_code.co_varnames[i]
        source_code.code.insert(0,(STORE_FAST,name_map[argname]))
        #  Fill in any missing args from the function defaults
        numreqd = func.func_code.co_argcount
        for i in xrange(numargs,numreqd):
            argname = func.func_code.co_varnames[i]
            defidx = i - numreqd + len(func.func_defaults)
            defval = func.func_defaults[defidx]
            source_code.code.insert(0,(STORE_FAST,name_map[argname]))
            source_code.code.insert(0,(LOAD_CONST,defval))
        #  Munge the source bytecode to leave return value on stack,
        #  by replacing RETURN_VALUE with a jump-to-end.
        end = Label()
        source_code.code.append((end,None))
        for (i,(op,arg)) in enumerate(source_code.code):
            if op == RETURN_VALUE:
                source_code.code[i] = (JUMP_ABSOLUTE,end)
        #  Replace the callsite with the inlined code,
        #  and remove loading of original function.
        dest_code.code[callsite:callsite+1] = source_code.code
        del dest_code.code[loadsite_start:loadsite_end]
    #  An simple optimisation pass would be awsome here, the above
    #  generates a lot of redundant loads, stores and jumps.
    caller.func_code = dest_code.to_code()
    _ALREADY_INLINED.setdefault(caller,[]).append(frame.f_lasti)
 

def _ids():
    """Generator producing unique ids, for variable renaming"""
    i = 0
    while True:
        i += 1
        yield i 
_ids = _ids()


def new_name(name=None):
    """Generate a new unique variable name

    If the given name is not None, it is included in the generated name for
    ease of reference in e.g. tracebacks or bytecode inspection.
    """
    if name is None:
        return "_inlined_var%s" % (_ids.next(),)
    else:
        return "_inlined_var%s_%s" % (_ids.next(),name,)


def _rename_local_vars(code,func):
    """Rename the local variables in the given code to new unique names.

    This adjusts name references inside the given code so that they're
    valid no matter where the code is executed from.  The following surgery
    is performed:

        * local variables are simply renamed to something unique, and
          the mapping from old to new names is returned.
        * global variables are modified to explicit operations on the
          global dictionary of the provided function
        * closure variables or by-name lookups cause a ValueError
    """
    name_map = {}
    for nm in code.to_code().co_varnames:
        name_map[nm] = new_name(nm)
    for (i,(op,arg)) in enumerate(code.code):
        if op in (LOAD_FAST,STORE_FAST,DELETE_FAST):
            try:
                newarg = name_map[arg]
            except KeyError:
                newarg = new_name(arg)
                name_map[arg] = newarg
            code.code[i] = (op,newarg)
        elif op == LOAD_GLOBAL:
            code.code[i] = (BINARY_SUBSCR,None)
            code.code.insert(i, (LOAD_CONST,arg))
            code.code.insert(i, (LOAD_CONST,func.func_globals))
        elif op in (LOAD_DEREF,STORE_DEREF,LOAD_NAME,STORE_NAME,DELETE_NAME,):
            raise ValueError("can't modify name reference")
    return name_map


def lookup_in_namespace(name,namespace):
    """Resolve a dotted name into an object, using given namespace."""
    bits = name.split(".")
    obj = namespace[bits[0]]
    for attr in bits[1:]:
        obj = getattr(obj,attr)
    return obj

