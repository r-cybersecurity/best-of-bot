import boto3
import json
import os
import random
import requests
import time
import tweepy
from botocore.exceptions import ClientError
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
        except Exception as e:
            print(e)
            # we don't know if we've saved this, so let's skip it
            # this enforces at most once tweeting
            continue

        print("-- attempting tweet")
        tweet = tweet_maker(
            stored_submission["title"], f'https://reddit.com{stored_submission["link"]}'
        )

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


def tweet_maker(title, link):
    with open("relevant_hashtags.json") as hashtags_file:
        hashtags = json.load(hashtags_file)

    tokens_to_clean = title.split(" ")
    clean_tokens = []
    hashtag_options = {}
    for token_to_clean in tokens_to_clean:
        # could also ensure no cashtags?
        clean_token = token_to_clean.strip("#@")
        possible_hashtag = f"#{clean_token}".rstrip(
            ".!?,'|\"[];:<>/-=_+()*&^%$#@`~#"
        ).lower()

        if possible_hashtag in hashtags.keys():
            if not len(hashtag_options) == 0:
                if avg(hashtag_options.values()) - 5 > hashtags[possible_hashtag]:
                    hashtag_options = {}

            hashtag_options[f"#{clean_token}"] = hashtags[possible_hashtag]
        clean_tokens.append(clean_token)

    random_hashtag = ""
    if len(hashtag_options.keys()) > 0:
        random_hashtag_shuffle = list(hashtag_options.keys())
        random.shuffle(random_hashtag_shuffle)
        random_hashtag = random_hashtag_shuffle[0]

    new_title_tokens = []
    for clean_token in clean_tokens:
        if f"#{clean_token}" == random_hashtag:
            new_title_tokens.append(random_hashtag)
        else:
            new_title_tokens.append(clean_token)

    new_title_tokens.append(link)
    new_title = " ".join(new_title_tokens)
    return new_title


def avg(lst):
    return sum(list(lst)) / len(list(lst))


if __name__ == "__main__":
    pprint(lambda_handler({}, {}))
