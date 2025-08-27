import os
from dotenv import load_dotenv
import traceback
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
import asyncio
from google import genai
from concurrent.futures import TimeoutError
from functools import partial
from logger import mcp_server_logger
import re
import json

# Load environment variables from .env file
load_dotenv()

# Access your API key and initialize Gemini client correctly
api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key)

max_iterations = 14
last_response = None 
iteration = 0
iteration_response = []

async def generate_with_timeout(client, prompt, timeout=10):
    """Generate content with a timeout"""
    mcp_server_logger.info("Starting LLM generation...")
    try:
        # Convert the synchronous generate_content call to run in a thread
        loop = asyncio.get_event_loop()
        response = await asyncio.wait_for(
            loop.run_in_executor(
                None, 
                lambda: client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=prompt
                )
            ),
            timeout=timeout
        )
        mcp_server_logger.info("LLM generation completed")
        return response
    except TimeoutError:
        mcp_server_logger.info("LLM generation timed out!")
        raise
    except Exception as e:
        mcp_server_logger.info(f"Error in LLM generation: {e}")
        raise

def reset_state():
    """Reset all global variables to their initial state"""
    global last_response, iteration, iteration_response
    last_response = None
    iteration = 0
    iteration_response = []

async def main():
    reset_state()  # Reset at the start of main
    mcp_server_logger.info("Starting main execution...")
    try:
        # Create a single MCP server connection
        mcp_server_logger.info("Establishing connection to MCP server...")
        server_params = StdioServerParameters(
            command="python",
            args=["paint_mcp_server.py"]
        )

        async with stdio_client(server_params) as (read, write):
            mcp_server_logger.info("Connection established, creating session...")
            async with ClientSession(read, write) as session:
                mcp_server_logger.info("Session created, initializing...")
                await session.initialize()
                
                # Get available tools
                mcp_server_logger.info("Requesting tool list...")
                tools_result = await session.list_tools()
                tools = tools_result.tools
                mcp_server_logger.info(f"Successfully retrieved {len(tools)} tools")

                # Create system prompt with available tools
                mcp_server_logger.info("Creating system prompt...")
                mcp_server_logger.info(f"Number of tools: {len(tools)}")
                
                try:
                    # First, let's inspect what a tool object looks like
                    # if tools:
                    #     mcp_server_logger.info(f"First tool properties: {dir(tools[0])}")
                    #     mcp_server_logger.info(f"First tool example: {tools[0]}")
                    
                    tools_description = []
                    for i, tool in enumerate(tools):
                        try:
                            # Get tool properties
                            params = tool.inputSchema
                            desc = getattr(tool, 'description', 'No description available')
                            name = getattr(tool, 'name', f'tool_{i}')
                            
                            # Format the input schema in a more readable way
                            if 'properties' in params:
                                param_details = []
                                for param_name, param_info in params['properties'].items():
                                    param_type = param_info.get('type', 'unknown')
                                    param_details.append(f"{param_name}: {param_type}")
                                params_str = ', '.join(param_details)
                            else:
                                params_str = 'no parameters'

                            tool_desc = f"{i+1}. {name}({params_str}) - {desc}"
                            tools_description.append(tool_desc)
                            mcp_server_logger.info(f"Added description for tool: {tool_desc}")
                        except Exception as e:
                            mcp_server_logger.info(f"Error processing tool {i}: {e}")
                            tools_description.append(f"{i+1}. Error processing tool")
                    
                    tools_description = "\n".join(tools_description)
                    mcp_server_logger.info("Successfully created tools description")
                except Exception as e:
                    mcp_server_logger.info(f"Error creating tools description: {e}")
                    tools_description = "Error loading tools"
                
                mcp_server_logger.info("Created system prompt...")
                
                system_prompt = f"""You are a mathematical reasoning agent that solves problems step by step.
You have access to these mathematical tools:
Available tools:
{tools_description}

Follow this process
- Before solving, identify the type of reasoning needed: Arithmetic, Logic, Lookup, Planning and Tag each step with its reasoning type. show the reasoning steps
- solve the steps
- Use verify tool to check the results of each step 
- finally provide final answer

Important:
- When a function returns multiple values, you need to process all of them
- Only give FINAL_ANSWER when you have completed all necessary calculations
- Do not repeat function calls with the same parameters
- Call one function at a time
- Incase if you are not able to answer tell `I dont have the capability for it, check the tools description`

Respond with EXACTLY ONE line in one of these formats:
1. {{"message_type": "FUNCTION_CALL", "name" : function_name, "params": {{"param1": value1, "param2": value2, ...}}}}
2. {{"message_type": "FINAL_ANSWER", "name" : "result", "params": "answer"}}

Example:
User: Can you add 5 and 3
Assistant: {{"message_type": "FUNCTION_CALL", "name": "add", "params": {{"a": 5, "b": 3}}}}
User: Convert "INDIA" to a list of ASCII values
Assistant: FUNCTION_CALL: {{"message_type": "FUNCTION_CALL", "name": "strings_to_chars_to_int", "params": {{"string": "INDIA"}}}}
User: Please multiply 2 and 3
Assistant: FUNCTION_CALL: {{"message_type": "FUNCTION_CALL", "name": "multiply", "params": {{"a": 2, "b": 3}}}}
User: Show reasonings for calculation
Assistant: FUNCTION_CALL: {{"message_type": "FUNCTION_CALL", "name": "show_reasoning", "params": {{"steps": ["1. First, solve inside parentheses: 2 + 3", "2. Then multiply the result by 4"]}}}}
User: Result is 5. Let's verify this step.
Assistant: FUNCTION_CALL: {{"message_type": "FUNCTION_CALL", "name": "verify", "params": {{"expression": "2 + 3", "expected": 5}}}}
User: Verified. Next step?
Assistant: FUNCTION_CALL: {{"message_type": "FUNCTION_CALL", "name": "calculate", "params": {{"expression": "5 * 4"}}}}
User: Result is 20. Let's verify the final answer.
Assistant: FUNCTION_CALL: {{"message_type": "FUNCTION_CALL", "name": "verify", "params": {{"expression": "(2 + 3) * 4", "expected": 20}}}}
User: Verified correct.
Assistant: FINAL_ANSWER: {{"message_type": "FINAL_ANSWER", "result": 20}}

Your entire response should be in json format with message type parameter either FUNCTION_CALL or FINAL_ANSWER"""

                query = """Find the ASCII values of characters in INDIA and then return sum of squares of those values. Show reasonings for calculations, verify the calculation and 
                After that, Open Microsoft paint, then draw a rectangle with 607, 425, 940, 619 coordinates, then use the final answer to add text in paint.
                then finally send me the final answer as email """
                # query = """Add two numbers 8 and 9, then multiply the result by 2."""
                mcp_server_logger.info("Starting iteration loop...")
                
                # Use global iteration variables
                global iteration, last_response
                
                while iteration < max_iterations:
                    mcp_server_logger.info(f"\n--- Iteration {iteration + 1} ---")
                    if last_response is None:
                        current_query = query
                    else:
                        current_query = current_query + "\n\n" + " ".join(iteration_response)
                        current_query = current_query + "  What should I do next?"

                    # Get model's response with timeout
                    mcp_server_logger.info("Preparing to generate LLM response...")
                    prompt = f"{system_prompt}\n\nQuery: {current_query}"
                    try:
                        response = await generate_with_timeout(client, prompt)
                        mcp_server_logger.info(f"type(response_text): {type(response)}")
                        content = response.candidates[0].content.parts[0].text.strip()
                        mcp_server_logger.info(f"RAW CONTENT: >>>{content}<<<") 
                        # Remove markdown fences if they exist
                        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.DOTALL).strip()

                        # Try to extract the last {...} JSON object in the string
                        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
                        if not match:
                            raise ValueError("No JSON object found in LLM response")
                        mcp_server_logger.info("match")
                        mcp_server_logger.info(match)
                        json_str = match.group(0)
                        mcp_server_logger.info(f"EXTRACTED JSON: >>>{json_str}<<<")

                        response_json = json.loads(json_str)
                        # raw_text = json.loads(response.text.strip())


                        # cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.DOTALL).strip()
                        # mcp_server_logger.info(f"CLEANED CONTENT: >>>{cleaned}<<<")
                        # response_json = json.loads(cleaned)
                        mcp_server_logger.info(f"type(response_text): {type(response_json)}")
                        mcp_server_logger.info(f"LLM Response: {response_json}")
                        mcp_server_logger.info(f"LLM Response: {response_json['message_type']}")
                        # mcp_server_logger.info(f"LLM Response: {response_json['params']}")
                        
                        # Find the FUNCTION_CALL line in the response
                        # for line in response_json.split('\n'):
                        #     line = line.strip()
                        #     if line.startswith("FUNCTION_CALL:"):
                        #         response_text = line
                        #         break
                        
                    except Exception as e:
                        mcp_server_logger.info(f"Failed to get LLM response: {e}")
                        break


                    if response_json['message_type'] == "FUNCTION_CALL":
                        # _, function_info = response_text.split(":", 1)
                        # match = re.search(r'FUNCTION_CALL:\s*(\{.*\})', response_text)
                        # func_name = None 
                        # params = {}
                        # if match:
                        #     data = json.loads(match.group(1))
                        func_name = response_json["name"]
                        params = response_json["params"]

                        mcp_server_logger.info(f"Function: {func_name}")
                        mcp_server_logger.info(f"Params: {params}")
                        # parts = [p.strip() for p in function_info.split("|")]
                        # func_name, params = parts[0], parts[1:]
                        
                        # mcp_server_logger.info(f"\nDEBUG: Raw function info: {function_info}")
                        # mcp_server_logger.info(f"DEBUG: Split parts: {parts}")
                        mcp_server_logger.info(f"DEBUG: Function name: {func_name}")
                        mcp_server_logger.info(f"DEBUG: Raw parameters: {params}")
                        
                        try:
                            # Find the matching tool to get its input schema
                            tool = next((t for t in tools if t.name == func_name), None)
                            if not tool:
                                mcp_server_logger.info(f"DEBUG: Available tools: {[t.name for t in tools]}")
                                raise ValueError(f"Unknown tool: {func_name}")

                            mcp_server_logger.info(f"DEBUG: Found tool: {tool.name}")
                            mcp_server_logger.info(f"DEBUG: Tool schema: {tool.inputSchema}")

                            # Prepare arguments according to the tool's input schema
                            arguments = {}
                            schema_properties = tool.inputSchema.get('properties', {})
                            mcp_server_logger.info(f"DEBUG: Schema properties: {schema_properties}")

                            for param_name, param_info in schema_properties.items():
                                if not params:  # Check if we have enough parameters
                                    raise ValueError(f"Not enough parameters provided for {func_name}")
                                    
                                value = params[param_name]  # Get and remove the first parameter
                                param_type = param_info.get('type', 'string')
                                
                                mcp_server_logger.info(f"DEBUG: Converting parameter {param_name} with value {value} to type {param_type}")
                                
                                # Convert the value to the correct type based on the schema
                                if param_type == 'integer':
                                    arguments[param_name] = int(value)
                                elif param_type == 'number':
                                    arguments[param_name] = float(value)
                                elif param_type == 'array':
                                    # Handle array input
                                    if isinstance(value, str):
                                        value = value.strip('[]').split(',')
                                        arguments[param_name] = [int(x.strip()) for x in value]
                                    else:
                                        arguments[param_name] = value
                                else:
                                    arguments[param_name] = str(value)

                            mcp_server_logger.info(f"DEBUG: Final arguments: {arguments}")
                            mcp_server_logger.info(f"DEBUG: Calling tool {func_name}")
                            
                            result = await session.call_tool(func_name, arguments=arguments)
                            mcp_server_logger.info(f"DEBUG: Raw result: {result}")
                            
                            # Get the full result content
                            if hasattr(result, 'content'):
                                mcp_server_logger.info(f"DEBUG: Result has content attribute")
                                # Handle multiple content items
                                if isinstance(result.content, list):
                                    iteration_result = [
                                        item.text if hasattr(item, 'text') else str(item)
                                        for item in result.content
                                    ]
                                else:
                                    iteration_result = str(result.content)
                            else:
                                mcp_server_logger.info(f"DEBUG: Result has no content attribute")
                                iteration_result = str(result)
                                
                            mcp_server_logger.info(f"DEBUG: Final iteration result: {iteration_result}")
                            
                            # Format the response based on result type
                            if isinstance(iteration_result, list):
                                result_str = f"[{', '.join(iteration_result)}]"
                            else:
                                result_str = str(iteration_result)
                            
                            iteration_response.append(
                                f"In the {iteration + 1} iteration you called {func_name} with {arguments} parameters, "
                                f"and the function returned {result_str}."
                            )
                            last_response = iteration_result

                        except Exception as e:
                            mcp_server_logger.info(f"DEBUG: Error details: {str(e)}")
                            mcp_server_logger.info(f"DEBUG: Error type: {type(e)}")
                            traceback.print_exc()
                            iteration_response.append(f"Error in iteration {iteration + 1}: {str(e)}")
                            break
                        
                        if func_name == "send_email":
                            mcp_server_logger.info("\n=== Agent Execution Complete ===")
                            break

                    elif response_json['message_type'] == "FINAL_ANSWER":
                        mcp_server_logger.info(response_json)
                        mcp_server_logger.info("\n=== Final answer got ===")
                        # break
                        # result = await session.call_tool("open_paint")
                        # mcp_server_logger.info(result.content[0].text)

                        # # Wait longer for Paint to be fully maximized
                        # await asyncio.sleep(1)

                        # # Draw a rectangle
                        # result = await session.call_tool(
                        #     "draw_rectangle",
                        #     arguments={
                        #         "x1": 780,
                        #         "y1": 380,
                        #         "x2": 1140,
                        #         "y2": 700
                        #     }
                        # )
                        # mcp_server_logger.info(result.content[0].text)

                        # # Draw rectangle and add text
                        # result = await session.call_tool(
                        #     "add_text_in_paint",
                        #     arguments={
                        #         "text": response_text
                        #     }
                        # )
                        # mcp_server_logger.info(result.content[0].text)
                        # break

                    iteration += 1

    except Exception as e:
        mcp_server_logger.info(f"Error in main execution: {e}")
        traceback.print_exc()
    finally:
        reset_state()  # Reset at the end of main

if __name__ == "__main__":
    asyncio.run(main())
    
    
