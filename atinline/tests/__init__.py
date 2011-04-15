
from atinline import inline

running_total = 0
@inline
def add_to_running_total(x):
    global running_total
    running_total += x
    return running_total

