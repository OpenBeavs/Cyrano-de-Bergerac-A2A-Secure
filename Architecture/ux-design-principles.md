# UX Design Principles

## Announce Before You Act

When an operation takes perceptible time, tell the user what is happening before it starts — not after it finishes, and not in silence while they wonder if something is broken.

This applies to every interface: CLI output, web UI loading states, API progress callbacks, agent status messages. The principle is the same regardless of medium. A user staring at a blank screen for ten seconds will assume something is wrong. A user who sees "Loading Cyrano ..." understands immediately that the system is working and what it's waiting on.

The announcement should name the specific thing being done. "Loading..." is better than silence. "Loading Cyrano..." is better than "Loading..." because it tells the user *what* is slow, which is information they can act on (or at least understand). If the operation can fail, follow the announcement with a clear success or failure indicator.

This is not about verbose logging. Most internal operations are fast enough that announcing them would be noise. The rule applies when the delay is long enough that a user would notice — roughly anything over one second.

## Errors Must Be Unmissable

When something fails, the failure must be visually distinct from normal output. A single-line error message buried in a stream of status text is effectively invisible.

Scale the visibility to the severity. A warning can be a line of text. A fatal error that prevents the system from starting should be impossible to scroll past — use visual weight (borders, whitespace, capitalization) to make it stand out. Point the user to where they can find details (a log file, a diagnostic command).

## Surface Results, Not Machinery

The user's console is not a debugging terminal. Status messages, framework warnings, internal handshake details, and library chatter are valuable to a developer diagnosing a problem — but they are noise to a user operating the system. Route them to a log file. Show the user only what they need to act on: what started, whether it succeeded, and what to do next.

This is a filtering problem, not a suppression problem. The information still exists — in a log, available on demand. The principle is about choosing the right audience for each piece of output. The console is for the operator. The log is for the debugger. When these two audiences see the same stream, neither is well served.
