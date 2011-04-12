
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

