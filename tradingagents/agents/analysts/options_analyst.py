from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_language_instruction,
)
from tradingagents.agents.utils.divergence_tools import get_divergence_report


def create_options_analyst(llm, memory=None):

    def options_analyst_node(state):
        current_date = state["trade_date"]
        instrument_context = build_instrument_context(state["company_of_interest"])

        tools = [
            get_divergence_report,
        ]

        system_message = (
            "You are an options and derivatives analyst specializing in reading "
            "options flow, implied volatility surfaces, put/call ratios, and "
            "divergence signals. Use the divergence report tool to obtain a "
            "multi-dimensional divergence analysis that fuses institutional flow, "
            "options sentiment, price-action momentum, and regime context. "
            "Interpret the composite score and individual dimension scores to "
            "assess whether smart-money positioning diverges from recent price "
            "action. Highlight any unusual options activity, skew changes, or "
            "volatility regime shifts. Provide specific, actionable insights "
            "with supporting evidence to help traders make informed decisions."
            + " Make sure to append a Markdown table at the end of the report "
            "to organize key points, organized and easy to read."
            + get_language_instruction()
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " Use the provided tools to progress towards answering the question."
                    " If you are unable to fully answer, that's OK; another assistant with different tools"
                    " will help where you left off. Execute what you can to make progress."
                    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                    " You have access to the following tools: {tool_names}.\n{system_message}"
                    "For your reference, the current date is {current_date}. {instrument_context}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(current_date=current_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm.bind_tools(tools)
        result = chain.invoke(state["messages"])

        report = ""
        if len(result.tool_calls) == 0:
            report = result.content

        return {
            "messages": [result],
            "options_report": report,
        }

    return options_analyst_node
