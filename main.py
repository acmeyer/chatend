from aws import (
    create_new_api,
    create_new_api_endpoint,
)
import openai
import os
import json
from tenacity import retry, wait_random_exponential, stop_after_attempt
import dotenv
dotenv.load_dotenv('.env')

openai.api_key = os.getenv('OPENAI_API_KEY')
assert openai.api_key is not None, "Please set your OPENAI_API_KEY in .env file"

GPT_4_MODEL = "gpt-4-0613"
GPT_3_MODEL = "gpt-3.5-turbo-0613"
GPT_MODEL = GPT_4_MODEL
MODEL_TEMPERATURE = 0.5


@retry(wait=wait_random_exponential(min=1, max=20), stop=stop_after_attempt(6))
def chat_completion_request(messages, functions, model=GPT_MODEL):
    if functions:
        response = openai.ChatCompletion.create(
            model=model,
            messages=messages,
            functions=functions,
        )
    else:
        response = openai.ChatCompletion.create(
            model=model,
            messages=messages,
        )
    return response["choices"][0]["message"]  # type: ignore


functions = [
    {
        "name": "create_new_api",
        "description": "Creates a new API Gateway API and Cognito User Pool for authentication.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The API's name, internal facing.",
                },
                "description": {
                    "type": "string",
                    "description": "The description for the API.",
                },
            },
            "required": ["name", "description"],
        },
    },
    {
        "name": "create_new_api_endpoint",
        "description": "Creates a new API Gateway API endpoint",
        "parameters": {
            "type": "object",
            "properties": {
                "api_id": {
                    "type": "string",
                    "description": "The API ID to add the endpoint to.",
                },
                "endpoint": {
                    "type": "string",
                    "description": "The endpoint path. This should not include the API's domain. E.g. /hello",
                },
                "method": {
                    "type": "string",
                    "enum": ["GET", "POST", "PUT", "DELETE"],
                    "description": "The REST method of the endpoint. E.g. GET, POST, PUT, DELETE.",
                },
                "code": {
                    "type": "string",
                    "description": "The Lambda code to run when the endpoint is triggered. This should be all of the code necessary for a single Lambda function.",
                },
                "authorizer_id": {
                    "type": "string",
                    "description": "The ID of the authorizer to use for this endpoint. If not included, there will be no authentication for this endpoint.",
                },
                "runtime": {
                    "type": "string",
                    "enum": ['nodejs14.x', 'nodejs16.x', 'java8', 'java8.al2', 'java11', 'python3.8', 'python3.9', 'dotnet6', 'go1.x', 'ruby2.7', 'provided', 'provided.al2', 'nodejs18.x', 'python3.10', 'java17', 'ruby3.2'],
                    "description": "The Lambda runtime to use.",
                }
            },
            "required": ["api_id", "endpoint", "method", "code"]
        },
    },
]


# To run directly on command line, run `python main.py`
if __name__ == "__main__":
    conversation_messages = []
    with open("prompts/chat_prompt.md") as f:
        chat_prompt = f.read()
    system_message = {"role": "system", "content": chat_prompt}
    conversation_messages.append(system_message)
    chat_response = chat_completion_request(
        messages=conversation_messages, functions=functions)
    assistant_message = chat_response["content"]
    conversation_messages.append(
        {"role": "assistant", "content": assistant_message})
    print(f'\033[96m\033[1mGPT: {assistant_message}\033[0m\033[1m')
    while (user_input := input('You: ').strip()) != "":
        user_message = {"role": "user", "content": user_input}
        conversation_messages.append(user_message)
        chat_response = chat_completion_request(
            messages=conversation_messages, functions=functions)
        if chat_response.get("function_call"):
            available_functions = {
                "create_new_api": create_new_api,
                "create_new_api_endpoint": create_new_api_endpoint,
            }  # only one function in this example, but you can have multiple
            function_name = chat_response["function_call"]["name"]
            function_to_call = available_functions[function_name]
            function_args = json.loads(
                chat_response["function_call"]["arguments"])
            if function_to_call == create_new_api:
                function_response = function_to_call(
                    name=function_args.get("name"),
                    description=function_args.get("description"),
                )
            elif function_to_call == create_new_api_endpoint:
                function_response = function_to_call(
                    api_id=function_args.get("api_id"),
                    endpoint=function_args.get("endpoint"),
                    method=function_args.get("method"),
                    authorizer_id=function_args.get("authorizer_id"),
                    code=function_args.get("code"),
                )
            else:
                raise NotImplementedError(
                    f"Function {function_name} not implemented")

            # extend conversation with assistant's reply
            conversation_messages.append(chat_response)
            conversation_messages.append(
                {
                    "role": "function",
                    "name": function_name,
                    "content": function_response,
                }
            )  # extend conversation with function response
            print(
                f'\033[96m\033[1mGPT: FUNCTION CALL: {function_name}\033[0m\033[1m')
            # get a new response from GPT where it can see the function response
            chat_response = chat_completion_request(
                messages=conversation_messages, functions=None)

        assistant_message = chat_response.get("content")
        conversation_messages.append(
            {"role": "assistant", "content": assistant_message})
        print(f'\033[96m\033[1mGPT: {assistant_message}\033[0m\033[1m')
