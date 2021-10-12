import boto3
import os
import requests
import time
import tweepy
from botocore.exceptions import ClientError

rank_settings = {
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


def logic_handler():
    url = "https://www.reddit.com/r/cybersecurity/hot/.json?count=25"
    headers = {"User-Agent": "r/cybersecurity Twitter Bot"}

    try:
        fetched_data = requests.get(url, headers=headers)
    except Exception:
        return 500, {"Reason": "Couldn't GET Reddit"}

    try:
        json_data = fetched_data.json()
    except Exception:
        return 500, {"Reason": "Reddit did not return valid JSON"}

    if "data" not in json_data:
        return 500, {"Reason": "Reddit did not return JSON with 'data' field."}

    try:
        qualifying_submissions = []
        for submission in json_data["data"]["children"]:
            submission_rank = submission_ranker(submission["data"])
            if submission_rank:
                qualifying_submissions.append(submission_rank)
    except Exception as e:
        return 500, {"Reason": f"Error while parsing submissions: {e}"}

    if len(qualifying_submissions) == 0:
        return 500, {"Reason": "No qualifying submissions found."}

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
        try:
            dynamo_get = client.get_item(
                TableName="twitter_bot__r_cybersecurity",
                Key={"link": {"S": stored_submission["link"]}},
            )
        except ClientError as e:
            print(e.response["Error"]["Message"])
            # we don't know if we've tweeted this, so let's skip it
            # this enforces at most once tweeting
            continue

        # we've confidently tweeted the submission, skip it
        if "Item" in dynamo_get:
            print("-- already tweeted, skipping")
            continue

        # we haven't tweeted the submission, try logging that we'll tweet it
        expires = str((14 * 24 * 60 * 60) + int(time.time()))  # 14 days from now
        try:
            dynamo_put = client.put_item(
                TableName="twitter_bot__r_cybersecurity",
                Item={"link": {"S": stored_submission["link"]}, "ttl": {"N": expires}},
            )
        except ClientError as e:
            print(e.response["Error"]["Message"])
            # we don't know if we've saved this, so let's skip it
            # this enforces at most once tweeting
            continue
        except Exception as e:
            print(e)
            # we don't know if we've saved this, so let's skip it
            # this enforces at most once tweeting
            continue

        print("-- attempting tweet")
        tweeted = True
        tweet = f'#cybersecurity professionals discuss: {stored_submission["title"]}\n\nhttps://reddit.com{stored_submission["link"]}'

        CONSUMER_KEY = os.getenv("CONSUMER_KEY")
        CONSUMER_SECRET = os.getenv("CONSUMER_SECRET")
        ACCESS_KEY = os.getenv("ACCESS_KEY")
        ACCESS_SECRET = os.getenv("ACCESS_SECRET")

        if CONSUMER_KEY and CONSUMER_SECRET and ACCESS_KEY and ACCESS_SECRET:
            auth = tweepy.OAuthHandler(CONSUMER_KEY, CONSUMER_SECRET)
            auth.set_access_token(ACCESS_KEY, ACCESS_SECRET)
            api = tweepy.API(auth)
            api.update_status(status=tweet)
        else:
            print("-- environment variables not present to tweet")

    if tweeted:
        return 200, {"Reason": "Tweeted successfully."}
    if not tweeted:
        return 200, {"Reason": "Nothing to tweet; exhausted."}


def submission_ranker(submission):
    if submission["over_18"] == True:
        return False

    try:
        weights = rank_settings[submission["link_flair_text"]]
    except Exception:
        return False

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
    }
