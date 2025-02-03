# Agentic

A new, easy to use AI Agents framework. Agentic offers these features:

- Approachable and simple to use
- Supports agents swarms
- Support Human-in-the-loop
- Easy definition and use of tools

## The problem with function calling

Since the introduction of "function calling" by OpenAI, most frameworks have built around
the idea of agent "tools" as functions. Many have extended this idea to include calling
agents calling other _agents as tools_. 

The problem is that function calling generally assumes synchronous semantics and strictly 
typed parameters and return values. Both of these make poor assumptions when dealing with
AI agents. Since agents can easily be long-running, it is much better assume an event-driven
model (sending messages, and waiting for events) than a synchronous one. Strict typing
is useful in compiled code, but LLMs are really best with text and language, not strict
compiler types.

As you start building more complex agents, you want them to run longer, be decomposable
into multiple units, and have flexible behavior like stopping for human input. Agentic
is designed to make these more complex use cases easy.

## Tools as Agents

Agentic assumes an event driven model for agents. We send events to agents when we want
them to do something, and the agent publishes events back to us with the results. Because
event driven is so key, _tool calling_ is also event driven. Although the framework
hides most of the details, every tool (function) call happens asynchronously. One of
the implications of this design is that tools can "interrupt" the agent, and wait for
human input. When your agent is waiting for input it is effectively paused, consuming
no resources. This means that complex patterns like "send an email for clarification,
and wait for the reply" are easy and low-cost to build.



## Basic example

```python
from agentic import Agent, AgentRunner
from agentic.tools import LinkedinTool, HumanInterruptTool

researcher = Agent(
    name="Person Researcher",
    welcome="I am your People Researcher. Who would you like to know more about?",
    instructions="""
You do research on people. Given a name and a company:
1. Search for matching profiles on linkedin.
2. If you find a single strong match, then prepare a background report on that person. Make sure
to print the full report.
3. If you find multiple matches, then ask stop and ask the user for clarification. Then go back to step 1.
If you are missing info, then seek clarification from the user.
""",
    tools=[LinkedinTool(), HumanInterruptTool()],
    model="openai://gpt-4o-mini",
)

researcher.add_child(
    Agent(
        name = "Person Report Writer",
        instructions="""
    You will receive the URL to a linkedin profile. Retrive the profile and
    write a background report on the person, focusing on their career progression
    and current role.
        """,
        tools=[LinkedinTool()],
        model="anthropic://claude-sonnet-3.5",
    )
)

runner = ActorAgentRunner(agent)

print(agent.welcome)
print("press <enter> to quit")
while True:
    prompt = input("> ").strip()
    if prompt == 'quit' or prompt == '':
        break
    runner.start(prompt)

    for event in runner.next():
        if event is None:
            break
        elif event.requests_input():
            response = input(f"\n{event.request_message} > ")
            runner.continue_with(response)
        else:
            event.print()
    print()
```

**Breaking down our example**

First we define our top-level agent, the "Person Researcher", give it a goal
and a task list, an LLM model, and some tools:

- A linkedin tool for searching for linkedin profiles
- A "Human interrupt" tool which the agent can call to ask for human help

Now, we define a "sub agent" for this agent to use as another tool. This
is the "Person Report Writer" agent, with its own instruction and a 
different LLM model. We connect this agent to the top level via:

    researcher.add_child(
        Agent(... define our sub-agent...)
    )

This creates a tool function in the parent taken from the name of the child
agent.

**Running our agent**

To run our agent, we construct an `AgentRunner`. This object manages
a single multi-turn session interacting with our agent.

Here is the complete (condensed) run output:

```markdown
(agentic) scottp@MacBook-Air agentic % python examples/people_researcher.py 
I am the People Researcher. Tell me who you want to know about.
> marc benioff
--> search_profiles({"name":"marc benioff"})
--> get_human_input({"request_message":"I found multiple profiles for Marc..."})
I found multiple LinkedIn profiles for Marc Benioff. Here are the details:

1. **Marc Benioff**  
   - **Headline:** Chair & CEO at Salesforce  
   ...

2. **Marc Benioff**  
   - **Headline:** Bachelor's degree at Brunel University London  
   ...
...
Please let me know which profile you would like to know more about. 
> 1
call_person_report_writer({"message":"Please prepare a background report on Marc Benioff..."})
--> get_profile({"url":"https://www.linkedin.com/in/marcbenioff"})
### Background Report on Marc Benioff
**Current Role:**
Marc Benioff is the Chair and CEO of Salesforce, a leading cloud-based software company headquartered in San Francisco, California. Under his leadership, Salesforce has become a pioneer in customer relationship management (CRM) software and has significantly influenced the tech industry with its innovative solutions and commitment to social responsibility.

**Career Progression:**
- **Early Career:** Marc Benioff began his career at Oracle Corporation, where he worked for 13 years. During his time at Oracle, he held various positions, gaining valuable experience in software development and sales.
...
```

We call `start` to start our agent.
Now we iteratively grab events from the agent until the turn is finished.

- The initial user prompt is passed to our Researcher agent. It considers
its instructions and the user input. Based on this it generates 
a tool call to `LinkedinTool.search_profiles`. 
- The `search_profiles` function is called, and the result is returned
to the agent, which "observes" this result and generates the next
event (the "observation" event.)
- The agent "loops" and determines that multiple profiles were returned,
so it prints the list (emits output events with the text), and then
creates a tool call to `get_human_input`.
- The runner returns the interrupt event, return True from `event.requests_input()`
to be the agent request. We print that request message, collect input from the user,
and then call `continue_with` on the runner with the response. The human response
will be returned as the value of the `get_human_input` tool call.
- On `runner.next` the agent considers that we specified to check the first
returned profile, so it generates
a tool call to `call_person_report_writer` to create the report. If the user had
responded "I don't know", then the agent could decide it can't go any further
and just finish the turn.
- The `call_person_report_writer` function now activates our "Person Report Writer"
agent, with the profile URL as input, but in a new LLM context. This agent calls
`get_profile` to get the full Linkedin profile, then writes the research report.
- Finally the report is returned to the parent agent, which prints the results.

### Things to note

Events have a `depth` attribute which indicates how deep is the agent that is
generating the event. So the top agent generates `depth=0`, the first level 
sub-agent generates at `depth=1` and so forth. 

The list of tools on an agent should be modifiable at any time:

    agent.add_tool(tool)
    agent.remove_tool(tool)

However, tools probably shouldn't modify the running agent directly. Safer that
they publish events like `EnableTool` which can be handled properly by the
framework (there might be security controls or what not).

**RunContext**

PydanticAI uses this object, and I have the same (same name!) in Supercog. Real tools
will often want to retrieve bits of context like the current agent name, or running
user, etc... An example of where we use this in SC is an "email_user" function which looks
up the current user email in the RunContext.

**Run state**

Langgraph has a `state` notion, a dict that is passed between nodes. I have a feeling
that this is poor encapsulation and probably leads to poor code. Letta has "memory blocks"
which can be shared between agents, and this feels like probably a better design choice where
you very explicitly decide to share state rather than just using tool inputs and outputs.

A good example of this is if agent B needs to return a large chunk of info to agent A
(like the contents of a file), then it could put the file to a memory block and 
return a reference to that block in its call response to agent A. 

# Running

Not sure if PYTHONPATH needs to be set, or local install needs to happen...

### Examples

    python examples/basic_agent.py

Run in streamlit:

    streamlit run src/agentic/ui/chat.py
    

