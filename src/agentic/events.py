# Shutup stupid pydantic warnings
import warnings
warnings.filterwarnings("ignore", message="Valid config keys have changed in V2:*")

from dataclasses import dataclass
from typing import Any
from .swarm.types import Result
import json

from litellm.types.utils import ModelResponse, Message

@dataclass
class Event:
    agent: str
    type: str
    payload: Any
    depth: int = 0

    def print(self):
        print(self)

    def __str__(self) -> str:
        return str(f"[{self.agent}: {self.type}] {self.payload}\n")
        
    def _safe(self, d, keys: list[str], default_val=None):
        for k in keys:
            if k in d:
                d = d[k]
            else:
                return default_val
        return d or default_val
    
    def debug(self, indent: bool = False):
        prefix = ""
        if indent:
            prefix = ".."*(self.depth+1)    
        return(f"{prefix}{self.type.upper()}: {self.payload}")

    @property
    def is_output(self):
        return False
class Prompt(Event):
    # The 'originator' is meant to be the address of the top-level caller (the user's loop) into the
    # agent. This gets passed around into the agent call chain in case sub-agents need to communicate
    # back to the top. Note that in Thespian, we don't have this address until the first receiveMessage
    # is called, so we set it then.
    debug: bool = False

    def __init__(
            self, 
            agent: str, 
            message: str, 
            depth: int = 0, 
            debug: bool = False, 
            originator=None, 
            ignore_result: bool=False
        ):
        super().__init__(agent, 'prompt', message, depth)
        self.debug = debug
        self.originator = originator
        self.ignore_result = ignore_result

class PromptStarted(Event):
    def __init__(self, agent: str, message: str, depth: int = 0):
        super().__init__(agent, 'prompt_stated', message, depth)

class ResetHistory(Event):
    def __init__(self, agent: str):
        super().__init__(agent, 'reset_history', {})
        
class Output(Event):
    def __init__(self, agent: str, message: str, depth: int = 0):
        super().__init__(agent, 'output', message, depth=depth)

    def __str__(self) -> str:
        return str(self.payload or '')

    def __repr__(self) -> str:
        return repr(self.__dict__)

    @property
    def is_output(self):
        return True

class ChatOutput(Output):
    def __init__(self, agent: str, payload: dict, depth: int = 0):
        Event.__init__(self, agent, 'chat_output', payload, depth)

    def __str__(self) -> str:
        return str(self.payload.get('content') or '')
    
    def __repr__(self) -> str:
        return repr(self.__dict__)
    
class ToolCall(Event):
    def __init__(self, agent: str, name: str, args: dict, depth: int = 0):
        super().__init__(agent, 'tool_call', name, depth=depth)
        self.args = args

    def __str__(self):
        name = self.payload
        return "--"*(self.depth+1) + f"> {name}({self.args})\n"

class ToolResult(Event):
    def __init__(self, agent: str, name: str, result: Any, depth: int = 0):
        super().__init__(agent, 'tool_result', name, depth=depth)
        self.result = result

    def __str__(self):
        name = self.payload
        return "<" + "--"*(self.depth+1) + f"{name}: {self.result}\n"

class StartCompletion(Event):
    def __init__(self, agent: str):
        super().__init__(agent, 'completion_start', {})

class FinishCompletion(Event):
    MODEL_KEY = 'model'
    COST_KEY = 'cost'
    INPUT_TOKENS_KEY = 'input_tokens'
    OUTPUT_TOKENS_KEY = 'output_tokens'
    ELAPSED_TIME_KEY = 'elapsed_time'

    def __init__(self, agent: str, llm_message: Message, metadata: dict = {}):
        super().__init__(agent, 'completion_end', llm_message)
        self.metadata = metadata

    @classmethod
    def create(cls, 
               agent: str, 
               llm_message: Message,
               model: str,
               cost: float,
               input_tokens: int|None,
               output_tokens: int|None,
               elapsed_time: float|None,
    ):
        meta =  {
            cls.MODEL_KEY: model,
            cls.COST_KEY: cost or 0,
            cls.INPUT_TOKENS_KEY: input_tokens or 0,
            cls.OUTPUT_TOKENS_KEY: output_tokens or 0,
            cls.ELAPSED_TIME_KEY: elapsed_time or 0,
        }

        return cls(agent, llm_message, meta)    

    @property
    def response(self) -> Message:
        return self.payload
class TurnEnd(Event):
    def __init__(self, agent: str, messages: list, context_variables: dict = {}):
        super().__init__(agent, 'turn_end', {"messages": messages, "vars": context_variables})

    @property
    def messages(self):
        return self.payload['messages']

    @property
    def result(self):
        return self.messages[-1]['content']
    
    @property
    def context_variables(self):
        return self.payload['vars']    
    
class SetState(Event):
    def __init__(self, agent, state: dict):
        super().__init__(agent, 'set_state', state)

class AddChild(Event):
    def __init__(self, agent, actor_ref, handoff: bool=False):
        super().__init__(agent, 'add_child', actor_ref)
        self.handoff = handoff

    @property
    def actor_ref(self):
        return self.payload

PAUSE_FOR_INPUT_SENTINEL = "__PAUSE4INPUT__"
PAUSE_FOR_CHILD_SENTINEL = "__PAUSE__CHILD"
FINISH_AGENT_SENTINEL = "__FINISH__"
class WaitForInput(Event):
    # Whenenever the agent needs to pause, either to wait for human input or a response from
    # another agent, we emit this event.
    def __init__(self, agent, request_keys: dict):
        super().__init__(agent, 'wait_for_input', request_keys)

    @property
    def request_keys(self) -> dict:
        return self.payload

# Sent by the caller with human input
class ResumeWithInput(Event):
    def __init__(self, agent, request_keys: dict):
        super().__init__(agent, 'resume_with_input', request_keys)

    @property
    def request_keys(self):
        return self.payload


class PauseForInputResult(Result):
    def __init__(self, request_keys: dict):
        super().__init__(value=PAUSE_FOR_INPUT_SENTINEL, context_variables=request_keys)
    
    @staticmethod
    def matches_sentinel(value) -> bool:
        return value == PAUSE_FOR_INPUT_SENTINEL


# Gonna snuggle this through the Swarm tool call
class PauseForChildResult(Result):
    def __init__(self, values: dict):
        super().__init__(value=PAUSE_FOR_CHILD_SENTINEL, context_variables=values)

    @staticmethod
    def matches_sentinel(value) -> bool:
        return value == PAUSE_FOR_CHILD_SENTINEL

# Special result which aborts any further processing by the agent.
class FinishAgentResult(Result):
    def __init__(self):
        super().__init__(value=FINISH_AGENT_SENTINEL)

    @staticmethod
    def matches_sentinel(value) -> bool:
        return value == FINISH_AGENT_SENTINEL
