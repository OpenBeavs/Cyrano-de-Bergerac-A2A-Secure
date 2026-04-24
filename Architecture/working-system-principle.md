# The Working System Principle

When building agentic systems, there is one rule that governs the entire development process: **you start with a working system on day one, and every change takes you from one working state to another.**

You never design an ambitious multi-agent architecture on paper and then spend days wiring it up before you can run it. You never write code that "doesn't work yet" with the expectation that it will come together later. That approach fails especially hard with agent systems, for reasons that are structural, not just philosophical:

- **Agents are non-deterministic.** An LLM-backed agent might handle the same input differently each time. You cannot reason about agent behavior purely on paper. You have to run the system to see what it actually does, and you have to run it early and often.

- **Integration failures surface at boundaries.** The hardest bugs in multi-agent systems live in the handoffs — message formats, protocol mismatches, context that gets lost between agents. These bugs are invisible until the agents are actually talking to each other. A working system forces those boundaries to exist from the start.

- **You can demo at any point.** A working system — even a trivially simple one — is always demonstrable. Stakeholders, collaborators, and your future self can see what the system does today, not what it will theoretically do someday.

- **Incremental changes are debuggable.** When you go from working state to working state, a failure means the last change broke something. When you go from nothing to a large non-working system, the failure could be anywhere.

This project follows that principle. The first working state was a single agent that could respond to a user. The next working state added a second agent behind the first. The next added the third. At no point was the system in a non-functional state waiting for future work to make it run. Each commit moved from working to working, with the architecture growing underneath.

That discipline is not optional for agentic systems. It is the method.
