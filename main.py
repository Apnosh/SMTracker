from supabase import create_client, Client
import requests
import os
from dotenv import load_dotenv
import schedule
import time
from threading import Thread
from fastapi import FastAPI
from contextlib import asynccontextmanager
from agent import app as agent_app

# Load environment variables from .env file
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_API_KEY = os.getenv("SUPABASE_API_KEY")
INSTAGRAM_ACCESS_TOKEN = os.getenv("INSTAGRAM_ACCESS_TOKEN")
INSTAGRAM_USER_ID = os.getenv("INSTAGRAM_USER_ID")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_API_KEY)

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

schedule.every(12).hours.do(job)

# Function to run the background Instagram fetching job
def start_instagram_background():
    while True:
        schedule.run_pending()  # Ensure jobs run on time
        time.sleep(60)  # Sleep for 1 minute to prevent CPU overload

# FastAPI lifespan event
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the background thread
    instagram_background_thread = Thread(target=start_instagram_background)
    instagram_background_thread.start()
    yield
    # Clean up (optional)
    instagram_background_thread.join()

# Create FastAPI app
app = FastAPI(lifespan=lifespan)

# Mount the agent app under a prefix (optional)
app.mount("/agent", agent_app)

@app.get("/")
def read_root():
    return {"Apnosh"}