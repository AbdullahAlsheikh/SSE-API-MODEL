# from transformers import pipeline
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel
from fastapi import FastAPI, Request
import uvicorn


import requests
import logging
import json
import asyncio


app = FastAPI()

logger = logging.getLogger()

MESSAGE_STREAM_DELAY = 1  # second
MESSAGE_STREAM_RETRY_TIMEOUT = 15000  # milisecond

# add CORS so our web page can connect to our api
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

on_call_queue = []

class body(BaseModel):
    sender: str
    text: str
    

# sentiment_classifier = pipeline(
#     task='text-classification',
#     model="CAMeL-Lab/bert-base-arabic-camelbert-da-sentiment", 
#     return_all_scores=True
# )


def fetch_rasa_response(message):
    # parms = {
    #     "sender":"sender",
    #     "message":message
    # }
    # response = requests.post("http://localhost:5005/webhooks/rest/webhook", json=parms)
    
    response = "تعيمات طباعة البطاقة"
    

    return response





def fetch_sentiment_score(text):
    # results = sentiment_classifier(text)
    
    # all_scores = []
    # for result in results:
    #     score = {}
    #     for result_scores in result:
    #         score[result_scores["label"]] = result_scores['score']
    #     all_scores.append(sentiment_score(score))

    #return the acerage of all scores
    return 10 



def stage_text(text):
    #Split based on '.' (full stop taking priority) 
    return text.split(".")


def sentiment_score(scores):
    required_keys = ['positive', 'negative', 'neutral']
    #check that positive, negative and neutral exist as keys 
    for key in required_keys:
        if key not in scores:
            scores[key] = 0 

    # Apply the formula to calculate the score that I made up (needs to be revised in the future)
    score = 1 + 4 * ((scores['positive']*100) - (scores['negative']*100) + ((scores['neutral'] / 2 )*100))
    
    # Ensure the score is within the range of 1 to 10
    score = min(max(score, 0), 10)
    
    return score

@app.get("/")
async def main():
    return "Hello World"

@app.post("/v1/leap-feature/")
async def sentiment(body:body):
    global on_call_queue
    #Takes text and splits it
    text = stage_text(body.text)

    #Client then pass it to Rasa
    rasa_response = "Instruction" if body.sender == "sender" else "No Instruction"


    #Agent Pass it to Sentiment
    sentiment_score = fetch_sentiment_score(text)
    
    

    data_json = {
        "sentiment": sentiment_score,
        "Co-pilot": rasa_response, 
        "coversation": {
            "sender": body.sender,
            "message": body.text
        }
    }


    #Store information in queue
    on_call_queue.append(json.dumps(data_json))

    

def get_data():
    global on_call_queue

    #Try-catch empty queue
    if(len(on_call_queue) > 0):
        data = on_call_queue.pop(0)
    else: 
        data = "empty"

    return data, data != "empty"


@app.get("/v1/leap-feature/stream")
async def message_stream(request: Request):
    async def event_generator():
        while True:
            if await request.is_disconnected():
                logger.debug("Request disconnected")
                break

            # Checks for new messages and return them to client if any
            data, exists = get_data()
            if exists:
                yield {
                    "event": "new_message",
                    "id": "message_id",
                    "retry": MESSAGE_STREAM_RETRY_TIMEOUT,
                    "data": data,
                }
            else:
                yield {
                    "event": "end_event",
                    "id": "message_id",
                    "retry": MESSAGE_STREAM_RETRY_TIMEOUT,
                }

            await asyncio.sleep(MESSAGE_STREAM_DELAY)

    return EventSourceResponse(event_generator())

