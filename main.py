from transformers import pipeline
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel
from fastapi import FastAPI, Request
from fastapi import HTTPException
from deep_translator import GoogleTranslator
from langdetect import detect

import uvicorn
import sys

from collections import deque


import requests
import logging
import json
import asyncio


app = FastAPI()

logger = logging.getLogger()

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
stream_handler = logging.StreamHandler(sys.stdout)
log_formatter = logging.Formatter("%(asctime)s [%(processName)s: %(process)d] [%(threadName)s: %(thread)d] [%(levelname)s] %(name)s: %(message)s")
stream_handler.setFormatter(log_formatter)
logger.addHandler(stream_handler)

logger.info('API is starting up')

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

on_call_queue = asyncio.Queue()
target_lag = 'ar'


sentiment_classifier = pipeline(
    task='text-classification',
    model="CAMeL-Lab/bert-base-arabic-camelbert-da-sentiment", 
    return_all_scores=True
)

class Body(BaseModel):
    sender: str
    text: str
    currlang: str
    targetlang: str 
    on_call_status: bool 


    

def fetch_rasa_response(message):
    # parms = {
    #     "sender":"sender",
    #     "message":message
    # }
    # response = requests.post("http://localhost:5005/webhooks/rest/webhook", json=parms)
    
    response = {
        "question": "كيف اطبع بطاقة عندك؟", 
        "answer": """لطباعة بطاقة عندك للعميل عليك اتباع الخطوات التالية:
            1. في الجزء الايمن من الشاشة يوجد زر (اطبع بطاقة عندك)
            2. في النموذج قم بتعبئة الثلاث خانات (اسم العميل، رقم الجوال، المسمى الوظيفي)
            3. قم بالضغط على زر (اطبع)
            4. سيظهر لك تصميم البطاقة النهائي مع معلومات العميل التي ادخلتها
            5. بعد التحقق من المعلومات قم بالضغط على زر (اطبع)"""
    }
    

    return response

async def fetch_sentiment_score(text):
    results = sentiment_classifier(text)
    
    all_scores = []
    for result in results:
        score = {}
        for result_scores in result:
            score[result_scores["label"]] = result_scores['score']
        all_scores.append(sentiment_score(score))

    #return the acerage of all scores
    return sum(all_scores)/len(all_scores) 



def stage_text(text):
    #Split based on '.' (full stop taking priority) 
    return text.split(".")


def sentiment_score(scores):
    #Calculating the sentiment score from
    required_keys = ['positive', 'negative', 'neutral']
    #check that positive, negative and neutral exist as keys 
    for key in required_keys:
        if key not in scores:
            scores[key] = 0 

    # Apply the formula to calculate the score that I made up (needs to be revised in the future)
    score = 1 + 4 * ((scores['positive']*100) - (scores['negative']*100) + ((scores['neutral'] / 2 )*100))
    
    # Ensure the score is within the range of 1 to 10
    score = min(max(score, 0), 100)
    
    return score

async def process_message(body:Body):
    ##Processing message from the client side (taking in call transcripts)
    data_json = {
        "call status": body.on_call_status,
        "conversation": {
            "sender": body.sender,
        }
    }

    translation =  GoogleTranslator(source=body.currlang, target=body.targetlang).translate(body.text)

    data_json["conversation"]["message_orginal"] = body.text
    data_json["conversation"]["message_translated"] = translation
    
    
    on_call_queue.put_nowait(data_json)
    return data_json


@app.get("/")
async def sanity_check():
    return {"message":"Hello World"}

@app.post("/v1/leap-feature/")
async def message(body:Body):
    logger.debug("Added: " +  body.sender + "--"+ body.text)
    response = await  process_message(body)
    logger.debug("Queue Length:" + str(on_call_queue.qsize()))
    return response


@app.get("/v2/leap-feature/stream")
async def message_stream(request: Request):
    async def event_generator():
        while True:
            if await request.is_disconnected():
                logger.debug("Request disconnected")
                break

            try:
                data = on_call_queue.get_nowait()#await asyncio.wait_for(on_call_queue.get(), 1800)
                logger.debug("length of queue: " + str(on_call_queue.qsize()))
                logger.debug("Porcssing Queue:" + str(data["conversation"]))
                yield {
                    "event": "message",
                    "id": "message_id",
                    "retry": MESSAGE_STREAM_RETRY_TIMEOUT,
                    "data": json.dumps(data),
                }

                #end connection if the data call status is false
                if not data["call status"]:
                    break

            except asyncio.TimeoutError:
                logger.debug("Timed out")
                raise HTTPException(status_code=408, detail="Request timed out")
            
            except asyncio.QueueEmpty:
                yield {
                    "event": "end_event",
                    "id": "message_id",
                    "retry": MESSAGE_STREAM_RETRY_TIMEOUT,
                }


            await asyncio.sleep(MESSAGE_STREAM_DELAY)
    
    return EventSourceResponse(event_generator())

