import os
import json
import logging
from google import genai
from google.genai import types
from telegram_bot import state_manager
from telegram_bot.automation_runner import start_automation, stop_automation, get_status, get_logs

logger = logging.getLogger('palladium_automation.agent')

# Initialize Gemini client
def get_client():
    return genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# Define the tools available to the LLM using Gemini types
def setup_and_start_automation(username: str, password: str, campaign: str, links: list[str], interval: int) -> str:
    """Configures and starts the Playwright automation for a user. Use this when the user wants to start, run, or setup a new campaign."""
    pass # Implementation happens in the processor

def stop_automation_tool() -> str:
    """Stops the currently running automation for the user."""
    pass

def check_status_tool() -> str:
    """Checks the current status of the automation, including if it's running, the current link, and total links."""
    pass

def get_recent_logs_tool() -> str:
    """Retrieves the recent activity logs for the user's automation to check for errors or progress."""
    pass

TOOLS = [setup_and_start_automation, stop_automation_tool, check_status_tool, get_recent_logs_tool]

async def process_user_message(user_id: int, user_message: str, bot_instance=None) -> str:
    """
    Sends the user's message to the Gemini LLM, allows it to call tools, and returns the response.
    """
    if not os.getenv("GEMINI_API_KEY"):
        return "⚠️ Gemini API key is missing. Please set GEMINI_API_KEY in the .env file to enable the AI Agent."

    try:
        client = get_client()
    except Exception as e:
         return f"⚠️ Failed to initialize Gemini Client: {e}"

    str_user_id = str(user_id)
    
    # Load user's current state to provide context to the LLM
    user_data = state_manager.get_user(user_id)
    running = state_manager.is_running(user_id)
    
    system_prompt = (
        "You are an intelligent automation assistant managing a Playwright bot for Palladium Expert.\n"
        "Your job is to understand user requests and manage their automation tasks using the provided tools.\n\n"
        "Current Context:\n"
        f"- Automation Running: {running}\n"
        f"- Current Configured Campaign: {user_data.get('campaign', 'None')}\n"
        f"- Configured Links: {len(user_data.get('links', []))} links\n"
        f"- Configured Interval: {user_data.get('interval', 'None')} minutes\n\n"
        "Rules:\n"
        "1. If the user wants to start automation but hasn't provided all required details (username, password, campaign, links, interval), "
        "politely ask them for the missing information in a conversational way.\n"
        "2. Once you have all the information, call `setup_and_start_automation`.\n"
        "3. If the user asks for status, call `check_status_tool` and summarize the result for them.\n"
        "4. If the user asks why it stopped or for logs, call `get_recent_logs_tool` and summarize the issues.\n"
        "5. Be concise, helpful, and friendly."
    )

    try:
        # Use synchronous generate_content since google-genai async support might vary, 
        # but we are in an async function so we wrap it or use the standard call.
        # For simplicity and stability, we use the standard generate_content
        
        chat = client.chats.create(
            model="gemini-2.5-flash",
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                tools=TOOLS,
                temperature=0.7,
            )
        )
        
        response = chat.send_message(user_message)
        
        # Check if the model wants to call a tool
        if getattr(response, "function_calls", None):
            for tool_call in response.function_calls:
                function_name = tool_call.name
                function_args = tool_call.args
                
                logger.info(f"Gemini called tool: {function_name} with args: {function_args}")
                
                tool_result = ""
                
                if function_name == "setup_and_start_automation":
                    # Save the config to state manager
                    new_data = {
                        "username": function_args.get("username", ""),
                        "password": function_args.get("password", ""),
                        "campaign": function_args.get("campaign", ""),
                        "links": list(function_args.get("links", [])),
                        "interval": int(function_args.get("interval", 10)),
                        "state": state_manager.COMPLETED
                    }
                    state_manager.update_user(user_id, new_data)
                    
                    if running:
                        tool_result = "Failed: Automation is already running. Stop it first."
                    else:
                        try:
                            # Start it
                            updated_data = state_manager.get_user(user_id)
                            start_automation(user_id, updated_data, logging.getLogger('palladium_automation.runner'), bot_instance)
                            tool_result = "Success: Automation started successfully."
                        except Exception as e:
                            tool_result = f"Failed to start: {str(e)}"
                            
                elif function_name == "stop_automation_tool":
                    if not running:
                        tool_result = "Automation is already stopped."
                    else:
                        try:
                            stop_automation(user_id)
                            tool_result = "Success: Automation stopped."
                        except Exception as e:
                            tool_result = f"Failed to stop: {str(e)}"
                            
                elif function_name == "check_status_tool":
                    status = get_status(user_id)
                    if not status:
                        tool_result = "Status: Not started yet."
                    else:
                        tool_result = json.dumps(status)
                        
                elif function_name == "get_recent_logs_tool":
                    logs = get_logs(user_id)
                    tool_result = "\n".join(logs[-10:]) if logs else "No logs available."
                
                # Send the tool result back to the model to get the final response
                second_response = chat.send_message(
                    [types.Part.from_function_response(
                        name=function_name,
                        response={"result": tool_result}
                    )]
                )
                return second_response.text
            
        else:
            # Gemini just wanted to talk
            return response.text

    except Exception as e:
        logger.error(f"Error in Gemini processing: {e}")
        return f"❌ Sorry, my AI brain encountered an error: {e}"