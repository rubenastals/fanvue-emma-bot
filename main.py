import uvicorn
from api.webhook import app

if __name__ == "__main__":
    print("🔥 Emma 2.0 - Ultimate Fanvue Chatter is starting...")
    print("💕 Listening for webhooks on port 8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
