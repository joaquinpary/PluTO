"""POST /transform: the transformation engine over HTTP (docs/contracts/transform-api.md).

A plugin sends the raw trajectory and gets the az/el one back in the same
response, instead of publishing it on the broker and waiting for it to come
back on another topic. It is a calculation with no side effects, reachable only
inside pluto-network, so it takes no credentials.
"""
from fastapi import FastAPI

from models import PolarCoordinatesPayload, RawCoordinatesPayload
from transformer import transform_payload

app = FastAPI(title='PluTO coord_transform', version='1')


@app.get('/health')
def health():
    return {'status': 'ok'}


# A plain def, not async: skyfield is CPU-bound, and FastAPI runs a sync
# endpoint on its thread pool instead of blocking the event loop.
@app.post('/transform', response_model=PolarCoordinatesPayload)
def transform(payload: RawCoordinatesPayload) -> PolarCoordinatesPayload:
    return transform_payload(payload)
