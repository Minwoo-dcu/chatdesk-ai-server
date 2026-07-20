from fastapi import FastAPI

app = FastAPI(
    title="Chatdesk AI Server",
    version="0.1.0"
)

@app.get("/")
def root():
    return {
        "message": "Chatdesk AI Server is running!"
    }