import asyncio
from typing import Callable, Any

from agentic.tools.linkedin_tool import LinkedinDataTool
from agentic.tools.google_news import GoogleNewsTool

from agentic.common import Agent, AgentRunner, PauseForInputResult, RunContext


def invoke_async(async_func: Callable, *args, **kwargs) -> Any:
    return asyncio.run(async_func(*args, **kwargs))


linkedin = LinkedinDataTool()


def search_profiles(name: str, company: str = ""):
    """Searches for linkedin profiles."""
    return invoke_async(linkedin.linkedin_people_search, name=name, company=company)


def get_profile(url: str):
    return invoke_async(linkedin.get_linkedin_profile_info, url)


gnt = GoogleNewsTool()


def query_news(topic: str):
    return gnt.query_news(topic)


def get_human_input(run_context: RunContext):
    if run_context.get("topic"):
        return run_context.get("topic")
    return PauseForInputResult({"topic": "What is the news topic?"})


model = "openai/gpt-4o-mini"
#model="lm_studio/qwen2.5-7b-instruct-1m"
#model="lm_studio/deepseek-r1-distill-qwen-7B"

reporter = Agent(
    name="News Reporter",
    instructions=f"""
Call Google News to get headlines on the indicated news topic.
""",
    model=model,
    tools=[query_news],
)
producer = Agent(
    name="Producer",
    welcome="I am the news producer. Tell me the topic, and I'll get the news from my reporter.",
    instructions="""
You are a news producer. Call the human to get the topic, then call the reporter with the indicated topic. 
Print one sentence summary of the report.
""",
    model=model,
    tools=[get_human_input],
)

producer.add_tool(reporter)

if __name__ == "__main__":
    AgentRunner(producer).repl_loop()
