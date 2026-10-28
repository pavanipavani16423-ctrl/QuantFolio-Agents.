"""The LangGraph workflow: a supervisor hub with one spoke per agent.

    START -> supervisor -> {guard | intake | research,risk,mandate (parallel) | optimize | backtest |
                            check | report | evaluate | trades | approval | execute} -> supervisor
                        -> END

The approval node calls `interrupt()`; with a checkpointer the run pauses there durably and
is resumed later with `Command(resume={...})`.
"""

from langgraph.graph import START, StateGraph

from app.graph import nodes
from app.graph.state import RunState

WORKERS = {
    "guard": nodes.guard_node,
    "intake": nodes.intake_node,
    "research": nodes.research_node,
    "risk": nodes.risk_node,
    "mandate": nodes.mandate_node,
    "optimize": nodes.optimize_node,
    "backtest": nodes.backtest_node,
    "check": nodes.check_node,
    "report": nodes.report_node,
    "evaluate": nodes.evaluate_node,
    "trades": nodes.trades_node,
    "approval": nodes.approval_node,
    "execute": nodes.execute_node,
}


def build_graph(checkpointer=None):  # noqa: ANN001, ANN201
    graph = StateGraph(RunState)
    graph.add_node("supervisor", nodes.supervisor_node)
    for name, fn in WORKERS.items():
        graph.add_node(name, fn)
        graph.add_edge(name, "supervisor")
    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges("supervisor", nodes.route, [*WORKERS, "__end__"])
    return graph.compile(checkpointer=checkpointer)


def mermaid() -> str:
    return build_graph().get_graph().draw_mermaid()
