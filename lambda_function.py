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
from mastodon import Mastodon


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
    posted = False
    disqualified_submissions = []

    while attempts < len(qualifying_submissions) and not posted:
        attempts += 1
        stored_submission = {"priority": 0}

        # identify which submission we want to post the most
        for submission in qualifying_submissions:
            if not submission["link"] in disqualified_submissions:
                if submission["priority"] > stored_submission["priority"]:
                    stored_submission = submission

        disqualified_submissions.append(stored_submission["link"])
        print(str(stored_submission["priority"]) + " " + stored_submission["link"])

        # check in DynamoDB if the submission has been posted
        dynamo_get = []
        try:
            dynamo_get = client.get_item(
                TableName="twitter_bot__r_cybersecurity",
                Key={"link": {"S": stored_submission["link"]}},
            )
        except ClientError as e:
            print(f"-- DynamoDB GET failed: {e.response['Error']['Message']}")
            # we don't know if we've posted this, so let's skip it
            # this enforces at most once posting
            continue
        except NoCredentialsError:
            # local devel without access to DDB, just keep going
            pass

        # we've confidently posted the submission, skip it
        if "Item" in dynamo_get:
            print("-- already posted, skipping")
            continue

        # we haven't posted the submission, try logging that we'll post it
        expires = str((14 * 24 * 60 * 60) + int(time.time()))  # 14 days from now
        try:
            client.put_item(
                TableName="twitter_bot__r_cybersecurity",
                Item={"link": {"S": stored_submission["link"]}, "ttl": {"N": expires}},
            )
        except ClientError as e:
            print(f"-- DynamoDB PUT failed: {e.response['Error']['Message']}")
            # we don't know if we've saved this, so let's skip it
            # this enforces at most once posting
            continue
        except NoCredentialsError:
            # local devel without access to DDB, just keep going
            pass
        except Exception as e:
            print(e)
            # we don't know if we've saved this, so let's skip it
            # this enforces at most once posting
            continue

        print("-- building post")
        title = unescape(stored_submission["title"])
        selftext_html = ""
        if "selftext_html" in stored_submission.keys():
            selftext_html = unescape(stored_submission["selftext_html"])

        summary = summarize(title, selftext_html)

        # shorten link by removing title component
        # still always counts as 23 characters though
        post_id = stored_submission["link"].strip("/").split("/")[3]
        post_link = f"https://reddit.com/r/cybersecurity/comments/{post_id}/"

        post_engine(post_toot, summary, title, post_link)
        post_engine(post_tweet, summary, title, post_link)

    if posted:
        return {"statusCode": 200, "body": "Posted successfully."}
    if not posted:
        return {"statusCode": 200, "body": "Exhausted all options for posting."}


def post_engine(target, summary, title, link):
    prioritized_posts = [f"{summary} {link}", f"{title} {link}", f"{link}"]
    succeeded = False
    for post in prioritized_posts:
        clean_post = clean_tokens(post)
        if not succeeded:
            succeeded = target(clean_post)


def clean_tokens(text_data):
    tokens_to_clean = text_data.split(" ")

    clean_tokens = []
    for token_to_clean in tokens_to_clean:
        # could also ensure no cashtags?
        clean_token = token_to_clean.strip("#@")
        clean_tokens.append(clean_token)

    return " ".join(clean_tokens)


def post_tweet(post_me):
    print("-- attempting tweet")

    try:
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
            api.update_status(status=post_me)
            print(f"-- tweeted {post_me}")
            return True
        else:
            print("-- environment variables not present to tweet")
            return False
    except Exception as e:
        print(f"-- tweet caused exception {str(e)}")
        return False


def post_toot(post_me):
    print("-- attempting toot")

    try:
        MASTO_CLIENT_KEY = os.getenv("MASTO_CLIENT_KEY")
        MASTO_CLIENT_SECRET = os.getenv("MASTO_CLIENT_SECRET")
        MASTO_ACCESS_TOKEN = os.getenv("MASTO_ACCESS_TOKEN")

        if MASTO_CLIENT_KEY and MASTO_CLIENT_SECRET and MASTO_ACCESS_TOKEN:
            mastodon = Mastodon(
                api_base_url="https://botsin.space",
                client_id=MASTO_CLIENT_KEY,
                client_secret=MASTO_CLIENT_SECRET,
                access_token=MASTO_ACCESS_TOKEN,
            )
            mastodon.toot(post_me)
            print(f"-- tooted {post_me}")
            return True
        else:
            print("-- environment variables not present to toot")
    except Exception as e:
        print(f"-- toot caused exception {str(e)}")
        return False


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


def summarize(title, selftext_html):
    # budget for tweets is 280 - 24 = 256 characters
    # mastodon is 500 (adjustable) but we have to use minimums here
    openai.api_key = os.getenv("OPENAI_API_KEY")

    try:
        completion = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system",
                    "content": "You will be given a discussion post from Reddit which is about cybersecurity. Summarize the post in 230 chracters or less, using only the information present in the post. Avoid any use of hashtags. Explicit language is OK as long as it's not discriminatory. If you cannot summarize the post for any reason, reply 'uavrcl'.",
                },
                {"role": "user", "content": openai_post_prep(title, selftext_html)},
            ],
        )

        summary = completion["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"OpenAI threw exception {str(e)}, no summary today")
        summary = ""

    if "uavrcl" in summary:
        summary = title

    return summary


def openai_post_prep(title, selftext_html):
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
