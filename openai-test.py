import openai
from config import openai_key
from pprint import pprint

openai.api_key = openai_key

article = "Researchers demanding bounty - response?"

input_2022_10_23 = f"You are an industry leader in the cybersecurity field. You are a long-time Twitter user and great at summarizing information. What hashtags would you use on Twitter to describe the following article?\n\nArticle: \"{article}\"\nHashtags:"

pprint(openai.Completion.create(
    model="text-davinci-002",
    prompt=input_2022_10_23,
    temperature=0,
    max_tokens=60,
    top_p=1.0,
    frequency_penalty=0.5,
    presence_penalty=0.0
))