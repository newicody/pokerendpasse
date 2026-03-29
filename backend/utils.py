# backend/utils.py
import json
from datetime import datetime, date
from enum import Enum


class JSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, date):
            return obj.isoformat()
        if isinstance(obj, Enum):
            return obj.value
        if hasattr(obj, 'model_dump'):
            return obj.model_dump()
        if hasattr(obj, '__dict__'):
            return {k: v for k, v in obj.__dict__.items() if not k.startswith('_')}
        return super().default(obj)


def json_response(data):
    from fastapi.responses import JSONResponse
    return JSONResponse(content=json.loads(json.dumps(data, cls=JSONEncoder)))
