import os
from pathlib import Path

import torch
from flwr.clientapp import ClientApp
from flwr.common import ConfigRecord, Context, Message, RecordDict

from app.flower_transport import decode_request, reply_content
from app.worker import execute

app = ClientApp()


@app.query("identify")
def identify(message: Message, context: Context) -> Message:
    bank_id = str(context.node_config["bank-id"])
    return Message(
        content=RecordDict({"identity": ConfigRecord({"bank_id": bank_id})}),
        reply_to=message,
    )


@app.train()
def train(message: Message, context: Context) -> Message:
    torch.set_num_threads(1)
    request = decode_request(message.content)
    bank_id = str(context.node_config["bank-id"])
    if request.bank_id != bank_id:
        raise ValueError("request was sent to the wrong bank")
    path = Path(
        str(
            context.node_config.get(
                "data-path", os.environ.get("BANK_DATA_PATH", "/data/train.npz")
            )
        )
    )
    return Message(content=reply_content(execute(request, path)), reply_to=message)
