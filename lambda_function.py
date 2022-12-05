import boto3
import json
import os
import openai
import random
import requests
import time
import tweepy
from html import escape, unescape
from botocore.exceptions import ClientError, NoCredentialsError
from pprint import pprint


rank_settings = {
    "Ask Me Anything!": {
        "karma": 1,
        "comments": 1,
    },
    "Business Security Questions &amp; Discussion": {
        "karma": 0.5,
        "comments": 1,
    },
    "Research Article": {
        "karma": 0.2,
        "comments": 0.5,
    },
    "Threat Actor TTPs &amp; Alerts": {
        "karma": 0.2,
        "comments": 0.5,
    },
    "New Vulnerability Disclosure": {
        "karma": 0.2,
        "comments": 0.5,
    },
    "Career Questions &amp; Discussion": {
        "karma": 0.2,
        "comments": 0.25,
    },
    "Other": {
        "karma": 0.1,
        "comments": 0.25,
    },
    "News - General": {
        "karma": 0.05,
        "comments": 0.1,
    },
    "News - Breaches &amp; Ransoms": {
        "karma": 0.05,
        "comments": 0.1,
    },
    "Corporate Blog": {
        "karma": 0.05,
        "comments": 0.1,
    },
}


client = boto3.client("dynamodb")


def lambda_handler(event, context):
    url = "https://www.reddit.com/r/cybersecurity/hot/.json?count=25"
    headers = {"User-Agent": "r/cybersecurity Twitter Bot"}

    try:
        fetched_data = requests.get(url, headers=headers)
    except Exception:
        return {"statusCode": 500, "body": "Couldn't GET Reddit"}

    try:
        json_data = fetched_data.json()
    except Exception:
        return {"statusCode": 500, "body": "Reddit did not return valid JSON"}

    if "data" not in json_data:
        return {"statusCode": 500, "body": "JSON does not contain 'data' field."}

    try:
        qualifying_submissions = []
        for submission in json_data["data"]["children"]:
            submission_rank = submission_ranker(submission["data"])
            if submission_rank:
                qualifying_submissions.append(submission_rank)
    except Exception as e:
        return {"statusCode": 500, "body": f"Error while parsing submissions: {e}"}

    if len(qualifying_submissions) == 0:
        return {"statusCode": 500, "body": "No qualifying submissions found."}

    attempts = 0
    tweeted = False
    disqualified_submissions = []

    while attempts < len(qualifying_submissions) and not tweeted:
        attempts += 1
        stored_submission = {"priority": 0}

        # identify which submission we want to tweet the most
        for submission in qualifying_submissions:
            if not submission["link"] in disqualified_submissions:
                if submission["priority"] > stored_submission["priority"]:
                    stored_submission = submission

        disqualified_submissions.append(stored_submission["link"])
        print(str(stored_submission["priority"]) + " " + stored_submission["link"])

        # check in DynamoDB if the submission has been tweeted
        dynamo_get = []
        try:
            dynamo_get = client.get_item(
                TableName="twitter_bot__r_cybersecurity",
                Key={"link": {"S": stored_submission["link"]}},
            )
        except ClientError as e:
            print(f"-- DynamoDB GET failed: {e.response['Error']['Message']}")
            # we don't know if we've tweeted this, so let's skip it
            # this enforces at most once tweeting
            continue
        except NoCredentialsError:
            # local devel without access to DDB, just keep going
            pass

        # we've confidently tweeted the submission, skip it
        if "Item" in dynamo_get:
            print("-- already tweeted, skipping")
            continue

        # we haven't tweeted the submission, try logging that we'll tweet it
        expires = str((14 * 24 * 60 * 60) + int(time.time()))  # 14 days from now
        try:
            client.put_item(
                TableName="twitter_bot__r_cybersecurity",
                Item={"link": {"S": stored_submission["link"]}, "ttl": {"N": expires}},
            )
        except ClientError as e:
            print(f"-- DynamoDB PUT failed: {e.response['Error']['Message']}")
            # we don't know if we've saved this, so let's skip it
            # this enforces at most once tweeting
            continue
        except NoCredentialsError:
            # local devel without access to DDB, just keep going
            pass
        except Exception as e:
            print(e)
            # we don't know if we've saved this, so let's skip it
            # this enforces at most once tweeting
            continue

        print("-- attempting tweet")

        title = unescape(stored_submission["title"])
        selftext_html = ""
        if "selftext_html" in stored_submission.keys():
            selftext_html = unescape(stored_submission["selftext_html"])

        tweet_text = tweet_maker(title, selftext_html)

        # shorten link by removing title component
        # still always counts as 23 characters though
        post_id = stored_submission["link"].strip("/").split("/")[3]
        post_link = f"https://reddit.com/r/cybersecurity/comments/{post_id}/"

        tweet = f"{tweet_text} {post_link}"
        print(f"Tweeting: '{tweet}'")

        CONSUMER_KEY = os.getenv("CONSUMER_KEY")
        CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")
        ACCESS_KEY = os.getenv("ACCESS_KEY")
        ACCESS_SECRET = os.getenv("ACCESS_SECRET")

        if CONSUMER_KEY and CONSUMER_SECRET and ACCESS_KEY and ACCESS_SECRET:
            # failing here is good -
            # we could unecessarily PUT all other potential tweets otherwise
            auth = tweepy.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET)
            auth.set_access_token(ACCESS_KEY, ACCESS_SECRET)
            api = tweepy.API(auth)
            api.update_status(status=tweet)
            tweeted = True
        else:
            print("-- environment variables not present to tweet")

    if tweeted:
        return {"statusCode": 200, "body": "Tweeted successfully."}
    if not tweeted:
        return {"statusCode": 200, "body": "Exhausted all options for tweeting."}


