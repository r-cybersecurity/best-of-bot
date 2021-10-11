import json
from logic import logic_handler


def lambda_handler(event, context):
    code, output_array = logic_handler()
    return {"statusCode": code, "body": json.dumps(output_array)}
