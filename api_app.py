from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def root():
    return {"message": "MailScribe API is running!"}