def submission_ranker(submission):
    if submission["over_18"] == True:
        return False

    try:
        weights = rank_settings[submission["link_flair_text"]]
    except Exception:
        weights = rank_settings["Other"]

    priority = (
        submission["upvote_ratio"]
        * submission["upvote_ratio"]
        * submission["ups"]
        * weights["karma"]
        * submission["num_comments"]
        * weights["comments"]
    )

    if priority < 10:
        return False

    return {
        "priority": priority,
        "link": submission["permalink"],
        "title": submission["title"],
        "flair": submission["link_flair_text"],
    }


def tweet_maker(title, selftext_html):
    # budget for tweets is 280 - 24 = 256 characters
    tokens_to_clean = title.split(" ")

    clean_tokens = []
    for token_to_clean in tokens_to_clean:
        # could also ensure no cashtags?
        clean_token = token_to_clean.strip("#@")
        clean_tokens.append(clean_token)

    # hashtags = openai_hashtag_selector(title, selftext_html)
    # for hashtag in hashtags:
    #    clean_tokens.append(hashtag)

    tweet = " ".join(clean_tokens)
    return tweet


def openai_hashtag_selector(title, selftext_html):
    with open("permitted_hashtags.json") as hashtags_file:
        hashtag_options = json.load(hashtags_file)

    openai.api_key = os.getenv("OPENAI_API_KEY")

    article = openai_article_prep(title, selftext_html)

    openai_prompt = f'You are an industry leader in the cybersecurity field who is great at summarizing information. What hashtags would you use on Twitter to describe the following article?\n\nArticle: "{article}"\nHashtags:'

    openai_response_raw = openai.Completion.create(
        model="text-davinci-002",
        prompt=openai_prompt,
        temperature=0,
        max_tokens=60,
        top_p=1.0,
        frequency_penalty=0.5,
        presence_penalty=0.0,
    )

    try:
        hashtags_raw = openai_response_raw["choices"][0]["text"]
    except Exception as e:
        print(f"OpenAI threw exception {str(e)}, no hashtags today")
        hashtags_raw = ""

    print(f"OpenAI selected the following possible hashtags: {hashtags_raw.strip()}")
    hashtags = hashtags_raw.strip().split(" ")

    hashtags_selected = []
    for hashtag in hashtags:
        if hashtag.lower() in hashtag_options.keys():
            if len(hashtags_selected) < 2:
                hashtags_selected.append(hashtag)

    return hashtags_selected


def openai_article_prep(title, selftext_html):
    title = remove_multiple_spaces_from_string(title)
    text = remove_html_tags(selftext_html)

    # openai seems to do better without any newlines
    text = text.replace("\n", " ").replace("\r", "")
    text = remove_multiple_spaces_from_string(text)

    article = f"{title} ... {text}"
    article_trim = article[:3600]  # leave ~400 characters for prompt, output, etc.
    if article != article_trim:
        article_trim += "... (continues)"

    return article_trim


def remove_multiple_spaces_from_string(input):
    return " ".join(input.split())


def remove_html_tags(text):
    """Remove html tags from a string"""
    import re

    clean = re.compile("<.*?>")
    return re.sub(clean, "", text)


if __name__ == "__main__":
    pprint(lambda_handler({}, {}))
