"""booking_agent: system prompt, model and LangGraph graph."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from langchain_core.messages import SystemMessage
from langchain_groq import ChatGroq
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from app.config import settings
from app.tools import TOOLS

PROMPTS = yaml.safe_load((Path(__file__).parent / "prompts.yaml").read_text(encoding="utf-8"))
TZ = ZoneInfo(settings.timezone)
WEEKDAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

model = ChatGroq(
    model=settings.agent_model,
    api_key=settings.groq_api_key,
    temperature=0,
    max_retries=3,
).bind_tools(TOOLS)


def system_prompt(now: datetime) -> str:
    """Fill the system prompt with the current date, so the LLM can resolve "mañana" or "el jueves"."""
    return PROMPTS["system"].format(
        now=f"{WEEKDAYS[now.weekday()]} {now:%Y-%m-%d %H:%M}",
        timezone=settings.timezone,
    )


def call_model(state: MessagesState) -> dict:
    """Agent node: ask the LLM for the next step, either a reply or a tool call."""
    # Rebuilt on every turn and never stored in memory, so the current time is always fresh.
    messages = [SystemMessage(system_prompt(datetime.now(TZ))), *state["messages"]]
    return {"messages": [model.invoke(messages)]}


graph = StateGraph(MessagesState)
graph.add_node("agent", call_model)
graph.add_node("tools", ToolNode(TOOLS))
graph.add_edge(START, "agent")

graph.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: END})
graph.add_edge("tools", "agent")

booking_agent = graph.compile(checkpointer=MemorySaver())
