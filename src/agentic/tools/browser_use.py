# pip install playwright
# pip install browser-use
from typing import Optional

from agentic.tools import tool_registry
from agentic.models import GPT_4O_MINI
from agentic.common import RunContext
from agentic.events import FinishCompletion
from browser_use import Agent as BrowserAgent
from browser_use import Browser, BrowserConfig
from langchain_openai import ChatOpenAI
from langchain.callbacks import StdOutCallbackHandler

@tool_registry.register(
    name="Browser-use Tool",
    description="Automate browser interactions with a smart agent. https://docs.browser-use.com/",
    dependencies=[
        tool_registry.Dependency(
            name="playwright",
            version="1.50.0",
            type="pip",
        ),
        tool_registry.Dependency(
            name="browser-use",
            version="0.1.37",
            type="pip",
        ),
    ],
)
class BrowserUseTool:
    # Automates browser interactions with a smart agent.
    # Set the chrome_instance_path to the path to your Chrome executable if you want to use YOUR browser with its
    # cookies and state - but be careful.
    #
    # Typical paths:
    # For MacOS: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', 
    # For Windows, typically: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
    # For Linux, typically: '/usr/bin/google-chrome'

    def __init__(self, chrome_instance_path: Optional[str]=None, model: str=GPT_4O_MINI):
        self.chrome_instance_path = chrome_instance_path
        self.model = model

    def get_tools(self):
        return [self.run_browser_agent]
    
    # Yield strings of browser actions
    async def run_browser_agent(
            self, 
            run_context: RunContext,
            instructions: str,
            model: Optional[str] = None
    ) -> list[str|FinishCompletion]:
        """ Execute a set of instructions via browser automation. Instructions can be in natural language. 
            The history of browsing actions taken is returned.
        """
        browser = None
        if self.chrome_instance_path:
            browser = browser = Browser(
                config=BrowserConfig(
                    chrome_instance_path=self.chrome_instance_path
                )
            )
        token_counter = TokenCounterStdOutCallback()
        agent = BrowserAgent(
            task=instructions,
            llm=ChatOpenAI(model=self.model, callbacks=[token_counter]),
            browser=browser,
        )
        result = await agent.run()
        return [
            "\n".join(result.extracted_content()),
            FinishCompletion.create(
                agent=run_context.agent.name,
                llm_message=f"Tokens used - Input: {token_counter.total_input_tokens}, Output: {token_counter.total_output_tokens}",
                model=self.model,
                cost=0,
                input_tokens=token_counter.total_input_tokens,
                output_tokens=token_counter.total_output_tokens,
                elapsed_time=0,
                depth=0,
            )
        ]
    


class TokenCounterStdOutCallback(StdOutCallbackHandler):
    def __init__(self):
        super().__init__()
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def on_llm_end(self, response, **kwargs):
        if hasattr(response, "llm_output") and response.llm_output:
            token_usage = response.llm_output.get("token_usage", {})
            input_tokens = token_usage.get("prompt_tokens", 0)
            output_tokens = token_usage.get("completion_tokens", 0)

            self.total_input_tokens += input_tokens
            self.total_output_tokens += output_tokens

            print(f"[AGENTIC] Tokens used - Input: {input_tokens}, Output: {output_tokens}")
            print(f"[AGENTIC] Total tokens - Input: {self.total_input_tokens}, Output: {self.total_output_tokens}")
        else:
            print("[AGENTIC] No token usage data available.")

