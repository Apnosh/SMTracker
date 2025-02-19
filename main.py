from supabase import create_client, Client
import requests
import os
from dotenv import load_dotenv
import schedule
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from openai import OpenAI
import json
import uvicorn
import threading
import time

# Load environment variables from .env file
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_API_KEY = os.getenv("SUPABASE_API_KEY")
INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN")
INSTAGRAM_USER_ID = os.getenv("INSTAGRAM_USER_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Initialize FastAPI app
app = FastAPI()

# Enable CORS
origins = [
    "http://localhost",
    "http://localhost:8000",
    "http://localhost:3000",
]

# Set all CORS enabled origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Supabase setup
supabase: Client = create_client(SUPABASE_URL, SUPABASE_API_KEY)

# OpenAI API setup
client = OpenAI(api_key=OPENAI_API_KEY)

class QueryRequest(BaseModel):
    question: str

class QueryResponse(BaseModel):
    response: str = Field(
        description="A natural language response to the user's question"
    )

# Fetch data from Instagram
def fetch_instagram_data():
    url = f"https://graph.instagram.com/{INSTAGRAM_USER_ID}/media?fields=id,caption,like_count,comments_count,media_type,media_url,permalink,thumbnail_url,timestamp&access_token={INSTAGRAM_ACCESS_TOKEN}"
    response = requests.get(url)
    
    if response.status_code == 200:
        return response.json()['data']
    else:
        print(f"Failed to fetch data: {response.status_code}")
        return None

# Fetch current followers count
def fetch_followers_count():
    url = f"https://graph.instagram.com/{INSTAGRAM_USER_ID}?fields=followers_count&access_token={INSTAGRAM_ACCESS_TOKEN}"
    response = requests.get(url)

    if response.status_code == 200:
        return response.json().get('followers_count', 0)
    else:
        print(f"Failed to fetch followers count: {response.status_code}")
        return 0

def calculate_engagement(likes, comments, weighted=False):
    if weighted:
        return likes + 2 * comments
    return likes + comments
    
# Store data in Supabase and ensure there are no duplicates
def store_data_in_supabase(data):
    curr_followers = fetch_followers_count()

    for post in data:
        instagram_id = post['id']

        # Check if the post already exists in Supabase (based on instagram_id)
        existing_post = supabase.table('instagram_posts').select('id').eq('instagram_id', instagram_id).execute()

        if existing_post.data:
            print(f"Post {instagram_id} already exists. Skipping.")
        else:
            # Calculate engagement
            engagement = calculate_engagement(post['like_count'], post['comments_count'], weighted=True)

            post_info = {
                "instagram_id": instagram_id,
                "caption": post['caption'],
                "likes": post['like_count'],
                "comments": post['comments_count'],
                "media_type": post['media_type'],
                "media_url": post['media_url'],
                "permalink": post['permalink'],
                "thumbnail_url": post.get('thumbnail_url'),
                "timestamp": post['timestamp'],
                "engagement": engagement,
                'total_followers': curr_followers
            }

            # Upsert the new post data into Supabase
            response = supabase.table('instagram_posts').upsert(post_info).execute()

            if response:
                print(f"Successfully stored post {instagram_id}")
            else:
                print(f"Failed to store post {instagram_id}: {response.status_code}")

# Schedule the task
def job():
    print("Fetching Instagram data...")
    data = fetch_instagram_data()
    if data:
        store_data_in_supabase(data)

schedule.every(1).hour.do(job)

def fetch_data():
    """Fetch Instagram data from Supabase."""
    response = supabase.table("instagram_posts").select("instagram_id, caption, likes, comments, media_type, timestamp, engagement, total_followers").order("timestamp", desc=True).execute()
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

def run_schedule():
    while True:
        schedule.run_pending()
        time.sleep(1)

# Start the scheduler thread
scheduler_thread = threading.Thread(target=run_schedule)
scheduler_thread.daemon = True  # Daemonize thread to exit when the main program exits
scheduler_thread.start()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)