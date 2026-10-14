# Plugging AI into your world: the Model Context Protocol (MCP)

*ENG 689 · Tutorial 13 · Dheemanth Joshi.* Written guide, shared before the talk. Example server: this repository.

## What it is

The Model Context Protocol (MCP) is an open standard for connecting AI applications to the systems where your work happens: a computing cluster, a lab database, a folder of instrument files, an email account. Anthropic introduced it in November 2024 and, in December 2025, donated it to the Agentic AI Foundation, part of the Linux Foundation, which Anthropic co-founded with Block and OpenAI. Claude, ChatGPT, VS Code, Cursor and many other applications support it.

Think of a standard plug, like USB-C. Whoever looks after a system builds one plug for it, called an *MCP server*; every application that supports MCP has a matching socket built in.

## Why it matters

An AI assistant on its own is disconnected. It can write a plausible job script for the Grace cluster, but it cannot know which software versions are installed today, which partitions exist, what your account is called or where your files are. It guesses, and you find the guesses when the job fails. MCP gives it a controlled way to look things up and act in your environment, so it works from facts.

For engineers outside computer science, the key point is that nobody else will build the plug for your world. Companies build plugs for email and calendars, not for your spectrometer files, CFD workflow or lab database. A server is a thin wrapper around commands and files you already use; inside, it can call Python, MATLAB, a legacy Fortran program or an instrument driver.

## Key ideas

**1. The connector problem.** Without a standard, every AI application needs its own connector to every system: N applications and M systems need N × M connectors. With a standard, each application builds the socket once and each system builds the plug once: N + M pieces. A fourth application then costs the systems nothing. In Anthropic's words: "Every new data source requires its own custom implementation, making truly connected systems difficult to scale."

**2. Three things a server can offer, and who decides when each is used.**

| | What it is | Who decides | Example |
|---|---|---|---|
| **Prompts** | Ready-made instructions: "how we do things here" | You, from a menu | "Write a Grace job script" |
| **Data** (*resources* in the specification) | Read-only material: "what we have" | The app, or you, attaches it | Storage guide; sample job scripts |
| **Tools** | Actions: "what we can do" | The AI, when needed (the app usually asks you first) | Submit a job |

**3. Host, client and server.** The *host* is the application you talk to, such as Claude Desktop or VS Code. Inside it, a *client* is the built-in socket; the host creates one client per server. The *server* is the plug: a small program offering prompts, data and tools for one system. You will almost always write servers, not clients.

**4. The AI picks tools by reading their descriptions.** Each tool has a name and a plain-language description of what it does and when to use it. The application shows these to the AI as a menu, and the AI chooses from it. Vague descriptions lead to wrong or missed tool calls, so writing them well matters.

**5. MCP connects systems to the application; the model coordinates.** The AI model itself never speaks MCP. The application translates the server's menu into the model's ordinary tool-use format (Tutorial 12). When the model asks for a tool, the application carries the request to the right server and returns the result. So one server works with different models, and adding a tool needs no retraining.

**6. Security and limits.** MCP does not make the AI trustworthy; the design around it has to.

- *Approval prompts.* Applications ask before a tool runs. Read them: they are your last check.
- *Narrow tools.* Offer "submit this job script", never "run any shell command". The server, not the AI, enforces limits such as allowed partitions and maximum run time, because allocations cost real money.
- *Prompt injection.* Anything the AI reads (tool descriptions, files, job output) can contain hidden instructions. Install only servers you trust; they run with your permissions.
- *Credentials stay outside the AI.* In the HPRC demo you log in once in a terminal with password and Duo; the server reuses that connection, and the AI never sees your password.
- *Where results go.* What a tool returns becomes part of the conversation and is sent to the model provider.

**A note on versions.** The current specification is version 2026-07-28, which made MCP *stateless*: each request carries its own version and identity, and servers keep no memory between requests (anything to remember, such as a job ID, is passed back as an argument). *Sampling* (a server asking the application's AI to write text) and *roots* (the application telling a server which folders it may use) are deprecated as of this version. This explains why older tutorials differ from the current documentation.

## Demo

**Demo 1: ready-made plugs.** In Claude Desktop, with the Google Drive and Gmail connectors switched on, Claude finds and summarizes a document. With Drive switched off, the same question can no longer be answered. Someone else built these plugs; the user only switches them on.

**Demo 2: our own plug for the Grace cluster.** The HPRC server in this repository offers:

- *Prompts:* write a Grace job script; debug a failed job.
- *Data:* a file-system guide (home vs. scratch), known-good CPU and GPU sample scripts, live software versions.
- *Tools:* submit, check, cancel and read the output of jobs; find software; check quota; list files; copy a file to the cluster; cluster status; the house rules.

To try it yourself, follow the quick start in `README.md`: clone the repository on your laptop, run `./setup.sh <NetID>`, log in once with `ssh grace` (password plus one Duo push), and open Claude. The server runs on your laptop and reuses that login until you close it (ask Claude to end the session, or run `ssh -O exit grace`; it also closes itself after an hour without use). Nothing is installed on Grace. Then you ask Claude: *"Run examples/monte_carlo_pi.py on Grace with 4 cores for 10 minutes and tell me the result."* Claude reads the house rules and a sample script, looks up the installed Python versions and writes a job script. After you click Allow, it submits the job, tracks it and reads the output. Without the server, plain Claude writes a plausible script with guessed versions, partitions and paths.

Before anything reaches the queue, the server checks the submission against `config/hprc_mcp.toml` (allowed partitions, maximum run time, nodes, GPUs). `hprc-mock`, a simulated cluster with the same tools, lets you try it without a Grace account (see `README.md`).

## Connections

- **Tutorial 12 (tool use and function calling).** MCP is built on tool use: instead of defining tools inside your own program, a separate program offers them to any application, which presents them to the model as ordinary tool definitions.
- **Tutorial 11 (the agent loop).** Each tool call is the "act" step and each result the "observe" step. MCP widens what an agent can act on: submit, check, read the output, try again.
- **Challenge 3 (retrieval and grounding).** Resources and read-only tools ground an agent in real domain data, such as the actual list of installed software.
- **Challenge 4 (orchestration).** Standard servers make multi-agent setups easier, because several agents or applications can share the same servers instead of each wiring its own connectors.
- **Capstone.** A small server for your field's data, instruments or cluster jobs lets your capstone agent evaluate candidates on the real system, for example by submitting each evaluation as a cluster job.

## Further reading

- MCP architecture overview: <https://modelcontextprotocol.io/docs/learn/architecture>
- Server concepts (prompts, resources, tools): <https://modelcontextprotocol.io/docs/learn/server-concepts>
- Client concepts: <https://modelcontextprotocol.io/docs/learn/client-concepts>
- Anthropic, "Introducing the Model Context Protocol" (November 2024): <https://www.anthropic.com/news/model-context-protocol>
- Anthropic, donating MCP and establishing the Agentic AI Foundation (December 2025): <https://www.anthropic.com/news/donating-the-model-context-protocol-and-establishing-of-the-agentic-ai-foundation>
- MCP security best practices (specification 2026-07-28): <https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/security_best_practices>
