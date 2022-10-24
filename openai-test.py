import openai
import os
from pprint import pprint

openai.api_key = os.getenv("OPENAI_API_KEY")

article = "How does end-to-end encryption work when there are multiple devices? ... Suppose a cloud backup service implements end-to-end encryption. The backup client on Device A creates a public/private keypair during installation. The client encrypts file.txt using the public key and uploads it to the cloud. The user then installs the backup client on Device B which generates a different keypair. They download file.txt but cannot open it because it is encrypted using the private key from Device A."

input_question = f'You are an industry expert in the cybersecurity field. Write a one sentence summary of the following question, your summary must start with "Someone asked ".\n\nQuestion: "{article}"\nSummary:'

# https://beta.openai.com/docs/models/overview
# max length is 4k tokens incl output

pprint(
    openai.Completion.create(
        model="text-davinci-002",
        prompt=input_question,
        temperature=0,
        max_tokens=60,
        top_p=1.0,
        frequency_penalty=0.5,
        presence_penalty=0.0,
    )
)
