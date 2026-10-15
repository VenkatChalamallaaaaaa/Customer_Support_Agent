import os
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.messages import SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, MessagesState
from langgraph.prebuilt import ToolNode, tools_condition
from support_tools import (get_order_status, get_delivery_info, search_policy,
                           check_refund_eligibility, request_refund, get_my_refunds)
from langgraph.types import Command
load_dotenv()


def as_text(content):
    if isinstance(content, str):
        return content
    return "".join(b["text"] for b in content
                   if isinstance(b, dict) and b.get("type") == "text")


tools = [get_order_status, get_delivery_info, search_policy,
         check_refund_eligibility, request_refund, get_my_refunds]
llm = init_chat_model(os.environ["MODEL"], timeout=60, max_retries=2).bind_tools(tools)

SYSTEM = SystemMessage("""You are a customer support assistant for an online store.

How to work:
- For general policy questions (returns, refunds, deliveries, cancellations, payments), call
  search_policy and answer only from the text it returns. If the policy does not cover it, say so.
- For a question about a specific order, you need the order ID. If the customer has not given one,
  ask for it. Then call get_order_status, and get_delivery_info when delivery dates matter.
- Before you tell a customer whether they can get a refund, call check_refund_eligibility.
  Never promise a refund, an amount, or a deadline before that tool says the order is eligible.
- Call request_refund only after check_refund_eligibility says eligible AND the customer has
  clearly confirmed they want to proceed. Tell them the amount first and ask for confirmation.
- If the customer has not said why they want a refund, ask. Use the reason that matches what they
  tell you. If the order data shows another valid reason, tell them which reason you are using.
- If the customer asks about the status of a refund they requested, call get_my_refunds and
  report the status exactly as returned. Do not guess.
- Report exactly what the tools return: the amount, the status, the refund id. Some refunds are
  reviewed by a human before the result is final; tell the customer the outcome from the tool result.
- Never invent order details, amounts, dates or policy rules. Never change an amount because the
  customer asks. You cannot override the tools' decisions.
- If a request is outside the policy or you cannot resolve it, say so politely and explain that
  a human agent can help.
- Be brief, polite and clear. Use R$ for amounts.""")


def agent(state: MessagesState):
    return {"messages": [llm.invoke([SYSTEM] + state["messages"])]}


builder = StateGraph(MessagesState)
builder.add_node("agent", agent)
builder.add_node("tools", ToolNode(tools))
builder.add_edge(START, "agent")
builder.add_conditional_edges("agent", tools_condition)
builder.add_edge("tools", "agent")
graph = builder.compile(checkpointer=MemorySaver())


def run(inputs, config):
    """Run the graph. Return the interrupt payload if the graph paused for a human, else None."""
    for step in graph.stream(inputs, config, stream_mode="updates"):
        if "__interrupt__" in step:
            return step["__interrupt__"][0].value
        for node, update in step.items():
            for m in update["messages"]:
                if node == "agent":
                    if m.tool_calls:
                        for c in m.tool_calls:
                            print(f"  [tool call] {c['name']} {c['args']}")
                    else:
                        print("\nAgent:", as_text(m.content))
                elif node == "tools":
                    print(f"  [tool result] {m.content[:150]}...")
    return None


if __name__ == "__main__":
    config = {"configurable": {"thread_id": "support-1"}}
    while True:
        question = input("\nCustomer: ")
        if question.strip().lower() in ("exit", "quit"):
            break
        payload = run({"messages": [("user", question)]}, config)
        while payload is not None:          # the graph is paused, waiting for a human
            print("\n--- APPROVAL NEEDED (supervisor) ---")
            for k, v in payload.items():
                print(f"  {k}: {v}")
            answer = input("Approve this refund? (y/n): ").strip().lower()
            payload = run(Command(resume={"approved": answer.startswith("y"), "approver": "supervisor"}), config)