import uvicorn
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
async def root():
    return {"status": "ok", "message": "Jarvis Orchestrator is online"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

if __name__ == "__main__":
    # Start the FastAPI server on port 8000
    uvicorn.run(app, host="0.0.0.0", port=8000)
