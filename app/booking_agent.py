"""booking_agent: system prompt, model and LangGraph graph."""

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from groq import BadRequestError
from langchain_core.messages import SystemMessage
from langchain_groq import ChatGroq
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from app.config import settings
from app.booking_agent_tools import TOOLS
from app.rules import OFFICE_CLOSE, OFFICE_OPEN

PROMPTS = yaml.safe_load((Path(__file__).parent / "prompts.yaml").read_text(encoding="utf-8"))
TZ = ZoneInfo(settings.timezone)
WEEKDAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
CALENDAR_DAYS = 14

model = ChatGroq(
    model=settings.agent_model,
    api_key=settings.groq_api_key,
    temperature=0,
    max_retries=3,
    reasoning_effort="low",
).bind_tools(TOOLS)


def calendar(today: date) -> str:
    """List the next days with weekday and ISO date, e.g. "- domingo 18/10 (mañana): 2026-10-18".

    LLMs are unreliable at calendar arithmetic, so the dates are computed here and only copied.
    """
    labels = {0: " (hoy)", 1: " (mañana)"}
    lines = []
    for offset in range(CALENDAR_DAYS):
        day = today + timedelta(days=offset)
        lines.append(f"- {WEEKDAYS[day.weekday()]} {day:%d/%m}{labels.get(offset, '')}: {day:%Y-%m-%d}")
    return "\n".join(lines)


def system_prompt(now: datetime) -> str:
    """Fill the system prompt with the date, calendar and office hours, so the LLM can resolve "mañana" or "el jueves"."""
    return PROMPTS["booking_agent_prompt"]["prompt"].format(
        now=f"{WEEKDAYS[now.weekday()]} {now:%Y-%m-%d %H:%M}",
        timezone=settings.timezone,
        calendar=calendar(now.date()),
        office_hours=f"lunes a viernes de {OFFICE_OPEN:%H:%M} a {OFFICE_CLOSE:%H:%M}",
    )


def call_model(state: MessagesState) -> dict:
    """Agent node: ask the LLM for the next step, either a reply or a tool call."""
    # Rebuilt on every turn and never stored in memory, so the current time is always fresh.
    messages = [SystemMessage(system_prompt(datetime.now(TZ))), *state["messages"]]
    try:
        return {"messages": [model.invoke(messages)]}
    except BadRequestError as exc:
        if "tool_use_failed" not in str(exc):
            raise
        feedback = SystemMessage(
            f"Tu llamada a una herramienta fue inválida: {exc.body['error']['message']}. "
            "No uses valores nulos ni inventados: si faltan datos, pídelos al usuario."
        )
        return {"messages": [model.invoke([*messages, feedback])]}


graph = StateGraph(MessagesState)
graph.add_node("agent", call_model)
graph.add_node("tools", ToolNode(TOOLS))
graph.add_edge(START, "agent")

graph.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: END})
graph.add_edge("tools", "agent")

booking_agent = graph.compile(checkpointer=MemorySaver(), name="booking_agent")
