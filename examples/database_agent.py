from agentic import Agent, AgentRunner
from agentic.tools.database_tool import DatabaseTool


# This is the simplest possible Text-to-SQL agent. It uses a database tool to answer questions.

database_agent = Agent(
    name="Database Agent",
    instructions="""
You are a helpful data analyst. Use your database tools to answer any questions. """,
    tools=[DatabaseTool(connection_string="sqlite:///examples/chinook.db")],
)

if __name__ == "__main__":
    AgentRunner(database_agent).repl_loop()
