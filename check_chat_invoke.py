import inspect
from dify_plugin.invocations.app.chat import ChatAppInvocation
print("File:", inspect.getfile(ChatAppInvocation))
print("---")
with open(inspect.getfile(ChatAppInvocation)) as f:
    for i, line in enumerate(f.readlines()[20:40], start=21):
        print(f"{i}: {line}", end="")
