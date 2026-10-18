# Break Your Agent's Memory

Hands-on lab for the [un]prompted workshop "Break Your Agent's Memory".

Assistants with persistent memory and file tools share files with each other all the time.
This lab builds a small sandboxed assistant with a memory store, file read and write tools,
and a shared folder, seeds one poisoned document, and measures how far the infection travels,
hop by hop, across a chain of assistants. Then it adds defenses one at a time and re-measures
both the spread and the cost to normal work.

A control only counts if it cuts second-hop survival by at least half and normal work still
succeeds.

> Status: scoping. See [docs/SCOPE.md](docs/SCOPE.md).
