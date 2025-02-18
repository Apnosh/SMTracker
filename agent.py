from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import os
import supabase
from openai import OpenAI
from dotenv import load_dotenv
import json

# Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_API_KEY = os.getenv("SUPABASE_API_KEY")

# Initialize FastAPI app
app = FastAPI()

# Initialize Supabase client
supabase_client = supabase.create_client(SUPABASE_URL, SUPABASE_API_KEY)

# OpenAI API setup
client = OpenAI(api_key=OPENAI_API_KEY)

class QueryRequest(BaseModel):
    question: str

class QueryResponse(BaseModel):
    response: str = Field(
        description="A natural language response to the user's question"
    )

def fetch_data():
    """Fetch Instagram data from Supabase."""
    response = supabase_client.table("instagram_posts").select("instagram_id, caption, likes, comments, media_type, timestamp, engagement, total_followers").order("timestamp", desc=True).limit(7).execute()
    if response.data:
        return response.data
    return "No engagement data found."

@app.post("/chat")
async def chat_with_ai(request: QueryRequest):
    try:
        # Define the tool function OpenAI can call
        tools = [{
            "type": "function",
            "function": {
                "name": "fetch_data",
                "description": "Fetch Instagram data, instagram_id, caption, likes, comments, media_type, timestamp, engagement, total_followers, from Supabase.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False
                },
                "strict": True
            }
        }]

        # Define the messages to send to OpenAI
        messages=[
            {"role": "system", "content": "You are an Instagram analytics assistant."},
            {"role": "user", "content": request.question}
        ]

        # Send request to ChatGPT
        response = client.beta.chat.completions.parse(
            model="gpt-4o",
            messages=messages,
            tools=tools,
            response_format=QueryResponse
        )

        # Check if GPT wants to call fetch_data
        if response.choices[0].message.tool_calls:
            for tool_call in response.choices[0].message.tool_calls:
                messages.append(response.choices[0].message)
                if tool_call.function.name == "fetch_data":
                    data = fetch_data()
                    messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": json.dumps(data)})
                    
                    # Call AI agent again with the fetched data from the tool
                    response = client.beta.chat.completions.parse(
                        model="gpt-4o",
                        messages=messages,
                        tools=tools,
                        response_format=QueryResponse
                    )

        return response.choices[0].message.parsed.response
        # return {"response": chat_response.strip() if chat_response else "No response from AI"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))