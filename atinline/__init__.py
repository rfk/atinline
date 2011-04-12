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
__ver_patch__ = 0
__ver_sub__ = ""
__version__ = "%d.%d.%d%s" % (__ver_major__,__ver_minor__,__ver_patch__,__ver_sub__)


import sys
import new
import timeit
from byteplay import *


def inline(func):
    """Decorator to declare a function inline.

    Functions decorated with @inline will forcibly insert themselves into
    the bytecode of any function that calls them.  Like a parasite.
    """
    #  The magic is all done by the _inlineme helper function.
    #  We add a little loader at the top of func's bytecod that
    #  calls _inlineme with the appropriate arguments.
    c = Code.from_code(func.func_code)
    c.code.insert(0,(LOAD_CONST,_inlineme))
    c.code.insert(1,(LOAD_CONST,func))
    c.code.insert(2,(CALL_FUNCTION,1))
    c.code.insert(3,(POP_TOP,None))
    func.func_code = c.to_code()
    return func

def find_caller(depth):
    """Find the calling function at the specified depth.

    This function finds out who's calling it at the specified depth up
    the stack.  It returns a 3-tuple giving the calling frame, namespace,
    and name of the executed function within that namespace.

    If the caller can't be determined, the tuple is filled with Nones.
    """
    #  Find the calling frame and corresponding code object.
    frame = sys._getframe(depth+1)
    code = frame.f_code
    #  Get the calling byte code up to the current call site.
    new_code = new.code(0, code.co_nlocals,
                           code.co_stacksize, code.co_flags,
                           code.co_code[:frame.f_lasti+3], code.co_consts,
                           code.co_names, code.co_varnames,
                           code.co_filename, "",
                           frame.f_lineno, code.co_lnotab)
    c = Code.from_code(new_code)
    #  Skip over the CALL_FUNCTION bytecode, as well as the bytecodes
    #  loading any arguments, to find the instruction loading the func.
    numargs = c.code[-1][1]
    idx = -2
    while numargs > 0:
        #  This little loop is to handle calls like func(x.y.z) where
        #  there are multiple instructions used to load a single argument.
        #  We keep moving backwards until the stack-effect is to push
        #  a single item.
        (npop,npush) = getse(*c.code[idx])
        while npush - npop != 1:
            idx -= 1
            npop += getse(*c.code[idx])[0]
            npush += getse(*c.code[idx])[1]
        numargs -= 1
        idx -=1
    #  Now branch based on how the function was loaded.
    #  Currently only load-by-name is supported.
    if c.code[idx][0] in (LOAD_GLOBAL,LOAD_NAME,):
        return (frame,frame.f_globals,c.code[idx][1])
    if c.code[idx][0] in (LOAD_FAST,):
        return (frame,frame.f_locals,c.code[idx][1])
    return (None,None,None)


def _inlineme(func):
    """Helper function to inline code at its call site.

    This function inlines the code of the given function at its call site.
    It expects to func the actual function executing at depth 2 up the stack,
    and will monkey-patch the function executing at depth 3.

    It exits without making any changes if it can't prove that the function
    is being called correctly.
    """
    #  The function to be inlined should be executing at depth 2.
    #  If we can't find it, bail out.
    (frame,namespace,name) = find_caller(2)
    if name is None:
        return
    try:
        if namespace[name] != func:
            return
    except KeyError:
        return
    #  The function to be inlined into should be executing at depth 3.
    #  If it's not there or not a function, bail out.
    (_,namespace,name) = find_caller(3)
    if name is None:
        return
    try:
        caller = namespace[name]
    except KeyError:
        return
    if type(caller) != type(_inlineme):
        return
    #  Verify that the code we're inlining is the code being executed.
    code = caller.func_code
    if frame.f_code != code:
        return
    #  Grab the bytecode up to call of target function.
    new_code = new.code(0, code.co_nlocals,
                           code.co_stacksize, code.co_flags,
                           code.co_code[:frame.f_lasti+3], code.co_consts,
                           code.co_names, code.co_varnames,
                           code.co_filename, "",
                           frame.f_lineno, code.co_lnotab)
    c = Code.from_code(new_code)
    c.code[:] = [op for op in c.code if op[0] != SetLineno]
    #  Double-check that we're inlining at the site of a CALL_FUNCTION.
    if c.code[-1][0] != CALL_FUNCTION:
        return
    callsite = len(c.code)
    #  Skip backwards over loading of arguments, to find the site where
    #  the target function is loaded.
    numargs = c.code[-1][1]
    idx = -2
    while numargs > 0:
        (npop,npush) = getse(*c.code[idx])
        while npush - npop != 1:
            idx -= 1
            npop += getse(*c.code[idx])[0]
            npush += getse(*c.code[idx])[1]
        numargs -= 1
        idx -=1
    loadsite = len(c.code) + idx + 1
    #  Give new names to the locals in the source bytecode
    source_code = Code.from_code(func.func_code)
    dest_code = Code.from_code(caller.func_code)
    name_map = _rename_local_vars(source_code)
    #  Remove any setlineno ops from the source bytecode.
    #  Also remove 4-code stub that calls into _inlineme.
    new_code = [c for c in source_code.code if c[0] != SetLineno]
    source_code.code[:] = new_code[4:]
    new_code = [c for c in dest_code.code if c[0] != SetLineno]
    dest_code.code[:] = new_code
    #  Pop the function arguments directly from the stack.
    #  Keyword args are currently not supported.
    numargs = dest_code.code[callsite][1] & 0xFF
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
        del dest_code.code[loadsite]
    #  An simple optimisation pass would be awsome here, the above
    #  generates a lot of redundant loads, stores and jumps.
    caller.func_code = dest_code.to_code()
 

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


def _rename_local_vars(code):
    """Rename the local variables in the given code to new unique names.

    This basically just changes LOAD_FAST, STORE_FAST and DELETE_FAST targets
    with new names, and helpfully returns a dictionary mapping old names to
    new names.
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
    return name_map

